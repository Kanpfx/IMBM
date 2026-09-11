"""Action history including resource waits with a separate, unbounded set of live intents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from game.actions.formatting import format_action


@dataclass
class ActionRecord:
    time: str
    key: str
    description: str
    status: str
    reason: str = ""


class ActionHistory:
    def __init__(self):
        self._recent: list[ActionRecord] = []
        self._active: dict[str, ActionRecord] = {}
        self._queued: dict[str, ActionRecord] = {}

    @staticmethod
    def _key(action: Any) -> str:
        return json.dumps(action, sort_keys=True, separators=(",", ":"))

    def sync_active(self, actions: list[dict[str, Any]], time: str) -> None:
        active = {}
        for action in actions:
            key = self._key(action)
            active[key] = self._active.get(key) or ActionRecord(
                time, key, format_action(action), "active"
            )
        self._active = active

    def record(self, action: Any, time: str, status: str, reason: str = "") -> None:
        if status not in {"accepted", "queued", "failed"}:
            raise ValueError("history status must be accepted, queued or failed")
        key = self._key(action)
        description = (
            format_action(action)
            if isinstance(action, dict) and set(action) == {"id", "args"}
            else str(action)
        )
        self._queued.pop(key, None)
        if status == "queued":
            self._recent = [record for record in self._recent if record.key != key]
            self._queued[key] = ActionRecord(time, key, description, status, reason)
            return
        if status == "failed":
            self._active.pop(key, None)
            for record in reversed(self._recent):
                if record.key == key and record.status == "accepted":
                    record.status = status
                    record.reason = reason
                    return
        self._recent.append(ActionRecord(time, key, description, status, reason))
        self._recent = self._recent[-10:]

    def forget_queued(self, action: Any) -> None:
        self._queued.pop(self._key(action), None)

    def annotate(self, action: Any, reason: str) -> None:
        key = self._key(action)
        for record in reversed(self._recent):
            if record.key == key and record.status == "accepted":
                record.reason = reason
                break

    def render(self) -> str:
        guide = (
            "Status guide:\n"
            "- `accepted`: One-time action accepted for submission, not proof of completion.\n"
            "- `active`: Ongoing control remains in effect until replaced; omission keeps it active.\n"
            "- `queued`: Waiting for resources; retried automatically, do not repeat.\n"
            "- `failed`: Invalid instruction, prerequisite or execution error; see the reason."
        )
        records = [*self._active.values(), *self._queued.values(), *self._recent]
        if not records:
            return f"{guide}\n\n[None]"
        rows = ["| Time | Action | Status | Reason |", "| --- | --- | --- | --- |"]
        for record in records:
            action = record.description.replace("|", "&#124;").replace("\n", " ")
            reason = record.reason.replace("|", "&#124;").replace("\n", " ")
            rows.append(f"| {record.time} | `{action}` | `{record.status}` | {reason} |")
        return f"{guide}\n\n" + "\n".join(rows)
