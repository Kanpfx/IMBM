"""Low-frequency BM producing only phase and guidance."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from llm.agents.base_agent import BaseAgent
from llm.agents.prompts import bm_messages
from llm.json_tools import parse_json_object
from llm.telemetry import Telemetry


@dataclass(frozen=True)
class BMResult:
    phase: str
    guidance: tuple[str, ...]


class BMAgent(BaseAgent):
    async def run(
        self,
        observation: str,
        tactic: dict[str, Any],
        action_entries: list[dict[str, Any]],
        trigger_reason: str = "",
        trace: Telemetry | None = None,
        iteration: int | None = None,
    ) -> BMResult:
        messages = bm_messages(observation, tactic, action_entries, trigger_reason)
        request_messages = self._request_messages(messages)
        response = ""
        started_at = perf_counter()
        try:
            response = await self.llm_client.complete(messages)
            payload = parse_json_object(response)
            phase = payload.get("phase")
            phase_ids = {item["id"] for item in tactic["phases"]}
            if phase not in phase_ids:
                raise ValueError("BM phase must be an ID from the tactical card")
            guidance = payload.get("guidance")
            if (
                not isinstance(guidance, list)
                or not guidance
                or not all(isinstance(item, str) and item.strip() for item in guidance)
            ):
                raise ValueError("BM guidance must contain non-empty strings")
            cleaned = [item.strip() for item in guidance]
            if trace is not None:
                trace.bm_conversation(
                    iteration=iteration,
                    trigger_reason=trigger_reason,
                    request=request_messages,
                    reply=response,
                    valid=True,
                    phase=phase,
                    guidance=cleaned,
                    latency_ms=round((perf_counter() - started_at) * 1000),
                )
            return BMResult(phase, tuple(cleaned))
        except Exception as exc:
            if trace is not None:
                trace.bm_conversation(
                    iteration=iteration,
                    trigger_reason=trigger_reason,
                    request=request_messages,
                    reply=response,
                    valid=False,
                    validation=str(exc),
                    latency_ms=round((perf_counter() - started_at) * 1000),
                )
            raise

    def _request_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        prepare = getattr(self.llm_client, "prepare_messages", None)
        return prepare(messages) if callable(prepare) else messages
