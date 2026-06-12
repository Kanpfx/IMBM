# IMBM 改造说明

## 总览

在 SunTzu 基础上引入**双模型异步架构**：IM（同步执行者）+ BM（异步战略顾问），两者通过 `DirectiveStore` 队列解耦通信。

## 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `runtime/directive.py` | ~60 | `Directive` 数据类 + `DirectiveStore` 线程安全队列（TTL=360 tick ≈ 16s） |
| `config/env.py` | ~30 | 双模型环境变量加载（`IM_*` / `BM_*` 独立配置） |
| `config/game.py` | ~20 | 地图/难度/种族常量 |
| `core/player.py` | ~255 | `ImBmPlayer(LLMPlayer)`，覆写 `__init__` 和 `run()`，新增 BM 异步调度 |
| `runtime/__init__.py` | 0 | 包标记 |
| `config/__init__.py` | 0 | 包标记 |
| `core/__init__.py` | 0 | 包标记 |

## 新增 Agent

| 文件 | 基于 | 改动 |
|------|------|------|
| `agents/im.py` | `action_agent.py` | ① Role 基于原版微调："As a top-tier StarCraft II executor, your task is to give some actions... You must also predict the near-future game state and request strategic guidance from the background model when facing strategic uncertainty." ② 输出新增 `predicted_observation`（10 section 前向预测）+ `request_background` + `background_reason` 三个字段 ③ prompt 新增 2 条规则（预测观测要求、后台请求条件）④ 原 5 条 executor 规则一字不改 |
| `agents/bm.py` | `plan_agent.py` | ① Role 基于原版微调："As a top-tier StarCraft II background strategist, your task is to give one or more medium-term strategic commands... Do NOT output executable actions — the executor will translate your commands into actions." ② prompt 新增 "Why You Were Consulted" 段（注入触发原因）③ `construct_rules`、`strategy_prompt`、`construct_plan_example`、`create_plan_critic_prompt`、`refine_plan_until_ready` 自纠错循环全部原封复用 |

## 修改文件

| 文件 | 改动 |
|------|------|
| `main.py` | ① 支持 `-bm` 开关 ② IM/BM 各自读独立环境变量（不再通过 CLI 传入 model/base_url/api_key）③ 使用 `ImBmPlayer` 替代 `LLMPlayer` ④ 包装进 `main()` 函数 |
| `agents/__init__.py` | 新增 `ImAgent`、`BmAgent`、`BaseAgent` 导出；`ActionAgent`、`PlanAgent` 标记 deprecated 保留 |
| `.env_template` | `BASE_URL`/`API_KEY` → `IM_MODEL_NAME`/`IM_BASE_URL`/`IM_API_KEY` + `BM_*` 双模型配置 |

## 参数调整

| 参数 | 原值 | 现值 | 说明 |
|------|------|------|------|
| IM 决策间隔（固定） | 10 tick | **30 tick** | `core/player.py`、`players/llm_player.py` |
| IM 决策间隔（随机） | 8~12 tick | **24~36 tick** | 数据采集模式 |
| IM/Action/Single 重试上限 | 3 | **2** | `im.py`、`action_agent.py`、`single_agent.py` |
| BM/Plan 自纠错上限 | 3 | **2** | `bm.py`、`plan_agent.py` |
| LLM 调用超时 | 180s | **90s** | `tools/llm.py` |
| 决策需矿物 | 170 | 170 | 不变 |

## 完全未动的 SunTzu 文件

`tools/` `knowledge/` `scripts/` `players/base_player.py` `players/llm_player.py`（仅决策间隔调整）
`players/miner_player.py` `players/no_player.py` `players/__init__.py`
`agents/base_agent.py` `agents/common.py` `agents/action_agent.py`（仅重试上限调整）
`agents/plan_agent.py`（仅自纠错上限调整）`agents/rag_agent.py` `agents/single_agent.py`（仅重试上限调整）

## BM 异步触发机制

三种触发条件（或关系，`_maybe_start_bm` 中判断）：

| 条件 | 触发原因 | 说明 |
|------|----------|------|
| `request_background=true` | `im_request` | IM 遇到战略不确定性主动求援 |
| `latest_directive is None` | `cold_start` | 尚无任何指令 |
| directive 过期 | `guidance_expired` | TTL=360 tick 超时 |

冲突处理：BM 已在跑时，若新触发是 IM 请求且当前 BM 非 IM 请求触发 → 杀死旧任务启动新的；否则跳过。

## 数据流

```
BM (异步，asyncio.create_task → run_in_executor)
│  prompt = obs + "Why You Were Consulted" + suggestions + rules + tech_tree
│  PlanVerifier 自纠错 (2 轮)
│  输出: 自然语言指令列表 ["Train SCV", "Build Depot", ...]
│
└──▶ DirectiveStore.write() ──▶ DirectiveStore.read()
                                        │
IM (同步，每 ~30 tick) ◀─────────────────┘
│  prompt = obs + "Given Tasks" + rules
│  输出: {predicted_observation, actions, request_background, background_reason}
│  schema 重试 + action 校验重试 (各最多 2 轮)
│
├──▶ run_actions()
└──▶ request_background=true ──▶ 触发新一轮 BM ──循环──▶
```

## 运行

```bash
python main.py --map_name Flat64 --difficulty VeryHard --ai_build RandomBuild --own_race Terran --enemy_race Terran -bm
```

前置条件：`.env` 中配置 `IM_MODEL_NAME` / `IM_BASE_URL` / `IM_API_KEY` + `BM_MODEL_NAME` / `BM_BASE_URL` / `BM_API_KEY`。
