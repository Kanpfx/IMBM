"""Single-IM scheduler for python-sc2 iterations."""

from __future__ import annotations

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
from game.observation.builder import Observation, ObservationBuilder
from game.observation.state import TagIdMapper
from knowledge.loader import ActionCatalog, load_tactic
from llm.agents.im_agent import IMAgent
from llm.client import LLMClient
from llm.telemetry import Telemetry


class LLMGameController:
    """Make one IM request for every non-automatic decision cycle."""

    def __init__(
        self,
        game_config: GameConfig | None = None,
        llm_config: LLMConfig | None = None,
        *,
        tactic_name: str = "BattleCruiserRush",
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
        self.telemetry = Telemetry(
            {
                "model": self.llm_config.model,
                "temperature": self.llm_config.temperature,
                "max_tokens": self.llm_config.max_tokens,
                "action_interval_iterations": self.game_config.im_interval_iterations,
                "tactic": tactic_name,
                **(run_metadata or {}),
            },
            directory=log_directory,
        )
        self.client = LLMClient(self.llm_config)
        self.im = IMAgent(self.llm_config, self.client)
        self.deferred_actions = DeferredActionQueue(
            self.catalog,
            self.game_config.deferred_action_ttl_iterations,
            self.game_config.resource_queue_mineral_tolerance,
            self.game_config.resource_queue_vespene_tolerance,
        )
        self.persistent_actions = PersistentActionRegistry(
            self.catalog, self.game_config.persistent_action_iterations
        )
        self._previous_validation_feedback: list[dict[str, Any]] = []

    @property
    def active(self) -> bool:
        """LLM control is valid only when the model endpoint is configured."""
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
        if not self.active or iteration % self.game_config.im_interval_iterations != 0:
            self.automation.register_worker_production(bot)
            return

        observation = self.observation_builder.build(bot, iteration)

        self.telemetry.observation(
            iteration=iteration,
            time=getattr(bot, "time_formatted", "00:00"),
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

        im_surface = self.action_exposure.build(bot, observation.context)
        entries = im_surface.entries
        try:
            im_started_at = perf_counter()
            result = await self.im.run(
                observation.text,
                self.tactic,
                entries,
                self._previous_validation_feedback,
                trace=self.telemetry,
                iteration=iteration,
            )
            phase = result.phase or "unassigned"
            review = self._review_im_actions(
                bot,
                result.actions,
                observation,
                im_surface,
            )
            validation_feedback = self._replace_validation_feedback(
                result.validation_feedback, review.issues
            )
            self.telemetry.im_conversation(
                iteration=iteration,
                request=result.request,
                reply=result.reply,
                previous_validation_feedback=result.previous_validation_feedback,
                valid=not validation_feedback,
                phase=phase,
                actions=result.actions,
                validation_feedback=validation_feedback,
                latency_ms=result.latency_ms,
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
            if validation_feedback:
                self.telemetry.event(
                    "im_validation_feedback",
                    iteration=iteration,
                    feedback=validation_feedback,
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
                validation_feedback=validation_feedback,
                latency_ms=round((perf_counter() - im_started_at) * 1000),
            )
            readable_actions = immediate_actions + queued_actions
            display_latency = perf_counter() - im_started_at
            readable_header = (
                f"[IM iteration={iteration}] "
                f"t={getattr(bot, 'time_formatted', '00:00')} "
                f"M={int(bot.minerals)} G={int(bot.vespene)} "
                f"supply={int(bot.supply_used)}/{int(bot.supply_cap)} "
                f"phase={phase} im={display_latency:.2f}s"
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

    def _review_im_actions(
        self,
        bot: Any,
        actions: list[dict[str, Any]],
        observation: Observation,
        surface: Any,
    ) -> ActionReview:
        """Keep valid actions and report rejected actions for the next turn."""
        initial = self.policy.review(bot, actions, observation.context, surface)
        accepted = list(initial.actions)
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

        return ActionReview(
            accepted[:limit],
            list(initial.issues) + overflow_issues,
            initial.normalizations,
        )

    def _replace_validation_feedback(
        self,
        output_feedback: list[dict[str, Any]],
        action_issues: list[ValidationIssue],
    ) -> list[dict[str, Any]]:
        """Replace the prior turn's feedback with errors from this turn."""
        feedback = list(output_feedback)
        feedback.extend(
            {
                "kind": "action",
                "action": issue.action,
                "error": issue.text(),
            }
            for issue in action_issues
        )
        self._previous_validation_feedback = feedback
        return feedback

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
