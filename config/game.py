"""Model scheduling and validation limits, separate from Ares configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    # Preserve the nominal old interval: 60 callbacks at GameStep=2, 22.4 loops/s.
    model_interval_seconds: float = 60 * 2 / 22.4
    max_actions_per_decision: int = 8
    max_action_units: int = 12
    max_action_targets: int = 8
    max_point_nudge_tiles: float = 2.0
    deferred_action_ttl_iterations: int = 180
    resource_queue_mineral_tolerance: int = 120
    resource_queue_vespene_tolerance: int = 60
