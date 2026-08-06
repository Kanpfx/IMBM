"""Deterministic phase selection for the fixed Battlecruiser Rush card."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class PhaseState:
    id: str
    revision: int


class PhaseResolver:
    def __init__(self) -> None:
        self._last_id: str | None = None
        self._revision = 0

    def resolve(self, counts: Mapping[str, int]) -> PhaseState:
        completed_bc = counts.get("BATTLECRUISER", 0)
        factory_started = (
            counts.get("FACTORY", 0) + counts.get("pending:FACTORY", 0) > 0
        )
        tech_ready = (
            counts.get("FUSIONCORE", 0) > 0
            and counts.get("STARPORT", 0) > 0
            and counts.get("STARPORTTECHLAB", 0) > 0
        )
        if completed_bc >= 1:
            phase = "bc_pressure"
        elif tech_ready:
            phase = "first_battlecruiser"
        elif factory_started:
            phase = "opening_air_tech"
        else:
            phase = "opening_factory"
        ordered_phases = (
            "opening_factory",
            "opening_air_tech",
            "first_battlecruiser",
            "bc_pressure",
        )
        if self._last_id is not None and ordered_phases.index(
            phase
        ) < ordered_phases.index(self._last_id):
            phase = self._last_id
        if phase != self._last_id:
            self._last_id = phase
            self._revision += 1
        return PhaseState(phase, self._revision)
