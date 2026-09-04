"""Single-call tactical phase and Ares action agent."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from config.llm import LLMConfig
from llm.agents.prompts import model_messages
from llm.client import LLMClient
from llm.model_output import parse_model_payload
from llm.telemetry import Telemetry


@dataclass(frozen=True)
class ModelResult:
    phase: str | None
    actions: list[dict[str, Any]]
    validation_feedback: list[dict[str, Any]]
    request: list[dict[str, str]]
    reply: str
    previous_validation_feedback: list[dict[str, Any]]
    latency_ms: int


def _symbol_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(
        character for character in value.strip().casefold() if character.isalnum()
    )


class ModelAgent:
    def __init__(self, config: LLMConfig, llm_client: LLMClient):
        self.config = config
        self.llm_client = llm_client

    async def run(
        self,
        observation: str,
        tactic: dict[str, Any],
        action_entries: list[dict[str, Any]],
        previous_validation_feedback: list[dict[str, Any]] | None = None,
        trace: Telemetry | None = None,
        iteration: int | None = None,
        max_actions_per_decision: int = 6,
    ) -> ModelResult:
        messages = model_messages(
            observation,
            tactic,
            action_entries,
            previous_validation_feedback or [],
            max_actions_per_decision=max_actions_per_decision,
        )
        request_messages = self._request_messages(messages)
        started_at = perf_counter()
        response = ""
        try:
            response = await self.llm_client.complete(messages)
        except Exception as exc:
            latency_ms = round((perf_counter() - started_at) * 1000)
            if trace is not None:
                trace.model_conversation(
                    iteration=iteration,
                    request=request_messages,
                    reply=response,
                    previous_validation_feedback=(previous_validation_feedback or []),
                    valid=False,
                    error=str(exc),
                    latency_ms=latency_ms,
                )
            raise

        feedback: list[dict[str, Any]] = []
        try:
            payload = parse_model_payload(response)
        except Exception as exc:
            feedback.append(
                {
                    "kind": "output_format",
                    "submitted_output": response,
                    "error": str(exc),
                }
            )
            return ModelResult(
                None,
                [],
                feedback,
                request_messages,
                response,
                list(previous_validation_feedback or []),
                round((perf_counter() - started_at) * 1000),
            )

        feedback.extend(
            {
                "kind": "action_format",
                "action_index": error["index"] + 1,
                "submitted_action": error["submitted_action"],
                "error": error["error"],
            }
            for error in payload["errors"]
        )

        submitted_phase = payload.get("phase")
        phase_ids = {
            _symbol_key(item.get("id")): item.get("id")
            for item in tactic.get("phases", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        phase = phase_ids.get(_symbol_key(submitted_phase))
        if phase is None:
            feedback.append(
                {
                    "kind": "phase",
                    "submitted_phase": submitted_phase,
                    "error": "phase must identify a phase ID from the tactical reference",
                }
            )

        actions = payload["actions"]
        return ModelResult(
            phase,
            actions,
            feedback,
            request_messages,
            response,
            list(previous_validation_feedback or []),
            round((perf_counter() - started_at) * 1000),
        )

    def _request_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        prepare = getattr(self.llm_client, "prepare_messages", None)
        return prepare(messages) if callable(prepare) else messages
