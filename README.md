# IM/BM StarCraft II Framework

This project is a trimmed StarCraft II battle flow built from SunTzu. It keeps only the current IM/BM queue decision pipeline:

- **BM (Background Model)** runs as a blocking planner whenever the previous BM request has finished and minerals are above 100, then appends high-level queue tasks unless queue pressure pauses it.
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

Start vLLM with values from `.env`:

```bash
source .env && vllm serve "$VLLM_MODEL_PATH" --served-model-name "$IM_MODEL_NAME" --host 0.0.0.0 --port "$VLLM_PORT" --max-num-seqs "$VLLM_MAX_NUM_SEQS"
```

Or use the helper script, which reads `.env` automatically:

```bash
bash scripts/start_vllm_qwen35_2b.sh
```

## Run

```bash
python main.py --map_name Flat48 --difficulty Hard --ai_build RandomBuild --own_race Terran --enemy_race Terran
```

Enable BM:

```bash
python main.py --map_name Flat48 --difficulty Hard --ai_build RandomBuild --own_race Terran --enemy_race Terran -bm
```

Logs and replay files are written under `logs/`.

## BM Design Notes

The BM prompt receives the main game state through the observation text. This already includes race, time, minerals, vespene, supply, own units, own structures, visible enemy units, visible enemy structures, available abilities, map information, and recent action history. Extra structured metrics are therefore optional rather than strictly required, but they may still be useful later if the BM needs stable numeric summaries instead of reading all values from text.

For future feedback design, prefer a short sliding window of queue outcomes over raw action history. Each record should describe the queue, task, result, reason, and recent game time, for example whether a task was completed, blocked, dropped, or replaced. This gives BM direct feedback about queue progress without forcing it to infer completion from low-level actions.

Current BM limitations:

- BM tasks are natural-language sentences and do not yet include explicit execution boundaries such as priority, preconditions, success conditions, expiry, or expected queue outcome.
- The BM output examples currently emphasize appending tasks and should include an explicit empty append example for cases where existing queues are sufficient.
- BM can only append tasks. It cannot yet cancel obsolete tasks, reorder tasks, replace tasks, or mark tasks as stale when the game state changes.
- BM scheduling is based on completion of the previous BM request plus a mineral threshold. If any queue grows beyond 5 tasks, BM pauses until every queue falls back to at most 2 tasks. It is not yet event-triggered by empty queues, repeated blocked tasks, attacks, supply blocks, or other urgent state changes.
- BM does not maintain an explicit long-term strategic state such as current game plan, tech route, army composition target, expansion plan, or attack timing.

## IM Design Notes

Each IM call receives one queue name, the queue head task, and the same SunTzu-style observation view. The available ability table is not filtered by queue; queue focus is provided by the task and IM prompt. This lets economy_build, production_tech, and combat translate their own waiting task into low-level SC2 actions in parallel while sharing a consistent world view.

Current IM limitations:

- IM output only contains low-level actions. It cannot explicitly report task outcome, partial progress, why a task is currently impossible, or whether the task should stay in the queue.
- An empty IM action list is treated as blocked by the runtime, but the prompt does not ask IM to provide a structured reason. Future queue feedback should preserve a reason from IM when available.
- The required output example only shows a `target_unit` action. It should also show `target_position`, no-target actions, and an explicit empty `actions` example.
- Queue-specific ability constraints are prompt-level guidance, not hard code constraints. Validation accepts any enabled ability currently available to the selected unit or structure.
- Parallel IM calls are validated independently before their actions are merged. The merged action set is not yet revalidated for cross-queue conflicts such as shared resources, supply, or issuing competing commands to the same unit.
- Queue tasks are marked done after IM validation but before actual SC2 action execution. If execution later fails because of placement, unit state, or ability availability changes, the task may already have been removed.
- IM retry only refines JSON/schema and action validation failures. It does not reason over execution failures from the previous frame, because those failures are not yet fed back as structured queue outcomes.
- IM does not distinguish atomic one-step execution from multi-step task progress. A broad task may be removed after one valid action even if the higher-level objective is only partially completed.
