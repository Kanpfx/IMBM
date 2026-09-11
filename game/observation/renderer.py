"""Canonical model observation renderer."""

from __future__ import annotations

from typing import Any


def _indent(content: str) -> str:
    """Indent non-empty lines by one XML nesting level."""
    return "\n".join(f"  {line}" if line else "" for line in content.splitlines())


def _tag(name: str, content: str | list[str]) -> str:
    """Wrap one observation domain in a stable XML-like semantic tag."""
    if isinstance(content, list):
        body = "\n\n".join(content) if content else "[None]"
    else:
        body = content or "[None]"
    return f"<{name}>\n{_indent(body)}\n</{name}>"


def _section(name: str, content: str | list[str], *, empty: str = "[None]") -> str:
    if isinstance(content, list):
        content = "\n\n".join(content) if content else empty
    return _tag(name, content or empty)


def observation_text(data: dict[str, Any]) -> str:
    """Render the factual observation read by model."""
    hint_sections = data["situational_hints"]
    alert_lines = [
        f"- {item}"
        for items in hint_sections.values()
        for item in items
    ]
    situation_alerts = (
        "Situational hints:\n" + "\n".join(alert_lines)
        if alert_lines
        else "Situational hints: [None]"
    )
    overview = "\n\n".join(
        (
            data["overview"]["match"],
            data["overview"]["resources"],
            data["overview"]["economy"],
            data["overview"]["military"],
            situation_alerts,
        )
    )
    technology = "\n".join(data["production_and_technology"])
    own_state = "\n\n".join(
        (
            _section("units", data["own_unit_blocks"]),
            _section("structures", data["own_structure_blocks"]),
            _section("production_and_technology", technology),
        )
    )
    enemy_state = "\n\n".join(
        (
            _section(
                "visible_units",
                data["enemy_unit_blocks"],
                empty="[None visible]",
            ),
            _section(
                "visible_structures",
                data["enemy_structure_blocks"],
                empty="[None visible]",
            ),
            _tag(
                "enemy_memory",
                "Previously seen enemy units and structures, with last-seen times and states. IDs are omitted because they cannot be selected. Current states are unknown. Last known building coordinates can be used as point targets; buildings may have moved or been destroyed.\n\n"
                + "\n\n".join(
                    (
                        _section(
                            "recently_seen_units",
                            data["remembered_enemy_unit_blocks"],
                        ),
                        _section(
                            "known_structures",
                            data["remembered_enemy_structure_blocks"],
                        ),
                    )
                ),
            ),
        )
    )
    recent_history = "\n\n".join(
        (
            _section("state_changes", data["recent_changes"]),
            _section("action_history", data["action_history"]),
        )
    )
    return "\n\n".join(
        (
            _tag("overview", overview),
            _tag("own_state", own_state),
            _tag("enemy_state", enemy_state),
            _tag("recent_history", recent_history),
        )
    )
