"""Game-loop configuration kept separate from Ares' YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    # In IMBM mode the foreground IM owns every non-automatic decision.
    # A decision is deliberately awaited every ten python-sc2 ``on_step`` ticks.
    # This is not SC2's ``state.game_loop`` counter.
    im_interval_ticks: int = 10
    # Refresh strategic guidance about every 240 on_step ticks. This reduces
    # the phase-transition wait observed with the previous 360-tick cadence
    # while keeping BM materially less frequent than foreground IM decisions.
    bm_refresh_loops: int = 240
    directive_ttl_loops: int = 360
    max_actions_per_decision: int = 6
    max_action_units: int = 12
    max_action_targets: int = 8
    max_point_nudge_tiles: float = 2.0
    deferred_action_ttl_loops: int = 180
