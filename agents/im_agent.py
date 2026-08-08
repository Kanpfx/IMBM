"""IMBM-style parse/verify/refine agent for Ares JSON instructions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from agents.base_agent import BaseAgent
from agents.prompts import im_messages, refine_messages
from tools.json_tools import parse_json_object
from tools.telemetry import Telemetry


Verifier = Callable[[list[dict[str, Any]]], tuple[bool, str]]


@dataclass(frozen=True)
class IMResult:
    actions: list[dict[str, Any]]
    request_background: bool
    background_reason: str


class IMAgent(BaseAgent):
    async def run(
        self,
        observation: str,
        guidance: list[str],
        action_entries: list[dict[str, Any]],
        verifier: Verifier,
        trace: Telemetry | None = None,
        iteration: int | None = None,
    ) -> IMResult:
        messages = im_messages(observation, guidance, action_entries)
        error = ""
        requested_background = False
        background_reason = ""
        for attempt in range(self.generation_config.max_refines + 1):
            request_messages = self._request_messages(messages)
            started_at = perf_counter()
            try:
                response = await self.llm_client.complete(messages)
            except Exception as exc:
                if trace is not None:
                    trace.im_conversation(
                        iteration=iteration,
                        attempt=attempt,
                        request=request_messages,
                        error=str(exc),
                        valid=False,
                        latency_ms=round((perf_counter() - started_at) * 1000),
                    )
                raise
            latency_ms = round((perf_counter() - started_at) * 1000)
            actions: list[dict[str, Any]] | None = None
            try:
                payload = parse_json_object(response)
                actions = payload.get("actions")
                if not isinstance(actions, list):
                    raise ValueError("actions must be a list")
                if payload.get("request_background", False):
                    requested_background = True
                    background_reason = str(
                        payload.get("background_reason", "")
                    ).strip()
                accepted, error = verifier(actions)
                if trace is not None:
                    trace.im_conversation(
                        iteration=iteration,
                        attempt=attempt,
                        request=request_messages,
                        reply=response,
                        valid=accepted,
                        validation=error,
                        actions=actions,
                        latency_ms=latency_ms,
                    )
                if accepted:
                    return IMResult(actions, requested_background, background_reason)
            except (ValueError, TypeError) as exc:
                error = str(exc)
                if trace is not None:
                    trace.im_conversation(
                        iteration=iteration,
                        attempt=attempt,
                        request=request_messages,
                        reply=response,
                        valid=False,
                        validation=error,
                        actions=actions,
                        latency_ms=latency_ms,
                    )
            if attempt < self.generation_config.max_refines:
                messages = refine_messages(
                    messages,
                    error,
                    '{"actions":[{"id":"...","args":{...}}],"request_background":false,"background_reason":""}',
                )
        raise ValueError(error or "IM action verification failed")

    def _request_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        prepare = getattr(self.llm_client, "prepare_messages", None)
        return prepare(messages) if callable(prepare) else messages
