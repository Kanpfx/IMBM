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
        "Situation alerts:\n" + "\n".join(alert_lines)
        if alert_lines
        else "Situation alerts: [None]"
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
                "known_structures",
                data["enemy_structure_blocks"],
                empty="[None known]",
            ),
            _section("last_known_units", data["last_known_enemy_blocks"]),
        )
    )
    recent_history = "\n\n".join(
        (
            _section("state_changes", data["recent_changes"]),
            _section("action_history", "\n".join(data["action_history"])),
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
