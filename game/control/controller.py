"""IMBM foreground-IM / background-BM scheduler for python-sc2 iterations."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from loguru import logger

from config.game import GameConfig
from config.llm import LLMConfig
from game.actions.adapter import AresActionAdapter
from game.actions.deferred import DeferredActionQueue
from game.actions.errors import InstructionError, ResourceError
from game.actions.exposure import ActionExposure
from game.actions.formatting import format_indexed_actions
from game.actions.persistent import PersistentActionRegistry
from game.actions.policy import ActionReview, PolicyValidator, ValidationIssue
from game.control.automation import AutomationController
from game.control.directive import BMDirective, DirectiveStore
from game.observation.builder import Observation, ObservationBuilder
from game.observation.state import TagIdMapper
from knowledge.loader import ActionCatalog, load_tactic, normalize_catalog_name
from llm.agents.bm_agent import BMAgent, BMResult
from llm.agents.correction_agent import CorrectionAgent
from llm.agents.im_agent import IMAgent
from llm.client import LLMClient
from llm.telemetry import Telemetry


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
        tactic_name: str = "BattleCruiserRush",
        enable_bm: bool = False,
        run_metadata: dict[str, Any] | None = None,
        log_directory: Path | None = None,
    ):
        self.game_config = game_config or GameConfig()
        self.llm_config = llm_config or LLMConfig.from_env()
        self.tactic = load_tactic(tactic_name)
        self.catalog = ActionCatalog.load()
        self.action_exposure = ActionExposure(self.catalog)
        self.adapter = AresActionAdapter(self.catalog)
        self.policy = PolicyValidator(self.catalog, self.game_config)
        self.observation_builder = ObservationBuilder(TagIdMapper())
        self.automation = AutomationController()
        self.directive_store = DirectiveStore()
        self.telemetry = Telemetry(
            {
                "model": self.llm_config.model,
                "temperature": self.llm_config.temperature,
                "max_tokens": self.llm_config.max_tokens,
                "max_correction_attempts": min(
                    2, max(0, self.llm_config.max_refines)
                ),
                "action_interval_iterations": self.game_config.im_interval_iterations,
                "strategy_refresh_iterations": self.game_config.bm_refresh_iterations,
                "strategic_planning_enabled": enable_bm,
                "tactic": tactic_name,
                **(run_metadata or {}),
            },
            directory=log_directory,
        )
        self.client = LLMClient(self.llm_config)
        self.bm = BMAgent(self.llm_config, self.client)
        self.im = IMAgent(self.llm_config, self.client)
        self.corrector = CorrectionAgent(self.llm_config, self.client)
        self.deferred_actions = DeferredActionQueue(
            self.catalog,
            self.game_config.deferred_action_ttl_iterations,
            self.game_config.resource_queue_mineral_tolerance,
            self.game_config.resource_queue_vespene_tolerance,
        )
        self.persistent_actions = PersistentActionRegistry(
            self.catalog, self.game_config.persistent_action_iterations
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
        self.observation_builder.collect_frame(bot)
        persistent_context = self.observation_builder.execution_context(bot)
        completed_persistent, failed_persistent = self.persistent_actions.run(
            bot, iteration, self.adapter, persistent_context
        )
        current_time = getattr(bot, "time_formatted", "--:--")
        if completed_persistent:
            self.observation_builder.record_completed_actions(
                completed_persistent, current_time
            )
        if failed_persistent:
            self.observation_builder.record_failed_actions(
                failed_persistent, current_time
            )
            self.telemetry.event(
                "persistent_actions_failed",
                iteration=iteration,
                actions=failed_persistent,
            )
        await self._poll_bm(iteration)
        if not self.active or iteration % self.game_config.im_interval_iterations != 0:
            self.automation.register_worker_production(bot)
            return

        observation = self.observation_builder.build(bot, iteration)

        # With BM enabled, the first directive is a startup gate. Later refreshes
        # remain asynchronous and the previous directive stays active meanwhile.
        bm_surface = self.action_exposure.build(bot, observation.context)
        await self._maybe_start_bm(observation, iteration, bm_surface.entries)
        directive = self.directive_store.read(iteration)
        if self.enable_bm and directive is None:
            await self._await_first_bm(observation, iteration, bm_surface.entries)
            directive = self.directive_store.read(iteration)
        # Phase IDs are tactic data interpreted exclusively by BM. The runtime
        # stores the selected ID but never derives or assigns semantics to it.
        phase = directive.phase if directive is not None else "unassigned"

        self.telemetry.observation(
            iteration=iteration,
            time=getattr(bot, "time_formatted", "00:00"),
            phase=phase,
            observation=observation.text,
        )

        ready_deferred, expired_deferred = self.deferred_actions.pop_ready(
            bot, iteration
        )
        if expired_deferred:
            self.observation_builder.record_expired_actions(
                expired_deferred, getattr(bot, "time_formatted", "--:--")
            )
            self.telemetry.event(
                "deferred_actions_expired",
                iteration=iteration,
                actions=expired_deferred,
            )
        if ready_deferred:
            self.adapter.compile_and_register(bot, ready_deferred, observation.context)
            persistent_ready = [
                action
                for action in ready_deferred
                if self.persistent_actions.is_persistent(action)
            ]
            completed_ready = [
                action
                for action in ready_deferred
                if not self.persistent_actions.is_persistent(action)
            ]
            for action in persistent_ready:
                self.persistent_actions.remember(action, iteration)
            if persistent_ready:
                self.observation_builder.record_active_actions(
                    persistent_ready, current_time
                )
            if completed_ready:
                self.observation_builder.record_registered_actions(
                    completed_ready, current_time
                )
            self.telemetry.event(
                "deferred_actions_registered",
                iteration=iteration,
                actions=ready_deferred,
            )

        guidance = list(directive.guidance) if directive is not None else []
        guidance_reference = (
            f"BM@{directive.issued_at_iteration}" if directive is not None else "none"
        )
        im_surface = self.action_exposure.build(bot, observation.context)
        entries = im_surface.entries
        try:
            # This await is intentional: unlike BM, IM owns the foreground game
            # decision and its accepted actions are registered in this iteration.
            im_started_at = perf_counter()
            result = await self.im.run(
                observation.text,
                guidance,
                entries,
                lambda _actions: (True, ""),
                trace=self.telemetry,
                iteration=iteration,
            )
            review = await self._review_im_actions(
                bot,
                result.actions,
                observation,
                guidance,
                entries,
                im_surface,
                iteration,
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

            worker_override: dict[str, Any] | None = None
            direct_immediate_actions: list[dict[str, Any]] = []
            immediate_actions: list[dict[str, Any]] = []
            queued_actions: list[dict[str, Any]] = []
            resource_blocked_actions: list[dict[str, Any]] = []
            for action in review.actions:
                action_id = self.catalog.get(action["id"])["id"]
                if action_id == "macro.build_workers":
                    # Automation owns worker production. The first valid IM
                    # target silently overrides its default for this cycle.
                    if worker_override is None:
                        worker_override = action
                        immediate_actions.append(action)
                    continue
                resource_status = self.deferred_actions.resource_status(bot, action)
                if resource_status == DeferredActionQueue.QUEUED:
                    if self.deferred_actions.enqueue(action, iteration):
                        queued_actions.append(action)
                elif resource_status == DeferredActionQueue.BLOCKED:
                    resource_blocked_actions.append(action)
                else:
                    direct_immediate_actions.append(action)
                    immediate_actions.append(action)
            (
                previous_worker_override,
                worker_override_changed,
            ) = self.automation.replace_worker_override(worker_override)
            if worker_override_changed and previous_worker_override is not None:
                self.observation_builder.record_completed_actions(
                    [previous_worker_override], current_time
                )
            if direct_immediate_actions:
                self.adapter.compile_and_register(
                    bot, direct_immediate_actions, observation.context
                )
            if immediate_actions:
                active_actions = (
                    [worker_override]
                    if worker_override is not None and worker_override_changed
                    else []
                ) + [
                    action
                    for action in direct_immediate_actions
                    if self.persistent_actions.is_persistent(action)
                ]
                completed_actions = [
                    action
                    for action in direct_immediate_actions
                    if not self.persistent_actions.is_persistent(action)
                ]
                for action in active_actions:
                    self.persistent_actions.remember(action, iteration)
                if active_actions:
                    self.observation_builder.record_active_actions(
                        active_actions, current_time
                    )
                if completed_actions:
                    self.observation_builder.record_registered_actions(
                        completed_actions, current_time
                    )
            if queued_actions:
                self.observation_builder.record_deferred_actions(
                    queued_actions, getattr(bot, "time_formatted", "--:--")
                )
                self.telemetry.event(
                    "im_actions_deferred",
                    iteration=iteration,
                    actions=queued_actions,
                    expires_after_iterations=(
                        self.game_config.deferred_action_ttl_iterations
                    ),
                )
            if resource_blocked_actions:
                self.observation_builder.record_failed_actions(
                    resource_blocked_actions, current_time
                )
                self.telemetry.event(
                    "im_actions_resource_blocked",
                    iteration=iteration,
                    actions=resource_blocked_actions,
                    errors=[
                        str(ResourceError.insufficient(action.get("id")))
                        for action in resource_blocked_actions
                    ],
                )
            self.telemetry.accepted_decision(
                iteration=iteration,
                time=getattr(bot, "time_formatted", "00:00"),
                phase=phase,
                actions=immediate_actions,
                deferred_actions=queued_actions,
                latency_ms=round((perf_counter() - im_started_at) * 1000),
            )
            readable_actions = immediate_actions + queued_actions
            display_latency = perf_counter() - im_started_at
            readable_header = (
                f"[IM iteration={iteration}] "
                f"t={getattr(bot, 'time_formatted', '00:00')} "
                f"M={int(bot.minerals)} G={int(bot.vespene)} "
                f"supply={int(bot.supply_used)}/{int(bot.supply_cap)} "
                f"phase={phase} im={display_latency:.2f}s "
                f"guidance={guidance_reference}"
            )
            await self._chat_im_decision(bot, readable_header, readable_actions)
            action_lines = "\n".join(
                f"  {line}" for line in format_indexed_actions(readable_actions)
            )
            logger.info("{}\n{}\n", readable_header, action_lines)
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
            logger.error(
                "[IM iteration={}] validation/request failed after {}ms: {}\n",
                iteration,
                latency_ms,
                exc,
            )
            self.automation.register_worker_production(bot)
            return

        self.automation.register_worker_production(bot)

    async def _review_im_actions(
        self,
        bot: Any,
        actions: list[dict[str, Any]],
        observation: Observation,
        guidance: list[str],
        entries: list[dict[str, Any]],
        surface: Any,
        iteration: int,
    ) -> ActionReview:
        """Keep valid actions and retry only rejected actions up to two times."""
        initial = self.policy.review(bot, actions, observation.context, surface)
        accepted = list(initial.actions)
        pending = list(initial.issues)
        discarded: list[ValidationIssue] = []
        normalizations = list(initial.normalizations)

        correction_attempts = min(2, max(0, self.llm_config.max_refines))
        for attempt in range(1, correction_attempts + 1):
            if not pending:
                break
            proposed = [issue.action for issue in pending]
            try:
                repaired_actions = await self.corrector.run(
                    observation.text,
                    guidance,
                    entries,
                    proposed,
                    [issue.text() for issue in pending],
                    attempt=attempt,
                    trace=self.telemetry,
                    iteration=iteration,
                )
            except Exception as correction_error:
                break

            returned = Counter(
                self._correction_action_key(action) for action in repaired_actions
            )
            for issue in pending:
                key = self._correction_action_key(issue.action)
                if returned[key] > 0:
                    returned[key] -= 1
                else:
                    discarded.append(issue)

            repaired_review = self.policy.review(
                bot,
                repaired_actions,
                observation.context,
                surface,
            )
            accepted.extend(repaired_review.actions)
            normalizations.extend(repaired_review.normalizations)
            pending = list(repaired_review.issues)

        discarded.extend(pending)
        limit = self.game_config.max_actions_per_decision
        overflow = accepted[limit:]
        overflow_issues = [
            ValidationIssue(
                len(actions) + index,
                action,
                str(
                    InstructionError(
                        "action limit exceeded",
                        f"at most {limit} actions may be executed in one decision",
                    )
                ),
            )
            for index, action in enumerate(overflow)
        ]

        # Re-review the merged list so corrected actions cannot conflict with
        # valid siblings retained from the original response.
        final_review = self.policy.review(
            bot,
            accepted[:limit],
            observation.context,
            surface,
        )
        normalizations.extend(final_review.normalizations)
        return ActionReview(
            final_review.actions,
            discarded + overflow_issues + final_review.issues,
            list(dict.fromkeys(normalizations)),
        )

    def _correction_action_key(self, action: Any) -> str:
        action_id = action.get("id") if isinstance(action, dict) else None
        if not isinstance(action_id, str):
            return ""
        try:
            return self.catalog.get(action_id)["id"]
        except ValueError:
            return normalize_catalog_name(action_id)

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
            )
            logger.info(
                "[BM iteration={}] phase={} bm={:.2f}s trigger={}\n{}\n",
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
            logger.info("[BM iteration={}] cancelled\n", iteration)
        except Exception as exc:
            self.telemetry.event("bm_failed", iteration=iteration, error=str(exc))
            logger.warning("[BM iteration={}] failed: {}\n", iteration, exc)

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
            "[BM iteration={}] trigger={} started\n",
            observation.iteration,
            trigger_reason,
        )

    @staticmethod
    async def _chat_im_decision(
        bot: Any, header: str, actions: list[dict[str, Any]]
    ) -> None:
        """Publish readable IM output without affecting decision execution."""
        try:
            await bot.chat_send(header, team_only=True)
            for line in format_indexed_actions(actions):
                chat_line = line if len(line) <= 240 else f"{line[:237]}..."
                await bot.chat_send(chat_line, team_only=True)
        except Exception as exc:
            logger.warning("{} chat output failed: {}\n", header, exc)

    def cancel_background_tasks(self) -> None:
        if self.bm_pending is not None and not self.bm_pending.task.done():
            self.bm_pending.task.cancel()
