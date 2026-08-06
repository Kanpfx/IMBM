"""IMBM foreground-IM / background-BM scheduler for an Ares game loop."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from loguru import logger

from agents.bm_agent import BMAgent
from agents.correction_agent import CorrectionAgent
from agents.im_agent import IMAgent
from config.game import GameConfig
from config.llm import LLMConfig
from config.policy import allowed_actions
from core.automation import AutomationController
from core.observation import Observation, ObservationBuilder
from core.phase import PhaseResolver
from core.policy import ActionReview, PolicyValidator, ValidationIssue
from core.state import TagIdMapper
from knowledge.loader import ActionCatalog, load_battlecruiser_tactic
from runtime.ares_adapter import AresActionAdapter
from runtime.deferred_actions import DeferredActionQueue
from runtime.directive import BMDirective, DirectiveStore
from tools.llm_client import LLMClient
from tools.telemetry import Telemetry


@dataclass
class PendingBM:
    task: asyncio.Task[list[str]]
    observation: Observation
    phase: str
    revision: int
    trigger_reason: str
    started_at: float


class LLMGameController:
    """Make IM the only non-automatic foreground decision maker.

    ``tick`` awaits IM on every decision interval. BM is deliberately the only
    background task: it produces a directive for a later IM decision and can
    never register an Ares behavior itself.
    """

    def __init__(
        self,
        game_config: GameConfig | None = None,
        llm_config: LLMConfig | None = None,
        *,
        enable_bm: bool = False,
        run_metadata: dict[str, Any] | None = None,
        log_directory: Path | None = None,
    ):
        self.game_config = game_config or GameConfig()
        self.llm_config = llm_config or LLMConfig.from_env()
        self.tactic = load_battlecruiser_tactic()
        self.catalog = ActionCatalog.load()
        self.adapter = AresActionAdapter(self.catalog)
        self.policy = PolicyValidator(self.catalog, self.game_config)
        self.observation_builder = ObservationBuilder(TagIdMapper())
        self.phase_resolver = PhaseResolver()
        self.automation = AutomationController()
        self.directive_store = DirectiveStore()
        self.telemetry = Telemetry(
            {
                "model": self.llm_config.model,
                "enable_bm": enable_bm,
                **(run_metadata or {}),
            },
            directory=log_directory,
        )
        self.client = LLMClient(self.llm_config)
        self.bm = BMAgent(self.llm_config, self.client)
        self.im = IMAgent(self.llm_config, self.client)
        self.corrector = CorrectionAgent(self.llm_config, self.client)
        self.deferred_actions = DeferredActionQueue(
            self.catalog, self.game_config.deferred_action_ttl_loops
        )
        self.enable_bm = enable_bm
        self.bm_pending: PendingBM | None = None
        self._last_bm_started_loop = -(10**9)

    @property
    def active(self) -> bool:
        """LLM control is valid only when it was enabled and fully configured."""
        return self.llm_config.configured

    async def tick(self, bot: Any, iteration: int) -> None:
        """Run frame automation and, every ten ticks, the blocking IM decision."""
        await self.automation.run(bot, iteration)
        await self._poll_bm(bot, iteration)
        if not self.active or iteration % self.game_config.im_interval_ticks != 0:
            return

        phase_state = self.phase_resolver.resolve(self._quick_counts(bot))
        observation = self.observation_builder.build(bot, iteration, phase_state.id)
        self.telemetry.observation(
            tick=iteration,
            time=getattr(bot, "time_formatted", "00:00"),
            phase=phase_state.id,
            resources={
                "minerals": int(bot.minerals),
                "vespene": int(bot.vespene),
                "supply": f"{int(bot.supply_used)}/{int(bot.supply_cap)}",
            },
            observation=observation.text,
        )

        ready_deferred, expired_deferred = self.deferred_actions.pop_ready(bot, iteration)
        if expired_deferred:
            self.telemetry.event(
                "deferred_actions_expired",
                loop=iteration,
                actions=expired_deferred,
            )
        if ready_deferred:
            self.adapter.compile_and_register(bot, ready_deferred, observation.context)
            self.observation_builder.record_registered_actions(ready_deferred)
            self.telemetry.event(
                "deferred_actions_registered",
                loop=iteration,
                actions=ready_deferred,
            )

        # Start a cold/expired/periodic BM refresh before awaiting IM. Both calls
        # can therefore make progress together, while IM still gates this tick.
        await self._maybe_start_bm(
            observation,
            phase_state.id,
            phase_state.revision,
            iteration,
        )

        directive = self.directive_store.read(iteration)
        guidance_source = (
            "BM"
            if directive is not None and directive.phase == phase_state.id
            else "none"
        )
        guidance = (
            list(directive.guidance)
            if directive is not None and directive.phase == phase_state.id
            else []
        )
        guidance_reference = (
            f"BM@{directive.issued_at_loop}"
            if directive is not None and directive.phase == phase_state.id
            else "none"
        )
        entries = self.catalog.prompt_entries(allowed_actions(phase_state.id))
        try:
            # This await is intentional: unlike BM, IM owns the foreground game
            # decision and its accepted actions are registered in this same tick.
            im_started_at = perf_counter()
            result = await self.im.run(
                observation.text,
                guidance,
                entries,
                lambda _actions: (True, "submitted for recoverable policy review"),
                trace=self.telemetry,
                tick=iteration,
            )
            review = self.policy.review(
                bot, result.actions, observation.context, phase_state.id
            )
            if review.issues:
                initial_review = review
                try:
                    repaired_actions = await self.corrector.run(
                        observation.text,
                        guidance,
                        entries,
                        [issue.action for issue in initial_review.issues],
                        [issue.text() for issue in initial_review.issues],
                        trace=self.telemetry,
                        tick=iteration,
                    )
                    repaired_review = self.policy.review(
                        bot, repaired_actions, observation.context, phase_state.id
                    )
                    available_slots = max(
                        0,
                        self.game_config.max_actions_per_decision
                        - len(initial_review.actions),
                    )
                    overflow = repaired_review.actions[available_slots:]
                    overflow_issues = [
                        ValidationIssue(
                            len(result.actions) + index,
                            action,
                            "omitted because the decision action limit was reached",
                        )
                        for index, action in enumerate(overflow)
                    ]
                    review = ActionReview(
                        initial_review.actions
                        + repaired_review.actions[:available_slots],
                        repaired_review.issues + overflow_issues,
                        initial_review.normalizations + repaired_review.normalizations,
                    )
                except Exception as correction_error:
                    self.telemetry.event(
                        "im_correction_failed",
                        loop=iteration,
                        error=str(correction_error),
                    )
            if review.normalizations:
                self.telemetry.event(
                    "im_actions_normalized",
                    loop=iteration,
                    notes=review.normalizations,
                )
            if review.issues:
                self.telemetry.event(
                    "im_actions_omitted",
                    loop=iteration,
                    errors=[issue.text() for issue in review.issues],
                    actions=[issue.action for issue in review.issues],
                )

            immediate_actions: list[dict[str, Any]] = []
            queued_actions: list[dict[str, Any]] = []
            for action in review.actions:
                if self.deferred_actions.should_defer(bot, action):
                    if self.deferred_actions.enqueue(action, iteration):
                        queued_actions.append(action)
                else:
                    immediate_actions.append(action)
            if immediate_actions:
                self.adapter.compile_and_register(
                    bot, immediate_actions, observation.context
                )
                self.observation_builder.record_registered_actions(immediate_actions)
            if queued_actions:
                self.telemetry.event(
                    "im_actions_deferred",
                    loop=iteration,
                    actions=queued_actions,
                    expires_after_loops=self.game_config.deferred_action_ttl_loops,
                )
            self.telemetry.event(
                "im_accepted",
                loop=iteration,
                phase=phase_state.id,
                directive_age=directive.age(iteration) if directive else None,
                actions=immediate_actions,
                deferred_actions=queued_actions,
                request_background=result.request_background,
                latency_ms=round((perf_counter() - im_started_at) * 1000),
            )
            self.telemetry.accepted_decision(
                tick=iteration,
                time=getattr(bot, "time_formatted", "00:00"),
                phase=phase_state.id,
                actions=immediate_actions,
                deferred_actions=queued_actions,
                guidance_source=guidance_source,
                guidance=guidance,
                request_background=result.request_background,
                background_reason=result.background_reason,
                latency_ms=round((perf_counter() - im_started_at) * 1000),
            )
            logger.info(
                "[IM tick={}] t={} M={} G={} supply={}/{} phase={} im={:.2f}s\n"
                "  actions={} deferred={} guidance={}",
                iteration,
                getattr(bot, "time_formatted", "00:00"),
                int(bot.minerals),
                int(bot.vespene),
                int(bot.supply_used),
                int(bot.supply_cap),
                phase_state.id,
                perf_counter() - im_started_at,
                json.dumps(immediate_actions, ensure_ascii=False, separators=(",", ":")),
                json.dumps(queued_actions, ensure_ascii=False, separators=(",", ":")),
                guidance_reference,
            )
        except Exception as exc:
            latency_ms = (
                round((perf_counter() - im_started_at) * 1000)
                if "im_started_at" in locals()
                else None
            )
            self.telemetry.event(
                "im_failed", loop=iteration, error=str(exc), latency_ms=latency_ms
            )
            self.observation_builder.record_validation_error(str(exc))
            logger.error(
                "[IM tick={}] validation/request failed after {}ms: {}",
                iteration,
                latency_ms,
                exc,
            )
            return

        if result.request_background:
            await self._maybe_start_bm(
                observation,
                phase_state.id,
                phase_state.revision,
                iteration,
                trigger_reason="im_request",
                background_reason=result.background_reason,
                force=True,
            )

    async def _poll_bm(self, bot: Any, iteration: int) -> None:
        pending = self.bm_pending
        if pending is None or not pending.task.done():
            return
        self.bm_pending = None
        try:
            guidance = pending.task.result()
            current = self.phase_resolver.resolve(self._quick_counts(bot))
            if current.revision != pending.revision:
                self.telemetry.event(
                    "bm_stale",
                    loop=iteration,
                    trigger_reason=pending.trigger_reason,
                )
                return
            self.directive_store.write(
                BMDirective(
                    pending.phase,
                    tuple(guidance),
                    pending.observation.loop,
                    pending.observation.loop + self.game_config.directive_ttl_loops,
                )
            )
            self.telemetry.event(
                "bm_accepted",
                loop=iteration,
                phase=pending.phase,
                trigger_reason=pending.trigger_reason,
                guidance=guidance,
                latency_ms=round((perf_counter() - pending.started_at) * 1000),
            )
            logger.info(
                "[BM tick={}] phase={} bm={:.2f}s trigger={}\n"
                "{}",
                pending.observation.loop,
                pending.phase,
                perf_counter() - pending.started_at,
                pending.trigger_reason,
                "\n".join(
                    f"  guidance[{index}]: {item}"
                    for index, item in enumerate(guidance, start=1)
                ),
            )
        except asyncio.CancelledError:
            self.telemetry.event("bm_cancelled", loop=iteration)
            logger.info("[BM tick={}] cancelled", iteration)
        except Exception as exc:
            self.telemetry.event("bm_failed", loop=iteration, error=str(exc))
            logger.warning("[BM tick={}] failed: {}", iteration, exc)

    async def _maybe_start_bm(
        self,
        observation: Observation,
        phase: str,
        revision: int,
        iteration: int,
        *,
        trigger_reason: str = "",
        background_reason: str = "",
        force: bool = False,
    ) -> None:
        if not self.enable_bm:
            return
        active_directive = self.directive_store.read(iteration)
        if not trigger_reason:
            if active_directive is None:
                trigger_reason = (
                    "cold_start"
                    if self._last_bm_started_loop < 0
                    else "guidance_expired"
                )
            elif (
                iteration - self._last_bm_started_loop
                >= self.game_config.bm_refresh_loops
            ):
                trigger_reason = "periodic_refresh"
            else:
                return

        if self.bm_pending is not None and not self.bm_pending.task.done():
            if not force:
                return
            self.bm_pending.task.cancel()
            self.telemetry.event(
                "bm_cancelled_for_im_request",
                loop=iteration,
                prior_reason=self.bm_pending.trigger_reason,
            )
            self.bm_pending = None

        if background_reason:
            trigger_reason = f"{trigger_reason}: {background_reason}"
        card_phase = self._card_phase(phase)
        task = asyncio.create_task(
            self.bm.run(
                observation.text,
                self.tactic,
                card_phase,
                trigger_reason,
                trace=self.telemetry,
                tick=observation.loop,
            )
        )
        self.bm_pending = PendingBM(
            task,
            observation,
            phase,
            revision,
            trigger_reason,
            perf_counter(),
        )
        self._last_bm_started_loop = iteration
        self.telemetry.event(
            "bm_started", loop=iteration, trigger_reason=trigger_reason
        )
        logger.info(
            "[BM tick={}] phase={} trigger={} started",
            observation.loop,
            phase,
            trigger_reason,
        )

    def cancel_background_tasks(self) -> None:
        if self.bm_pending is not None and not self.bm_pending.task.done():
            self.bm_pending.task.cancel()

    def _card_phase(self, phase_id: str) -> dict[str, Any]:
        return next(phase for phase in self.tactic["phases"] if phase["id"] == phase_id)

    @staticmethod
    def _quick_counts(bot: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for unit in list(bot.units) + list(bot.structures):
            name = getattr(unit.type_id, "name", "UNKNOWN")
            counts[name] = counts.get(name, 0) + 1
        for name in ("FACTORY", "STARPORT", "FUSIONCORE", "STARPORTTECHLAB"):
            try:
                from sc2.ids.unit_typeid import UnitTypeId

                counts[f"pending:{name}"] = int(
                    bot.already_pending(getattr(UnitTypeId, name))
                )
            except (AttributeError, KeyError):
                counts[f"pending:{name}"] = 0
        return counts
