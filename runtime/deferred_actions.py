"""Small queue for macro actions blocked only by temporary resource shortages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from knowledge.loader import ActionCatalog


@dataclass(frozen=True)
class DeferredAction:
    action: dict[str, Any]
    queued_iteration: int
    expires_iteration: int


class DeferredActionQueue:
    """Retry selected macro actions without asking the model to repeat them."""

    _COSTED_ACTIONS = {
        "macro.build_structure": "structure_id",
        "macro.tech_up": "desired_tech",
        "macro.upgrade_c_cs": "to",
    }

    def __init__(self, catalog: ActionCatalog, ttl_iterations: int):
        self.catalog = catalog
        self.ttl_iterations = ttl_iterations
        self._items: list[DeferredAction] = []

    def should_defer(self, bot: Any, action: dict[str, Any]) -> bool:
        target = self._cost_target(action)
        can_afford = getattr(bot, "can_afford", None)
        if target is None or not callable(can_afford):
            return False
        try:
            return not bool(can_afford(target))
        except (AttributeError, TypeError, ValueError):
            return False

    def enqueue(self, action: dict[str, Any], iteration: int) -> bool:
        key = self._key(action)
        if any(self._key(item.action) == key for item in self._items):
            return False
        self._items.append(
            DeferredAction(
                action,
                iteration,
                iteration + self.ttl_iterations,
            )
        )
        return True

    def pop_ready(
        self, bot: Any, iteration: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ready: list[dict[str, Any]] = []
        expired: list[dict[str, Any]] = []
        remaining: list[DeferredAction] = []
        for item in self._items:
            if iteration > item.expires_iteration:
                expired.append(item.action)
            elif self.should_defer(bot, item.action):
                remaining.append(item)
            else:
                ready.append(item.action)
        self._items = remaining
        return ready, expired

    def _cost_target(self, action: dict[str, Any]) -> Any | None:
        try:
            entry = self.catalog.get(action.get("id"))
            action_id = entry["id"]
            arg_name = self._COSTED_ACTIONS[action_id]
            value = action["args"][arg_name]
        except (KeyError, TypeError):
            return None
        if not isinstance(value, str):
            return None
        from sc2.ids.unit_typeid import UnitTypeId
        from sc2.ids.upgrade_id import UpgradeId

        try:
            return UnitTypeId[value]
        except KeyError:
            try:
                return UpgradeId[value]
            except KeyError:
                return None

    @staticmethod
    def _key(action: dict[str, Any]) -> str:
        return json.dumps(action, sort_keys=True, separators=(",", ":"))
