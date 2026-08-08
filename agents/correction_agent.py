"""Focused IM-style repair agent for partially invalid action lists."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from agents.base_agent import BaseAgent
from agents.prompts import correction_messages
from tools.json_tools import parse_json_object
from tools.telemetry import Telemetry


class CorrectionAgent(BaseAgent):
    """Turn structured validator feedback into one repaired action proposal."""

    async def run(
        self,
        observation: str,
        guidance: list[str],
        action_entries: list[dict[str, Any]],
        proposed_actions: list[dict[str, Any]],
        errors: list[str],
        trace: Telemetry | None = None,
        iteration: int | None = None,
    ) -> list[dict[str, Any]]:
        messages = correction_messages(
            observation, guidance, action_entries, proposed_actions, errors
        )
        request_messages = self._request_messages(messages)
        started_at = perf_counter()
        response = ""
        try:
            response = await self.llm_client.complete(messages)
            payload = parse_json_object(response)
            actions = payload.get("actions")
            if not isinstance(actions, list):
                raise ValueError("corrected actions must be a list")
            if trace is not None:
                trace.event(
                    "im_correction",
                    iteration=iteration,
                    request=request_messages,
                    reply=response,
                    valid=True,
                    errors=errors,
                    actions=actions,
                    latency_ms=round((perf_counter() - started_at) * 1000),
                )
            return actions
        except Exception as exc:
            if trace is not None:
                trace.event(
                    "im_correction",
                    iteration=iteration,
                    request=request_messages,
                    reply=response,
                    valid=False,
                    errors=errors,
                    validation=str(exc),
                    latency_ms=round((perf_counter() - started_at) * 1000),
                )
            raise

    def _request_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        prepare = getattr(self.llm_client, "prepare_messages", None)
        return prepare(messages) if callable(prepare) else messages
