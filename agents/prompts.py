"""Prompt builders for the shared IMBM observation contract."""

from __future__ import annotations

import json
from typing import Any


BM_ROLE = """You are an expert StarCraft II game-control model. Select the current phase from the complete fixed tactic card, then formulate the 1-3 highest-impact strategic priorities for the next approximately 30 game seconds. Use the action catalog to keep the priorities executable. Prefer priorities that are feasible now; do not repeat completed or already pending work. Give concrete natural-language strategy only: do not output unit IDs, executable action objects, coordinates, grids, code, or JSON arguments. Return only the required JSON."""

IM_ROLE = """You are an expert StarCraft II game-control model. Based on the observation, strategic priorities, and available action information, give short-term concrete actions that can be executed now. Each submitted action is registered once and executes once; Action history records prior submissions, not persistent commands. Use the unit IDs from the observation and the exact action IDs and argument formats from the action information. Return only the required JSON."""

CORRECTION_ROLE = """You are the IM Action Correction Module. Repair the rejected actions using the observation, strategic guidance, available actions, and validation errors. Valid sibling actions have already been retained. Keep valid intent when possible. Correct small argument mistakes; replace an impossible action only with a close, listed action that is executable now; otherwise omit it. Never invent action names, arguments, unit IDs, landmarks, abilities, or coordinates. Return only the required JSON."""


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
        "Visible unit ID, landmark (`main`, `natural`, `enemy_main`), or `{\"x\": number, \"y\": number}`.",
    ),
    "point_ref": (
        "Point",
        "Landmark (`main`, `natural`, `enemy_main`) or `{\"x\": number, \"y\": number}`.",
    ),
    "unit_ref": ("Unit", "One unit ID from Observation."),
    "unit_refs": ("Units", "Non-empty list of unit IDs from Observation."),
    "unit_type_id": ("UnitType", "Exact SC2 unit or structure name, e.g. `STARPORT`."),
}


def bm_messages(
    observation: str,
    tactic: dict[str, Any],
    action_entries: list[dict[str, Any]],
    reason: str = "",
) -> list[dict[str, str]]:
    rules = "\n".join(f"- {rule}" for rule in tactic["rules"])
    phases = "\n\n".join(_tactic_phase_card(phase) for phase in tactic["phases"])
    action_cards = "\n\n".join(_action_card(entry) for entry in action_entries)
    type_legend = _type_legend(action_entries) or "[No action arguments are available.]"
    task = _bm_task_text(reason)
    user = f"""# Your current task
{task}

# Observation
{observation}

# Complete tactical card
## Core idea
{tactic['concept']}

## Constraint rules
{rules}

## Phases
{phases}

# Argument type legend
{type_legend}

# Available actions
{action_cards or '[Empty]'}

# JSON format and example
Select exactly one phase ID listed above. Return that phase and 1-3 concrete tactical priorities.
{{"phase":"opening_factory","guidance":["priority 1","priority 2"]}}"""
    return [{"role": "system", "content": BM_ROLE}, {"role": "user", "content": user}]


def _tactic_phase_card(phase: dict[str, Any]) -> str:
    enter_when = "\n".join(f"- {item}" for item in phase["enter_when"])
    guidance = "\n".join(f"- {item}" for item in phase["guidance"])
    return f"""### Phase `{phase['id']}`
#### Enter when
{enter_when}
#### Goal
{phase['goal']}
#### Complete guidance
{guidance}"""


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
    required = [param["name"] for param in params]
    signature = f'{entry["name"]}({", ".join(required)})'
    lines = [f'`{signature}`: {entry["description"]}']
    availability = entry.get("prompt_availability")
    if availability:
        status = str(availability["status"]).replace("_", " ")
        lines.append(
            f'- Availability [{status}]: {availability["note"].rstrip(".")}.'
        )
    lines.extend(_parameter_card(param) for param in params)
    return "\n".join(lines)


def _parameter_card(param: dict[str, Any]) -> str:
    """Render the catalog description with its compact model-facing type label."""
    description = str(param.get("description", "")).strip().rstrip(".")
    label = TYPE_LEGEND.get(param["type"], (param["type"], ""))[0]
    constraints = ""
    if allowed := param.get("allowed_values"):
        constraints = f" Allowed now: {', '.join(map(str, allowed))}."
    elif allowed := param.get("allowed_keys"):
        constraints = f" Allowed object keys now: {', '.join(map(str, allowed))}."
    return f'- `{param["name"]}` [{label}]: {description}.{constraints}'


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
        f'- `[{label}]`: {description}'
        for type_name, (label, description) in TYPE_LEGEND.items()
        if type_name in used_types
    ]
    return "\n".join(lines)


def im_messages(
    observation: str, directive: list[str], action_entries: list[dict[str, Any]]
) -> list[dict[str, str]]:
    priorities = "\n".join(f"- {item}" for item in directive) or "[No active strategic task]"
    action_cards = "\n\n".join(_action_card(entry) for entry in action_entries)
    type_legend = _type_legend(action_entries) or "[No action arguments are available.]"
    user = f"""# Objective
Based on the observation, action catalog, and strategic guidance, provide concrete JSON actions that can be executed now.

# Observation
{observation}

# Strategic guidance to follow
{priorities}

# Rules
1. Do not give an action that is irrelevant to the strategic guidance.
2. Use each unit ID at most once in the whole response.
3. Do not duplicate an action in the same response. Action history is only a record of past one-time submissions; use the current observation to decide whether a later action is still needed.
4. If a task cannot be completed now, omit it instead of inventing a workaround.
5. If a listed macro action is temporarily blocked only by resources, submit it once; the runtime may wait and retry it. Otherwise perform only the most important feasible action, or return no actions.
6. Use only unit IDs shown in Observation.
7. Use only the short action names and required argument names documented below.
8. Use `GasBuildingController` for Refineries; never pass REFINERY to `BuildStructure`.
9. Use at most 6 actions.
10. Set `request_background` to true only for strategic uncertainty, never for a local execution failure.

# Argument type legend
{type_legend}

# Available actions
{action_cards or '[Empty]'}

# JSON format and example
## Required format
{{"actions":[{{"id":"AMove","args":{{"unit":"u1","target":"enemy_main"}}}}],"request_background":false,"background_reason":""}}

## Complete valid example
{{"actions":[{{"id":"BuildStructure","args":{{"base_location":"main","structure_id":"SUPPLYDEPOT"}}}}],"request_background":false,"background_reason":""}}"""
    return [{"role": "system", "content": IM_ROLE}, {"role": "user", "content": user}]


def correction_messages(
    observation: str,
    directive: list[str],
    action_entries: list[dict[str, Any]],
    proposed_actions: list[dict[str, Any]],
    errors: list[str],
) -> list[dict[str, str]]:
    """Ask a focused IM-style model to repair only rejected actions."""
    priorities = "\n".join(f"- {item}" for item in directive) or "[No active strategic task]"
    action_cards = "\n\n".join(_action_card(entry) for entry in action_entries)
    error_list = "\n".join(f"- {error}" for error in errors)
    user = f"""# Observation
{observation}

# Strategic guidance
{priorities}

# Proposed actions
{json.dumps(proposed_actions, ensure_ascii=False)}

# Validation errors
{error_list}

# Available actions
{action_cards or '[Empty]'}

# Repair rules
1. Use only the short action names and exact required argument names listed above.
2. The proposed list contains only rejected actions; do not repeat valid sibling actions.
3. Correct only mistakes that can be resolved from this information.
4. Replace an invalid action only with a close, currently executable listed action.
5. Omit an action when it cannot be corrected confidently.

# Required JSON format
{{"actions":[{{"id":"ActionName","args":{{}}}}]}}"""
    return [{"role": "system", "content": CORRECTION_ROLE}, {"role": "user", "content": user}]


def refine_messages(
    previous: list[dict[str, str]], error: str, output_shape: str
) -> list[dict[str, str]]:
    return previous + [
        {"role": "assistant", "content": "Previous output was rejected."},
        {
            "role": "user",
            "content": (
                f"### Validation Error\n{error}\n\n"
                f"Return only corrected JSON in this shape: {output_shape}"
            ),
        },
    ]
