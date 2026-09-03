"""Single-call tactical phase and Ares action agent."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from llm.agents.base_agent import BaseAgent
from llm.agents.prompts import im_messages
from llm.json_tools import parse_im_payload
from llm.telemetry import Telemetry


@dataclass(frozen=True)
class IMResult:
    phase: str | None
    actions: list[dict[str, Any]]
    validation_feedback: list[dict[str, Any]]
    request: list[dict[str, str]]
    reply: str
    previous_validation_feedback: list[dict[str, Any]]
    latency_ms: int


class IMAgent(BaseAgent):
    async def run(
        self,
        observation: str,
        tactic: dict[str, Any],
        action_entries: list[dict[str, Any]],
        previous_validation_feedback: list[dict[str, Any]] | None = None,
        trace: Telemetry | None = None,
        iteration: int | None = None,
    ) -> IMResult:
        messages = im_messages(
            observation,
            tactic,
            action_entries,
            previous_validation_feedback or [],
        )
        request_messages = self._request_messages(messages)
        started_at = perf_counter()
        response = ""
        try:
            response = await self.llm_client.complete(messages)
        except Exception as exc:
            latency_ms = round((perf_counter() - started_at) * 1000)
            if trace is not None:
                trace.im_conversation(
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
            payload = parse_im_payload(response)
        except Exception as exc:
            feedback.append(
                {
                    "kind": "output_format",
                    "submitted_output": response,
                    "error": str(exc),
                }
            )
            return IMResult(
                None,
                [],
                feedback,
                request_messages,
                response,
                list(previous_validation_feedback or []),
                round((perf_counter() - started_at) * 1000),
            )

        submitted_phase = payload.get("phase")
        phase_ids = {
            phase.get("id")
            for phase in tactic.get("phases", [])
            if isinstance(phase, dict)
        }
        phase = submitted_phase if submitted_phase in phase_ids else None
        if phase is None:
            feedback.append(
                {
                    "kind": "phase",
                    "submitted_phase": submitted_phase,
                    "error": "phase must be an exact phase ID from the tactical reference",
                }
            )

        actions = payload["actions"]
        return IMResult(
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
