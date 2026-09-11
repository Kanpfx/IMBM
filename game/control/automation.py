"""Reliable, low-latency rules that run independently of model decisions."""

from __future__ import annotations

from typing import Any

from ares.behaviors.macro import AutoSupply, BuildWorkers
from ares.behaviors.macro.mining import Mining
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId


class AutomationController:
    """Own baseline economy and safety behaviors without using ``MacroPlan``."""

    def __init__(self, default_worker_target: int = 20) -> None:
        self.default_worker_target = default_worker_target
        self.worker_target = default_worker_target
        self._worker_override: dict[str, Any] | None = None

    async def run(self, bot: Any, iteration: int) -> None:
        """Register automatic behaviors that should run before model spending."""
        workers_per_gas = 3 if bot.supply_workers >= 13 else 0
        bot.register_behavior(Mining(workers_per_gas=workers_per_gas))
        bot.register_behavior(AutoSupply(base_location=bot.start_location))
        bot._mules()
        bot._general_repair()
        if getattr(bot, "tactic_name", "") != "WorkerRush":
            bot._look_for_terran_bunker()
        if iteration % 16 == 0:
            depots = bot.mediator.get_own_structures_dict[UnitTypeId.SUPPLYDEPOT]
            for depot in depots:
                if depot.is_ready and depot.type_id == UnitTypeId.SUPPLYDEPOT:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    def replace_worker_override(
        self, action: dict[str, Any] | None
    ) -> tuple[dict[str, Any] | None, bool]:
        """Update the worker target; omission keeps the last accepted target."""
        previous = self._worker_override
        if action is None:
            return previous, False
        changed = previous != action
        self._worker_override = action
        self.worker_target = (
            int(action["args"]["to_count"])
            if action is not None
            else self.default_worker_target
        )
        return previous, changed

    @property
    def worker_action(self) -> dict[str, Any] | None:
        return self._worker_override

    def register_worker_production(self, bot: Any) -> None:
        """Register worker production after foreground model spending behaviors."""
        bot.register_behavior(BuildWorkers(to_count=self.worker_target))
