"""Ares/python-sc2 state -> one compact model observation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from game.observation.action_history import ActionHistory
from game.actions.resolver import EntityContext
from game.observation.hints import SituationHintBuilder
from game.observation.overview import OverviewBuilder
from game.observation.renderer import observation_text
from game.observation.state import TagIdMapper
from game.observation.technology import ProductionTechnologyBuilder

PENDING_NAMES = (
    "COMMANDCENTER",
    "ORBITALCOMMAND",
    "SUPPLYDEPOT",
    "REFINERY",
    "BARRACKS",
    "FACTORY",
    "STARPORT",
    "FUSIONCORE",
    "STARPORTTECHLAB",
    "MARINE",
    "REAPER",
    "MARAUDER",
    "GHOST",
    "HELLION",
    "WIDOWMINE",
    "CYCLONE",
    "SIEGETANK",
    "THOR",
    "VIKINGFIGHTER",
    "MEDIVAC",
    "LIBERATOR",
    "BANSHEE",
    "RAVEN",
    "BATTLECRUISER",
)

IMPORTANT_UNIT_NAMES = {
    "BATTLECRUISER",
    "MEDIVAC",
    "RAVEN",
    "GHOST",
    "SIEGETANK",
}
COMPACT_UNIT_NAMES = {"SCV", "MARINE", "MULE"}
IMPORTANT_STRUCTURE_NAMES = {
    "COMMANDCENTER",
    "ORBITALCOMMAND",
    "PLANETARYFORTRESS",
    "FACTORY",
    "STARPORT",
    "FUSIONCORE",
    "STARPORTTECHLAB",
}
COMPACT_STRUCTURE_NAMES = {
    "SUPPLYDEPOT",
    "SUPPLYDEPOTLOWERED",
    "REFINERY",
    "REFINERYRICH",
    "BUNKER",
    "MISSILETURRET",
}


@dataclass
class Observation:
    iteration: int
    counts: dict[str, int]
    text: str
    context: EntityContext


def _type_name(unit: Any) -> str:
    type_name = getattr(getattr(unit, "type_id", None), "name", None)
    if type_name:
        return type_name
    try:
        return getattr(unit, "name", "UNKNOWN") or "UNKNOWN"
    except (AttributeError, KeyError, TypeError, ValueError):
        return "UNKNOWN"


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
        self.overview_builder = OverviewBuilder()
        self.hint_builder = SituationHintBuilder()
        self.technology_builder = ProductionTechnologyBuilder()
        self.action_history = ActionHistory()
        self._previous_facts: dict[str, int | str] | None = None

    def record_registered_actions(
        self, actions: list[dict[str, Any]], time: str = "--:--"
    ) -> None:
        for action in actions:
            self.action_history.record(action, time, "accepted")

    def sync_active_actions(
        self, actions: list[dict[str, Any]], time: str = "--:--"
    ) -> None:
        self.action_history.sync_active(actions, time)

    def record_failed_actions(
        self, actions: list[Any], time: str = "--:--", reason: str = ""
    ) -> None:
        for action in actions:
            self.action_history.record(action, time, "failed", reason)

    def collect_frame(self, bot: Any) -> None:
        """Collect short-lived facts even when no model observation is due."""
        self.hint_builder.collect_frame(bot)

    def build(self, bot: Any, iteration: int) -> Observation:
        own_units = list(bot.units)
        structures = list(bot.structures)
        enemies = [
            unit
            for unit in bot.enemy_units
            if getattr(unit, "is_visible", True)
            and not getattr(unit, "is_memory", False)
        ]
        remembered_enemies = [
            unit for unit in bot.enemy_units if getattr(unit, "is_memory", False)
        ]
        enemy_structures = [
            unit for unit in bot.enemy_structures if getattr(unit, "is_visible", True)
        ]
        remembered_structures = [
            unit
            for unit in bot.enemy_structures
            if not getattr(unit, "is_visible", True)
        ]
        own_counts = _count(own_units)
        structure_counts = _count(structures)
        pending = self._pending_counts(bot)
        counts = dict(own_counts)
        counts.update(structure_counts)
        counts.update({f"pending:{name}": value for name, value in pending.items()})

        context = self.execution_context(bot)
        own_unit_blocks = self._own_unit_blocks(own_units, context, bot)
        own_structure_blocks = self._structure_blocks(
            structures, context, bot, own=True
        )
        enemy_unit_blocks = self._enemy_unit_blocks(enemies, context, bot)
        enemy_structure_blocks = self._structure_blocks(
            enemy_structures, context, bot, own=False
        )
        facts = self._facts(own_counts, structures, enemies, enemy_structures, bot)
        overview = self.overview_builder.build(
            bot,
            structures,
            own_units,
            enemies,
            enemy_structures,
        )
        data = {
            "overview": overview,
            "situational_hints": self.hint_builder.build(bot),
            "own_unit_blocks": own_unit_blocks,
            "own_structure_blocks": own_structure_blocks,
            "enemy_unit_blocks": enemy_unit_blocks,
            "enemy_structure_blocks": enemy_structure_blocks,
            "remembered_enemy_unit_blocks": self._remembered_enemy_unit_blocks(
                remembered_enemies, bot
            ),
            "remembered_enemy_structure_blocks": (
                self._remembered_enemy_structure_blocks(remembered_structures, bot)
            ),
            "production_and_technology": self.technology_builder.build(
                bot, structures, pending
            ),
            "action_history": self._action_history_text(),
            "recent_changes": self._recent_changes(facts),
        }
        self._previous_facts = facts
        return Observation(iteration, counts, observation_text(data), context)

    def execution_context(self, bot: Any) -> EntityContext:
        """Build a lightweight current-frame context without rendering a prompt."""
        context = EntityContext()
        self._add_execution_context(bot, context)
        for entity in list(bot.units) + list(bot.structures):
            context.own_entities[self.ids.alias(entity.tag)] = entity
        for entity in list(bot.enemy_units) + list(bot.enemy_structures):
            if getattr(entity, "is_visible", True) and not getattr(
                entity, "is_memory", False
            ):
                context.enemy_entities[self.ids.alias(entity.tag)] = entity
        return context

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
        for name in PENDING_NAMES:
            if hasattr(UnitTypeId, name):
                pending[name] = int(bot.already_pending(getattr(UnitTypeId, name)))
        return pending

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
        lines.append(f"Position: {self._position_label(unit, bot)}")
        energy = self._energy_line(unit)
        if energy:
            lines.append(energy)
        if _type_name(unit) == "BATTLECRUISER":
            lines.extend(self._battlecruiser_ability_lines(unit))
        return "\n".join(lines)

    @staticmethod
    def _battlecruiser_ability_lines(unit: Any) -> list[str]:
        """Expose only the two BC decisions that model can act on directly."""
        abilities = getattr(unit, "abilities", None)
        if abilities is None:
            return [
                "Tactical Jump: [Unknown]",
                "Yamato Cannon: [Unknown]",
            ]
        names = {getattr(ability, "name", str(ability)) for ability in abilities}
        return [
            "Tactical Jump: ready"
            if "EFFECT_TACTICALJUMP" in names
            else "Tactical Jump: unavailable",
            "Yamato Cannon: ready"
            if "YAMATO_YAMATOGUN" in names
            else "Yamato Cannon: unavailable",
        ]

    def _structure_detail(self, structure: Any, bot: Any) -> str:
        lines = self._health_lines(structure)
        lines.append(f"Position: {self._position_label(structure, bot)}")
        energy = self._energy_line(structure)
        if energy:
            lines.append(energy)
        return "\n".join(lines)

    @staticmethod
    def _health_lines(unit: Any) -> list[str]:
        health = getattr(unit, "health", None)
        health_max = getattr(unit, "health_max", None)
        if not isinstance(health, (int, float)) or not isinstance(
            health_max, (int, float)
        ):
            return []
        if health_max <= 0:
            return []
        return [
            f"Health: {int(health)}/{int(health_max)} ({int((health / health_max) * 100)}%)"
        ]

    @staticmethod
    def _health_list(units: list[Any]) -> str:
        values: list[str] = []
        for unit in units:
            health = getattr(unit, "health", None)
            health_max = getattr(unit, "health_max", None)
            if (
                isinstance(health, (int, float))
                and isinstance(health_max, (int, float))
                and health_max > 0
            ):
                values.append(f"{int(health)}/{int(health_max)}")
                continue
            percentage = getattr(unit, "health_percentage", None)
            if isinstance(percentage, (int, float)):
                values.append(f"{int(percentage * 100)}%")
        return f"Health: [{', '.join(values)}]" if values else ""

    @staticmethod
    def _energy_line(unit: Any) -> str:
        energy = getattr(unit, "energy", 0)
        energy_max = getattr(unit, "energy_max", 0)
        if not isinstance(energy, (int, float)) or not isinstance(
            energy_max, (int, float)
        ):
            return ""
        if energy_max <= 0:
            return ""
        return f"Energy: {int(energy)}/{int(energy_max)}"

    def _position_label(self, unit: Any, bot: Any) -> str:
        position = getattr(unit, "position", None)
        if position is None:
            return "[Unknown]"
        try:
            coordinates = f"({int(position.x)}, {int(position.y)})"
        except (AttributeError, TypeError, ValueError):
            coordinates = "[Unknown]"
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

    def _own_unit_blocks(
        self, units: list[Any], context: EntityContext, bot: Any
    ) -> list[str]:
        role_labels = self._role_labels(bot)
        counts = _count(units)
        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for unit in units:
            name = _type_name(unit)
            state = role_labels.get(unit.tag, self._own_unit_state(unit))
            if name in COMPACT_UNIT_NAMES:
                detail = f"Location: {self._area_label(unit, bot)}"
            elif name in IMPORTANT_UNIT_NAMES or counts[name] <= 2:
                detail = self._unit_detail(unit, bot)
            else:
                # Combat units remain compact, but their group must still have
                # enough spatial context for the model to select the right group.
                detail = f"Location: {self._area_label(unit, bot)}"
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
                or (counts[name] <= 2 and name not in COMPACT_UNIT_NAMES)
                else ""
            )
            grouped[(name, state, detail)].append(unit)
        return self._group_blocks(grouped, context.enemy_entities)

    def _remembered_enemy_unit_blocks(
        self, units: list[Any], bot: Any
    ) -> list[str]:
        grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for unit in units:
            grouped[(_type_name(unit), self._area_label(unit, bot))].append(unit)

        blocks: dict[tuple[str, str, str], list[Any]] = {}
        for (name, location), members in grouped.items():
            ages: list[int] = []
            for unit in members:
                try:
                    ages.append(max(0, int(float(getattr(unit, "age", 0.0)))))
                except (AttributeError, TypeError, ValueError):
                    ages.append(0)
            youngest, oldest = min(ages), max(ages)
            age = str(youngest) if youngest == oldest else f"{youngest}-{oldest}"
            blocks[
                (
                    name,
                    f"last seen {age}s ago",
                    f"Location: {location}",
                )
            ] = members
        return self._group_blocks(blocks, None)

    def _remembered_enemy_structure_blocks(
        self, structures: list[Any], bot: Any
    ) -> list[str]:
        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for structure in structures:
            grouped[
                (
                    _type_name(structure),
                    "last known",
                    f"Last known position: {self._position_label(structure, bot)}",
                )
            ].append(structure)
        return self._group_blocks(grouped, None)

    def _structure_blocks(
        self, structures: list[Any], context: EntityContext, bot: Any, *, own: bool
    ) -> list[str]:
        counts = _count(structures)
        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for structure in structures:
            name = _type_name(structure)
            state = self._structure_state(structure)
            detail = ""
            if name in COMPACT_STRUCTURE_NAMES:
                detail = f"Location: {self._area_label(structure, bot)}"
            elif name in IMPORTANT_STRUCTURE_NAMES or counts[name] == 1:
                detail = self._structure_detail(structure, bot)
            grouped[(name, state, detail)].append(structure)
        target = context.own_entities if own else context.enemy_entities
        return self._group_blocks(grouped, target)

    def _group_blocks(
        self,
        grouped: dict[tuple[str, str, str], list[Any]],
        entity_map: dict[str, Any] | None,
    ) -> list[str]:
        priority = {
            "BATTLECRUISER": 0,
            **dict.fromkeys(COMPACT_UNIT_NAMES | COMPACT_STRUCTURE_NAMES, 9),
        }
        blocks: list[tuple[tuple[int, str, str], str]] = []
        for (name, state, extra), members in grouped.items():
            members.sort(key=lambda unit: getattr(unit, "tag", 0))
            if entity_map is None:
                observation_ids = f"[{','.join('*' for _ in members)}]"
            else:
                aliases = []
                for unit in members:
                    alias = self.ids.alias(unit.tag)
                    aliases.append(alias)
                    entity_map[alias] = unit
                observation_ids = f"[{','.join(aliases)}]"
            is_compact = name in COMPACT_UNIT_NAMES or name in COMPACT_STRUCTURE_NAMES
            label = self._display_name(
                name,
                plural=len(members) > 1 and not is_compact,
            )
            lines = [f"{observation_ids} {label}"]
            if state:
                lines.append(f"  Status: {state}")
            if name in COMPACT_STRUCTURE_NAMES:
                if health := self._health_list(members):
                    lines.append(f"  {health}")
            if extra:
                lines.extend(f"  {line}" for line in extra.splitlines())
            blocks.append(((priority.get(name, 5), name, state), "\n".join(lines)))
        blocks.sort(key=lambda item: item[0])
        return [block for _, block in blocks]

    @staticmethod
    def _display_name(name: str, *, plural: bool = False) -> str:
        names = {
            "SUPPLYDEPOT": "Supply Depot",
            "SUPPLYDEPOTLOWERED": "Supply Depot",
            "COMMANDCENTER": "Command Center",
            "STARPORTTECHLAB": "Starport Tech Lab",
            "FUSIONCORE": "Fusion Core",
            "ORBITALCOMMAND": "Orbital Command",
            "PLANETARYFORTRESS": "Planetary Fortress",
            "BARRACKS": "Barracks",
            "BATTLECRUISER": "Battlecruiser",
            "MARINE": "Marine",
            "MULE": "MULE",
            "SCV": "SCV",
            "BUNKER": "Bunker",
            "MISSILETURRET": "Missile Turret",
            "REFINERY": "Refinery",
            "REFINERYRICH": "Refinery",
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
                return (
                    "near our main"
                    if index == 0
                    else (
                        "near our natural"
                        if index == 1
                        else f"near our base {index + 1}"
                    )
                )
        return self._area_label(unit, bot)

    def _area_label(self, unit: Any, bot: Any) -> str:
        """Return a compact descriptive region without exposing raw coordinates."""
        position = getattr(unit, "position", None)
        if position is None:
            return "[Unknown]"
        candidates = (
            ("our main", getattr(bot, "start_location", None)),
            ("our natural", self._safe_mediator(bot, "get_own_nat")),
            (
                "enemy main",
                (getattr(bot, "enemy_start_locations", []) or [None])[0],
            ),
            ("enemy natural", self._safe_mediator(bot, "get_enemy_nat")),
            (
                "map center",
                getattr(getattr(bot, "game_info", None), "map_center", None),
            ),
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
            return "ready and idle"
        return "ready"

    def _facts(
        self,
        own_counts: dict[str, int],
        structures: list[Any],
        enemies: list[Any],
        enemy_structures: list[Any],
        bot: Any,
    ) -> dict[str, int | str]:
        facts: dict[str, int | str] = {}
        facts.update({f"own:{name}": count for name, count in own_counts.items()})
        structure_counts = _count(structures)
        ready_structure_counts = _count(
            [
                structure
                for structure in structures
                if float(getattr(structure, "build_progress", 1.0)) >= 1.0
            ]
        )
        facts.update(
            {f"structure:{name}": count for name, count in structure_counts.items()}
        )
        facts.update(
            {
                f"ready_structure:{name}": count
                for name, count in ready_structure_counts.items()
            }
        )
        facts.update(
            {f"enemy:{name}": count for name, count in _count(enemies).items()}
        )
        facts.update(
            {
                f"enemy_structure:{name}": count
                for name, count in _count(enemy_structures).items()
            }
        )
        facts["threat"] = (
            "present"
            if self._safe_mediator(bot, "get_ground_enemy_near_bases")
            else "none"
        )
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
            elif (
                key.startswith("enemy_structure:")
                and isinstance(after, int)
                and after > before
            ):
                changes.append(
                    f"Enemy {self._display_name(key.split(':', 1)[1])} first seen."
                )
            elif key.startswith("own:") and isinstance(after, int) and after > before:
                changes.append(
                    f"Our {self._display_name(key.split(':', 1)[1])} count increased to {after}."
                )
            elif (
                key.startswith("ready_structure:")
                and isinstance(after, int)
                and after > before
            ):
                changes.append(
                    f"Our {self._display_name(key.split(':', 1)[1])} became ready."
                )
            elif (
                key.startswith("structure:")
                and isinstance(after, int)
                and after > before
            ):
                name = key.split(":", 1)[1]
                ready_key = f"ready_structure:{name}"
                ready_increased = facts.get(ready_key, 0) > self._previous_facts.get(
                    ready_key, 0
                )
                if not ready_increased:
                    changes.append(f"Our {self._display_name(name)} started building.")
            if len(changes) == 5:
                break
        return changes

    def _action_history_text(self) -> str:
        return self.action_history.render()

    @staticmethod
    def _safe_mediator(bot: Any, attribute: str) -> Any:
        try:
            return getattr(bot.mediator, attribute)
        except (AttributeError, KeyError):
            return None
