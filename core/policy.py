"""Recoverable IM action review before Ares behavior construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.game import GameConfig
from config.policy import COMBAT_MICRO_ACTIONS, COMBAT_UNIT_TYPES, allowed_actions
from core.action_exposure import ActionSurface
from knowledge.loader import ActionCatalog
from runtime.ares_adapter import AresActionAdapter, InstructionError
from runtime.resolver import EntityContext


@dataclass(frozen=True)
class ValidationIssue:
    """One action-level problem suitable for a correction-model prompt."""

    index: int
    action: Any
    reason: str

    def text(self) -> str:
        return f"Action {self.index + 1}: {self.reason}"


@dataclass(frozen=True)
class ActionReview:
    """Valid actions are retained even when sibling actions need repair."""

    actions: list[dict[str, Any]]
    issues: list[ValidationIssue]
    normalizations: list[str]

    @property
    def accepted(self) -> bool:
        return not self.issues

    @property
    def message(self) -> str:
        if not self.issues:
            return "accepted"
        return "\n".join(issue.text() for issue in self.issues)


class PolicyValidator:
    def __init__(self, catalog: ActionCatalog, game_config: GameConfig):
        self.catalog = catalog
        self.adapter = AresActionAdapter(catalog)
        self.game_config = game_config

    def verify(
        self,
        bot: Any,
        actions: list[dict[str, Any]],
        context: EntityContext,
        phase: str,
        surface: ActionSurface | None = None,
    ) -> tuple[bool, str]:
        """Compatibility wrapper for callers that need all-or-nothing status."""
        review = self.review(bot, actions, context, phase, surface)
        return review.accepted, review.message

    def review(
        self,
        bot: Any,
        actions: list[dict[str, Any]],
        context: EntityContext,
        phase: str,
        surface: ActionSurface | None = None,
    ) -> ActionReview:
        """Keep valid actions and report repairable failures individually.

        This deliberately does not invent replacement actions. Deterministic
        repairs are limited to clamping a point that is only slightly outside
        the playable area; semantic repairs belong to the correction model.
        """
        if not isinstance(actions, list):
            return ActionReview(
                [], [ValidationIssue(0, actions, "actions must be a list")], []
            )

        valid: list[dict[str, Any]] = []
        issues: list[ValidationIssue] = []
        normalizations: list[str] = []
        seen_own: set[str] = set()
        for index, action in enumerate(actions):
            if index >= self.game_config.max_actions_per_decision:
                issues.append(
                    ValidationIssue(
                        index,
                        action,
                        f"at most {self.game_config.max_actions_per_decision} actions are executed per decision",
                    )
                )
                continue
            try:
                if not isinstance(action, dict):
                    raise ValueError("each action must be an object")
                action_id = action.get("id")
                entry = self.catalog.get(action_id)
                if entry["id"] not in allowed_actions(phase):
                    raise ValueError(f"action {action_id!r} is not allowed in phase {phase}")
                if entry.get("llm_exposure") != "eligible":
                    raise ValueError(f"action {action_id!r} is not enabled for LLM output")

                normalized, notes = self._normalize_action(
                    entry, action, bot, phase, context
                )
                if surface is not None:
                    surface.validate(entry, normalized["args"])
                self.adapter._validate_shape(normalized)
                self._validate_ares_behavior_constraints(action_id, normalized["args"])
                provisional_seen = set(seen_own)
                self._validate_live_args(
                    entry, normalized["args"], context, provisional_seen
                )
                self.adapter._resolve_arguments(entry, normalized["args"], context)
                seen_own = provisional_seen
                valid.append(normalized)
                normalizations.extend(
                    f"Action {index + 1}: {note}" for note in notes
                )
            except (KeyError, TypeError, InstructionError, ValueError) as exc:
                issues.append(ValidationIssue(index, action, str(exc)))
        return ActionReview(valid, issues, normalizations)

    def _normalize_action(
        self,
        entry: dict[str, Any],
        action: dict[str, Any],
        bot: Any,
        phase: str,
        context: EntityContext,
    ) -> tuple[dict[str, Any], list[str]]:
        """Apply only lossless, local corrections before validation."""
        if not isinstance(action.get("args"), dict):
            return action, []
        normalized = {"id": action.get("id"), "args": dict(action["args"])}
        notes: list[str] = []
        # ``TECHLAB`` is a common human/LLM shorthand, but it is an abstract
        # UnitTypeId which Ares' TechUp cannot look up in its technology table.
        # BC Rush has exactly one intended addon at this point: a Starport Tech
        # Lab. Normalize only in the two phases where that intent is unambiguous.
        if (
            entry["id"] == "macro.tech_up"
            and phase in {"opening_air_tech", "first_battlecruiser"}
            and normalized["args"].get("desired_tech") in {"TECHLAB", "STARPORT_TECHLAB"}
        ):
            normalized["args"]["desired_tech"] = "STARPORTTECHLAB"
            notes.append("normalized desired_tech to STARPORTTECHLAB for BC Rush")
        for param in self.catalog.required_model_params(entry).values():
            name = param["name"]
            type_name = param["type"]
            if type_name == "unit_refs":
                value = normalized["args"].get(name)
                if isinstance(value, list):
                    repaired = [
                        self._canonicalize_known_entity_alias(alias, context)
                        for alias in value
                    ]
                    if repaired != value:
                        normalized["args"][name] = repaired
                        notes.append(f"normalized {name} observation IDs")
            elif type_name in {"unit_ref", "point_or_unit_ref"}:
                value = normalized["args"].get(name)
                repaired = self._canonicalize_known_entity_alias(value, context)
                if repaired != value:
                    normalized["args"][name] = repaired
                    notes.append(f"normalized {name} observation ID")

            if param["type"] not in {"point_ref", "point_or_unit_ref"}:
                continue
            value = normalized["args"].get(name)
            if not isinstance(value, dict):
                continue
            corrected = self._clamp_nearby_point(value, bot)
            if corrected != value:
                normalized["args"][name] = corrected
                notes.append(f"clamped {name} to the playable area")
        return normalized, notes

    @staticmethod
    def _canonicalize_known_entity_alias(value: Any, context: EntityContext) -> Any:
        """Normalize only aliases that identify a current entity.

        Unknown values are retained for the ordinary resolver to reject as a
        stale ID; landmarks such as ``enemy_main`` are also intentionally left
        untouched.
        """
        try:
            canonical = context.canonical_entity_alias(value)
        except ValueError:
            return value
        return canonical if canonical in context.entities else value

    def _clamp_nearby_point(self, value: dict[str, Any], bot: Any) -> dict[str, Any]:
        if not isinstance(value.get("x"), (int, float)) or not isinstance(
            value.get("y"), (int, float)
        ):
            return value
        game_info = getattr(bot, "game_info", None)
        area = getattr(game_info, "playable_area", None)
        if area is None:
            return value
        try:
            min_x, min_y = float(area.x), float(area.y)
            max_x = min_x + float(area.width) - 1.0
            max_y = min_y + float(area.height) - 1.0
        except (AttributeError, TypeError, ValueError):
            return value
        x, y = float(value["x"]), float(value["y"])
        clamped_x = min(max(x, min_x), max_x)
        clamped_y = min(max(y, min_y), max_y)
        if (clamped_x, clamped_y) == (x, y):
            return value
        distance = max(abs(clamped_x - x), abs(clamped_y - y))
        if distance > self.game_config.max_point_nudge_tiles:
            raise ValueError("point is outside the playable area")
        return {"x": clamped_x, "y": clamped_y}

    @staticmethod
    def _validate_ares_behavior_constraints(
        action_id: str, args: dict[str, Any]
    ) -> None:
        """Reject catalog-valid values that an Ares behavior cannot execute."""
        if action_id not in {"macro.build_structure", "BuildStructure"}:
            return
        structure_name = args.get("structure_id")
        if not isinstance(structure_name, str):
            return
        from ares.dicts.structure_to_building_size import STRUCTURE_TO_BUILDING_SIZE
        from sc2.ids.unit_typeid import UnitTypeId

        try:
            structure_id = UnitTypeId[structure_name]
        except KeyError as exc:
            raise ValueError(f"unknown structure type: {structure_name}") from exc
        if structure_id not in STRUCTURE_TO_BUILDING_SIZE:
            raise ValueError(
                f"{structure_name} cannot use macro.build_structure; "
                "use macro.gas_building_controller for Refineries"
            )

    def _validate_live_args(
        self,
        entry: dict[str, Any],
        args: dict[str, Any],
        context: EntityContext,
        seen_own: set[str],
    ) -> None:
        for param in self.catalog.required_model_params(entry).values():
            if param["name"] not in args:
                continue
            value, type_name, name = args[param["name"]], param["type"], param["name"]
            if type_name == "unit_ref":
                own_only = name in {"unit", "group"}
                entity = context.resolve_entity(value, own_only=own_only)
                if own_only:
                    allowed_types = entry.get("actor_unit_types")
                    actual_type = getattr(getattr(entity, "type_id", None), "name", "UNKNOWN")
                    if allowed_types and actual_type not in allowed_types:
                        allowed = ", ".join(allowed_types)
                        raise ValueError(f"{entry['name']} requires one of: {allowed}")
                    if (
                        entry["id"] in COMBAT_MICRO_ACTIONS
                        and actual_type not in COMBAT_UNIT_TYPES
                    ):
                        allowed = ", ".join(sorted(COMBAT_UNIT_TYPES))
                        raise ValueError(
                            f"{entry['name']} is limited to combat units: {allowed}"
                        )
                    if value in seen_own:
                        raise ValueError(
                            f"unit {value} already has a higher-priority action"
                        )
                    seen_own.add(value)
            elif type_name == "unit_refs":
                if not isinstance(value, list) or not value:
                    raise ValueError(f"{name} must be a non-empty list")
                for alias in value:
                    context.resolve_entity(alias, own_only=name == "group")
            elif type_name == "point_ref":
                point = context.resolve_point(value)
                if point.x < 0 or point.y < 0:
                    raise ValueError("point must be on the playable map")
            elif type_name == "ability_id":
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be an ability enum name")
                from sc2.ids.ability_id import AbilityId

                try:
                    ability = AbilityId[value]
                except KeyError as exc:
                    raise ValueError(f"unknown ability: {value}") from exc
                actor_alias = args.get("unit")
                if isinstance(actor_alias, str):
                    actor = context.resolve_entity(actor_alias, own_only=True)
                    available = getattr(actor, "abilities", None)
                    if available is not None and ability not in available:
                        raise ValueError(
                            f"ability {value} is not ready for unit {actor_alias}"
                        )
        self._validate_fixed_abilities(entry, args, context)

    @staticmethod
    def _validate_fixed_abilities(
        entry: dict[str, Any], args: dict[str, Any], context: EntityContext
    ) -> None:
        """Check an IMBM high-level action's hidden, fixed ability."""
        actor_alias = args.get("unit")
        if not isinstance(actor_alias, str):
            return
        actor = context.resolve_entity(actor_alias, own_only=True)
        available = getattr(actor, "abilities", None)
        if available is None:
            return
        from sc2.ids.ability_id import AbilityId

        for param in entry["params"]:
            if param.get("input") != "runtime" or param.get("type") != "ability_id":
                continue
            ability_name = param.get("value")
            try:
                ability = AbilityId[ability_name]
            except (KeyError, TypeError) as exc:
                raise ValueError(f"unknown fixed ability: {ability_name}") from exc
            if ability not in available:
                raise ValueError(f"{entry['name']} is not ready for unit {actor_alias}")
