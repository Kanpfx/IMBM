"""Generate the versioned Ares LLM action catalog from local docs and source.

The generator is intentionally static: it parses AST and Markdown directives
instead of importing Ares, which makes regeneration safe outside a running SC2
client. Documentation is the chapter/description source; source is the API
truth and supplies undocumented-public coverage.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
ARES_ROOT = ROOT / "ares"
SRC = ARES_ROOT / "src"
DOCS = ARES_ROOT / "docs" / "api_reference"
OUT = Path(__file__).resolve().parent
SCHEMA_VERSION = "1.0"

CHAPTERS = (
    {
        "id": "api_reference",
        "title": "API Reference",
        "documentation_url": "https://aressc2.github.io/ares-sc2/api_reference/index.html",
        "docs": DOCS / "index.md",
        "output": OUT / "API Reference.json",
        "module_roots": ("ares.main",),
    },
    {
        "id": "behavior.individual_combat",
        "title": "Individual Combat Behaviors",
        "documentation_url": "https://aressc2.github.io/ares-sc2/api_reference/behaviors/combat_behaviors.html",
        "docs": DOCS / "behaviors" / "combat_behaviors.md",
        "output": OUT / "Behaviors" / "Individual Combat Behaviors.json",
        "module_roots": ("ares.behaviors.combat.combat_maneuver", "ares.behaviors.combat.individual"),
    },
    {
        "id": "behavior.group_combat",
        "title": "Group Combat Behaviors",
        "documentation_url": "https://aressc2.github.io/ares-sc2/api_reference/behaviors/group_combat_behaviors.html",
        "docs": DOCS / "behaviors" / "group_combat_behaviors.md",
        "output": OUT / "Behaviors" / "Group Combat Behaviors.json",
        "module_roots": ("ares.behaviors.combat.group",),
    },
    {
        "id": "behavior.macro",
        "title": "Macro Behaviors",
        "documen…64656 tokens truncated…"api": {
        "import": "ares.behaviors.macro.production_controller.ProductionController",
        "source_path": "ares/src/ares/behaviors/macro/production_controller.py",
        "dispatch": "register_behavior"
      },
      "params": [
        {
          "name": "army_composition_dict",
          "type": "unit_type_id",
          "python_type": "dict[UnitID, dict[str, float | int]]",
          "input": "model",
          "required": true,
          "description": "A dictionary detailing how an army composition should be made up. The proportional values should all add up to 1.0, with a priority integer for unit emphasis."
        },
        {
          "name": "base_location",
          "type": "point_ref",
          "python_type": "Point2",
          "input": "model",
          "required": true,
          "description": "The location where production should be built."
        },
        {
          "name": "add_production_at_bank",
          "type": "json_value",
          "python_type": "tuple[int, int]",
          "input": "model",
          "required": false,
          "description": "When the bank reaches this size, calculate what extra production would be useful. Tuple where the first value is minerals and the second is vespene. Defaults to `(300, 300)`.",
          "default": [
            400,
            400
          ]
        },
        {
          "name": "alpha",
          "type": "number",
          "python_type": "float",
          "input": "model",
          "required": false,
          "description": "Controls how much production to add when the bank is higher than `add_production_at_bank`. Defaults to `0.9`.",
          "default": 0.9
        },
        {
          "name": "unit_pending_progress",
          "type": "number",
          "python_type": "float",
          "input": "model",
          "required": false,
          "description": "Check for production structures almost ready. For example, a marine might almost be ready, meaning we don't need to add extra production just yet. Defaults to `0.8`.",
          "default": 0.75
        },
        {
          "name": "ignore_below_proportion",
          "type": "number",
          "python_type": "float",
          "input": "model",
          "required": false,
          "description": "If we don't want many of a unit, there's no point adding production. Checks if it's possible to build a unit first. Defaults to `0.05`.",
          "default": 0.05
        },
        {
          "name": "should_repower_structures",
          "type": "boolean",
          "python_type": "bool",
          "input": "model",
          "required": false,
          "description": "Search for unpowered structures and build a new pylon if needed. Defaults to `True`.",
          "default": true
        },
        {
          "name": "max_production_structures",
          "type": "integer",
          "python_type": "int",
          "input": "model",
          "required": false,
          "description": "Stop adding production at this number Defaults to 12",
          "default": 12
        }
      ],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "eligible"
    },
    {
      "id": "macro.protoss_static_defence",
      "name": "ProtossStaticDefence",
      "kind": "executable_behavior",
      "description": "Build protoss static defence at all bases with a Nexus.",
      "documentation_status": "source_only_public",
      "api": {
        "import": "ares.behaviors.macro.protoss_static_defence.ProtossStaticDefence",
        "source_path": "ares/src/ares/behaviors/macro/protoss_static_defence.py",
        "dispatch": "register_behavior"
      },
      "params": [
        {
          "name": "pylons_per_base",
          "type": "integer",
          "python_type": "int",
          "input": "model",
          "required": false,
          "description": "Number of pylons to maintain per base.",
          "default": 1
        },
        {
          "name": "photon_cannons_per_base",
          "type": "integer",
          "python_type": "int",
          "input": "model",
          "required": false,
          "description": "Number of photon cannons to maintain per base.",
          "default": 1
        },
        {
          "name": "shield_batteries_per_base",
          "type": "integer",
          "python_type": "int",
          "input": "model",
          "required": false,
          "description": "Number of shield batteries to maintain per base.",
          "default": 1
        },
        {
          "name": "exclude_base_locations",
          "type": "point_ref",
          "python_type": "set[Point2]",
          "input": "model",
          "required": false,
          "description": "Base locations to skip when placing defence.",
          "default": {
            "expression": "field(default_factory=set)"
          }
        },
        {
          "name": "max_on_route",
          "type": "integer",
          "python_type": "int",
          "input": "model",
          "required": false,
          "description": "Max number of workers on route per structure type.",
          "default": 1
        },
        {
          "name": "tech_base_location",
          "type": "point_ref",
          "python_type": "Point2 | None",
          "input": "model",
          "required": false,
          "description": "Where to build tech requirements (forge/core).",
          "default": null
        }
      ],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "disabled",
      "llm_exposure_reason": "Requires review because it is not listed by the current documentation chapter."
    },
    {
      "id": "macro.restore_power",
      "name": "RestorePower",
      "kind": "executable_behavior",
      "description": "Restore power for protoss structures.",
      "documentation_status": "documented",
      "api": {
        "import": "ares.behaviors.macro.restore_power.RestorePower",
        "source_path": "ares/src/ares/behaviors/macro/restore_power.py",
        "dispatch": "register_behavior"
      },
      "params": [],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "eligible"
    },
    {
      "id": "macro.spawn_controller",
      "name": "SpawnController",
      "kind": "executable_behavior",
      "description": "Handle spawning army compositions.",
      "documentation_status": "documented",
      "api": {
        "import": "ares.behaviors.macro.spawn_controller.SpawnController",
        "source_path": "ares/src/ares/behaviors/macro/spawn_controller.py",
        "dispatch": "register_behavior"
      },
      "params": [
        {
          "name": "army_composition_dict",
          "type": "unit_type_id",
          "python_type": "dict[UnitID, dict[str, float | int]]",
          "input": "model",
          "required": true,
          "description": "A dictionary detailing how an army composition should be made up. The proportional values should all add up to 1.0, with a priority integer for unit emphasis."
        },
        {
          "name": "freeflow_mode",
          "type": "boolean",
          "python_type": "bool",
          "input": "model",
          "required": false,
          "description": "If set to True, army composition proportions are ignored, and resources will be spent freely. Defaults to `False`.",
          "default": false
        },
        {
          "name": "ignore_proportions_below_unit_count",
          "type": "integer",
          "python_type": "int",
          "input": "model",
          "required": false,
          "description": "In early game, units affect the army proportions significantly. This allows some units to be freely built before proportions are respected. Defaults to `0`.",
          "default": 0
        },
        {
          "name": "over_produce_on_low_tech",
          "type": "boolean",
          "python_type": "bool",
          "input": "model",
          "required": false,
          "description": "If only one tech is available for a unit, this allows that unit to be constantly produced. Defaults to `True`.",
          "default": true
        },
        {
          "name": "ignored_build_from_tags",
          "type": "json_value",
          "python_type": "set[int]",
          "input": "model",
          "required": false,
          "description": "A set of tags to prevent the spawn controller from morphing from these tags.",
          "default": {
            "expression": "field(default_factory=set)"
          }
        },
        {
          "name": "maximum",
          "type": "integer",
          "python_type": "int",
          "input": "model",
          "required": false,
          "description": "The maximum number of a unit type that can be produced in a single step. Defaults to `20`.",
          "default": 20
        },
        {
          "name": "spawn_target",
          "type": "point_ref",
          "python_type": "Point2 | None",
          "input": "model",
          "required": false,
          "description": "A location to prioritize spawning units near. Defaults to `None`.",
          "default": null
        },
        {
          "name": "__build_dict",
          "type": "unit_type_id",
          "python_type": "dict[Unit, UnitID]",
          "input": "model",
          "required": false,
          "description": "  build dict.",
          "default": {
            "expression": "field(default_factory=dict)"
          }
        },
        {
          "name": "__excluded_structure_tags",
          "type": "json_value",
          "python_type": "set[int]",
          "input": "model",
          "required": false,
          "description": "  excluded structure tags.",
          "default": {
            "expression": "field(default_factory=set)"
          }
        },
        {
          "name": "__supply_available",
          "type": "number",
          "python_type": "float",
          "input": "model",
          "required": false,
          "description": "  supply available.",
          "default": 0.0
        }
      ],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "eligible"
    },
    {
      "id": "macro.speed_mining",
      "name": "SpeedMining",
      "kind": "executable_behavior",
      "description": "Speed mine worker at provided townhall and target resource.",
      "documentation_status": "source_only_public",
      "api": {
        "import": "ares.behaviors.macro.speed_mining.SpeedMining",
        "source_path": "ares/src/ares/behaviors/macro/speed_mining.py",
        "dispatch": "register_behavior"
      },
      "params": [
        {
          "name": "worker",
          "type": "unit_ref",
          "python_type": "Unit",
          "input": "model",
          "required": true,
          "description": "The worker to mine with."
        },
        {
          "name": "target",
          "type": "point_or_unit_ref",
          "python_type": "Union[Point2, Unit]",
          "input": "model",
          "required": true,
          "description": "The resource to mine."
        },
        {
          "name": "worker_position",
          "type": "point_ref",
          "python_type": "Point2",
          "input": "model",
          "required": true,
          "description": "Position of worker."
        },
        {
          "name": "resource_target_pos",
          "type": "point_ref",
          "python_type": "Point2",
          "input": "model",
          "required": true,
          "description": "Position in front or resource to move to before queueing a mine command."
        },
        {
          "name": "distance_to_townhall_factor",
          "type": "number",
          "python_type": "float",
          "input": "model",
          "required": false,
          "description": "How far away from th to move command. Default is 1.08",
          "default": 1.08
        },
        {
          "name": "townhall",
          "type": "json_value",
          "python_type": "Optional[Unit]",
          "input": "model",
          "required": false,
          "description": "Townhall worker is assigned to. Default to None (will calculate closest if so)",
          "default": null
        }
      ],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "disabled",
      "llm_exposure_reason": "Requires review because it is not listed by the current documentation chapter."
    },
    {
      "id": "macro.tech_up",
      "name": "TechUp",
      "kind": "executable_behavior",
      "description": "Automatically tech up so desired upgrade/unit can be built.",
      "documentation_status": "documented",
      "api": {
        "import": "ares.behaviors.macro.tech_up.TechUp",
        "source_path": "ares/src/ares/behaviors/macro/tech_up.py",
        "dispatch": "register_behavior"
      },
      "params": [
        {
          "name": "desired_tech",
          "type": "unit_type_id",
          "python_type": "Union[UpgradeId, UnitID]",
          "input": "model",
          "required": true,
          "description": "The desired upgrade or unit type."
        },
        {
          "name": "base_location",
          "type": "point_ref",
          "python_type": "Point2",
          "input": "model",
          "required": true,
          "description": "The main building location to make tech."
        },
        {
          "name": "ignore_existing_techlabs",
          "type": "boolean",
          "python_type": "bool",
          "input": "model",
          "required": false,
          "description": "If set to `True`, will keep building techlabs even if others exist. Defaults to `False`.",
          "default": false
        }
      ],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "eligible"
    },
    {
      "id": "macro.upgrade_c_cs",
      "name": "UpgradeCCs",
      "kind": "executable_behavior",
      "description": "Handy behavior for Terran and Protoss. Especially combined with `Mining` and ares built in placement solver. Finds an ideal mining worker, and an available precalculated placement. Then removes worker from mining records and provides a new role.",
      "documentation_status": "source_only_public",
      "api": {
        "import": "ares.behaviors.macro.upgrade_ccs.UpgradeCCs",
        "source_path": "ares/src/ares/behaviors/macro/upgrade_ccs.py",
        "dispatch": "register_behavior"
      },
      "params": [
        {
          "name": "to",
          "type": "unit_type_id",
          "python_type": "UnitID",
          "input": "model",
          "required": true,
          "description": "The structure type we want to build."
        },
        {
          "name": "prioritize",
          "type": "boolean",
          "python_type": "bool",
          "input": "model",
          "required": false,
          "description": "If True and there is a CC waiting to upgrade, but we can't afford it yet, this behavior will return True This is useful in a MacroPlan as it will prevent other spending actions occurring. Default is False",
          "default": false
        }
      ],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "disabled",
      "llm_exposure_reason": "Requires review because it is not listed by the current documentation chapter."
    },
    {
      "id": "macro.upgrade_controller",
      "name": "UpgradeController",
      "kind": "executable_behavior",
      "description": "Research upgrades, if the upgrade is not currently researchable this behavior will automatically make the tech buildings required.",
      "documentation_status": "documented",
      "api": {
        "import": "ares.behaviors.macro.upgrade_controller.UpgradeController",
        "source_path": "ares/src/ares/behaviors/macro/upgrade_controller.py",
        "dispatch": "register_behavior"
      },
      "params": [
        {
          "name": "upgrade_list",
          "type": "upgrade_id",
          "python_type": "list[UpgradeId]",
          "input": "model",
          "required": true,
          "description": "List of desired upgrades."
        },
        {
          "name": "base_location",
          "type": "point_ref",
          "python_type": "Point2",
          "input": "model",
          "required": true,
          "description": "Location to build upgrade buildings."
        },
        {
          "name": "auto_tech_up_enabled",
          "type": "boolean",
          "python_type": "bool",
          "input": "model",
          "required": false,
          "description": "bool",
          "default": true
        },
        {
          "name": "prioritize",
          "type": "boolean",
          "python_type": "bool",
          "input": "model",
          "required": false,
          "description": "If True and there is an Upgrade ready to go, but we can't afford it yet, this behavior will return True. This is useful in a MacroPlan as it will prevent other spending actions occurring. Default is False",
          "default": false
        }
      ],
      "parser": {
        "mode": "construct_and_register",
        "instruction_shape": "{id, args}"
      },
      "llm_exposure": "eligible"
    }
  ]
}

