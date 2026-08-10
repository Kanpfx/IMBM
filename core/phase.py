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
        ready_bc = counts.get("ready:BATTLECRUISER", 0)
        pending_bc = counts.get("pending:BATTLECRUISER", 0)
        tech_ready = (
            counts.get("ready:FUSIONCORE", 0) > 0
            and counts.get("ready:STARPORTTECHLAB", 0) > 0
        )
        if ready_bc >= 1:
            phase = "bc_pressure"
        elif pending_bc >= 1:
            phase = "first_bc_transition"
        elif tech_ready:
            phase = "first_bc_preparation"
        else:
            phase = "opening_tech"
        ordered_phases = (
            "opening_tech",
            "first_bc_preparation",
            "first_bc_transition",
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
