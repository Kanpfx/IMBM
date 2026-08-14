"""Prompt builders for the shared IMBM observation contract."""

from __future__ import annotations

import json
from html import escape
from typing import Any

BM_ROLE = """You are responsible for short-term strategic planning for a StarCraft II bot.

Use the current observation, tactical reference, and available action set to select the phase that best matches the current game state. Then provide 1–3 prioritized items of strategic guidance for approximately the next 20 seconds of gameplay. Strategic guidance should describe objectives and priorities rather than executable action calls or arguments.

Output only one valid JSON object containing the selected `phase` ID and `guidance` list. Do not output executable actions, code, extra text, chain-of-thought, `<thinking>` content, or other reasoning traces.
"""

IM_ROLE = """You are responsible for converting short-term strategy into executable actions for a StarCraft II bot.

Use the current observation, strategic guidance, and available action set to issue appropriate short-term actions. Every action must follow the documented action and argument formats and use only valid values from the current message.

Output only one valid JSON object containing the `actions` list. Do not output natural-language explanations, code, extra text, chain-of-thought, `<thinking>` content, or other reasoning traces."""

CORRECTION_ROLE = """You are responsible for repairing rejected executable actions for a StarCraft II bot.

Use the current observation, strategic guidance, validation errors, and available action set to correct rejected actions.

Output only one valid JSON object containing the corrected `actions` list. Do not output natural-language explanations, code, extra text, chain-of-thought, `<thinking>` content, or other reasoning traces."""


TYPE_LEGEND = {
    "ability_id": ("Ability", "Exact SC2 ability identifier."),
    "army_composition": (
        "Composition",
        "Army composition object keyed by unit type.",
    ),
    "boolean": ("Boolean", "`true` or `false`."),
    "grid_ref": (
        "Grid",
        "Safety/pathing grid: `ground`, `air`, `ground_avoidance`, "
        "`air_avoidance`, or `tactical_ground`.",
    ),
    "integer": ("Integer", "Whole number without a fractional part."),
    "number": ("Number", "Integer or decimal number."),
    "point_or_unit_ref": (
        "Point | Unit",
        'Current unit or structure ID, documented landmark, or `{"x": number, "y": number}`.',
    ),
    "point_ref": (
        "Point",
        'Landmark (`main`, `natural`, `enemy_main`) or `{"x": number, "y": number}`.',
    ),
    "unit_ref": ("Unit", "One unit or structure ID from the current observation."),
    "unit_refs": ("Units", "Non-empty list of `Unit` values defined above."),
    "unit_or_upgrade_id": (
        "Tech",
        "Exact SC2 unit, structure, add-on, or upgrade name.",
    ),
    "unit_or_unit_type_id": (
        "Unit | UnitType",
        "One current unit or structure ID, or an exact SC2 unit or structure type name.",
    ),
    "unit_type_id": ("UnitType", "Exact SC2 unit or structure type name."),
    "upgrade_ids": (
        "Upgrades",
        "Non-empty list of exact SC2 upgrade names.",
    ),
}

ACTION_DESCRIPTION_OVERRIDES = {
    "AMoveGroup": "Attack-move a group toward a target.",
    "AttackTarget": "Attack a specified enemy unit or structure.",
    "DropCargo": "Unload cargo from a transport.",
    "GhostSnipe": "Use a Ghost to snipe a nearby valid enemy target.",
    "MedivacHeal": "Heal nearby allied biological units with a Medivac.",
    "KeepUnitSafe": "Move a unit away from danger using an influence grid.",
    "RavenAutoTurret": "Deploy a Raven Auto-Turret near visible enemies.",
    "ReaperGrenade": "Use a Reaper grenade against visible enemies.",
    "ShootAndMoveToTarget": "Move toward a destination while attacking enemies in range.",
    "ShootTargetInRange": "Attack a suitable target in range.",
    "UseAOEAbility": "Use an area-of-effect ability against suitable targets.",
    "UseTransfuse": "Use a Queen to transfuse an allied unit.",
    "AddonSwap": "Swap two Terran production structures to exchange add-ons.",
    "BuildStructure": "Construct a structure near a controlled base using an available worker and placement.",
    "BuildWorkers": "Produce workers until the requested total is reached.",
    "ExpansionController": "Expand until the requested total base count is reached.",
    "GasBuildingController": "Maintain the requested number of gas buildings.",
    "ProductionController": "Maintain production capacity for the requested army composition.",
    "SpawnController": "Produce units toward the requested army composition.",
    "TechUp": "Construct the technology required for a requested unit or upgrade.",
    "UpgradeController": "Research requested upgrades and construct their prerequisites when needed.",
}

PARAMETER_DESCRIPTION_OVERRIDES = {
    "unit": "Own unit to control.",
    "group": "Own units to control.",
    "ability": "Ability to use.",
    "ability_id": "Ability to use.",
    "close_enemy": "Nearby enemy target.",
    "close_allied": "Nearby allied units eligible for healing.",
    "enemies": "Enemy units to approach while stutter-stepping.",
    "enemy_units": "Enemy units to consider as targets.",
    "targets": "Candidate targets for this action.",
    "pickup_targets": "Allied units to load into the transport.",
    "all_close_enemy": "Nearby enemy units to consider.",
    "min_targets": "Minimum number of targets required.",
    "structure_needing_addon": "Production structure that requires the add-on.",
    "addon_required": "Required add-on type.",
    "structure_id": "Structure type to construct.",
    "to_count": "Target total count.",
    "army_composition_dict": "Desired army composition by unit type.",
    "base_location": "Controlled base location used for construction.",
    "desired_tech": "Requested unit type or upgrade.",
    "upgrade_list": "Requested upgrades.",
}

ACTION_PARAMETER_DESCRIPTION_OVERRIDES = {
    ("AMoveGroup", "target"): "Attack-move destination.",
    ("AMove", "target"): "Attack-move destination.",
    ("AttackTarget", "target"): "Enemy unit or structure to attack.",
    ("DropCargo", "unit"): "Transport to unload.",
    ("GhostSnipe", "unit"): "Ghost that will use Snipe.",
    ("MedivacHeal", "unit"): "Medivac that will heal allied units.",
    ("PickUpAndDropCargo", "target"): "Cargo drop destination.",
    ("PlacePredictiveAoE", "path"): "Path ending at the predicted target position.",
    ("QueenSpreadCreep", "unit"): "Queen that will spread creep.",
    ("RavenAutoTurret", "unit"): "Raven that will deploy the Auto-Turret.",
    ("ReaperGrenade", "unit"): "Reaper that will throw the grenade.",
    ("ShootAndMoveToTarget", "target"): "Final movement destination.",
    ("StutterUnitBack", "target"): "Enemy unit to attack while retreating.",
    ("StutterUnitForward", "target"): "Enemy unit to attack while advancing.",
    ("WorkerKiteBack", "target"): "Enemy unit to attack while retreating.",
}


def _section(tag: str, content: str, **attributes: str) -> str:
    """Use XML only for major semantic sections, not every nested field."""
    attrs = "".join(
        f' {key}="{escape(str(value), quote=True)}"'
        for key, value in attributes.items()
    )
    body = content.strip() or "[None]"
    return f"<{tag}{attrs}>\n{body}\n</{tag}>"


def _list(label: str, items: list[str], *, empty: str = "[None]") -> str:
    body = "\n".join(f"- {item}" for item in items) or empty
    return f"**{label}:**\n{body}"


def bm_messages(
    observation: str,
    tactic: dict[str, Any],
    action_entries: list[dict[str, Any]],
    _reason: str = "",
) -> list[dict[str, str]]:
    output_contract = "\n".join(
        (
            _list(
                "Output requirements",
                [
                    "Select exactly one phase ID defined in `<tactical_reference>`.",
                    "Return the selected phase and 1-3 prioritized items of strategic guidance.",
                    "Return only the required JSON object.",
                ],
            ),
            "**Required JSON template:**",
            json.dumps(
                {
                    "phase": "<phase ID>",
                    "guidance": [
                        "<strategic priority 1>",
                        "<strategic priority 2>",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    )
    user = "\n\n".join(
        (
            _section("observation", observation),
            _tactic_card(tactic),
            _action_reference(action_entries),
            _section("output_contract", output_contract),
        )
    )
    return [{"role": "system", "content": BM_ROLE}, {"role": "user", "content": user}]


def _tactic_card(tactic: dict[str, Any]) -> str:
    phases = "\n\n".join(
        _tactic_phase_card(index, phase)
        for index, phase in enumerate(tactic["phases"], start=1)
    )
    overview = "\n".join(
        (
            f"**Tactic ID:** `{tactic.get('id', 'fixed_tactic')}`",
            f"**Tactic concept:** {tactic['concept']}",
            _list("Global tactic rules", list(tactic["rules"])),
        )
    )
    content = "\n\n".join((overview, phases))
    return "<tactical_reference>\n" + content + "\n</tactical_reference>"


def _tactic_phase_card(index: int, phase: dict[str, Any]) -> str:
    content = "\n".join(
        (
            f"**Phase ID:** `{phase['id']}`",
            _list("Phase selection criteria", list(phase["enter_when"])),
            f"**Phase objective:** {phase['goal']}",
            _list("Phase guidance", list(phase["guidance"])),
        )
    )
    return f'<phase_reference index="{index}">\n{content}\n</phase_reference>'


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
    description = ACTION_DESCRIPTION_OVERRIDES.get(
        entry["name"], str(entry["description"]).strip()
    )
    lines = [f'- `{entry["name"]}({arguments})`: {description}']
    lines.extend(_parameter_line(param, entry["name"]) for param in params)
    return "\n".join(lines)


def _parameter_line(param: dict[str, Any], action_name: str) -> str:
    """Render the catalog description with its compact model-facing type label."""
    description = ACTION_PARAMETER_DESCRIPTION_OVERRIDES.get(
        (action_name, param["name"]),
        PARAMETER_DESCRIPTION_OVERRIDES.get(
            param["name"], str(param.get("description", "")).strip()
        ),
    )
    label = TYPE_LEGEND.get(param["type"], (param["type"], ""))[0]
    return f'  - `{param["name"]}` ({label}): {description}'


def _allowed_values(
    entries: list[dict[str, Any]],
) -> tuple[str, dict[str, set[str]], dict[str, set[str]]]:
    """Collect each dynamic argument domain once for the type definitions."""
    entity_groups: dict[str, set[str]] = {}
    values_by_type: dict[str, set[str]] = {}
    keys_by_type: dict[str, set[str]] = {}
    for entry in entries:
        for param in entry["params"]:
            if param["input"] != "model" or not param["required"]:
                continue
            grouped_values = param.get("allowed_value_groups", {})
            for label, values in grouped_values.items():
                entity_groups.setdefault(str(label), set()).update(map(str, values))
            ungrouped = set(map(str, param.get("allowed_values", ())))
            grouped = {
                value
                for values in grouped_values.values()
                for value in map(str, values)
            }
            if remaining := ungrouped - grouped:
                values_by_type.setdefault(param["type"], set()).update(remaining)
            if allowed_keys := param.get("allowed_keys"):
                keys_by_type.setdefault(param["type"], set()).update(
                    map(str, allowed_keys)
                )

    entity_values = ""
    if entity_groups:
        entity_values = "; ".join(
            f"`{label}[{','.join(sorted(values))}]`"
            for label, values in sorted(entity_groups.items())
        )
    return entity_values, values_by_type, keys_by_type


def _type_legend(entries: list[dict[str, Any]]) -> str:
    used_types = {
        param["type"]
        for entry in entries
        for param in entry["params"]
        if param["input"] == "model"
        and param["required"]
        and param["name"] != "group_tags"
    }
    entity_values, values_by_type, keys_by_type = _allowed_values(entries)
    if entity_values:
        # Entity candidates are shared by Unit, Units, and Point | Unit. Define
        # them once under Unit and let the other type definitions refer to it.
        used_types.add("unit_ref")

    lines: list[str] = ["Argument types, value formats, and current constraints:"]
    for type_name, (label, description) in TYPE_LEGEND.items():
        if type_name not in used_types:
            continue
        lines.append(f"- `{label}`: {description}")
        if type_name == "unit_ref" and entity_values:
            lines.append(f"  - Allowed values: {entity_values}.")
        if values := values_by_type.get(type_name):
            rendered_values = ", ".join(f"`{value}`" for value in sorted(values))
            lines.append(f"  - Allowed values: {rendered_values}.")
        if keys := keys_by_type.get(type_name):
            rendered_keys = ", ".join(f"`{key}`" for key in sorted(keys))
            lines.append(f"  - Allowed object keys: {rendered_keys}.")
        if type_name == "army_composition":
            lines.extend(
                [
                    "  - Each key must be an allowed unit type.",
                    "  - Each value must contain numeric `proportion` and integer `priority` fields.",
                    "  - All `proportion` values must sum to `1.0`.",
                ]
            )
    return "<argument_types>\n" + "\n".join(lines) + "\n</argument_types>"


def _available_actions(entries: list[dict[str, Any]]) -> str:
    body = "\n".join(_action_card(entry) for entry in entries) or "[None]"
    return "\n".join(
        (
            "<available_actions>",
            "Each action below is currently available. Use the exact action and argument names shown:",
            body,
            "</available_actions>",
        )
    )


def _action_reference(entries: list[dict[str, Any]]) -> str:
    return "\n\n".join((_type_legend(entries), _available_actions(entries)))


def im_messages(
    observation: str, directive: list[str], action_entries: list[dict[str, Any]]
) -> list[dict[str, str]]:
    decision_rules = [
        "Do not issue actions unrelated to the strategic guidance.",
        "Assign each own acting unit ID to at most one action in the response. Target IDs may be reused.",
        "Do not submit the same action with identical arguments more than once in the same response. Action history records past one-time submissions; use the current observation to decide whether an action is still needed.",
        "If an action is invalid for any reason other than a temporary resource shortfall, omit it instead of inventing a workaround.",
        "If an available macro action is blocked only by a small temporary resource shortfall, submit it once so the execution system can queue and retry it.",
        "Submit only the highest-priority feasible actions, or return an empty action list.",
        "Use only unit or structure IDs shown in the current observation.",
        "Use only the action names and required argument names documented in `<available_actions>`.",
        "Use `GasBuildingController` for Refineries; never pass `REFINERY` to `BuildStructure`.",
        "Return 0-6 actions.",
    ]
    decision_context = "\n\n".join(
        (
            "**Objective:** Use the current observation, strategic guidance, and "
            "available action set to provide concrete JSON actions for this "
            "decision.",
            _list(
                "Strategic guidance",
                directive,
                empty="[No active strategic guidance]",
            ),
            _list("Decision rules", decision_rules),
        )
    )
    output_contract = "\n".join(
        (
            "**Required JSON template:**",
            json.dumps(
                {
                    "actions": [
                        {
                            "id": "<action name>",
                            "args": {"<argument name>": "<argument value>"},
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            "Return only one JSON object matching this template.",
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
        "Repair only the rejected actions listed in `<rejected_actions>`.",
        "Other valid actions from the original response have already been retained; do not repeat them.",
        "Use only the action names and exact required argument names in `<available_actions>`.",
        "Correct only invalid arguments that can be resolved from the current message.",
        "Preserve each rejected action's action name and intent; only invalid arguments may be corrected.",
        "Do not add actions and never replace a rejected action with a different action.",
        "Do not invent action names, arguments, unit or structure IDs, landmarks, abilities, or coordinates.",
        "Omit an action when it cannot be corrected confidently.",
    ]
    strategic_guidance = (
        "\n".join(f"- {item}" for item in directive) or "[No active strategic guidance]"
    )
    rejected_actions = _rejected_action_items(proposed_actions, errors)
    repair_rule_text = "\n".join(f"- {rule}" for rule in repair_rules)
    user = "\n\n".join(
        (
            _section("observation", observation),
            _section("strategic_guidance", strategic_guidance),
            _section("rejected_actions", rejected_actions),
            _section("repair_rules", repair_rule_text),
            _action_reference(action_entries),
            _section(
                "output_contract",
                "\n".join(
                    (
                        "**Required JSON template:**",
                        json.dumps(
                            {
                                "actions": [
                                    {
                                        "id": "<action name>",
                                        "args": {"<argument name>": "<argument value>"},
                                    }
                                ]
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
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


def _rejected_action_items(
    proposed_actions: list[dict[str, Any]], errors: list[str]
) -> str:
    """Bind every rejected action directly to its validation error."""
    items: list[str] = []
    numbered = len(proposed_actions) > 1
    for index, action in enumerate(proposed_actions, start=1):
        error = errors[index - 1] if index <= len(errors) else "[Unknown]"
        error_source, separator, error_detail = error.partition(":")
        if separator and error_source.removeprefix("Action ").isdigit():
            error = error_detail.lstrip()
        action_label = f"**Action {index}:**" if numbered else "**Action:**"
        error_label = (
            f"**Validation error {index}:**" if numbered else "**Validation error:**"
        )
        content = "\n".join(
            (
                action_label,
                json.dumps(action, ensure_ascii=False, indent=2),
                error_label,
                error,
            )
        )
        items.append(content)
    if len(errors) > len(proposed_actions):
        unmatched = "\n".join(f"- {error}" for error in errors[len(proposed_actions) :])
        items.append(f"**Unmatched validation errors:**\n{unmatched}")
    return "\n\n".join(items) or "[None]"


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
                        f"**Validation error:** {error}",
                        f"**Required JSON template:** {output_shape}",
                        "Return only one corrected JSON object.",
                    )
                ),
            ),
        },
    ]
