"""IMBM foreground-IM / background-BM scheduler for python-sc2 iterations."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from loguru import logger

from agents.bm_agent import BMAgent, BMResult
from agents.correction_agent import CorrectionAgent
from agents.im_agent import IMAgent
from config.game import GameConfig
from config.llm import LLMConfig
from config.policy import allowed_actions
from core.action_exposure import BCRushActionExposure
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
    task: asyncio.Task[BMResult]
    observation: Observation
    trigger_reason: str
    started_at: float


class LLMGameController:
    """Make IM the only non-automatic foreground decision maker.

    ``run_iteration`` awaits IM on every decision iteration. The first enabled
    BM call is awaited before IM starts; later BM refreshes run in the background
    and can never register an Ares behavior themselves.
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
        bm_action_ids: set[str] = set()
        for tactic_phase in self.tactic["phases"]:
            bm_action_ids.update(allowed_actions(tactic_phase["id"]))
        self.bm_action_ids = bm_action_ids
        self.action_exposure = BCRushActionExposure(self.catalog)
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
            self.catalog, self.game_config.deferred_action_ttl_iterations
        )
        self.enable_bm = enable_bm
        self.bm_pending: PendingBM | None = None
        self._last_bm_started_iteration = -(10**9)

    @property
    def active(self) -> bool:
        """LLM control is valid only when it was enabled and fully configured."""
        return self.llm_config.configured

    async def run_iteration(self, bot: Any, iteration: int) -> None:
        """Run automation and the blocking IM decision on its iteration interval."""
        await self.automation.run(bot, iteration)
        await self._poll_bm(iteration)
        if (
            not self.active
            or iteration % self.game_config.im_interval_iterations != 0
        ):
            return

        phase_state = self.phase_resolver.resolve(self._quick_counts(bot))
        observation = self.observation_builder.build(bot, iteration, phase_state.id)

        # With BM enabled, the first directive is a startup gate. Later refreshes
        # remain asynchronous and the previous directive stays active meanwhile.
        bm_surface = self.action_exposure.build(
            bot, observation.context, self.bm_action_ids
        )
        await self._maybe_start_bm(observation, iteration, bm_surface.entries)
        directive = self.directive_store.read(iteration)
        if self.enable_bm and directive is None:
            await self._await_first_bm(
                observation, iteration, bm_surface.entries
            )
            directive = self.directive_store.read(iteration)
        phase = directive.phase if directive is not None else phase_state.id

        self.telemetry.observation(
            iteration=iteration,
            time=getattr(bot, "time_formatted", "00:00"),
            phase=phase,
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
                iteration=iteration,
                actions=expired_deferred,
            )
        if ready_deferred:
            self.adapter.compile_and_register(bot, ready_deferred, observation.context)
            self.observation_builder.record_registered_actions(ready_deferred)
            self.telemetry.event(
                "deferred_actions_registered",
                iteration=iteration,
                actions=ready_deferred,
            )

        guidance_source = "BM" if directive is not None else "none"
        guidance = list(directive.guidance) if directive is not None else []
        guidance_reference = (
            f"BM@{directive.issued_at_iteration}"
            if directive is not None
            else "none"
        )
        im_surface = self.action_exposure.build(
            bot, observation.context, allowed_actions(phase)
        )
        entries = im_surface.entries
        try:
            # This await is intentional: unlike BM, IM owns the foreground game
            # decision and its accepted actions are registered in this iteration.
            im_started_at = perf_counter()
            result = await self.im.run(
                observation.text,
                guidance,
                entries,
                lambda _actions: (True, "submitted for recoverable policy review"),
                trace=self.telemetry,
                iteration=iteration,
            )
            review = self.policy.review(
                bot, result.actions, observation.context, phase, im_surface
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
                        iteration=iteration,
                    )
                    repaired_review = self.policy.review(
                        bot, repaired_actions, observation.context, phase, im_surface
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
                        iteration=iteration,
                        error=str(correction_error),
                    )
            if review.normalizations:
                self.telemetry.event(
                    "im_actions_normalized",
                    iteration=iteration,
                    notes=review.normalizations,
                )
            if review.issues:
                self.telemetry.event(
                    "im_actions_omitted",
                    iteration=iteration,
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
                    iteration=iteration,
                    actions=queued_actions,
                    expires_after_iterations=(
                        self.game_config.deferred_action_ttl_iterations
                    ),
                )
            self.telemetry.event(
                "im_accepted",
                iteration=iteration,
                phase=phase,
                directive_age=directive.age(iteration) if directive else None,
                actions=immediate_actions,
                deferred_actions=queued_actions,
                request_background=result.request_background,
                latency_ms=round((perf_counter() - im_started_at) * 1000),
            )
            self.telemetry.accepted_decision(
                iteration=iteration,
                time=getattr(bot, "time_formatted", "00:00"),
                phase=phase,
                actions=immediate_actions,
                deferred_actions=queued_actions,
                guidance_source=guidance_source,
                guidance=guidance,
                request_background=result.request_background,
                background_reason=result.background_reason,
                latency_ms=round((perf_counter() - im_started_at) * 1000),
            )
            logger.info(
                "[IM iteration={}] t={} M={} G={} supply={}/{} phase={} im={:.2f}s\n"
                "  actions={} deferred={} guidance={}",
                iteration,
                getattr(bot, "time_formatted", "00:00"),
                int(bot.minerals),
                int(bot.vespene),
                int(bot.supply_used),
                int(bot.supply_cap),
                phase,
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
                "im_failed",
                iteration=iteration,
                error=str(exc),
                latency_ms=latency_ms,
            )
            self.observation_builder.record_validation_error(str(exc))
            logger.error(
                "[IM iteration={}] validation/request failed after {}ms: {}",
                iteration,
                latency_ms,
                exc,
            )
            return

        if self.enable_bm and result.request_background:
            self.telemetry.event(
                "im_background_request_noted",
                iteration=iteration,
                reason=result.background_reason,
                scheduling="periodic_refresh_only",
            )

    async def _await_first_bm(
        self,
        observation: Observation,
        iteration: int,
        action_entries: list[dict[str, Any]],
    ) -> None:
        """Keep the first IM decision blocked until BM yields a valid directive."""
        while self.directive_store.read(iteration) is None:
            await self._maybe_start_bm(observation, iteration, action_entries)
            if self.bm_pending is None:
                return
            await self._await_pending_bm(iteration)
            if self.directive_store.read(iteration) is None:
                await asyncio.sleep(0.5)

    async def _await_pending_bm(self, iteration: int) -> None:
        pending = self.bm_pending
        if pending is None:
            return
        await asyncio.gather(pending.task, return_exceptions=True)
        await self._poll_bm(iteration)

    async def _poll_bm(self, iteration: int) -> None:
        pending = self.bm_pending
        if pending is None or not pending.task.done():
            return
        self.bm_pending = None
        try:
            result = pending.task.result()
            self.directive_store.write(
                BMDirective(
                    result.phase,
                    tuple(result.guidance),
                    pending.observation.iteration,
                    pending.observation.iteration
                    + self.game_config.directive_ttl_iterations,
                )
            )
            self.telemetry.event(
                "bm_accepted",
                iteration=iteration,
                phase=result.phase,
                trigger_reason=pending.trigger_reason,
                guidance=result.guidance,
                latency_ms=round((perf_counter() - pending.started_at) * 1000),
            )
            logger.info(
                "[BM iteration={}] phase={} bm={:.2f}s trigger={}\n"
                "{}",
                pending.observation.iteration,
                result.phase,
                perf_counter() - pending.started_at,
                pending.trigger_reason,
                "\n".join(
                    f"  guidance[{index}]: {item}"
                    for index, item in enumerate(result.guidance, start=1)
                ),
            )
        except asyncio.CancelledError:
            self.telemetry.event("bm_cancelled", iteration=iteration)
            logger.info("[BM iteration={}] cancelled", iteration)
        except Exception as exc:
            self.telemetry.event("bm_failed", iteration=iteration, error=str(exc))
            logger.warning("[BM iteration={}] failed: {}", iteration, exc)

    async def _maybe_start_bm(
        self,
        observation: Observation,
        iteration: int,
        action_entries: list[dict[str, Any]],
        *,
        trigger_reason: str = "",
    ) -> None:
        if not self.enable_bm:
            return
        active_directive = self.directive_store.read(iteration)
        if not trigger_reason:
            if active_directive is None:
                trigger_reason = (
                    "cold_start"
                    if self._last_bm_started_iteration < 0
                    else "guidance_expired"
                )
            elif (
                iteration - self._last_bm_started_iteration
                >= self.game_config.bm_refresh_iterations
            ):
                trigger_reason = "periodic_refresh"
            else:
                return

        if self.bm_pending is not None and not self.bm_pending.task.done():
            return

        task = asyncio.create_task(
            self.bm.run(
                observation.text,
                self.tactic,
                action_entries,
                trigger_reason,
                trace=self.telemetry,
                iteration=observation.iteration,
            )
        )
        self.bm_pending = PendingBM(
            task,
            observation,
            trigger_reason,
            perf_counter(),
        )
        self._last_bm_started_iteration = iteration
        self.telemetry.event(
            "bm_started", iteration=iteration, trigger_reason=trigger_reason
        )
        logger.info(
            "[BM iteration={}] trigger={} started",
            observation.iteration,
            trigger_reason,
        )

    def cancel_background_tasks(self) -> None:
        if self.bm_pending is not None and not self.bm_pending.task.done():
            self.bm_pending.task.cancel()

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
