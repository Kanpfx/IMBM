"""Iteration-based scheduling kept separate from Ares' YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    # In IMBM mode the foreground IM owns every non-automatic decision.
    # A decision is deliberately awaited every thirty python-sc2 ``on_step``
    # iterations.
    # This is not SC2's ``state.game_loop`` counter.
    im_interval_iterations: int = 30
    # After the blocking cold start, refresh BM guidance asynchronously every
    # 240 on_step iterations. IM requests do not preempt this schedule.
    bm_refresh_iterations: int = 240
    directive_ttl_iterations: int = 360
    max_actions_per_decision: int = 6
    max_action_units: int = 12
    max_action_targets: int = 8
    max_point_nudge_tiles: float = 2.0
    deferred_action_ttl_iterations: int = 180
    resource_queue_mineral_tolerance: int = 120
    resource_queue_vespene_tolerance: int = 60
    # Keep short-lived combat behaviors active for the complete IM cycle.
    persistent_action_iterations: int = 30
