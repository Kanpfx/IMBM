"""Detailed, tactic-independent overview of the current game state."""

from __future__ import annotations

from collections import Counter
from typing import Any

from game.observation.technology import display_name as _display_name


WORKER_TYPES = frozenset({"SCV", "DRONE", "PROBE", "MULE"})
PRODUCTION_TYPES = ("BARRACKS", "FACTORY", "STARPORT")


def _type_name(unit: Any) -> str:
    return getattr(getattr(unit, "type_id", None), "name", "UNKNOWN")


class OverviewBuilder:
    """Render direct high-level facts needed to orient each model call."""

    def build(
        self,
        bot: Any,
        structures: list[Any],
        own_units: list[Any],
        enemy_units: list[Any],
        enemy_structures: list[Any],
    ) -> dict[str, str]:
        return {
            "match": self._match(bot),
            "resources": self._resources(bot, structures),
            "economy": self._economy(bot, structures),
            "military": self._military(
                bot,
                own_units,
                enemy_units,
                enemy_structures,
            ),
        }

    @staticmethod
    def _match(bot: Any) -> str:
        own_race = getattr(getattr(bot, "race", None), "name", "Terran")
        enemy_race = getattr(getattr(bot, "enemy_race", None), "name", "[Unknown]")
        fields = [
            f"Time: {getattr(bot, 'time_formatted', '00:00')}",
            f"Matchup: {own_race} (you) vs {enemy_race} (enemy)",
        ]
        map_size = getattr(getattr(bot, "game_info", None), "map_size", None)
        width = getattr(map_size, "x", getattr(map_size, "width", None))
        height = getattr(map_size, "y", getattr(map_size, "height", None))
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            fields.append(f"Map size: {int(width)} x {int(height)}")
        return "\n".join(fields)

    def _resources(self, bot: Any, structures: list[Any]) -> str:
        minerals = int(getattr(bot, "minerals", 0))
        vespene = int(getattr(bot, "vespene", 0))
        used = int(getattr(bot, "supply_used", 0))
        cap = int(getattr(bot, "supply_cap", 0))
        free = max(0, cap - used)
        workers = int(
            getattr(bot, "supply_workers", len(getattr(bot, "workers", [])))
        )
        army = int(getattr(bot, "supply_army", max(0, used - workers)))
        fields = [f"Resources: {minerals} minerals, {vespene} vespene"]

        score = getattr(getattr(bot, "state", None), "score", None)
        mineral_rate = getattr(score, "collection_rate_minerals", None)
        gas_rate = getattr(score, "collection_rate_vespene", None)
        if isinstance(mineral_rate, (int, float)) and isinstance(
            gas_rate, (int, float)
        ):
            fields.append(
                f"Income: {int(mineral_rate)} minerals/min, "
                f"{int(gas_rate)} vespene/min"
            )

        supply_notes = [f"workers {workers}", f"army {army}", f"free {free}"]
        if free == 0:
            supply_notes.append("blocked")
        depots = [
            int(float(getattr(item, "build_progress", 1.0)) * 100)
            for item in structures
            if _type_name(item) == "SUPPLYDEPOT"
            and float(getattr(item, "build_progress", 1.0)) < 1.0
        ]
        if depots:
            supply_notes.append(f"Supply Depot {max(depots)}% complete")
        fields.append(f"Supply: {used}/{cap} ({', '.join(supply_notes)})")
        return "\n".join(fields)

    def _economy(self, bot: Any, structures: list[Any]) -> str:
        workers = list(getattr(bot, "workers", []))
        townhalls = list(getattr(bot, "townhalls", []))
        ready = sum(self._is_ready(base) for base in townhalls)
        building = max(0, len(townhalls) - ready)
        idle = sum(bool(getattr(worker, "is_idle", False)) for worker in workers)
        lines = [
            f"Economy: {ready} {'base' if ready == 1 else 'bases'} ready, {building} under construction; "
            f"{len(workers)} workers, {idle} idle",
        ]

        saturation = self._saturation(bot, townhalls)
        if saturation:
            lines.append("Saturation: " + ", ".join(saturation))
        production = self._production_capacity(structures)
        if production:
            lines.append("Production capacity: " + ", ".join(production))
        construction = self._construction(structures)
        if construction:
            lines.append("Construction: " + ", ".join(construction))
        return "\n".join(lines)

    @staticmethod
    def _is_ready(entity: Any) -> bool:
        return bool(
            getattr(
                entity,
                "is_ready",
                float(getattr(entity, "build_progress", 1.0)) >= 1.0,
            )
        )

    @classmethod
    def _saturation(cls, bot: Any, townhalls: list[Any]) -> list[str]:
        entries: list[str] = []
        ready_bases = [base for base in townhalls if cls._is_ready(base)]
        for index, base in enumerate(ready_bases):
            label = ("main", "natural")[index] if index < 2 else f"base {index + 1}"
            assigned = getattr(base, "assigned_harvesters", None)
            ideal = getattr(base, "ideal_harvesters", None)
            if not isinstance(assigned, int) or not isinstance(ideal, int) or ideal <= 0:
                continue
            entries.append(f"{label} {assigned}/{ideal}")

        gas_buildings = [
            gas
            for gas in getattr(bot, "gas_buildings", [])
            if cls._is_ready(gas)
        ]
        gas_assigned = sum(
            int(getattr(gas, "assigned_harvesters", 0)) for gas in gas_buildings
        )
        gas_ideal = sum(
            int(getattr(gas, "ideal_harvesters", 0)) for gas in gas_buildings
        )
        if gas_ideal:
            entries.append(f"refineries {gas_assigned}/{gas_ideal}")
        return entries

    @classmethod
    def _production_capacity(cls, structures: list[Any]) -> list[str]:
        entries: list[str] = []
        for type_name in PRODUCTION_TYPES:
            buildings = [
                structure
                for structure in structures
                if _type_name(structure) == type_name and cls._is_ready(structure)
            ]
            if not buildings:
                continue
            busy = sum(not bool(getattr(item, "is_idle", False)) for item in buildings)
            entries.append(
                f"{_display_name(type_name, len(buildings))} "
                f"{busy}/{len(buildings)} busy"
            )
        return entries

    @staticmethod
    def _construction(structures: list[Any]) -> list[str]:
        pending: dict[str, list[int]] = {}
        for structure in structures:
            progress = float(getattr(structure, "build_progress", 1.0))
            if progress >= 1.0:
                continue
            pending.setdefault(_type_name(structure), []).append(int(progress * 100))
        entries: list[str] = []
        for name, progress in sorted(pending.items()):
            values = ", ".join(f"{value}%" for value in sorted(progress))
            entries.append(f"{_display_name(name, len(progress))} ({values})")
        return entries

    def _military(
        self,
        bot: Any,
        own_units: list[Any],
        enemy_units: list[Any],
        enemy_structures: list[Any],
    ) -> str:
        army = [unit for unit in own_units if _type_name(unit) not in WORKER_TYPES]
        counts = Counter(_type_name(unit) for unit in army)
        composition = ", ".join(
            f"{count} {_display_name(name, count)}"
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ) or "[None]"
        army_supply = int(getattr(bot, "supply_army", len(army)))
        lines = [f"Army: {army_supply} supply ({composition})"]

        if army:
            activity = Counter()
            for unit in army:
                if bool(getattr(unit, "is_attacking", False)):
                    activity["attacking"] += 1
                elif bool(getattr(unit, "is_moving", False)):
                    activity["moving"] += 1
                elif bool(getattr(unit, "is_idle", False)):
                    activity["idle"] += 1
                else:
                    activity["other"] += 1
            lines.append(
                "Army activity: "
                + ", ".join(
                    f"{activity[name]} {name}"
                    for name in ("attacking", "moving", "idle", "other")
                )
            )

            health = [self._health_ratio(unit) for unit in army]
            known_health = [value for value in health if value is not None]
            if known_health:
                damaged = sum(value < 1.0 for value in known_health)
                condition = f"Army condition: {damaged}/{len(known_health)} damaged"
                if damaged:
                    condition += f" (lowest health {int(min(known_health) * 100)}%)"
                lines.append(condition)

        enemy_counts = Counter(_type_name(unit) for unit in enemy_units)
        enemy_composition = ", ".join(
            f"{count} {_display_name(name, count)}"
            for name, count in sorted(
                enemy_counts.items(), key=lambda item: (-item[1], item[0])
            )
        )
        visible_enemy = (
            f"Visible enemy: {len(enemy_units)} {'unit' if len(enemy_units) == 1 else 'units'}, "
            f"{len(enemy_structures)} {'structure' if len(enemy_structures) == 1 else 'structures'}"
        )
        if enemy_composition:
            visible_enemy += f" ({enemy_composition})"
        lines.append(visible_enemy)

        combat_totals = self._combat_totals(bot)
        if combat_totals:
            lines.append(combat_totals)
        return "\n".join(lines)

    @staticmethod
    def _health_ratio(unit: Any) -> float | None:
        percentage = getattr(unit, "health_percentage", None)
        if isinstance(percentage, (int, float)):
            return max(0.0, min(1.0, float(percentage)))
        health = getattr(unit, "health", None)
        health_max = getattr(unit, "health_max", None)
        shield = getattr(unit, "shield", 0.0)
        shield_max = getattr(unit, "shield_max", 0.0)
        if not isinstance(health, (int, float)) or not isinstance(
            health_max, (int, float)
        ):
            return None
        maximum = float(health_max) + float(shield_max or 0.0)
        return (float(health) + float(shield or 0.0)) / maximum if maximum else None

    @staticmethod
    def _combat_totals(bot: Any) -> str:
        score = getattr(getattr(bot, "state", None), "score", None)
        names = (
            "killed_value_units",
            "killed_value_structures",
            "lost_minerals_army",
            "lost_vespene_army",
        )
        values = [getattr(score, name, None) for name in names]
        if not all(isinstance(value, (int, float)) for value in values):
            return ""
        killed_units, killed_structures, lost_minerals, lost_vespene = map(
            int, values
        )
        if not any((killed_units, killed_structures, lost_minerals, lost_vespene)):
            return ""
        return (
            f"Combat totals: enemy unit value destroyed {killed_units}, "
            f"structure value destroyed {killed_structures} "
            f"(own army losses {lost_minerals} minerals, {lost_vespene} vespene; "
            "cumulative)"
        )
