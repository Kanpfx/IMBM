"""IMBM-style parse/verify/refine agent for Ares JSON instructions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from game.actions.errors import InstructionError
from llm.agents.base_agent import BaseAgent
from llm.agents.prompts import im_messages
from llm.json_tools import parse_im_payload
from llm.telemetry import Telemetry

Verifier = Callable[[list[dict[str, Any]]], tuple[bool, str]]


@dataclass(frozen=True)
class IMResult:
    actions: list[dict[str, Any]]


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
        request_messages = self._request_messages(messages)
        started_at = perf_counter()
        response = ""
        actions: list[dict[str, Any]] | None = None
        try:
            response = await self.llm_client.complete(messages)
            payload = parse_im_payload(response)
            actions = payload["actions"]
            accepted, error = verifier(actions)
            if not accepted:
                raise InstructionError(
                    "verification failed",
                    error or "the submitted action list did not pass verification",
                )
            if trace is not None:
                trace.im_conversation(
                    iteration=iteration,
                    request=request_messages,
                    reply=response,
                    valid=True,
                    actions=actions,
                    latency_ms=round((perf_counter() - started_at) * 1000),
                )
            return IMResult(actions)
        except Exception as exc:
            if trace is not None:
                trace.im_conversation(
                    iteration=iteration,
                    request=request_messages,
                    reply=response,
                    valid=False,
                    error=str(exc),
                    actions=actions,
                    latency_ms=round((perf_counter() - started_at) * 1000),
                )
            raise

    def _request_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        prepare = getattr(self.llm_client, "prepare_messages", None)
        return prepare(messages) if callable(prepare) else messages
