"""Reliable, low-latency rules that run independently of model decisions."""

from __future__ import annotations

from typing import Any

from ares.behaviors.macro import AutoSupply, BuildWorkers
from ares.behaviors.macro.mining import Mining
from loguru import logger
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId


class AutomationController:
    """Own baseline economy and safety behaviors without using ``MacroPlan``."""

    def __init__(self, default_worker_target: int = 20) -> None:
        self.default_worker_target = default_worker_target
        self.worker_target = default_worker_target
        self._worker_override: dict[str, Any] | None = None
        self._scout_targets: list[Point2] = []
        self._scout_index = 0
        self._last_scout_scan = -20.0

    async def run(self, bot: Any, iteration: int) -> None:
        """Register automatic behaviors that should run before model spending."""
        workers_per_gas = 3 if bot.supply_workers >= 13 else 0
        bot.register_behavior(Mining(workers_per_gas=workers_per_gas))
        bot.register_behavior(AutoSupply(base_location=bot.start_location))
        scan_orbital = self._scan_map(bot)
        bot._mules(skip_tag=scan_orbital)
        bot._general_repair()
        if getattr(bot, "tactic_name", "") != "WorkerRush":
            bot._look_for_terran_bunker()
        if iteration % 16 == 0:
            depots = bot.mediator.get_own_structures_dict[UnitTypeId.SUPPLYDEPOT]
            for depot in depots:
                if depot.is_ready and depot.type_id == UnitTypeId.SUPPLYDEPOT:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    def _scan_map(self, bot: Any) -> int | None:
        """Spend surplus economy on occasional scans of expansions and map blind spots."""
        if bot.minerals < 1500 or bot.time - self._last_scout_scan < 20.0:
            return None
        orbitals = [
            unit
            for unit in bot.mediator.get_own_structures_dict[UnitTypeId.ORBITALCOMMAND]
            if unit.is_ready and unit.energy >= 50
        ]
        if not orbitals:
            return None
        if not self._scout_targets:
            area = bot.game_info.playable_area
            self._scout_targets = list(bot.expansion_locations_list)
            # Cover non-expansion locations too, including map edges and air space.
            columns = max(1, int(area.width / 18) + 1)
            rows = max(1, int(area.height / 18) + 1)
            self._scout_targets.extend(
                Point2((area.x + (x + 0.5) * area.width / columns,
                        area.y + (y + 0.5) * area.height / rows))
                for x in range(columns)
                for y in range(rows)
            )
        for _ in self._scout_targets:
            target = self._scout_targets[self._scout_index]
            self._scout_index = (self._scout_index + 1) % len(self._scout_targets)
            if bot.is_visible(target):
                continue
            orbital = max(orbitals, key=lambda unit: unit.energy)
            orbital(AbilityId.SCANNERSWEEP_SCAN, target)
            self._last_scout_scan = bot.time
            logger.info("{} - Automatic scouting scan at {}", bot.time_formatted, target)
            return orbital.tag
        return None

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
