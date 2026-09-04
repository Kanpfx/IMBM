"""Prompt builder for the single-model observation contract."""

from __future__ import annotations

import json
from html import escape
from typing import Any

MODEL_ROLE = """Choose the tactical phase that best matches the current StarCraft II observation, then issue concrete actions for that phase.

Use only phase IDs, actions, arguments, and values documented in the current message. Return only the tagged Function DSL described in the output contract, with one action call per line; do not include explanations or reasoning."""


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
        "Current unit or structure ID, documented landmark, or `{x:number,y:number}`.",
    ),
    "point_ref": (
        "Point",
        "Landmark (`main`, `natural`, `enemy_main`) or `{x:number,y:number}`.",
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


SIMPLE_PARAMETER_NAMES = {
    "ability",
    "ability_id",
    "all_close_enemy",
    "close_allied",
    "close_enemy",
    "enemies",
    "enemy_units",
    "group",
    "pickup_targets",
    "target",
    "targets",
    "unit",
}

ACTION_PARAMETER_NOTES = {
    ("PickUpCargo", "cargo_switch_to_role"): "Select cargo by unit role.",
    ("PickUpAndDropCargo", "cargo_switch_to_role"): "Select cargo by unit role.",
    ("PlacePredictiveAoE", "path"): "Path must end at the predicted target position.",
}


def _indent(content: str) -> str:
    return "\n".join(f"  {line}" if line else "" for line in content.splitlines())


def _section(tag: str, content: str, **attributes: str) -> str:
    """Use XML only for major semantic sections, not every nested field."""
    attrs = "".join(
        f' {key}="{escape(str(value), quote=True)}"'
        for key, value in attributes.items()
    )
    body = content.strip() or "[None]"
    return f"<{tag}{attrs}>\n{_indent(body)}\n</{tag}>"


def _list(label: str, items: list[str], *, empty: str = "[None]") -> str:
    body = "\n".join(f"- {item}" for item in items) or empty
    return f"{label}:\n\n{body}"


def _tactic_card(tactic: dict[str, Any]) -> str:
    phases = "\n\n".join(
        _tactic_phase_card(index, phase)
        for index, phase in enumerate(tactic["phases"], start=1)
    )
    overview = "\n".join(
        (
            f"**Tactic ID:** `{tactic.get('id', 'fixed_tactic')}`",
            f"Tactic concept: {tactic['concept']}",
            _list("Global tactic rules", list(tactic["rules"])),
        )
    )
    content = "\n\n".join((overview, phases))
    return _section("tactical_reference", content)


def _tactic_phase_card(index: int, phase: dict[str, Any]) -> str:
    content = "\n\n".join(
        (
            f"**Phase ID:** `{phase['id']}`",
            _list("Phase selection criteria", list(phase["enter_when"])),
            f"**Phase objective:** {phase['goal']}",
            _list("Phase guidance", list(phase["guidance"])),
        )
    )
    return _section("phase_reference", content, index=str(index))


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
    lines.extend(
        _parameter_note(param, entry["name"])
        for param in params
        if param["name"] not in SIMPLE_PARAMETER_NAMES
    )
    return "\n".join(lines)


def _parameter_note(param: dict[str, Any], action_name: str) -> str:
    """Render a note for a parameter not covered by the simple-name blacklist."""
    description = ACTION_PARAMETER_NOTES.get(
        (action_name, param["name"]), str(param.get("description", "")).strip()
    )
    label = TYPE_LEGEND.get(param["type"], (param["type"], ""))[0]
    return f'  - `{param["name"]}` ({label}): {description}'


def _type_legend(entries: list[dict[str, Any]]) -> str:
    used_types = {
        param["type"]
        for entry in entries
        for param in entry["params"]
        if param["input"] == "model"
        and param["required"]
        and param["name"] != "group_tags"
    }
    lines: list[str] = ["Argument types and value formats:"]
    for type_name, (label, description) in TYPE_LEGEND.items():
        if type_name not in used_types:
            continue
        lines.append(f"- `{label}`: {description}")

        if type_name == "army_composition":
            lines.extend(
                [
                    "  - Each key must be an allowed unit type.",
                    "  - Each value must contain numeric `proportion` and integer `priority` fields.",
                    "  - All `proportion` values must sum to `1.0`.",
                ]
            )
    return _section("argument_types", "\n\n".join((lines[0], "\n".join(lines[1:]))))


def _available_actions(entries: list[dict[str, Any]]) -> str:
    body = "\n".join(_action_card(entry) for entry in entries) or "[None]"
    instruction = (
        "Each action below is currently available. "
        "Use the exact action and argument names shown:"
    )
    return _section("available_actions", f"{instruction}\n\n{body}")


def _actions_reference(entries: list[dict[str, Any]]) -> str:
    content = "\n\n".join((_type_legend(entries), _available_actions(entries)))
    return _section("actions_reference", content)


def _observation_with_feedback(
    observation: str,
    previous_validation_feedback: list[dict[str, Any]] | None,
) -> str:
    if not previous_validation_feedback:
        return observation

    feedback = _section(
        "previous_validation_feedback",
        json.dumps(previous_validation_feedback, ensure_ascii=False, indent=2),
    )
    action_history_end = "</action_history>"
    if action_history_end in observation:
        return observation.replace(
            action_history_end,
            f"{action_history_end}\n\n{_indent(feedback)}",
            1,
        )
    return f"{observation.rstrip()}\n\n{feedback}"


def model_messages(
    observation: str,
    tactic: dict[str, Any],
    action_entries: list[dict[str, Any]],
    previous_validation_feedback: list[dict[str, Any]] | None = None,
    *,
    max_actions_per_decision: int = 6,
) -> list[dict[str, str]]:
    output_contract = """<phase>
PHASE_ID
</phase>
<actions>
ActionName(argument=value,...)
</actions>

Use one documented phase ID and return 0-{max_actions} currently available actions, one per line.
Use exact action and argument names. Use bare names for enums and landmarks, `true`/`false` for booleans, `[...]` for lists, and `{key:value}` for objects."""
    output_contract = output_contract.replace(
        "{max_actions}", str(max_actions_per_decision)
    )
    final_instruction = (
        "Select the best-matching phase from the tactical reference, then compose "
        "and return suitable actions using only the available actions and their "
        "documented parameters."
    )
    sections = [
        _tactic_card(tactic),
        _section("output_contract", output_contract),
        _actions_reference(action_entries),
        _section(
            "observation",
            _observation_with_feedback(observation, previous_validation_feedback),
        ),
        final_instruction,
    ]
    user = "\n\n".join(sections)
    return [
        {"role": "system", "content": MODEL_ROLE},
        {"role": "user", "content": user},
    ]
