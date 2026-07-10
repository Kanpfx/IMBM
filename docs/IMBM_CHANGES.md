# IMBM 改造说明

## 总览

项目在 SunTzu 基础上引入双模型异步架构：IM（Immediate Model，同步执行者）+ BM（Background Model，异步战略顾问）。两者通过 `DirectiveStore` 解耦通信。

本轮目录整理后，当前活跃主链路按运行职责拆分，但细分模块收进所属上层包：`agents/` 管 LLM agent 和 prompt，`game/` 管游戏观测、动作、校验、自动逻辑和建议；旧 SunTzu 与实验脚本统一放在 `archive/`。动作校验和游戏控制逻辑保持不变；IM 的 `predicted_observation` 输出现在由 `-observation` 开关控制。

## 当前活跃文件

| 路径 | 说明 |
|---|---|
| `main.py` | 薄入口，调用 `cli.main()`。 |
| `cli.py` | 解析地图/难度/种族/`-bm`，加载 `.env`，创建 IM/BM LLM client，启动 `python-sc2`。 |
| `player.py` | `ImBmPlayer` 主循环：自动逻辑、IM 同步动作、BM 异步调度、DirectiveStore 接入。 |
| `runtime/directive.py` | `Directive` 数据类和线程安全 `DirectiveStore`。 |
| `agents/immediate.py` | IM：LLM 调用、response parse/refine、verifier 回调。 |
| `agents/background.py` | BM：基于当前观测、触发原因和 suggestions 输出自然语言中期指令。 |
| `agents/prompts/` | IM/BM prompt、规则和 prompt builder。 |
| `game/base_player.py` | 薄 adapter，挂接 `game/observation/`、`game/verifier/`、`game/actions/` 和 `knowledge/`。 |
| `game/llm_player.py` | 薄 adapter，挂接 `game/automation/` 与 `game/suggestions/`；旧 agent 兼容导入来自 `archive.legacy_suntzu`。 |
| `game/observation/` | 观测文本构造。 |
| `game/actions/` | 动作执行和建筑落点。 |
| `game/verifier/` | 动作 schema 与合法性校验。 |
| `game/automation/` | 自动工人、MULE、自动还击和早期 SCV 防守。 |
| `game/suggestions/` | 全局和三族建议规则。 |
| `config/` | 环境变量和游戏枚举配置。 |
| `utils/` | LLM client、格式化和通用工具。 |

## 归档内容

| 路径 | 说明 |
|---|---|
| `archive/legacy_suntzu/agents/` | 旧 planner/action/single/RAG agent。 |
| `archive/legacy_suntzu/players/` | 旧 baseline player。 |
| `archive/scripts/` | 旧 benchmark、采集、Elo、SFT、GUI、notebook 和日志汇总脚本。 |
| `archive/tools/` | 当前主链路未使用的 tokenizer 工具和资源。 |

## BM 异步触发机制

| 条件 | 触发原因 | 说明 |
|---|---|---|
| `request_background=true` | `im_request` | IM 遇到战略不确定性主动请求 BM。 |
| `latest_directive is None` | `cold_start` | 尚无 BM 指令。 |
| directive 过期 | `guidance_expired` | TTL=360 tick 超时。 |

BM 已在运行时，如果新触发来自 IM 请求且当前任务不是 IM 请求触发，则取消旧 BM 任务并启动新任务；否则跳过本次触发。

## 数据流

```text
BM async task
  obs + trigger reason + suggestions + rules
  -> natural-language command list
  -> DirectiveStore.write()

IM decision loop
  obs + active directive
  -> actions + background request
  -> schema/action verifier
  -> run_actions()
  -> maybe trigger BM
```

`predicted_observation` 现在由启动参数 `-observation` 控制：默认不要求 IM 输出该字段；开启后恢复预测观测输出和对应的 10 段 observation 校验。

## 运行

```bash
python main.py --map_name Flat64 --difficulty VeryHard --ai_build RandomBuild --own_race Terran --enemy_race Terran -bm
```

前置条件：`.env` 中配置 `IM_MODEL_NAME` / `IM_BASE_URL` / `IM_API_KEY`；启用 `-bm` 时还需要 `BM_MODEL_NAME` / `BM_BASE_URL` / `BM_API_KEY`。
