"""Prompt builder for the single-model observation contract."""

from __future__ import annotations

from html import escape
from typing import Any

from game.actions.formatting import format_feedback
from game.actions.persistent import PERSISTENT_ACTION_IDS

MODEL_ROLE = """You are a StarCraft II control model responsible for making tactical decisions and issuing executable actions.
Your task is to identify the tactical phase that best matches the current game observation, then issue concrete actions appropriate for that phase.
Use only phase IDs, actions, arguments, and values explicitly documented in the current message. Follow the specified action format exactly.
Return only the Function DSL specified in the output contract. Do not include explanations, reasoning, chain-of-thought, or any additional text."""


GLOBAL_RULES = """Use these rules when choosing actions:

- Automation handles harvesting, SCV assignment (three SCVs per Refinery from 13 SCVs), routine supply, MULEs, repairs, Supply Depot lowering, proxy Bunker scouting, and periodic map scans when minerals are at least 1500. You still choose army search and attack targets. Request Supply Depots manually only for specific placement needs.
- SCV production defaults to 20. A new BuildWorkers target replaces the previous target and remains effective until changed.
- You choose SCV targets, army composition, production capacity, tech progression, expansions, and army objectives. Automation executes these choices without selecting a new tactic.
- Each macro controller type has one target. New parameters replace its previous target, including placement preferences.
- Continuous macro and combat instructions remain active until replaced or their referenced entities become invalid. Omission keeps them active.
- A new unit task replaces its previous task. When replacing part of a group, unaffected members keep their tasks.
- Prefer one group action for units sharing an intent; use individual actions for unit-specific control.
- Do not repeat unchanged active instructions or construction already pending. Request another structure after completion only when an additional one is needed.
- During cleanup, actively clear remaining known enemy structures; when none are known, assign map searches and attack newly found enemies until the game ends.
- If units have reached a target and cleared nearby enemies, choose a new target or search area. If repeated actions make no progress, reconsider the target or prerequisites instead of issuing the same ineffective command.
- Check action history and execution feedback: accepted means submitted, not completed; active means ongoing; queued means automatically retried; failed means an invalid instruction or execution error. Ares starting no new work alone is not failure.
- Resource shortages do not stop active production. One-time construction may queue within a shortfall of 120 minerals and 60 vespene gas. Larger shortages and ended waits return for reconsideration, not execution failure. TechUp delegates prerequisite steps to Ares without requiring the final unit cost upfront.
- The game continues during inference. Replies are checked against the latest state; request failures preserve existing controls.
"""

TYPE_LEGEND = {
    "ability_id": ("Ability", "SC2 AbilityId identifier, not the in-game display name."),
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
    "unit_refs": ("Units", "List of `Unit` values; non-empty unless the action explicitly allows []."),
    "unit_or_upgrade_id": (
        "Tech",
        "SC2 UnitTypeId or UpgradeId identifier for a unit, structure, add-on, or upgrade.",
    ),
    "unit_or_unit_type_id": (
        "Unit | UnitType",
        "One current unit or structure ID, or an SC2 UnitTypeId identifier.",
    ),
    "unit_type_id": ("UnitType", "SC2 UnitTypeId identifier, such as SUPPLYDEPOT for Supply Depot or BATTLECRUISER for Battlecruiser."),
    "upgrade_ids": (
        "Upgrades",
        "Non-empty list of SC2 UpgradeId identifiers, not in-game display names.",
    ),
}

ACTION_DESCRIPTION_OVERRIDES = {
    "AMoveGroup": "Attack-move a group toward a target.",
    "AttackTarget": "Attack a specified enemy unit or structure.",
    "DropCargo": "Unload cargo from a transport.",
    "GhostSnipe": "Use a Ghost to cast Snipe (EFFECT_GHOSTSNIPE) on a nearby valid enemy target.",
    "MedivacHeal": "Use a Medivac to cast Heal on nearby allied biological units.",
    "KeepGroupSafe": "Keep a group safe using the influence grid; close_enemy may be [] when no enemies are visible.",
    "KeepUnitSafe": "Move a unit away from danger using an influence grid.",
    "RavenAutoTurret": "Use a Raven to deploy an Auto-Turret near visible enemies.",
    "ReaperGrenade": "Use a Reaper to throw a KD8 Charge at visible enemies.",
    "ShootAndMoveToTarget": "Move toward a destination while attacking enemies in range.",
    "ShootTargetInRange": "Attack a suitable target in range.",
    "UseAOEAbility": "Use an area-of-effect ability against suitable targets.",
    "UseTransfuse": "Use a Queen to cast Transfusion on a valid allied biological target.",
    "AddonSwap": "Swap two Terran production structures to exchange add-ons.",
    "BuildStructure": "Construct a regular Terran structure near a controlled base. Use GasBuildingController for Refineries and TechUp for add-ons; do not pass REFINERY or TECHLAB here. Routine Supply Depots are automated.",
    "BuildWorkers": "Train SCVs until the requested total SCV count is reached.",
    "ExpansionController": "Expand until the requested total base count is reached.",
    "GasBuildingController": "Maintain the requested number of Refineries.",
    "ProductionController": "Build production structures and prerequisites for the requested army composition. This does not train the army; use SpawnController to train units.",
    "SpawnController": "Train army units toward the requested composition; pair with ProductionController when production capacity is needed.",
    "TechUp": "Advance one prerequisite construction step toward a requested unit or upgrade, including add-ons. For Battlecruiser tech use desired_tech=BATTLECRUISER. Reissue when further prerequisite steps are needed.",
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
    "grid",
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


def _section(tag: str, content: str, **attributes: str) -> str:
    """Use XML only for major semantic sections, not every nested field."""
    attrs = "".join(
        f' {key}="{escape(str(value), quote=True)}"'
        for key, value in attributes.items()
    )
    body = content.strip() or "[None]"
    return f"<{tag}{attrs}>\n\n{body}\n\n</{tag}>"


def _list(label: str, items: list[str], *, empty: str = "[None]") -> str:
    body = "\n".join(f"- {item}" for item in items) or empty
    return f"**{label}**\n\n{body}"


def _tactic_card(tactic: dict[str, Any]) -> str:
    phases = "\n\n".join(
        _tactic_phase_card(index, phase)
        for index, phase in enumerate(tactic["phases"], start=1)
    )
    overview = "\n\n".join(
        (
            f"**Tactic ID:** `{tactic.get('id', 'fixed_tactic')}`",
            f"**Tactic concept:** {tactic['concept']}",
            _list("Global tactic rules", list(tactic["rules"])),
        )
    )
    content = "\n\n".join((overview, phases))
    return _section("tactical_reference", content)


def _tactic_phase_card(index: int, phase: dict[str, Any]) -> str:
    content = "\n\n".join(
        (
            f"**Phase ID:** `{phase['id']}`",
            _list("Selection criteria", list(phase["enter_when"])),
            f"**Objective:** {phase['goal']}",
            _list("Guidance", list(phase["guidance"])),
        )
    )
    return f'<phase index="{index}">\n\n{content}\n\n</phase>'


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
    ongoing = entry["id"] in PERSISTENT_ACTION_IDS or entry["id"] == "macro.build_workers"
    lifetime = "Ongoing control." if ongoing else "One-time action."
    lines = [f'- `{entry["name"]}({arguments})`: {description} {lifetime}']
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
    lines: list[str] = [
        "Use these argument types and value formats:"
    ]
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
    return _section("argument_definitions", "\n\n".join((lines[0], "\n".join(lines[1:]))))


def _available_actions(entries: list[dict[str, Any]]) -> str:
    groups: dict[str, list[str]] = {
        "Group Combat Behaviors": [],
        "Individual Combat Behaviors": [],
        "Macro Behaviors": [],
    }
    for entry in entries:
        if entry["id"].startswith("combat.group."):
            category = "Group Combat Behaviors"
        elif entry["id"].startswith("macro."):
            category = "Macro Behaviors"
        else:
            category = "Individual Combat Behaviors"
        groups[category].append(_action_card(entry))
    body = "\n\n".join(
        f"**{category}**\n\n" + "\n".join(actions)
        for category, actions in groups.items()
        if actions
    ) or "[None]"
    instruction = (
        "Choose from these available actions and follow their argument definitions:"
    )
    return _section("available_actions", f"{instruction}\n\n{body}")


def _actions_reference(entries: list[dict[str, Any]]) -> str:
    content = "\n\n".join((_type_legend(entries), _available_actions(entries)))
    return _section("actions_reference", content)


def _observation_with_feedback(
    observation: str,
    previous_validation_feedback: list[dict[str, Any]] | None,
) -> str:
    feedback = _section(
        "previous_validation_feedback",
        "Review previous validation and execution feedback before choosing actions.\n\n"
        + format_feedback(previous_validation_feedback or []),
    )
    action_history_end = "</action_history>"
    if action_history_end in observation:
        return observation.replace(
            action_history_end,
            f"{action_history_end}\n\n{feedback}",
            1,
        )
    return f"{observation.rstrip()}\n\n{feedback}"


def model_messages(
    observation: str,
    tactic: dict[str, Any],
    action_entries: list[dict[str, Any]],
    previous_validation_feedback: list[dict[str, Any]] | None = None,
    *,
    max_actions_per_decision: int = 8,
) -> list[dict[str, str]]:
    output_contract = """Follow this output format:

- Select one phase ID from the tactical reference and return 0-{max_actions} actions, one per line.
- Use action names, argument names, and permitted values from the action reference.
- Use bare names for enums and landmarks, `true`/`false` for booleans, `[...]` for lists, and `{key:value}` for objects.
- Return only the DSL shown below, without explanations or additional text. Use actual line breaks, not escaped newline sequences.

```text
# phase
PHASE_ID

# actions
ActionName(argument=value,...)
```"""
    output_contract = output_contract.replace(
        "{max_actions}", str(max_actions_per_decision)
    )
    sections = [
        _section("global_rules", GLOBAL_RULES),
        _tactic_card(tactic),
        _actions_reference(action_entries),
        _observation_with_feedback(observation, previous_validation_feedback),
        _section("output_contract", output_contract),
    ]
    user = "\n\n".join(sections)
    return [
        {"role": "system", "content": MODEL_ROLE},
        {"role": "user", "content": user},
    ]
