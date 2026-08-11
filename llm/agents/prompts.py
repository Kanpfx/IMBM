"""Prompt builders for the shared IMBM observation contract."""

from __future__ import annotations

import json
from html import escape
from typing import Any

BM_ROLE = """You are an expert StarCraft II control model responsible for providing short-term strategic guidance.

Based on the current game observations, rules, and predefined strategy table, determine the current strategy phase. Then, using the goal and tactical guidance associated with the selected phase, provide 1–3 detailed natural-language strategic instructions for approximately the next 30 seconds of gameplay.

Output only natural-language strategic instructions. Do not output parameters, code, API calls, or other low-level commands. Do not provide chain-of-thought, `<thinking>` content, or other reasoning traces.
"""

IM_ROLE = """You are an expert StarCraft II control model responsible for issuing concrete, executable actions.

Based on the current game observations, tactical guidance, and available action table, select and issue appropriate short-term actions. Each action must strictly follow the specified action and parameter formats, and must use concrete information from the current observations, such as valid unit IDs, structure IDs, and target positions.

Output only the required actions in valid JSON format. Do not output natural-language explanations, code, chain-of-thought, `<thinking>` content, or other reasoning traces."""

CORRECTION_ROLE = """You are the IM Action Correction Module. Repair only the rejected actions using the observation, strategic guidance, available actions, and validation errors. Valid sibling actions have already been retained. You may change only incorrect parameters and must preserve both the original action ID and the original intent. Never add an action, replace an action with a different action, or invent action names, arguments, unit IDs, landmarks, abilities, or coordinates. If an action cannot be repaired under these rules, omit it. Return only the required JSON."""


TYPE_LEGEND = {
    "ability_id": ("Ability", "Exact SC2 ability name."),
    "army_composition": (
        "Composition",
        "BC/Marine composition object; proportions sum to 1.0.",
    ),
    "boolean": ("Boolean", "`true` or `false`."),
    "grid_ref": (
        "Grid",
        "Safety/pathing grid: `ground`, `air`, `ground_avoidance`, "
        "`air_avoidance`, or `tactical_ground`.",
    ),
    "integer": ("Integer", "Whole number."),
    "number": ("Number", "Number."),
    "point_or_unit_ref": (
        "Point | Unit",
        'Visible unit ID, landmark (`main`, `natural`, `enemy_main`), or `{"x": number, "y": number}`.',
    ),
    "point_ref": (
        "Point",
        'Landmark (`main`, `natural`, `enemy_main`) or `{"x": number, "y": number}`.',
    ),
    "unit_ref": ("Unit", "One unit ID from Observation."),
    "unit_refs": ("Units", "Non-empty list of unit IDs from Observation."),
    "unit_or_upgrade_id": (
        "Tech",
        "Exact SC2 unit, structure, add-on, or upgrade name.",
    ),
    "unit_or_unit_type_id": (
        "Unit | UnitType",
        "One current unit ID or an exact SC2 unit/structure name.",
    ),
    "unit_type_id": ("UnitType", "Exact SC2 unit or structure name, e.g. `STARPORT`."),
    "upgrade_ids": (
        "Upgrades",
        "Non-empty list of exact SC2 upgrade names.",
    ),
}

COMPOSITION_EXAMPLE = """{
  "BATTLECRUISER": {"proportion": 0.8, "priority": 0},
  "MARINE": {"proportion": 0.2, "priority": 1}
}"""


def _section(tag: str, content: str, **attributes: str) -> str:
    """Use XML only for major semantic sections, not every nested field."""
    attrs = "".join(
        f' {key}="{escape(str(value), quote=True)}"'
        for key, value in attributes.items()
    )
    body = content.strip() or "[Empty]"
    return f"<{tag}{attrs}>\n{body}\n</{tag}>"


def _list(label: str, items: list[str], *, empty: str = "[Empty]") -> str:
    body = "\n".join(f"- {item}" for item in items) or empty
    return f"{label}:\n{body}"


def bm_messages(
    observation: str,
    tactic: dict[str, Any],
    action_entries: list[dict[str, Any]],
    reason: str = "",
) -> list[dict[str, str]]:
    task = _bm_task_text(reason)
    example_phase = str(tactic["phases"][0]["id"])
    output_contract = "\n".join(
        (
            _list(
                "Rules",
                [
                    "Select exactly one phase ID from the tactical card.",
                    "Return that phase and 1-3 concrete tactical priorities.",
                    "Return only the required JSON object.",
                ],
            ),
            "JSON schema/example:",
            json.dumps(
                {
                    "phase": example_phase,
                    "guidance": ["priority 1", "priority 2"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    )
    user = "\n\n".join(
        (
            _section("observation", observation),
            _section("task", task),
            _tactic_card(tactic),
            _action_reference(action_entries),
            _section("output_contract", output_contract),
        )
    )
    return [{"role": "system", "content": BM_ROLE}, {"role": "user", "content": user}]


def _tactic_card(tactic: dict[str, Any]) -> str:
    content = "\n\n".join(
        (
            f"Concept: {tactic['concept']}",
            _list("Global rules", list(tactic["rules"])),
            "\n\n".join(_tactic_phase_card(phase) for phase in tactic["phases"]),
        )
    )
    tactic_id = str(tactic.get("id", "fixed_tactic"))
    return _section("tactical_card", content, id=tactic_id)


def _tactic_phase_card(phase: dict[str, Any]) -> str:
    return "\n".join(
        (
            f"Phase `{phase['id']}`",
            _list("Enter when", list(phase["enter_when"])),
            f"Goal: {phase['goal']}",
            _list("Guidance", list(phase["guidance"])),
        )
    )


def _bm_task_text(reason: str) -> str:
    normalized_reason = reason.replace(" ", "_")
    if not normalized_reason or normalized_reason == "cold_start":
        return "The game has just started. Create an opening tactical plan."
    if normalized_reason.startswith("im_request"):
        question = reason.partition(":")[2].strip()
        if question:
            return f"The observing model needs you to resolve this strategic question: {question}"
        return "The observing model needs you to resolve a strategic question."
    return "Review the current observation and update the tactical plan if priorities have changed."


def _action_card(entry: dict[str, Any]) -> str:
    params = [
        param
        for param in entry["params"]
        if param["input"] == "model"
        and param["required"]
        and param["name"] != "group_tags"
    ]
    arguments = ", ".join(
        f'{param["name"]}: {TYPE_LEGEND.get(param["type"], (param["type"], ""))[0]}'
        for param in params
    )
    lines = [f'- `{entry["name"]}({arguments})` — {entry["description"]}']
    availability = entry.get("prompt_availability")
    if availability:
        lines.append(
            f'  Availability [{availability["status"]}]: '
            f'{str(availability["note"]).strip()}'
        )
    lines.extend(_parameter_line(param) for param in params)
    return "\n".join(lines)


def _parameter_line(param: dict[str, Any]) -> str:
    """Render the catalog description with its compact model-facing type label."""
    description = str(param.get("description", "")).strip()
    label = TYPE_LEGEND.get(param["type"], (param["type"], ""))[0]
    suffix = ""
    if allowed := param.get("allowed_values"):
        suffix = f" Allowed: {', '.join(map(str, allowed))}."
    elif allowed := param.get("allowed_keys"):
        suffix = f" Allowed object keys: {', '.join(map(str, allowed))}."
    return f'  - `{param["name"]}` ({label}): {description}{suffix}'


def _type_legend(entries: list[dict[str, Any]]) -> str:
    used_types = {
        param["type"]
        for entry in entries
        for param in entry["params"]
        if param["input"] == "model"
        and param["required"]
        and param["name"] != "group_tags"
    }
    lines = [
        f"- {label}: {description}"
        for type_name, (label, description) in TYPE_LEGEND.items()
        if type_name in used_types
    ]
    return "Argument types:\n" + (
        "\n".join(lines) or "[No action arguments are available.]"
    )


def _available_actions(entries: list[dict[str, Any]]) -> str:
    return "Available actions:\n" + (
        "\n".join(_action_card(entry) for entry in entries) or "[Empty]"
    )


def _composition_example(entries: list[dict[str, Any]]) -> str:
    has_composition = any(
        param["type"] == "army_composition"
        and param["input"] == "model"
        and param["required"]
        for entry in entries
        for param in entry["params"]
    )
    if not has_composition:
        return ""
    return "\n".join(
        (
            "Composition format for `army_composition_dict`:",
            COMPOSITION_EXAMPLE,
        )
    )


def _action_reference(entries: list[dict[str, Any]]) -> str:
    sections = [_type_legend(entries)]
    if composition := _composition_example(entries):
        sections.append(composition)
    sections.append(_available_actions(entries))
    return _section("action_reference", "\n\n".join(sections))


def im_messages(
    observation: str, directive: list[str], action_entries: list[dict[str, Any]]
) -> list[dict[str, str]]:
    decision_rules = [
        "Do not give an action that is irrelevant to the strategic guidance.",
        "Use each unit ID at most once in the whole response.",
        "Do not duplicate an action in the same response. Action history records past one-time submissions; use the current observation to decide whether an action is still needed.",
        "If a task cannot be completed now, omit it instead of inventing a workaround.",
        "If a listed macro action is temporarily blocked only by resources, submit it once so the runtime may wait and retry it. Otherwise perform only the most important feasible action, or return no actions.",
        "Use only unit IDs shown in Observation.",
        "Use only the short action names and required argument names documented in the action reference.",
        "Use GasBuildingController for Refineries; never pass REFINERY to BuildStructure.",
        "Use at most 6 actions.",
        "Set request_background to true only for strategic uncertainty, never for a local execution failure.",
    ]
    decision_context = "\n\n".join(
        (
            "Objective: Based on the observation, strategic guidance, and action "
            "reference, provide concrete JSON actions that can be executed now.",
            _list(
                "Strategic guidance",
                directive,
                empty="[No active strategic task]",
            ),
            _list("Decision rules", decision_rules),
        )
    )
    output_contract = "\n".join(
        (
            "Required JSON shape:",
            '{"actions":[{"id":"AMove","args":{"unit":"u1","target":"enemy_main"}}],"request_background":false,"background_reason":""}',
            "Valid macro example:",
            '{"actions":[{"id":"BuildStructure","args":{"base_location":"main","structure_id":"SUPPLYDEPOT"}}],"request_background":false,"background_reason":""}',
            "Return only one JSON object matching the required shape.",
        )
    )
    user = "\n\n".join(
        (
            _section("observation", observation),
            _section("decision_context", decision_context),
            _action_reference(action_entries),
            _section("output_contract", output_contract),
        )
    )
    return [{"role": "system", "content": IM_ROLE}, {"role": "user", "content": user}]


def correction_messages(
    observation: str,
    directive: list[str],
    action_entries: list[dict[str, Any]],
    proposed_actions: list[dict[str, Any]],
    errors: list[str],
) -> list[dict[str, str]]:
    """Ask a focused IM-style model to repair only rejected actions."""
    repair_rules = [
        "Use only the short action names and exact required argument names in the action reference.",
        "The proposed list contains only rejected actions; do not repeat valid sibling actions.",
        "Correct only incorrect parameters that can be resolved from the supplied information.",
        "Preserve the original action ID and original intent; only incorrect arguments may be corrected.",
        "Do not add actions and never replace a rejected action with a different action.",
        "Omit an action when it cannot be corrected confidently.",
    ]
    correction_context = "\n\n".join(
        (
            _list(
                "Strategic guidance",
                directive,
                empty="[No active strategic task]",
            ),
            "Rejected actions:\n"
            + json.dumps(proposed_actions, ensure_ascii=False, separators=(",", ":")),
            _list("Validation errors", errors),
            _list("Repair rules", repair_rules),
        )
    )
    user = "\n\n".join(
        (
            _section("observation", observation),
            _section("correction_context", correction_context),
            _action_reference(action_entries),
            _section(
                "output_contract",
                "\n".join(
                    (
                        "Required JSON shape:",
                        '{"actions":[{"id":"ActionName","args":{}}]}',
                        "Return only one corrected JSON object.",
                    )
                ),
            ),
        )
    )
    return [
        {"role": "system", "content": CORRECTION_ROLE},
        {"role": "user", "content": user},
    ]


def refine_messages(
    previous: list[dict[str, str]], error: str, output_shape: str
) -> list[dict[str, str]]:
    return previous + [
        {
            "role": "assistant",
            "content": "Previous output was rejected.",
        },
        {
            "role": "user",
            "content": _section(
                "correction_request",
                "\n".join(
                    (
                        f"Validation error: {error}",
                        f"Required JSON shape: {output_shape}",
                        "Return only one corrected JSON object.",
                    )
                ),
            ),
        },
    ]
