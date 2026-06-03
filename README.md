# IM/BM StarCraft II Framework

This project is a trimmed StarCraft II battle flow built from SunTzu. It keeps only the current IM/BM decision pipeline:

- **IM (Interaction Model)** runs synchronously at decision ticks and outputs executable SC2 actions.
- **BM (Background Model)** runs asynchronously and writes high-level directives.
- **DirectiveStore** is the only shared channel between IM and BM.
- SunTzu observation, action validation, action execution, worker distribution, and logging are retained.

## Structure

```text
main.py                 # Run IM/BM games
config/
  env.py                # Environment and generation config helpers
  game.py               # Map, race, difficulty, and build choices
core/
  base_player.py        # SC2 observation, action validation/execution, logging
  economy.py            # Automatic worker and MULE handling
  player.py             # IM/BM runtime scheduling
agents/
  base.py               # Agent base class
  im.py                 # Interaction model prompt, parsing, retry
  bm.py                 # Background model prompt and directive parsing
  prompts.py            # Shared strategy and race rules
runtime/
  directive.py          # Directive and DirectiveStore
  format.py             # JSON/code-block helpers
  llm.py                # OpenAI-compatible LLM client
  logging.py            # Logger setup
  metrics.py            # Small runtime metrics helpers
knowledge/              # SC2 ability and game data
archive/                # Legacy SunTzu files and reference artifacts
```

## Environment

Copy `.env_template` to `.env` and fill in:

```text
IM_MODEL_NAME=
IM_BASE_URL=
IM_API_KEY=

BM_MODEL_NAME=
BM_BASE_URL=
BM_API_KEY=
```

BM variables are required only when running with `-bm`.

## Run

```bash
python main.py --map_name Flat64 --difficulty Medium --ai_build RandomBuild --own_race Terran --enemy_race Terran
```

Enable BM:

```bash
python main.py --map_name Flat64 --difficulty Medium --ai_build RandomBuild --own_race Terran --enemy_race Terran -bm
```

Logs and replay files are written under `logs/`.
