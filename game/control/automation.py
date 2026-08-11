"""Reliable, low-latency rules that are intentionally outside the IM action space."""

from __future__ import annotations

from typing import Any

from ares.behaviors.macro.mining import Mining
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId


class AutomationController:
    async def run(self, bot: Any, iteration: int) -> None:
        workers_per_gas = 3 if bot.supply_workers >= 13 else 0
        bot.register_behavior(Mining(workers_per_gas=workers_per_gas))
        bot._mules()
        bot._general_repair()
        if getattr(bot, "tactic_name", "") != "WorkerRush":
            bot._look_for_terran_bunker()
        if iteration % 16 == 0:
            depots = bot.mediator.get_own_structures_dict[UnitTypeId.SUPPLYDEPOT]
            for depot in depots:
                if depot.is_ready and depot.type_id == UnitTypeId.SUPPLYDEPOT:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
