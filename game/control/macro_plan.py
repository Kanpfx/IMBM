"""Merge one IM decision cycle with automatic macro defaults."""

from __future__ import annotations

from typing import Any

from ares.behaviors.macro import AutoSupply, BuildWorkers, MacroPlan

from game.actions.adapter import AresActionAdapter
from game.actions.resolver import EntityContext
from knowledge.loader import ActionCatalog


class MacroPlanController:
    """Keep one effective IM action per macro slot until the next IM output."""

    PRODUCTION = "production"
    SUPPLY = "supply"
    GAS = "gas"
    CC_UPGRADE = "cc_upgrade"
    UPGRADES = "upgrades"
    SPAWN = "spawn"
    WORKERS = "workers"
    EXPANSION = "expansion"

    _SLOT_BY_ACTION_ID = {
        "macro.production_controller": PRODUCTION,
        "macro.gas_building_controller": GAS,
        "macro.upgrade_c_cs": CC_UPGRADE,
        "macro.upgrade_controller": UPGRADES,
        "macro.spawn_controller": SPAWN,
        "macro.build_workers": WORKERS,
        "macro.expansion_controller": EXPANSION,
    }
    _WHY_PRIORITY = (
        PRODUCTION,
        SUPPLY,
        GAS,
        CC_UPGRADE,
        UPGRADES,
        SPAWN,
        WORKERS,
        EXPANSION,
    )

    def __init__(self, catalog: ActionCatalog, default_worker_target: int = 20):
        self.catalog = catalog
        self.default_worker_target = default_worker_target
        self._im_actions: dict[str, dict[str, Any]] = {}

    def replace_cycle(
        self, actions: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Replace managed intents and return (effective macro, other actions).

        The first IM action for a slot wins, preserving the model's output order
        while silently collapsing duplicate controller requests.
        """
        selected: dict[str, dict[str, Any]] = {}
        other: list[dict[str, Any]] = []
        for action in actions:
            slot = self.slot_for(action)
            if slot is None:
                other.append(action)
            elif slot not in selected:
                selected[slot] = action
        self._im_actions = selected
        return list(selected.values()), other

    def slot_for(self, action: dict[str, Any]) -> str | None:
        try:
            action_id = self.catalog.get(action.get("id"))["id"]
        except (TypeError, ValueError):
            return None
        return self._SLOT_BY_ACTION_ID.get(action_id)

    def register(
        self,
        bot: Any,
        adapter: AresActionAdapter,
        context: EntityContext,
    ) -> MacroPlan:
        """Build and register the single effective plan for this game step."""
        plan = MacroPlan()
        for slot in self._WHY_PRIORITY:
            if action := self._im_actions.get(slot):
                plan.add(adapter.compile([action], context)[0])
            elif slot == self.SUPPLY:
                plan.add(AutoSupply(base_location=bot.start_location))
            elif slot == self.WORKERS:
                plan.add(BuildWorkers(to_count=self.default_worker_target))
        bot.register_behavior(plan)
        return plan
