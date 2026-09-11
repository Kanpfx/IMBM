"""Single-model scheduler for python-sc2 iterations."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from loguru import logger

from config.game import GameConfig
from config.llm import LLMConfig
from game.actions.adapter import AresActionAdapter
from game.actions.deferred import DeferredActionQueue
from game.actions.errors import ResourceError
from game.actions.exposure import ActionExposure
from game.actions.formatting import format_feedback, format_indexed_actions
from game.actions.persistent import PersistentActionRegistry
from game.actions.policy import ActionReview, PolicyValidator, ValidationIssue
from game.control.automation import AutomationController
from game.observation.builder import Observation, ObservationBuilder
from game.observation.state import TagIdMapper
from knowledge.loader import ActionCatalog, load_tactic
from llm.agents.model_agent import ModelAgent
from llm.client import LLMClient
from llm.telemetry import Telemetry


class LLMGameController:
    """Make one model request for every non-automatic decision cycle."""

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
                "action_interval_iterations": self.game_config.model_interval_iterations,
                "tactic": tactic_name,
                **(run_metadata or {}),
            },
            directory=log_directory,
        )
        self.client = LLMClient(self.llm_config)
        self.model_agent = ModelAgent(self.llm_config, self.client)
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
        """Run automation and the blocking model decision on its iteration interval."""
        await self.automation.run(bot, iteration)
        try:
            self.observation_builder.collect_frame(bot)
            self._run_persistent_actions(bot, iteration)
            if (
                not self.active
                or iteration % self.game_config.model_interval_iterations != 0
            ):
                return
            await self._run_model_decision(bot, iteration)
        finally:
            self.automation.register_worker_production(bot)

    async def _run_model_decision(self, bot: Any, iteration: int) -> None:
        model_started_at = perf_counter()
        game_time = getattr(bot, "time_formatted", "--:--")
        try:
            observation = self.observation_builder.build(bot, iteration)
            self.telemetry.observation(
                iteration=iteration,
                time=getattr(bot, "time_formatted", "00:00"),
                observation=observation.text,
            )
            self._process_deferred_actions(bot, iteration, observation, game_time)
            model_surface = self.action_exposure.build(bot, observation.context)
            available_actions = model_surface.entries
            result = await self.model_agent.run(
                observation.text,
                self.tactic,
                available_actions,
                self._previous_validation_feedback,
                trace=self.telemetry,
                iteration=iteration,
                max_actions_per_decision=(self.game_config.max_actions_per_decision),
            )
            phase = result.phase or "unassigned"
            action_review = self._review_model_actions(
                bot,
                result.actions,
                observation,
                model_surface,
            )
            validation_feedback = self._replace_validation_feedback(
                result.validation_feedback, action_review.issues
            )
            self.telemetry.model_conversation(
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
            if action_review.normalizations:
                self.telemetry.event(
                    "model_actions_normalized",
                    iteration=iteration,
                    notes=action_review.normalizations,
                )
            if action_review.issues:
                self.telemetry.event(
                    "model_actions_omitted",
                    iteration=iteration,
                    errors=[issue.text() for issue in action_review.issues],
                    actions=[issue.action for issue in action_review.issues],
                )
            if validation_feedback:
                self.telemetry.event(
                    "model_validation_feedback",
                    iteration=iteration,
                    feedback=validation_feedback,
                )

            immediate_actions, queued_actions = self._dispatch_actions(
                bot,
                iteration,
                action_review,
                observation,
                game_time,
            )
            await self._publish_decision(
                bot,
                iteration,
                phase,
                immediate_actions,
                queued_actions,
                validation_feedback,
                model_started_at,
            )
        except Exception as exc:
            latency_ms = round((perf_counter() - model_started_at) * 1000)
            self.telemetry.event(
                "model_failed",
                iteration=iteration,
                error=str(exc),
                latency_ms=latency_ms,
            )
            logger.error(
                "[model iteration={}] validation/request failed after {}ms: {}\n",
                iteration,
                latency_ms,
                exc,
            )
            self._clear_worker_override(game_time)

    def _run_persistent_actions(self, bot: Any, iteration: int) -> None:
        context = self.observation_builder.execution_context(bot)
        expired, failed = self.persistent_actions.run(
            bot, iteration, self.adapter, context
        )
        game_time = getattr(bot, "time_formatted", "--:--")
        if expired:
            self.observation_builder.record_expired_actions(expired, game_time)
        if failed:
            self.observation_builder.record_failed_actions(failed, game_time)
            self.telemetry.event(
                "persistent_actions_failed",
                iteration=iteration,
                actions=failed,
            )

    def _process_deferred_actions(
        self,
        bot: Any,
        iteration: int,
        observation: Observation,
        game_time: str,
    ) -> None:
        ready, expired = self.deferred_actions.pop_ready(bot, iteration)
        if expired:
            self.observation_builder.record_expired_actions(expired, game_time)
            self.telemetry.event(
                "deferred_actions_expired",
                iteration=iteration,
                actions=expired,
            )
        if not ready:
            return

        self.adapter.compile_and_register(bot, ready, observation.context)
        persistent = [
            action for action in ready if self.persistent_actions.is_persistent(action)
        ]
        completed = [
            action
            for action in ready
            if not self.persistent_actions.is_persistent(action)
        ]
        for action in persistent:
            self.persistent_actions.remember(action, iteration)
        if persistent:
            self.observation_builder.record_active_actions(persistent, game_time)
        if completed:
            self.observation_builder.record_registered_actions(completed, game_time)
        self.telemetry.event(
            "deferred_actions_registered",
            iteration=iteration,
            actions=ready,
        )

    def _dispatch_actions(
        self,
        bot: Any,
        iteration: int,
        action_review: ActionReview,
        observation: Observation,
        game_time: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        worker_override: dict[str, Any] | None = None
        direct_actions: list[dict[str, Any]] = []
        immediate_actions: list[dict[str, Any]] = []
        queued_actions: list[dict[str, Any]] = []
        blocked_actions: list[dict[str, Any]] = []

        for action in action_review.actions:
            action_id = self.catalog.get(action["id"])["id"]
            if action_id == "macro.build_workers":
                if worker_override is None:
                    worker_override = action
                    immediate_actions.append(action)
                continue
            resource_status = self.deferred_actions.resource_status(bot, action)
            if resource_status == DeferredActionQueue.QUEUED:
                if self.deferred_actions.enqueue(action, iteration):
                    queued_actions.append(action)
            elif resource_status == DeferredActionQueue.BLOCKED:
                blocked_actions.append(action)
            else:
                direct_actions.append(action)
                immediate_actions.append(action)

        previous_override, override_changed = self.automation.replace_worker_override(
            worker_override
        )
        if override_changed and previous_override is not None:
            self.observation_builder.record_expired_actions(
                [previous_override], game_time
            )
        if direct_actions:
            self.adapter.compile_and_register(bot, direct_actions, observation.context)

        active_actions = (
            [worker_override]
            if worker_override is not None and override_changed
            else []
        ) + [
            action
            for action in direct_actions
            if self.persistent_actions.is_persistent(action)
        ]
        completed_actions = [
            action
            for action in direct_actions
            if not self.persistent_actions.is_persistent(action)
        ]
        for action in active_actions:
            self.persistent_actions.remember(action, iteration)
        if active_actions:
            self.observation_builder.record_active_actions(active_actions, game_time)
        if completed_actions:
            self.observation_builder.record_registered_actions(
                completed_actions, game_time
            )
        if queued_actions:
            self.observation_builder.record_deferred_actions(queued_actions, game_time)
            self.telemetry.event(
                "model_actions_deferred",
                iteration=iteration,
                actions=queued_actions,
                expires_after_iterations=(
                    self.game_config.deferred_action_ttl_iterations
                ),
            )
        if blocked_actions:
            self.observation_builder.record_failed_actions(blocked_actions, game_time)
            self.telemetry.event(
                "model_actions_resource_blocked",
                iteration=iteration,
                actions=blocked_actions,
                errors=[
                    str(ResourceError.insufficient(action.get("id")))
                    for action in blocked_actions
                ],
            )
        return immediate_actions, queued_actions

    def _clear_worker_override(self, game_time: str) -> None:
        previous_override, changed = self.automation.replace_worker_override(None)
        if changed and previous_override is not None:
            self.observation_builder.record_expired_actions(
                [previous_override], game_time
            )

    async def _publish_decision(
        self,
        bot: Any,
        iteration: int,
        phase: str,
        immediate_actions: list[dict[str, Any]],
        queued_actions: list[dict[str, Any]],
        validation_feedback: list[dict[str, Any]],
        started_at: float,
    ) -> None:
        elapsed_s = perf_counter() - started_at
        latency_ms = round(elapsed_s * 1000)
        self.telemetry.accepted_decision(
            iteration=iteration,
            time=getattr(bot, "time_formatted", "00:00"),
            phase=phase,
            actions=immediate_actions,
            deferred_actions=queued_actions,
            validation_feedback=validation_feedback,
            latency_ms=latency_ms,
        )
        displayed_actions = immediate_actions + queued_actions
        decision_header = (
            f"[model iteration={iteration}] "
            f"t={getattr(bot, 'time_formatted', '00:00')} "
            f"M={int(bot.minerals)} G={int(bot.vespene)} "
            f"supply={int(bot.supply_used)}/{int(bot.supply_cap)} "
            f"phase={phase} model={elapsed_s:.2f}s"
        )
        await self._chat_model_decision(bot, decision_header, displayed_actions)
        action_lines = "\n".join(
            f"  {line}" for line in format_indexed_actions(displayed_actions)
        )
        logger.info("{}\n{}\n", decision_header, action_lines)
        if validation_feedback:
            logger.warning("Validation feedback:\n{}", format_feedback(validation_feedback))

    def _review_model_actions(
        self,
        bot: Any,
        actions: list[dict[str, Any]],
        observation: Observation,
        surface: Any,
    ) -> ActionReview:
        """Keep valid actions and report rejected actions for the next turn."""
        return self.policy.review(bot, actions, observation.context, surface)

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
    async def _chat_model_decision(
        bot: Any, header: str, actions: list[dict[str, Any]]
    ) -> None:
        """Publish readable model output without affecting decision execution."""
        try:
            await bot.chat_send(header, team_only=True)
            for line in format_indexed_actions(actions):
                chat_line = line if len(line) <= 240 else f"{line[:237]}..."
                await bot.chat_send(chat_line, team_only=True)
        except Exception as exc:
            logger.warning("{} chat output failed: {}\n", header, exc)
