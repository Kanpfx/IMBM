"""Canonical shared IMBM observation renderer."""

from __future__ import annotations

from typing import Any


def _tag(name: str, content: str | list[str]) -> str:
    """Wrap one observation domain in a stable XML-like semantic tag."""
    if isinstance(content, list):
        body = "\n\n".join(content) if content else "[Empty]"
    else:
        body = content or "[Empty]"
    return f"<{name}>\n{body}\n</{name}>"


def _subsection(label: str, content: str | list[str], *, empty: str = "[Empty]") -> str:
    if isinstance(content, list):
        body = "\n\n".join(content) if content else empty
    else:
        body = content or empty
    return f"## {label}\n{body}"


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
    economy = "\n".join(
        (
            f"Bases: {data['base_overview']}.",
            (
                f"Workers: {data['workers']} total — "
                f"{data['workers_on_minerals']} mining minerals, "
                f"{data['workers_on_gas']} mining gas, "
                f"{data['idle_workers']} idle."
            ),
            f"Supply status: {data['supply_status']}.",
        )
    )
    overview = "\n\n".join(
        (
            _subsection("Game state", game_state),
            _subsection("Economy", economy),
            _subsection(
                "Production and technology", data["production_and_technology"]
            ),
        )
    )
    own_forces = "\n\n".join(
        (
            _subsection("Units", data["own_unit_blocks"]),
            _subsection("Structures", data["own_structure_blocks"]),
        )
    )
    visible_enemy = "\n\n".join(
        (
            _subsection(
                "Units",
                data["enemy_unit_blocks"],
                empty="[Empty \u2014 no enemy units are visible now.]",
            ),
            _subsection(
                "Structures",
                data["enemy_structure_blocks"],
                empty="[Empty \u2014 no enemy structures are visible now.]",
            ),
        )
    )
    recent_history = "\n\n".join(
        (
            _subsection("Recent changes", data["recent_changes"]),
            _subsection("Action history", data["action_history"]),
        )
    )
    return "\n\n".join(
        (
            _tag("overview", overview),
            _tag("own_forces", own_forces),
            _tag("visible_enemy", visible_enemy),
            _tag("recent_history", recent_history),
        )
    )
