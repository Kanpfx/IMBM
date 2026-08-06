"""Ares/python-sc2 state -> one compact, shared IMBM observation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from core.renderer import observation_text
from core.state import TagIdMapper
from runtime.resolver import EntityContext


PENDING_STRUCTURE_NAMES = (
    "COMMANDCENTER",
    "ORBITALCOMMAND",
    "SUPPLYDEPOT",
    "REFINERY",
    "BARRACKS",
    "FACTORY",
    "STARPORT",
    "FUSIONCORE",
    "STARPORTTECHLAB",
)

IMPORTANT_UNIT_NAMES = {
    "BATTLECRUISER",
    "MEDIVAC",
    "RAVEN",
    "GHOST",
    "SIEGETANK",
}
IMPORTANT_STRUCTURE_NAMES = {
    "COMMANDCENTER",
    "ORBITALCOMMAND",
    "PLANETARYFORTRESS",
    "FACTORY",
    "STARPORT",
    "FUSIONCORE",
    "STARPORTTECHLAB",
}
PRODUCTION_STRUCTURE_NAMES = {"BARRACKS", "FACTORY", "STARPORT"}


@dataclass
class Observation:
    loop: int
    counts: dict[str, int]
    text: str
    context: EntityContext

    # Compatibility aliases intentionally return the same source text. BM and
    # IM must never receive divergent versions of the current game state.
    @property
    def strategy_text(self) -> str:
        return self.text

    @property
    def action_text(self) -> str:
        return self.text


def _type_name(unit: Any) -> str:
    return getattr(
        getattr(unit, "type_id", None), "name", getattr(unit, "name", "UNKNOWN")
    )


def _count(units: list[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for unit in units:
        name = _type_name(unit)
        result[name] = result.get(name, 0) + 1
    return result


class ObservationBuilder:
    """Build the canonical observation and preserve only useful cross-frame state."""

    def __init__(self, ids: TagIdMapper):
        self.ids = ids
        self._action_history: list[str] = []
        self._last_validation_error = ""
        self._previous_facts: dict[str, int | str] | None = None

    def record_registered_actions(self, actions: list[dict[str, Any]]) -> None:
        for action in actions:
            action_id = str(action.get("id", "unknown action"))
            args = action.get("args", {})
            detail = self._action_detail(action_id, args)
            self._action_history.append(f"Sent once: {action_id}{detail}")
        self._action_history = self._action_history[-10:]
        self._last_validation_error = ""

    def record_validation_error(self, error: str) -> None:
        # Network failures are not action validation feedback and would only
        # distract the next IM decision.
        if error:
            self._last_validation_error = self._friendly_validation_error(error)

    def build(self, bot: Any, loop: int, _phase: str) -> Observation:
        own_units = list(bot.units)
        structures = list(bot.structures)
        enemies = [unit for unit in bot.enemy_units if getattr(unit, "is_visible", True)]
        enemy_structures = [
            unit for unit in bot.enemy_structures if getattr(unit, "is_visible", True)
        ]
        own_counts = _count(own_units)
        structure_counts = _count(structures)
        pending = self._pending_counts(bot)
        counts = dict(own_counts)
        counts.update(structure_counts)
        counts.update({f"pending:{name}": value for name, value in pending.items()})

        context = EntityContext()
        self._add_execution_context(bot, context)
        own_unit_blocks = self._own_unit_blocks(own_units, context, bot)
        own_structure_blocks = self._structure_blocks(structures, context, bot, own=True)
        enemy_unit_blocks = self._enemy_unit_blocks(enemies, context, bot)
        enemy_structure_blocks = self._structure_blocks(
            enemy_structures, context, bot, own=False
        )
        facts = self._facts(own_counts, structure_counts, enemies, enemy_structures, bot)
        data = {
            "time": getattr(bot, "time_formatted", "00:00"),
            "enemy_race": getattr(
                getattr(bot, "enemy_race", None), "name", "Unknown"
            ),
            "minerals": int(bot.minerals),
            "vespene": int(bot.vespene),
            "supply_used": int(bot.supply_used),
            "supply_cap": int(bot.supply_cap),
            "supply_free": int(bot.supply_cap - bot.supply_used),
            "army_supply": int(
                getattr(
                    bot,
                    "supply_army",
                    sum(1 for unit in own_units if _type_name(unit) != "SCV"),
                )
            ),
            **self._economy(bot, structures),
            "own_unit_blocks": own_unit_blocks,
            "own_structure_blocks": own_structure_blocks,
            "enemy_unit_blocks": enemy_unit_blocks,
            "enemy_structure_blocks": enemy_structure_blocks,
            "production_and_technology": self._production_and_technology(structures),
            "base_security": self._base_security(bot, enemies),
            "action_history": self._history_blocks(),
            "recent_changes": self._recent_changes(facts),
        }
        self._previous_facts = facts
        return Observation(loop, counts, observation_text(data), context)

    def _add_execution_context(self, bot: Any, context: EntityContext) -> None:
        candidates = {
            "main": getattr(bot, "start_location", None),
            "natural": self._safe_mediator(bot, "get_own_nat"),
            "enemy_main": (getattr(bot, "enemy_start_locations", []) or [None])[0],
        }
        context.positions.update(
            {name: point for name, point in candidates.items() if point is not None}
        )
        for alias, attr in {
            "ground": "get_ground_grid",
            "air": "get_air_grid",
            "ground_avoidance": "get_ground_avoidance_grid",
            "air_avoidance": "get_air_avoidance_grid",
            "tactical_ground": "get_tactical_ground_grid",
        }.items():
            value = self._safe_mediator(bot, attr)
            if value is not None:
                context.grids[alias] = value

    def _pending_counts(self, bot: Any) -> dict[str, int]:
        from sc2.ids.unit_typeid import UnitTypeId

        pending: dict[str, int] = {}
        for name in PENDING_STRUCTURE_NAMES:
            if hasattr(UnitTypeId, name):
                pending[name] = int(bot.already_pending(getattr(UnitTypeId, name)))
        return pending

    def _economy(self, bot: Any, structures: list[Any]) -> dict[str, int | str]:
        workers = list(bot.workers)
        idle = sum(bool(getattr(worker, "is_idle", False)) for worker in workers)
        on_gas = self._workers_on_gas(bot)
        active_bases = sum(
            bool(getattr(base, "is_ready", True)) for base in getattr(bot, "townhalls", [])
        )
        building_bases = len(getattr(bot, "townhalls", [])) - active_bases
        supply_status = "blocked" if bot.supply_cap - bot.supply_used <= 0 else "not blocked"
        depot_progress = [
            int(float(getattr(structure, "build_progress", 1.0)) * 100)
            for structure in structures
            if _type_name(structure) == "SUPPLYDEPOT"
            and float(getattr(structure, "build_progress", 1.0)) < 1.0
        ]
        if depot_progress:
            supply_status = f"Supply Depot building ({max(depot_progress)}%)"
        return {
            "active_bases": active_bases,
            "building_bases": building_bases,
            "workers": len(workers),
            "workers_on_gas": on_gas,
            "idle_workers": idle,
            "workers_on_minerals": max(0, len(workers) - on_gas - idle),
            "supply_status": supply_status,
        }

    def _unit_overview(self, units: list[Any]) -> str:
        counts = _count(units)
        workers = counts.pop("SCV", 0)
        army_total = sum(counts.values())
        army = self._summary_counts(counts) if army_total else "none"
        return f"Units: army {army_total} ({army}); workers {workers} SCVs."

    def _role_labels(self, bot: Any) -> dict[int, str]:
        """Translate only the few Ares roles that make sense to a commander."""
        try:
            from ares.consts import UnitRole

            get_units = bot.mediator.get_units_from_role
        except (AttributeError, ImportError):
            return {}
        labels: dict[int, str] = {}
        for role, label in (
            (UnitRole.ATTACKING_MAIN_SQUAD, "attacking"),
            (UnitRole.ATTACKING, "attacking"),
            (UnitRole.DEFENDING, "defending"),
            (UnitRole.BASE_DEFENDER, "defending"),
            (UnitRole.BUILDING, "constructing"),
            (UnitRole.GATHERING, "gathering"),
            (UnitRole.REPAIRING, "repairing"),
            (UnitRole.MAP_CONTROL, "scouting"),
        ):
            try:
                for unit in get_units(role=role):
                    labels[unit.tag] = label
            except (AttributeError, KeyError, TypeError):
                continue
        return labels

    def _unit_detail(self, unit: Any, bot: Any) -> str:
        lines = self._health_lines(unit)
        lines.append(f"Position: {self._position_label(unit, bot)}.")
        energy = self._energy_line(unit)
        if energy:
            lines.append(energy)
        if _type_name(unit) == "BATTLECRUISER":
            lines.extend(self._battlecruiser_ability_lines(unit))
        return "\n".join(lines)

    @staticmethod
    def _battlecruiser_ability_lines(unit: Any) -> list[str]:
        """Expose only the two BC decisions that IM can act on directly."""
        abilities = getattr(unit, "abilities", None)
        if abilities is None:
            return ["Tactical Jump: availability unknown.", "Yamato Cannon: availability unknown."]
        names = {getattr(ability, "name", str(ability)) for ability in abilities}
        return [
            "Tactical Jump: ready."
            if "EFFECT_TACTICALJUMP" in names
            else "Tactical Jump: unavailable.",
            "Yamato Cannon: ready."
            if "YAMATO_YAMATOGUN" in names
            else "Yamato Cannon: unavailable.",
        ]

    def _structure_detail(self, structure: Any, bot: Any) -> str:
        lines = self._health_lines(structure)
        lines.append(f"Position: {self._position_label(structure, bot)}.")
        energy = self._energy_line(structure)
        if energy:
            lines.append(energy)
        production = self._production_text(structure)
        if production:
            lines.append(production)
        return "\n".join(lines)

    @staticmethod
    def _health_lines(unit: Any) -> list[str]:
        health = getattr(unit, "health", None)
        health_max = getattr(unit, "health_max", None)
        if not isinstance(health, (int, float)) or not isinstance(health_max, (int, float)):
            return []
        if health_max <= 0:
            return []
        return [
            f"Health: {int(health)}/{int(health_max)} ({int((health / health_max) * 100)}%)."
        ]

    @staticmethod
    def _energy_line(unit: Any) -> str:
        energy = getattr(unit, "energy", 0)
        energy_max = getattr(unit, "energy_max", 0)
        if not isinstance(energy, (int, float)) or not isinstance(energy_max, (int, float)):
            return ""
        if energy_max <= 0:
            return ""
        return f"Energy: {int(energy)}/{int(energy_max)}."

    def _position_label(self, unit: Any, bot: Any) -> str:
        position = getattr(unit, "position", None)
        if position is None:
            return "unknown"
        try:
            coordinates = f"({int(position.x)}, {int(position.y)})"
        except (AttributeError, TypeError, ValueError):
            coordinates = "unknown"
        candidates = (
            ("our main", getattr(bot, "start_location", None)),
            ("our natural", self._safe_mediator(bot, "get_own_nat")),
            (
                "enemy main",
                (getattr(bot, "enemy_start_locations", []) or [None])[0],
            ),
            ("enemy natural", self._safe_mediator(bot, "get_enemy_nat")),
        )
        nearest_name = "on the map"
        nearest_distance = float("inf")
        for name, point in candidates:
            if point is None:
                continue
            try:
                distance = (position.x - point.x) ** 2 + (position.y - point.y) ** 2
            except AttributeError:
                continue
            if distance < nearest_distance:
                nearest_name, nearest_distance = name, distance
        if nearest_distance <= 400:
            return f"{coordinates}, near {nearest_name}"
        return coordinates

    def _production_and_technology(self, structures: list[Any]) -> list[str]:
        counts = _count(structures)
        infrastructure_order = (
            "COMMANDCENTER",
            "ORBITALCOMMAND",
            "BARRACKS",
            "FACTORY",
            "STARPORT",
        )
        infrastructure = [
            f"{count} {self._display_name(name, plural=count != 1)}"
            for name in infrastructure_order
            if (count := counts.get(name, 0))
        ]
        lines = [
            "Infrastructure: "
            + (", ".join(infrastructure) if infrastructure else "[Empty]")
            + "."
        ]
        technology = [
            self._display_name(_type_name(structure))
            for structure in structures
            if _type_name(structure) in {"FUSIONCORE", "STARPORTTECHLAB"}
            and float(getattr(structure, "build_progress", 1.0)) >= 1.0
        ]
        if technology:
            lines.append(
                "Technology: " + "; ".join(f"{name} complete" for name in technology) + "."
            )
        production = []
        idle = []
        in_progress = []
        for structure in structures:
            name = _type_name(structure)
            progress = float(getattr(structure, "build_progress", 1.0))
            alias = self.ids.alias(structure.tag)
            if progress < 1.0:
                in_progress.append(f"{self._display_name(name)} ({int(progress * 100)}%)")
                continue
            if name in PRODUCTION_STRUCTURE_NAMES:
                queue = self._production_text(structure)
                if queue:
                    production.append(f"{self._display_name(name)} [{alias}] {queue[12:]}")
                elif getattr(structure, "is_idle", False):
                    idle.append(f"{self._display_name(name)} [{alias}]")
        if production:
            lines.append("Production: " + "; ".join(production) + ".")
        if idle:
            lines.append("Idle production: " + ", ".join(idle) + ".")
        if in_progress:
            lines.append("In progress: " + ", ".join(in_progress) + ".")
        return lines

    def _base_security(self, bot: Any, enemies: list[Any]) -> list[str]:
        ground = self._safe_mediator(bot, "get_ground_enemy_near_bases") or {}
        air = self._safe_mediator(bot, "get_flying_enemy_near_bases") or {}
        lines: list[str] = []
        largest: tuple[int, str] = (0, "")
        for index, base in enumerate(getattr(bot, "townhalls", [])):
            label = ("Main", "Natural")[index] if index < 2 else f"Base {index + 1}"
            ground_tags = set(ground.get(base.tag, set()))
            air_tags = set(air.get(base.tag, set()))
            if not ground_tags and not air_tags:
                lines.append(f"{label}: no visible ground or air threat.")
                continue
            if ground_tags:
                lines.append(
                    f"{label}: ground threat — {self._summary_units_for_tags(enemies, ground_tags)}."
                )
            if air_tags:
                lines.append(
                    f"{label}: air threat — {self._summary_units_for_tags(enemies, air_tags)}."
                )
            if len(ground_tags) + len(air_tags) > largest[0]:
                largest = (len(ground_tags) + len(air_tags), label)
        if largest[0]:
            lines.append(f"Largest current threat: our {largest[1].lower()}.")
        return lines

    def _summary_units_for_tags(self, units: list[Any], tags: set[int]) -> str:
        selected = [unit for unit in units if unit.tag in tags]
        return self._summary_counts(_count(selected)) if selected else f"{len(tags)} enemy units"

    def _summary_counts(self, counts: dict[str, int]) -> str:
        parts = []
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            parts.append(f"{count} {self._display_name(name, plural=count != 1)}")
        return ", ".join(parts)

    def _own_unit_blocks(
        self, units: list[Any], context: EntityContext, bot: Any
    ) -> list[str]:
        role_labels = self._role_labels(bot)
        counts = _count(units)
        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for unit in units:
            name = _type_name(unit)
            state = role_labels.get(unit.tag, self._own_unit_state(unit))
            if name in IMPORTANT_UNIT_NAMES or (
                counts[name] <= 2 and name not in {"SCV", "MARINE"}
            ):
                detail = self._unit_detail(unit, bot)
            elif name != "SCV":
                # Combat units remain compact, but their group must still have
                # enough spatial context for an IM to select the right group.
                detail = f"Location: {self._area_label(unit, bot)}."
            else:
                detail = ""
            grouped[(name, state, detail)].append(unit)
        return self._group_blocks(grouped, context.own_entities)

    def _enemy_unit_blocks(
        self, units: list[Any], context: EntityContext, bot: Any
    ) -> list[str]:
        counts = _count(units)
        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for unit in units:
            state = self._enemy_state(unit, bot)
            name = _type_name(unit)
            detail = (
                self._unit_detail(unit, bot)
                if name in IMPORTANT_UNIT_NAMES
                or (counts[name] <= 2 and name not in {"SCV", "MARINE"})
                else ""
            )
            grouped[(name, state, detail)].append(unit)
        return self._group_blocks(grouped, context.enemy_entities)

    def _structure_blocks(
        self, structures: list[Any], context: EntityContext, bot: Any, *, own: bool
    ) -> list[str]:
        counts = _count(structures)
        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for structure in structures:
            name = _type_name(structure)
            state = self._structure_state(structure)
            detail = ""
            if name in IMPORTANT_STRUCTURE_NAMES or counts[name] == 1:
                detail = self._structure_detail(structure, bot)
            grouped[(name, state, detail)].append(structure)
        target = context.own_entities if own else context.enemy_entities
        return self._group_blocks(grouped, target)

    def _group_blocks(
        self,
        grouped: dict[tuple[str, str, str], list[Any]],
        entity_map: dict[str, Any],
    ) -> list[str]:
        priority = {"BATTLECRUISER": 0, "MARINE": 1, "SCV": 9}
        blocks: list[tuple[tuple[int, str, str], str]] = []
        for (name, state, extra), members in grouped.items():
            members.sort(key=lambda unit: getattr(unit, "tag", 0))
            aliases = []
            for unit in members:
                alias = self.ids.alias(unit.tag)
                aliases.append(alias)
                entity_map[alias] = unit
            label = self._display_name(name, plural=len(members) > 1)
            observation_ids = " ".join(f"[{alias}]" for alias in aliases)
            lines = [f"{observation_ids} {label}", f"Status: {state}."]
            if extra:
                lines.extend(extra.splitlines())
            blocks.append(((priority.get(name, 5), name, state), "\n".join(lines)))
        blocks.sort(key=lambda item: item[0])
        return [block for _, block in blocks]

    @staticmethod
    def _display_name(name: str, *, plural: bool = False) -> str:
        names = {
            "SUPPLYDEPOT": "Supply Depot",
            "COMMANDCENTER": "Command Center",
            "STARPORTTECHLAB": "Starport Tech Lab",
            "FUSIONCORE": "Fusion Core",
            "ORBITALCOMMAND": "Orbital Command",
            "PLANETARYFORTRESS": "Planetary Fortress",
            "BARRACKS": "Barracks",
            "BATTLECRUISER": "Battlecruiser",
            "MARINE": "Marine",
            "SCV": "SCV",
            "REFINERY": "Refinery",
            "FACTORY": "Factory",
            "STARPORT": "Starport",
        }
        value = names.get(name, name.title())
        if plural and value not in {"Barracks", "SCV"}:
            return f"{value}s"
        return value

    @staticmethod
    def _own_unit_state(unit: Any) -> str:
        if getattr(unit, "is_constructing_scv", False):
            return "constructing"
        if getattr(unit, "is_repairing", False):
            return "repairing"
        if getattr(unit, "is_attacking", False):
            return "attacking"
        if getattr(unit, "is_idle", False):
            return "idle"
        if _type_name(unit) == "SCV":
            return "collecting resources automatically"
        return "active"

    def _enemy_state(self, unit: Any, bot: Any) -> str:
        state = "attacking" if getattr(unit, "is_attacking", False) else "visible"
        return f"{state}; {self._enemy_area_label(unit, bot)}"

    def _enemy_area_label(self, unit: Any, bot: Any) -> str:
        """Locate this specific enemy instead of applying a global threat flag."""
        ground = self._safe_mediator(bot, "get_ground_enemy_near_bases") or {}
        air = self._safe_mediator(bot, "get_flying_enemy_near_bases") or {}
        for index, base in enumerate(getattr(bot, "townhalls", [])):
            try:
                nearby_tags = set(ground.get(base.tag, set())) | set(
                    air.get(base.tag, set())
                )
            except AttributeError:
                nearby_tags = set()
            if getattr(unit, "tag", None) in nearby_tags:
                return "near our main" if index == 0 else (
                    "near our natural" if index == 1 else f"near our base {index + 1}"
                )
        return self._area_label(unit, bot)

    def _area_label(self, unit: Any, bot: Any) -> str:
        """Return a compact descriptive region without exposing raw coordinates."""
        position = getattr(unit, "position", None)
        if position is None:
            return "unknown location"
        candidates = (
            ("our main", getattr(bot, "start_location", None)),
            ("our natural", self._safe_mediator(bot, "get_own_nat")),
            (
                "enemy main",
                (getattr(bot, "enemy_start_locations", []) or [None])[0],
            ),
            ("enemy natural", self._safe_mediator(bot, "get_enemy_nat")),
            ("map center", getattr(getattr(bot, "game_info", None), "map_center", None)),
        )
        closest_name = "elsewhere"
        closest_distance = float("inf")
        for name, point in candidates:
            if point is None:
                continue
            try:
                distance = (position.x - point.x) ** 2 + (position.y - point.y) ** 2
            except AttributeError:
                continue
            if distance < closest_distance:
                closest_name, closest_distance = name, distance
        return f"near {closest_name}" if closest_distance <= 400 else "elsewhere"

    @staticmethod
    def _structure_state(structure: Any) -> str:
        progress = float(getattr(structure, "build_progress", 1.0))
        if progress < 1.0:
            return f"building ({int(progress * 100)}%)"
        if getattr(structure, "is_idle", False):
            return "idle"
        return "complete"

    @staticmethod
    def _production_text(structure: Any) -> str:
        names = []
        for order in getattr(structure, "orders", []):
            ability = getattr(order, "ability", None)
            name = getattr(ability, "friendly_name", getattr(ability, "name", ""))
            if name:
                names.append(str(name).replace("Train ", ""))
        return f"production: {', '.join(names)}" if names else ""

    @staticmethod
    def _health_label(unit: Any, *, include: bool) -> str:
        if not include:
            return ""
        percentage = float(getattr(unit, "health_percentage", 1.0))
        if percentage < 0.3:
            return f"critical ({int(percentage * 100)}%)"
        if percentage < 0.9:
            return f"damaged ({int(percentage * 100)}%)"
        return "healthy"

    def _facts(
        self,
        own_counts: dict[str, int],
        structures: dict[str, int],
        enemies: list[Any],
        enemy_structures: list[Any],
        bot: Any,
    ) -> dict[str, int | str]:
        facts: dict[str, int | str] = {}
        facts.update({f"own:{name}": count for name, count in own_counts.items()})
        facts.update({f"structure:{name}": count for name, count in structures.items()})
        facts.update({f"enemy:{name}": count for name, count in _count(enemies).items()})
        facts.update(
            {f"enemy_structure:{name}": count for name, count in _count(enemy_structures).items()}
        )
        facts["threat"] = "present" if self._safe_mediator(bot, "get_ground_enemy_near_bases") else "none"
        return facts

    def _recent_changes(self, facts: dict[str, int | str]) -> list[str]:
        if self._previous_facts is None:
            return []
        changes: list[str] = []
        for key in sorted(set(facts) | set(self._previous_facts)):
            before = self._previous_facts.get(key, 0)
            after = facts.get(key, 0)
            if before == after:
                continue
            if key == "threat":
                changes.append(
                    "A visible ground threat is near our base."
                    if after == "present"
                    else "The visible ground threat near our base is gone."
                )
            elif key.startswith("enemy_structure:") and isinstance(after, int) and after > before:
                changes.append(f"Enemy {self._display_name(key.split(':', 1)[1])} first seen.")
            elif key.startswith("own:") and isinstance(after, int) and after > before:
                changes.append(f"Our {self._display_name(key.split(':', 1)[1])} count increased to {after}.")
            elif key.startswith("structure:") and isinstance(after, int) and after > before:
                changes.append(f"Our {self._display_name(key.split(':', 1)[1])} completed.")
            if len(changes) == 5:
                break
        return changes

    def _history_blocks(self) -> list[str]:
        history = list(self._action_history)
        if self._last_validation_error:
            history.append(f"Previous validation error: {self._last_validation_error}")
        return history

    @staticmethod
    def _action_detail(action_id: str, args: Any) -> str:
        if not isinstance(args, dict):
            return ""
        if action_id == "macro.build_structure":
            return f" ({args.get('structure_id', 'structure')} near {args.get('base_location', 'base')})"
        if action_id == "macro.gas_building_controller":
            return f" (target: {args.get('to_count', '?')} Refineries)"
        return ""

    @staticmethod
    def _friendly_validation_error(error: str) -> str:
        if error.isdigit():
            return "An action used a numeric enum value. Use the documented enum name instead."
        return error

    @staticmethod
    def _workers_on_gas(bot: Any) -> int:
        gas_tags = {gas.tag for gas in getattr(bot, "gas_buildings", [])}
        return sum(
            1
            for worker in bot.workers
            if getattr(worker, "order_target", None) in gas_tags
        )

    @staticmethod
    def _safe_mediator(bot: Any, attribute: str) -> Any:
        try:
            return getattr(bot.mediator, attribute)
        except (AttributeError, KeyError):
            return None
