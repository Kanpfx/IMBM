"""Compile only catalog-described instructions into registered Ares behaviors."""

from __future__ import annotations

import importlib
from math import isclose
from typing import Any

from knowledge.loader import ActionCatalog
from runtime.resolver import EntityContext, ResolveError


class InstructionError(ValueError):
    pass


class AresActionAdapter:
    def __init__(self, catalog: ActionCatalog):
        self.catalog = catalog

    def compile_and_register(
        self, bot: Any, actions: list[dict[str, Any]], context: EntityContext
    ) -> list[Any]:
        compiled: list[Any] = []
        for action in actions:
            entry = self._validate_shape(action)
            kwargs = self._resolve_arguments(entry, action["args"], context)
            module_name, class_name = entry["api"]["import"].rsplit(".", 1)
            behavior_type = getattr(importlib.import_module(module_name), class_name)
            behavior = behavior_type(**kwargs)
            bot.register_behavior(behavior)
            compiled.append(behavior)
        return compiled

    def _validate_shape(self, action: Any) -> dict[str, Any]:
        if not isinstance(action, dict) or set(action) != {"id", "args"}:
            raise InstructionError("each action must contain exactly id and args")
        if not isinstance(action["id"], str) or not isinstance(action["args"], dict):
            raise InstructionError(
                "action id must be a string and args must be an object"
            )
        try:
            entry = self.catalog.get(action["id"])
        except KeyError as exc:
            raise InstructionError(f"unknown action id: {action['id']}") from exc
        if entry.get("llm_exposure") != "eligible":
            raise InstructionError(f"{action['id']} is not enabled for LLM output")
        if entry["parser"]["mode"] != "construct_and_register":
            raise InstructionError(f"{action['id']} is not directly compilable")
        return entry

    def _resolve_arguments(
        self, entry: dict[str, Any], args: dict[str, Any], context: EntityContext
    ) -> dict[str, Any]:
        params = self.catalog.required_model_params(entry)
        unknown = set(args) - set(params)
        if unknown:
            raise InstructionError(f"unknown arguments: {sorted(unknown)}")
        kwargs: dict[str, Any] = {}
        if any(param["name"] == "group_tags" for param in entry["params"]):
            kwargs["group_tags"] = {
                context.resolve_entity(alias, own_only=True).tag
                for alias in args.get("group", [])
            }
            if not kwargs["group_tags"]:
                raise InstructionError("group requires a non-empty own-unit list")
        for name, param in params.items():
            if name not in args:
                raise InstructionError(f"missing required argument: {name}")
            try:
                if entry["id"] == "macro.tech_up" and name == "desired_tech":
                    kwargs[name] = self._resolve_tech_up_target(args[name])
                else:
                    kwargs[name] = self._resolve_value(
                        args[name], param["type"], context, args, name
                    )
            except ResolveError as exc:
                raise InstructionError(str(exc)) from exc
        for param in entry["params"]:
            if param.get("input") != "runtime":
                continue
            name = param["name"]
            if "value" not in param:
                raise InstructionError(f"runtime argument {name} has no fixed value")
            try:
                kwargs[name] = self._resolve_value(
                    param["value"], param["type"], context, args, name
                )
            except ResolveError as exc:
                raise InstructionError(str(exc)) from exc
        return kwargs

    def _resolve_value(
        self,
        value: Any,
        type_name: str,
        context: EntityContext,
        args: dict[str, Any],
        name: str,
    ) -> Any:
        if value is None:
            return None
        if type_name == "boolean":
            if not isinstance(value, bool):
                raise ResolveError(f"{name} must be a boolean")
            return value
        if type_name == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ResolveError(f"{name} must be an integer")
            return value
        if type_name == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ResolveError(f"{name} must be a number")
            return value
        if type_name == "army_composition":
            return self._resolve_army_composition(value, name)
        # The upstream generated catalog calls this a UnitTypeId even though
        # SpawnController accepts a mapping of UnitTypeId to composition data.
        # Keep the raw catalog intact during restoration and normalize its one
        # known compound parameter at the runtime boundary.
        if name == "army_composition_dict" and type_name == "unit_type_id":
            return self._resolve_army_composition(value, name)
        if type_name == "unit_ref":
            return context.resolve_entity(value)
        if type_name == "unit_refs":
            if not isinstance(value, list) or not value:
                raise ResolveError(f"{name} must be a non-empty unit id list")
            return [context.resolve_entity(alias) for alias in value]
        if type_name == "point_ref":
            return context.resolve_point(value)
        if type_name == "point_or_unit_ref":
            return (
                context.resolve_entity(value)
                if context.has_entity_alias(value)
                else context.resolve_point(value)
            )
        if type_name == "grid_ref":
            try:
                return context.grids[value]
            except KeyError as exc:
                raise ResolveError(f"unknown grid: {value}") from exc
        if type_name == "unit_type_id":
            from sc2.ids.unit_typeid import UnitTypeId

            return UnitTypeId[value]
        if type_name == "ability_id":
            from sc2.ids.ability_id import AbilityId

            return AbilityId[value]
        if type_name == "upgrade_id":
            from sc2.ids.upgrade_id import UpgradeId

            return UpgradeId[value]
        if type_name == "unit_role":
            from ares.consts import UnitRole

            return UnitRole[value]
        raise ResolveError(f"unsupported catalog type for {name}: {type_name}")

    @staticmethod
    def _resolve_tech_up_target(value: Any) -> Any:
        """Resolve only targets that Ares' ``TechUp`` can safely inspect.

        Ares indexes ``UNIT_TECH_REQUIREMENT`` during behavior execution.  A
        generic enum such as ``TECHLAB`` therefore used to pass our adapter and
        crash the game loop with a KeyError. Validate the same prerequisite
        lookup here so malformed targets become recoverable policy issues.
        """
        if not isinstance(value, str):
            raise ResolveError("desired_tech must be a unit or upgrade enum name")

        from ares.behaviors.macro.tech_up import BUILD_TECHLAB_FROM
        from ares.consts import ALL_STRUCTURES, GATEWAY_UNITS, TECHLAB_TYPES
        from ares.dicts.unit_tech_requirement import UNIT_TECH_REQUIREMENT
        from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
        from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
        from sc2.ids.unit_typeid import UnitTypeId
        from sc2.ids.upgrade_id import UpgradeId

        try:
            desired_tech: Any = UnitTypeId[value]
        except KeyError:
            try:
                desired_tech = UpgradeId[value]
            except KeyError as exc:
                raise ResolveError(f"unknown TechUp target: {value}") from exc

        try:
            if isinstance(desired_tech, UpgradeId):
                researched_from = UPGRADE_RESEARCHED_FROM[desired_tech]
            elif desired_tech in ALL_STRUCTURES:
                researched_from = desired_tech
            else:
                researched_from = next(iter(UNIT_TRAINED_FROM[desired_tech]))
                if desired_tech in GATEWAY_UNITS:
                    researched_from = UnitTypeId.GATEWAY

            if researched_from in TECHLAB_TYPES:
                if researched_from not in BUILD_TECHLAB_FROM:
                    raise KeyError(researched_from)
            else:
                UNIT_TECH_REQUIREMENT[researched_from]
        except (KeyError, StopIteration) as exc:
            raise ResolveError(
                f"{value} is not a concrete technology target supported by TechUp"
            ) from exc
        return desired_tech

    @staticmethod
    def _resolve_army_composition(value: Any, name: str) -> dict[Any, dict[str, Any]]:
        """Convert the only model-exposed composition shape to Ares enums.

        The opening is fixed to BC Rush, so allowing arbitrary unit keys would
        quietly reintroduce an unrestricted production surface.
        """
        if not isinstance(value, dict) or not value:
            raise ResolveError(f"{name} must be a non-empty object")
        allowed_units = {"MARINE", "BATTLECRUISER"}
        if set(value) - allowed_units:
            raise ResolveError(
                f"{name} may only contain {sorted(allowed_units)} in BC Rush mode"
            )
        from sc2.ids.unit_typeid import UnitTypeId

        composition: dict[Any, dict[str, Any]] = {}
        total = 0.0
        for unit_name, settings in value.items():
            if not isinstance(settings, dict) or set(settings) != {
                "proportion",
                "priority",
            }:
                raise ResolveError(
                    f"{name}.{unit_name} must contain exactly proportion and priority"
                )
            proportion = settings["proportion"]
            priority = settings["priority"]
            if isinstance(proportion, bool) or not isinstance(proportion, (int, float)):
                raise ResolveError(f"{name}.{unit_name}.proportion must be a number")
            if not 0.0 < float(proportion) <= 1.0:
                raise ResolveError(f"{name}.{unit_name}.proportion must be in (0, 1]")
            if (
                isinstance(priority, bool)
                or not isinstance(priority, int)
                or not 0 <= priority < 11
            ):
                raise ResolveError(
                    f"{name}.{unit_name}.priority must be an integer from 0 to 10"
                )
            total += float(proportion)
            composition[UnitTypeId[unit_name]] = {
                "proportion": float(proportion),
                "priority": priority,
            }
        if not isclose(total, 1.0, abs_tol=1e-6):
            raise ResolveError(f"{name} proportions must sum to 1.0")
        return composition
