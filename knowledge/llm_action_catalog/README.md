# Ares LLM Action Catalog

This directory contains a versioned, machine-readable inventory of the public
Ares action surface. It separates executable behavior from observation/query
capabilities and is generated from both the local documentation sources and
the current Python source tree.

## Layout

- `Behaviors/`: one JSON file per documented behavior chapter.
- `API Reference.json`: public `AresBot` entry points and lifecycle methods.
- `Manager Mediator.json`: manager queries and manager commands. Queries are
  recorded but are not exposed as LLM output actions.
- `Source Coverage.json`: documented/source-only coverage and exclusions.
- `shared_types.json`: compact, serializable argument types used by every
  action entry.
- `schemas/`: schema for catalog files and for LLM action instructions.

## Canonical LLM instruction

```json
{
  "actions": [
    {
      "id": "combat.individual.a_move",
      "args": {
        "unit": "u12",
        "target": {"x": 80.5, "y": 42.0}
      }
    }
  ]
}
```

`id` is stable across prompt generation and execution. The parser resolves
unit aliases, positions, grids, enum IDs and default values before constructing
the Ares behavior and calling `bot.register_behavior(...)`.

## Source policy

`documentation_status` has one of the following values:

- `documented`: listed by the local API-reference chapter.
- `source_only_public`: publicly re-exported by an Ares package but absent
  from that chapter.
- `source_only_nonpublic`: concrete source class not re-exported; recorded for
  audit but not offered to an LLM.

Only documented, non-composite behavior entries are enabled by default for LLM
instructions. Source-only behavior can be deliberately enabled after review.

## Regeneration

Run this command from the repository root using the project Conda environment:

```powershell
conda run -n StarWM python llm_action_catalog/generate_catalog.py
```

The generator uses only the Python standard library and does not import Ares
or start StarCraft II.

