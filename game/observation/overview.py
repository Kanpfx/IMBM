"""Compact, tactic-independent overview of the current game state."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable


def _type_name(unit: Any) -> str:
    return getattr(getattr(unit, "type_id", None), "name", "UNKNOWN")


def _display_name(name: str, count: int = 1) -> str:
    names = {
        "BATTLECRUISER": "Battlecruiser",
        "HELLIONTANK": "Hellbat",
        "ORBITALCOMMAND": "Orbital Command",
        "PLANETARYFORTRESS": "Planetary Fortress",
        "SIEGETANKSIEGED": "Siege Tank",
        "VIKINGFIGHTER": "Viking",
    }
    value = names.get(name, name.replace("_", " ").title())
    if count != 1 and value not in {"Barracks", "SCV"}:
        value += "s"
    return value


class OverviewBuilder:
    """Render only the high-level facts needed to orient each model call."""

    def build(
        self,
        bot: Any,
        structures: list[Any],
        own_units: list[Any],
        area_label: Callable[[Any, Any], str],
    ) -> dict[str, str]:
        return {
            "match": self._match(bot),
            "resources": self._resources(bot, structures),
            "economy": self._economy(bot, structures),
            "military": self._military(bot, own_units, area_label),
        }

    @staticmethod
    def _match(bot: Any) -> str:
        own_race = getattr(getattr(bot, "race", None), "name", "Terran")
        enemy_race = getattr(getattr(bot, "enemy_race", None), "name", "[Unknown]")
        return "\n".join(
            (
                f"Time: {getattr(bot, 'time_formatted', '00:00')}",
                f"Matchup: {own_race} (you) vs {enemy_race} (enemy).",
            )
        )

    def _resources(self, bot: Any, structures: list[Any]) -> str:
        minerals = int(getattr(bot, "minerals", 0))
        vespene = int(getattr(bot, "vespene", 0))
        used = int(getattr(bot, "supply_used", 0))
        cap = int(getattr(bot, "supply_cap", 0))
        free = max(0, cap - used)
        lines = [f"Resources: {minerals} minerals, {vespene} vespene."]

        score = getattr(getattr(bot, "state", None), "score", None)
        mineral_rate = getattr(score, "collection_rate_minerals", None)
        gas_rate = getattr(score, "collection_rate_vespene", None)
        if isinstance(mineral_rate, (int, float)) and isinstance(
            gas_rate, (int, float)
        ):
            lines.append(
                f"Income: {int(mineral_rate)} minerals/min, "
                f"{int(gas_rate)} vespene/min."
            )

        supply = f"Supply: {used}/{cap}, {free} free"
        if free == 0:
            supply = f"Supply: {used}/{cap}, blocked"
        depots = [
            int(float(getattr(item, "build_progress", 1.0)) * 100)
            for item in structures
            if _type_name(item) == "SUPPLYDEPOT"
            and float(getattr(item, "build_progress", 1.0)) < 1.0
        ]
        if depots:
            supply += f"; Supply Depot building at {max(depots)}%"
        lines.append(supply + ".")
        return "\n".join(lines)

    def _economy(self, bot: Any, structures: list[Any]) -> str:
        workers = list(getattr(bot, "workers", []))
        townhalls = list(getattr(bot, "townhalls", []))
        active = sum(bool(getattr(base, "is_ready", True)) for base in townhalls)
        building = max(0, len(townhalls) - active)
        idle = sum(bool(getattr(worker, "is_idle", False)) for worker in workers)
        gas_tags = {gas.tag for gas in getattr(bot, "gas_buildings", [])}
        on_gas = sum(
            1
            for worker in workers
            if getattr(worker, "order_target", None) in gas_tags
        )
        on_minerals = max(0, len(workers) - on_gas - idle)
        lines = [
            f"Bases: {active} active, {building} building.",
            f"Workers: {len(workers)} total — {on_minerals} on minerals, "
            f"{on_gas} on gas, {idle} idle.",
        ]

        saturation = self._saturation(townhalls, structures)
        if saturation:
            lines.append("Saturation: " + "; ".join(saturation) + ".")
        return "\n".join(lines)

    @staticmethod
    def _saturation(townhalls: list[Any], structures: list[Any]) -> list[str]:
        entries: list[str] = []
        ready_bases = [base for base in townhalls if getattr(base, "is_ready", True)]
        for index, base in enumerate(ready_bases):
            label = ("main", "natural")[index] if index < 2 else f"base {index + 1}"
            assigned = getattr(base, "assigned_harvesters", None)
            ideal = getattr(base, "ideal_harvesters", None)
            if not isinstance(assigned, int) or not isinstance(ideal, int) or ideal <= 0:
                continue
            difference = assigned - ideal
            if difference == 0:
                state = "saturated"
            elif difference < 0:
                state = f"undersaturated by {-difference}"
            else:
                state = f"oversaturated by {difference}"
            entries.append(f"{label} {state}")
        return entries

    def _military(
        self,
        bot: Any,
        own_units: list[Any],
        area_label: Callable[[Any, Any], str],
    ) -> str:
        workers = {"SCV", "DRONE", "PROBE", "MULE"}
        army = [unit for unit in own_units if _type_name(unit) not in workers]
        counts = Counter(_type_name(unit) for unit in army)
        composition = ", ".join(
            f"{count} {_display_name(name, count)}"
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ) or "[None]"
        army_supply = int(getattr(bot, "supply_army", len(army)))
        lines = [f"Army: {army_supply} supply — {composition}."]
        if army:
            regions = Counter(area_label(unit, bot) for unit in army)
            region, amount = regions.most_common(1)[0]
            if amount > len(army) / 2:
                lines.append(f"Deployment: most combat units are {region}.")
            else:
                lines.append("Deployment: combat units are dispersed across the map.")
        return "\n".join(lines)
