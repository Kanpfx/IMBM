# IM/BM StarCraft II Framework

This project is a trimmed StarCraft II battle flow built from SunTzu. It keeps only the current IM/BM queue decision pipeline:

- **BM (Background Model)** runs as a blocking planner every 60 ticks when minerals are above 100, then appends high-level queue tasks.
- **IM (Interaction Model)** runs one foreground executor per non-empty queue and turns the queue head into executable SC2 actions.
- **ActionQueueStore** keeps three queues: economy_build, production_tech, and combat.
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
  bm.py                 # Background model prompt and queue append parsing
  prompts.py            # Shared strategy and race rules
runtime/
  action_queue.py       # ActionQueueStore and queue constants
  directive.py          # Legacy directive structures
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

## vLLM

Start a local OpenAI-compatible vLLM server:

```bash
bash scripts/start_vllm_qwen35_2b.sh
```

Defaults:

```text
MODEL_PATH=/root/autodl-tmp/models/Qwen3.5-2B
SERVED_MODEL_NAME=Qwen3.5-2B
PORT=12001
MAX_NUM_SEQS=8
```

`MAX_NUM_SEQS=8` is intended to cover one blocking BM request plus three parallel IM requests with a little headroom. Override any value as needed:

```bash
MAX_NUM_SEQS=4 PORT=12001 bash scripts/start_vllm_qwen35_2b.sh
```

## Run

```bash
python main.py --map_name Flat64 --difficulty Medium --ai_build RandomBuild --own_race Terran --enemy_race Terran
```

Enable BM:

```bash
python main.py --map_name Flat64 --difficulty Medium --ai_build RandomBuild --own_race Terran --enemy_race Terran -bm
```

Logs and replay files are written under `logs/`.

## BM Design Notes

The BM prompt receives the main game state through the observation text. This already includes race, time, minerals, vespene, supply, own units, own structures, visible enemy units, visible enemy structures, available abilities, map information, and recent action history. Extra structured metrics are therefore optional rather than strictly required, but they may still be useful later if the BM needs stable numeric summaries instead of reading all values from text.

For future feedback design, prefer a short sliding window of queue outcomes over raw action history. Each record should describe the queue, task, result, reason, and recent game time, for example whether a task was completed, blocked, dropped, or replaced. This gives BM direct feedback about queue progress without forcing it to infer completion from low-level actions.

Current BM limitations:

- BM tasks are natural-language sentences and do not yet include explicit execution boundaries such as priority, preconditions, success conditions, expiry, or expected queue outcome.
- The BM output examples currently emphasize appending tasks and should include an explicit empty append example for cases where existing queues are sufficient.
- BM can only append tasks. It cannot yet cancel obsolete tasks, reorder tasks, replace tasks, or mark tasks as stale when the game state changes.
- BM scheduling is based on a fixed interval and mineral threshold. It is not yet event-triggered by empty queues, repeated blocked tasks, attacks, supply blocks, or other urgent state changes.
- BM does not maintain an explicit long-term strategic state such as current game plan, tech route, army composition target, expansion plan, or attack timing.
