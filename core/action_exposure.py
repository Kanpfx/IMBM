"""State-driven model action surfaces for the current Battlecruiser Rush."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from config.policy import COMBAT_UNIT_TYPES
from knowledge.loader import ActionCatalog
from runtime.resolver import EntityContext


BC_BUILD_TARGETS = (
    "SUPPLYDEPOT",
    "BARRACKS",
    "FACTORY",
    "STARPORT",
    "FUSIONCORE",
)
BC_COMPOSITION_TARGETS = ("MARINE", "BATTLECRUISER")


class ActionSurfaceError(ValueError):
    pass


@dataclass(frozen=True)
class ActionSurface:
    """The exact action subset and argument domains shown to one model call."""

    entries: list[dict[str, Any]]
    action_ids: frozenset[str]
    parameter_domains: dict[str, dict[str, frozenset[str]]]

    def validate(self, entry: dict[str, Any], args: dict[str, Any]) -> None:
        action_id = entry["id"]
        if action_id not in self.action_ids:
            raise ActionSurfaceError(
                f"action {entry['name']!r} is not currently available"
            )
        for name, allowed in self.parameter_domains.get(action_id, {}).items():
            if name not in args:
                continue
            value = args[name]
            if isinstance(value, dict):
                submitted = {str(item) for item in value}
            elif isinstance(value, list):
                submitted = {
                    EntityContext.canonical_entity_alias(item) for item in value
                }
            else:
                try:
                    submitted = {EntityContext.canonical_entity_alias(value)}
                except ValueError:
                    submitted = {str(value)}
            if not submitted.issubset(allowed):
                invalid = sorted(submitted - allowed)
                raise ActionSurfaceError(
                    f"{name} is not currently available: {invalid}; "
                    f"allowed values are {sorted(allowed)}"
                )


@dataclass(frozen=True)
class _Availability:
    status: str
    note: str
    domains: dict[str, frozenset[str]]


class BCRushActionExposure:
    """Reduce the BC action union to the current state and tech frontier."""

    def __init__(self, catalog: ActionCatalog):
        self.catalog = catalog

    def build(
        self,
        bot: Any,
        context: EntityContext,
        candidate_action_ids: set[str],
    ) -> ActionSurface:
        prompt_entries: list[dict[str, Any]] = []
        domains: dict[str, dict[str, frozenset[str]]] = {}
        for entry in self.catalog.prompt_entries(candidate_action_ids):
            availability = self._availability(entry, bot, context)
            if availability is None:
                continue
            param_names = {param["name"] for param in entry["params"]}
            if unknown := set(availability.domains) - param_names:
                raise ValueError(
                    f"{entry['id']} availability references unknown parameters: "
                    f"{sorted(unknown)}"
                )
            prompt_entry = deepcopy(entry)
            prompt_entry["prompt_availability"] = {
                "status": availability.status,
                "note": availability.note,
            }
            for param in prompt_entry["params"]:
                allowed = availability.domains.get(param["name"])
                if allowed is None:
                    continue
                key = (
                    "allowed_keys"
                    if param["type"] == "army_composition"
                    else "allowed_values"
                )
                param[key] = sorted(allowed)
            prompt_entries.append(prompt_entry)
            domains[entry["id"]] = availability.domains
        return ActionSurface(
            prompt_entries,
            frozenset(entry["id"] for entry in prompt_entries),
            domains,
        )

    def _availability(
        self, entry: dict[str, Any], bot: Any, context: EntityContext
    ) -> _Availability | None:
        config = entry.get("availability", {})
        mode = config.get("mode", "always")
        if mode == "bc_build_frontier":
            return self._build_structure(bot, context)
        if mode == "bc_gas":
            return self._gas(bot, context)
        if mode == "bc_tech_frontier":
            return self._tech_frontier(context)
        if mode == "bc_upgrade_cc":
            return self._upgrade_cc(bot, context)
        if mode == "bc_production":
            return self._production(context)
        if mode == "bc_spawn":
            return self._spawn(bot, context)
        if mode == "bc_expansion":
            return self._expansion(bot, context)
        if mode == "bc_actor":
            return self._actor(entry, config, context)
        if mode == "bc_group":
            return self._group(config, context)
        if mode == "always":
            return _Availability("available_now", "General action.", {})
        raise ValueError(f"unsupported availability mode for {entry['id']}: {mode}")

    def _build_structure(
        self, bot: Any, context: EntityContext
    ) -> _Availability | None:
        if not self._aliases(context.own_entities, {"SCV"}):
            return None
        targets = {
            target
            for target in BC_BUILD_TARGETS
            if self._tech_progress(bot, target, context) >= 0.85
            and not self._has_unready(context, target)
        }
        if not targets:
            return None
        return _Availability(
            "development_frontier",
            "A worker can start one of the currently tech-ready structures.",
            {"structure_id": frozenset(targets)},
        )

    def _gas(self, bot: Any, context: EntityContext) -> _Availability | None:
        if not self._aliases(context.own_entities, {"SCV"}) or not self._aliases(
            context.own_entities,
            {"COMMANDCENTER", "ORBITALCOMMAND", "PLANETARYFORTRESS"},
        ):
            return None
        townhalls = list(getattr(bot, "townhalls", []) or [])
        gas_buildings = list(getattr(bot, "gas_buildings", []) or [])
        if townhalls and len(gas_buildings) >= len(townhalls) * 2:
            return None
        return _Availability(
            "development_frontier",
            "A worker and a town hall can support another Refinery if a geyser is free.",
            {},
        )

    def _tech_frontier(self, context: EntityContext) -> _Availability | None:
        targets: set[str]
        if not self._has_any(context, "FACTORY"):
            targets = {"FACTORY"}
        elif not self._has_ready(context, "FACTORY"):
            targets = set()
        elif not self._has_any(context, "STARPORT"):
            targets = {"STARPORT"}
        elif not self._has_ready(context, "STARPORT"):
            targets = set()
        else:
            targets = {
                target
                for target in ("FUSIONCORE", "STARPORTTECHLAB")
                if not self._has_any(context, target)
            }
            if not targets and self._has_ready(
                context, "FUSIONCORE"
            ) and self._has_ready(context, "STARPORTTECHLAB"):
                targets = {"BATTLECRUISER"}
        if not targets:
            return None
        return _Availability(
            "development_frontier",
            "These are the next Battlecruiser technology targets reachable now.",
            {"desired_tech": frozenset(targets)},
        )

    def _upgrade_cc(
        self, bot: Any, context: EntityContext
    ) -> _Availability | None:
        command_centers = self._aliases(
            context.own_entities, {"COMMANDCENTER"}, ready=True, idle=True
        )
        if not command_centers or self._tech_progress(
            bot, "ORBITALCOMMAND", context
        ) < 1.0:
            return None
        return _Availability(
            "available_now",
            "At least one ready idle Command Center can become an Orbital Command.",
            {"to": frozenset({"ORBITALCOMMAND"})},
        )

    def _production(self, context: EntityContext) -> _Availability | None:
        if not self._aliases(context.own_entities, {"SCV"}):
            return None
        return _Availability(
            "development_frontier",
            "May add BC-Rush technology and production for the selected composition.",
            {"army_composition_dict": frozenset(BC_COMPOSITION_TARGETS)},
        )

    def _spawn(self, bot: Any, context: EntityContext) -> _Availability | None:
        trainable: set[str] = set()
        if self._has_ready(context, "BARRACKS"):
            trainable.add("MARINE")
        if self._bc_trainable(bot, context):
            trainable.add("BATTLECRUISER")
        if not trainable:
            return None
        return _Availability(
            "available_now",
            "Only units with ready technology and a production structure are allowed.",
            {"army_composition_dict": frozenset(trainable)},
        )

    def _expansion(self, bot: Any, context: EntityContext) -> _Availability | None:
        if not self._aliases(context.own_entities, {"SCV"}):
            return None
        expansions = getattr(getattr(bot, "mediator", None), "get_own_expansions", None)
        if expansions is not None and not expansions:
            return None
        return _Availability(
            "development_frontier",
            "A worker can take an unoccupied expansion location.",
            {},
        )

    def _actor(
        self,
        entry: dict[str, Any],
        config: dict[str, Any],
        context: EntityContext,
    ) -> _Availability | None:
        actor_types = set(config.get("actor_unit_types") or COMBAT_UNIT_TYPES)
        actors = self._aliases(context.own_entities, actor_types)
        ability = config.get("required_ability")
        if ability:
            actors = {
                alias
                for alias in actors
                if self._ability_ready(context.own_entities[alias], ability)
            }
        enemies = frozenset(context.enemy_entities)
        if not actors or (config.get("requires_enemy") and not enemies):
            return None
        actor_param = config.get("actor_param", "unit")
        domains: dict[str, frozenset[str]] = {actor_param: frozenset(actors)}
        for param_name in config.get("enemy_params", []):
            domains[param_name] = enemies
        note = f"Current actors: {', '.join(f'[{alias}]' for alias in sorted(actors))}."
        return _Availability("available_now", note, domains)

    def _group(
        self, config: dict[str, Any], context: EntityContext
    ) -> _Availability | None:
        actor_types = set(config.get("actor_unit_types") or COMBAT_UNIT_TYPES)
        actors = self._aliases(context.own_entities, actor_types)
        if len(actors) < int(config.get("minimum_actors", 2)):
            return None
        enemies = frozenset(context.enemy_entities)
        if config.get("requires_enemy") and not enemies:
            return None
        domains: dict[str, frozenset[str]] = {"group": frozenset(actors)}
        for param_name in config.get("enemy_params", []):
            domains[param_name] = enemies
        grids = frozenset(context.grids)
        for param_name in config.get("grid_params", []):
            if not grids:
                return None
            domains[param_name] = grids
        note = f"Current group candidates: {', '.join(f'[{a}]' for a in sorted(actors))}."
        return _Availability("available_now", note, domains)

    @staticmethod
    def _aliases(
        entities: dict[str, Any],
        unit_types: set[str],
        *,
        ready: bool = False,
        idle: bool = False,
    ) -> set[str]:
        aliases: set[str] = set()
        for alias, entity in entities.items():
            name = getattr(getattr(entity, "type_id", None), "name", "UNKNOWN")
            if name not in unit_types:
                continue
            if ready and not bool(getattr(entity, "is_ready", True)):
                continue
            if idle and not bool(getattr(entity, "is_idle", False)):
                continue
            aliases.add(alias)
        return aliases

    @classmethod
    def _has_any(cls, context: EntityContext, unit_type: str) -> bool:
        return bool(cls._aliases(context.own_entities, {unit_type}))

    @staticmethod
    def _has_unready(context: EntityContext, unit_type: str) -> bool:
        return any(
            getattr(getattr(entity, "type_id", None), "name", "UNKNOWN")
            == unit_type
            and not bool(getattr(entity, "is_ready", True))
            for entity in context.own_entities.values()
        )

    @classmethod
    def _has_ready(cls, context: EntityContext, unit_type: str) -> bool:
        return bool(cls._aliases(context.own_entities, {unit_type}, ready=True))

    @staticmethod
    def _ability_ready(unit: Any, ability_name: str) -> bool:
        abilities: Iterable[Any] | None = getattr(unit, "abilities", None)
        if abilities is None:
            return False
        return ability_name in {
            getattr(ability, "name", str(ability)) for ability in abilities
        }

    @classmethod
    def _bc_trainable(cls, bot: Any, context: EntityContext) -> bool:
        if not cls._has_ready(context, "FUSIONCORE"):
            return False
        has_techlab = cls._has_ready(context, "STARPORTTECHLAB") or any(
            getattr(entity, "has_techlab", False)
            for entity in context.own_entities.values()
            if getattr(getattr(entity, "type_id", None), "name", "") == "STARPORT"
            and getattr(entity, "is_ready", True)
        )
        if not has_techlab:
            return False
        checker = getattr(bot, "tech_ready_for_unit", None)
        if not callable(checker):
            return True
        try:
            from sc2.ids.unit_typeid import UnitTypeId

            return bool(checker(UnitTypeId.BATTLECRUISER))
        except (AttributeError, KeyError, TypeError):
            return False

    @classmethod
    def _tech_progress(
        cls, bot: Any, unit_type: str, context: EntityContext
    ) -> float:
        checker = getattr(bot, "tech_requirement_progress", None)
        if callable(checker):
            try:
                from sc2.ids.unit_typeid import UnitTypeId

                return float(checker(UnitTypeId[unit_type]))
            except (AttributeError, KeyError, TypeError, ValueError):
                pass
        prerequisites = {
            "SUPPLYDEPOT": (),
            "BARRACKS": ("SUPPLYDEPOT",),
            "FACTORY": ("BARRACKS",),
            "STARPORT": ("FACTORY",),
            "FUSIONCORE": ("STARPORT",),
            "ORBITALCOMMAND": ("BARRACKS",),
        }
        required = prerequisites.get(unit_type, ())
        return 1.0 if all(cls._has_ready(context, item) for item in required) else 0.0
