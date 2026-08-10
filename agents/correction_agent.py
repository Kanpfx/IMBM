"""Focused IM-style repair agent for partially invalid action lists."""

from __future__ import annotations

from collections import Counter
from time import perf_counter
from typing import Any

from agents.base_agent import BaseAgent
from agents.prompts import correction_messages
from core.action_errors import OutputFormatError
from knowledge.loader import normalize_catalog_name
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
                raise OutputFormatError.field_type(
                    "actions", "a JSON list of corrected actions"
                )
            actions, discarded_actions = self._preserve_action_ids(
                actions, proposed_actions, action_entries
            )
            if trace is not None:
                trace.event(
                    "im_correction",
                    iteration=iteration,
                    request=request_messages,
                    reply=response,
                    valid=True,
                    errors=errors,
                    actions=actions,
                    discarded_actions=discarded_actions,
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

    @staticmethod
    def _preserve_action_ids(
        corrected_actions: list[Any],
        proposed_actions: list[dict[str, Any]],
        action_entries: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        """Discard repairs that replace or add actions instead of fixing arguments."""
        aliases: dict[str, str] = {}
        for entry in action_entries or []:
            canonical = str(entry.get("id", ""))
            for alias in (entry.get("id"), entry.get("name")):
                if isinstance(alias, str):
                    aliases[normalize_catalog_name(alias)] = canonical

        def canonical_id(value: Any) -> str | None:
            if not isinstance(value, str):
                return None
            normalized = normalize_catalog_name(value)
            return aliases.get(normalized, normalized)

        remaining_ids = Counter(
            canonical_id(action.get("id"))
            for action in proposed_actions
            if isinstance(action, dict) and isinstance(action.get("id"), str)
        )
        accepted: list[dict[str, Any]] = []
        discarded: list[Any] = []
        for action in corrected_actions:
            action_id = action.get("id") if isinstance(action, dict) else None
            canonical = canonical_id(action_id)
            if canonical is not None and remaining_ids[canonical] > 0:
                accepted.append(action)
                remaining_ids[canonical] -= 1
            else:
                discarded.append(action)
        return accepted, discarded

    def _request_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        prepare = getattr(self.llm_client, "prepare_messages", None)
        return prepare(messages) if callable(prepare) else messages
