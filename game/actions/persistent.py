"""Short-lived re-registration for Ares behaviors that expect per-step use."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from game.actions.adapter import AresActionAdapter
from game.actions.resolver import EntityContext
from knowledge.loader import ActionCatalog

PERSISTENT_ACTION_IDS = {
    "combat.bc.move_safely",
    "combat.individual.keep_unit_safe",
    "combat.individual.medivac_heal",
    "combat.individual.move_to_safe_target",
    "combat.individual.path_unit_to_target",
    "combat.individual.pick_up_and_drop_cargo",
    "combat.individual.pick_up_cargo",
    "combat.individual.reaper_grenade",
    "combat.individual.shoot_and_move_to_target",
    "combat.individual.siege_tank_decision",
    "combat.individual.stutter_unit_back",
    "combat.individual.stutter_unit_forward",
    "combat.individual.worker_kite_back",
    "combat.group.keep_group_safe",
    "combat.group.path_group_to_target",
    "combat.group.stutter_group_back",
    "combat.group.stutter_group_forward",
}


@dataclass(frozen=True)
class PersistentAction:
    action: dict[str, Any]
    expires_iteration: int


class PersistentActionRegistry:
    """Repeat selected accepted actions until the next IM decision window."""

    def __init__(self, catalog: ActionCatalog, duration_iterations: int = 10):
        self.catalog = catalog
        self.duration_iterations = duration_iterations
        self._items: dict[str, PersistentAction] = {}

    def is_persistent(self, action: dict[str, Any]) -> bool:
        try:
            return self.catalog.get(action.get("id"))["id"] in PERSISTENT_ACTION_IDS
        except (TypeError, ValueError):
            return False

    def remember(self, action: dict[str, Any], iteration: int) -> None:
        if not self.is_persistent(action):
            return
        key = json.dumps(action, sort_keys=True, separators=(",", ":"))
        self._items[key] = PersistentAction(
            action,
            iteration + self.duration_iterations,
        )

    def run(
        self,
        bot: Any,
        iteration: int,
        adapter: AresActionAdapter,
        context: EntityContext,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Re-register live actions and return (completed, failed) actions."""
        completed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for key, item in list(self._items.items()):
            if iteration >= item.expires_iteration:
                completed.append(item.action)
                self._items.pop(key)
                continue
            try:
                adapter.compile_and_register(bot, [item.action], context)
            except (TypeError, ValueError):
                failed.append(item.action)
                self._items.pop(key)
        return completed, failed
