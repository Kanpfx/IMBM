"""Canonical shared IMBM observation renderer."""

from __future__ import annotations

from typing import Any


def _section(title: str, content: str | list[str], level: int = 1) -> str:
    if isinstance(content, list):
        body = "\n\n".join(content) if content else "[Empty]"
    else:
        body = content or "[Empty]"
    return f"{'#' * level} {title}\n{body}"


def observation_text(data: dict[str, Any]) -> str:
    """Render the single factual observation read by both BM and IM."""

    game_state = "\n".join(
        (
            f"Time: {data['time']}",
            f"Race: Terran (you) vs {data['enemy_race']} (enemy).",
            (
                f"Resources: {data['minerals']} minerals, {data['vespene']} vespene, "
                f"supply {data['supply_used']}/{data['supply_cap']} "
                f"({data['supply_free']} free)."
            ),
            f"Units: army {data['army_supply']}, workers {data['workers']}.",
        )
    )
    own_units = "\n".join(
        (
            f"Bases: {data['active_bases']} active, {data['building_bases']} building.",
            (
                f"Workers: {data['workers']} total — "
                f"{data['workers_on_minerals']} mining minerals, "
                f"{data['workers_on_gas']} mining gas, "
                f"{data['idle_workers']} idle."
            ),
            f"Supply status: {data['supply_status']}.",
            "",
            "\n\n".join(data["own_unit_blocks"]) if data["own_unit_blocks"] else "[Empty]",
        )
    )
    own_situation = "\n\n".join(
        (
            _section("Own units", own_units, level=3),
            _section("Own structures", data["own_structure_blocks"], level=3),
        )
    )
    enemy_intelligence = "\n\n".join(
        (
            _section(
                "Visible enemy units",
                data["enemy_unit_blocks"]
                or "[Empty \u2014 no enemy units are visible now.]",
                level=3,
            ),
            _section(
                "Visible enemy structures",
                data["enemy_structure_blocks"]
                or "[Empty \u2014 no enemy structures are visible now.]",
                level=3,
            ),
        )
    )
    analysis = "\n\n".join(
        (
            _section("Base security", data["base_security"], level=3),
            _section("Recent changes", data["recent_changes"], level=3),
        )
    )
    return "\n\n".join(
        (
            _section("Game state", game_state, level=2),
            _section("Own situation", own_situation, level=2),
            _section("Production and technology", data["production_and_technology"], level=2),
            _section("Enemy intelligence", enemy_intelligence, level=2),
            _section("Analysis", analysis, level=2),
            _section("Action history", data["action_history"], level=2),
        )
    )
