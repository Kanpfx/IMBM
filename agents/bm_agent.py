"""Low-frequency BM producing only phase and guidance."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from agents.base_agent import BaseAgent
from agents.prompts import bm_messages
from tools.json_tools import parse_json_object
from tools.telemetry import Telemetry


class BMAgent(BaseAgent):
    async def run(
        self,
        observation: str,
        tactic: dict[str, Any],
        phase: dict[str, Any],
        trigger_reason: str = "",
        trace: Telemetry | None = None,
        tick: int | None = None,
    ) -> list[str]:
        messages = bm_messages(observation, tactic, phase, trigger_reason)
        request_messages = self._request_messages(messages)
        response = ""
        started_at = perf_counter()
        try:
            response = await self.llm_client.complete(messages)
            payload = parse_json_object(response)
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
                    tick=tick,
                    trigger_reason=trigger_reason,
                    request=request_messages,
                    reply=response,
                    valid=True,
                    phase=phase["id"],
                    guidance=cleaned,
                    latency_ms=round((perf_counter() - started_at) * 1000),
                )
            return cleaned
        except Exception as exc:
            if trace is not None:
                trace.bm_conversation(
                    tick=tick,
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
