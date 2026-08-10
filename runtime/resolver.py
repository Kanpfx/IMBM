"""Current-frame aliases and controlled landmarks used by model instructions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.action_errors import ResolveError


def _normalized_label(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


@dataclass
class EntityContext:
    own_entities: dict[str, Any] = field(default_factory=dict)
    enemy_entities: dict[str, Any] = field(default_factory=dict)
    positions: dict[str, Any] = field(default_factory=dict)
    grids: dict[str, Any] = field(default_factory=dict)

    @property
    def entities(self) -> dict[str, Any]:
        return self.own_entities | self.enemy_entities

    @staticmethod
    def canonical_entity_alias(alias: Any) -> str:
        """Accept the common JSON representations of an observation ``[id]``.

        Observations deliberately display compact aliases as ``[851]``. A
        model may faithfully copy that label as ``851``, ``"851"``, or
        ``"[851]"``. All three identify the same current-frame entity; this
        conversion is deterministic and must not consume a correction turn.
        """
        if isinstance(alias, bool):
            raise ResolveError.format("unit", "an observation unit ID, not a boolean")
        if isinstance(alias, int):
            return str(alias)
        if isinstance(alias, float):
            if alias.is_integer():
                return str(int(alias))
            raise ResolveError.format("unit", "an integer observation unit ID")
        if isinstance(alias, str):
            normalized = alias.strip()
            if normalized.startswith("[") and normalized.endswith("]"):
                normalized = normalized[1:-1].strip()
            if normalized:
                return normalized
        raise ResolveError.format("unit", "an observation [id] label")

    def has_entity_alias(self, alias: Any) -> bool:
        try:
            return self.canonical_entity_alias(alias) in self.entities
        except ResolveError:
            return False

    def resolve_entity(self, alias: Any, *, own_only: bool = False) -> Any:
        source = self.own_entities if own_only else self.entities
        canonical = self.canonical_entity_alias(alias)
        try:
            return source[canonical]
        except KeyError as exc:
            raise ResolveError.invalid_value(
                "unit", canonical, "a current observation unit ID"
            ) from exc

    def resolve_point(self, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return self.positions[_normalized_label(value)]
            except KeyError as exc:
                raise ResolveError.invalid_value(
                    "point", value, "a known landmark or an {x, y} coordinate"
                ) from exc
        if not isinstance(value, dict) or not isinstance(value.get("x"), (int, float)) or not isinstance(value.get("y"), (int, float)):
            raise ResolveError.format(
                "point", "a known landmark or an {x, y} coordinate object"
            )
        from sc2.position import Point2

        return Point2((value["x"], value["y"]))
