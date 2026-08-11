"""Human-readable action formatting kept outside structured telemetry."""

from __future__ import annotations

import json
from typing import Any


def format_action(action: dict[str, Any]) -> str:
    """Render a normalized action as ``Name(arg=value)``."""
    action_id = str(action.get("id", "UnknownAction"))
    args = action.get("args")
    if not isinstance(args, dict):
        return f"{action_id}()"
    rendered_args = ", ".join(
        f"{name}={_format_value(value)}" for name, value in args.items()
    )
    return f"{action_id}({rendered_args})"


def format_indexed_actions(actions: list[dict[str, Any]]) -> list[str]:
    """Render one indexed action per line for chat and console output."""
    if not actions:
        return ["actions=[]"]
    return [
        f"actions[{index}]={format_action(action)}"
        for index, action in enumerate(actions)
    ]


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
