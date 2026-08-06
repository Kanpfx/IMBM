"""Read the existing generated catalogs without duplicating their data."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def catalog_root() -> Path:
    configured = os.getenv("LLM_KNOWLEDGE_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parent


class ActionCatalog:
    def __init__(self, entries: dict[str, dict[str, Any]]):
        self.entries = entries
        self._names = {
            entry["name"]: entry
            for entry in entries.values()
            if isinstance(entry.get("name"), str)
        }

    @classmethod
    def load(cls) -> "ActionCatalog":
        root = catalog_root() / "llm_action_catalog" / "Behaviors"
        entries: dict[str, dict[str, Any]] = {}
        for name in (
            "Individual Combat Behaviors.json",
            "Group Combat Behaviors.json",
            "Macro Behaviors.json",
        ):
            payload = json.loads((root / name).read_text(encoding="utf-8"))
            entries.update({entry["id"]: entry for entry in payload["entries"]})
        return cls(entries)

    def get(self, action_id: str) -> dict[str, Any]:
        if action_id in self.entries:
            return self.entries[action_id]
        return self._names[action_id]

    @staticmethod
    def required_model_params(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Return the deliberately small argument surface exposed to IM."""
        return {
            param["name"]: param
            for param in entry["params"]
            if param["input"] == "model"
            and param["required"]
            and param["name"] != "group_tags"
        }

    def prompt_entries(self, allowed: set[str]) -> list[dict[str, Any]]:
        return [
            self.entries[action_id]
            for action_id in sorted(allowed)
            if action_id in self.entries
            and self.entries[action_id].get("llm_exposure") == "eligible"
        ]


def load_battlecruiser_tactic() -> dict[str, Any]:
    path = catalog_root() / "llm_tactic_catalog" / "BattleCruiserRush.json"
    return json.loads(path.read_text(encoding="utf-8"))
