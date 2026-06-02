# IM + BM Flow Structure for SunTzu

## 1. 目标

在 SunTzu benchmark 上接入一个快慢双模型决策框架：

- **IM (Interaction Model)**：快模型，负责实际控制游戏，固定每 **30 tick** 调用一次，输出可执行 action JSON。
- **BM (Background Model)**：慢模型，负责后台战略分析，不直接控制游戏，只异步生成 `latest_directive`。
- **交互方式**：IM 每次决策时读取当前 `latest_directive`；BM 完成后覆盖写入新的 directive。IM 不等待 BM。

核心原则：不重写 SunTzu 的观测、动作校验、动作执行，只在现有流程外增加 IM/BM 协同层。

```text
SunTzu Env
  -> obs_to_text()
  -> IM every 30 tick
  -> action JSON
  -> verify_actions()
  -> run_actions()

BM async:
  trigger from IM/rules
  -> same SunTzu obs_text snapshot
  -> directive JSON
  -> latest_directive
```

## 2. 复用 SunTzu 原生能力

必须复用：

- `BasePlayer.obs_to_text()`：IM 和 BM 使用同一份 SunTzu 原生观测文本。
- `BasePlayer.verify_actions()`：校验 IM 输出动作。
- `BasePlayer.run_actions()`：执行动作。
- `LLMPlayer.run(iteration)`：作为 IM/BM 接入主位置。
- `SingleAgent / ActionAgent / PlanAgent`：作为 IM/BM prompt 和调用逻辑的基础。

不使用：

- 暂不接入 RAG。当前 SunTzu 的 RAG 入口未启用，且 `RagAgent` 依赖固定外部服务。
- 不让 BM 直接访问 live SC2 对象，只使用触发时冻结下来的 `obs_text`、history、metrics 快照。

## 3. IM 快线

IM 是唯一会输出并执行动作的模型。

### 运行频率

```text
每 30 tick 调用一次 IM
```

这比“每 tick 调用”更符合 SunTzu 的现有决策架构，也能避免过高延迟和成本。

### 输入

- 当前 `obs_text`
- 当前有效 `latest_directive`
- 最近 action history
- SunTzu 原生 ability description

### 输出

IM 输出结构化 JSON，而不是在文本里混入 `<call_bg>`：

```json
{
  "actions": [
    {
      "action": "COMMANDCENTERTRAIN_SCV",
      "units": [101]
    }
  ],
  "request_background": false,
  "background_reason": ""
}
```

规则：

- 只有 `actions` 会交给 `verify_actions()` 和 `run_actions()`。
- `request_background=true` 只表示请求 BM 后台分析，不影响当前动作执行。
- 如果 directive 和当前 observation 冲突，以当前 observation 为准。

IM 的小阻塞可以接受，因为 SunTzu 当前架构本来就是在决策点等待 LLM 返回；本设计只要求 BM 不阻塞 IM。

## 4. BM 慢线

BM 是后台战略分析器，不直接输出 SC2 action。

### 触发方式

BM 可以由以下条件触发：

- IM 返回 `request_background=true`
- 当前没有有效 directive
- directive 过期
- 固定低频 cadence，例如每 180 tick
- 关键事件，例如发现敌方战斗单位、资源严重浮余、连续动作校验失败

### 输入

BM 使用和 IM 一样的 SunTzu 原生观测快照：

- `obs_text`
- 最近 action history
- 当前 `latest_directive`
- 当前 tick / game time / resource metrics

BM 触发时必须冻结这些输入，不能在后台任务中读取 live SC2 对象。

### 输出

BM 只写入 directive JSON：

```json
{
  "summary": "Focus on stabilizing economy, then produce infantry for an early attack.",
  "priority": "economy_then_attack",
  "macro": "Keep worker production active and avoid floating minerals.",
  "production": [
    "Train workers if townhall is idle",
    "Build supply before unused supply drops below 7",
    "Add Barracks units when resources allow"
  ],
  "combat": "Defend near base unless visible enemies are weak; attack once army supply is sufficient.",
  "avoid": [
    "Do not build redundant gas structures before existing gas is saturated",
    "Do not issue repeated commands to busy units"
  ],
  "confidence": 0.75,
  "valid_until_tick": 360
}
```

字段说明：

- `summary`：一句话战略摘要。
- `priority`：当前主要战略方向。
- `macro`：经济与扩张建议。
- `production`：生产与科技建议。
- `combat`：侦查、防守、进攻建议。
- `avoid`：明确禁止或应避免的行为。
- `confidence`：BM 对该建议的置信度。
- `valid_until_tick`：过期 tick，按 SunTzu 的 `iteration` 计。

## 5. DirectiveStore

IM 和 BM 只通过 `DirectiveStore` 共享信息。

```python
class Directive:
    data: dict
    issued_at_tick: int
    valid_until_tick: int
    source: str = "BM"

class DirectiveStore:
    def read(current_tick: int) -> Directive | None:
        ...

    def write(directive: Directive) -> None:
        ...
```

规则：

- freshest-wins：新 directive 覆盖旧 directive。
- `current_tick > valid_until_tick` 时视为无效。
- IM 每次决策主动读取 directive。
- BM 只写 directive，不 push、不打断 IM。

## 6. 最小代码结构

建议新增少量模块，贴合现有 SunTzu：

```text
agents/
  im_agent.py          # 基于 SingleAgent/ActionAgent，输出 actions + request_background
  bm_agent.py          # 基于 PlanAgent，输出 directive JSON

tools/
  directive.py         # Directive / DirectiveStore

players/
  im_bm_player.py      # 接入 IM/BM 的 player，复用 BasePlayer 能力
```

可选后续再整理：

```text
tools/
  llm_backend.py       # 统一 IM/BM 模型调用配置
```

第一版可以继续复用现有 `LLMClient`。IM 同步调用，BM 使用后台异步任务包装同步调用。

## 7. 运行时序

```text
tick t:
  1. SunTzu 生成 obs_text
  2. IM 读取 latest_directive
  3. IM 输出 { actions, request_background, background_reason }
  4. actions 交给 verify_actions()
  5. actions 交给 run_actions()
  6. 如果 request_background=true 或规则触发，则启动 BM 后台任务

background:
  7. BM 使用触发时冻结的 obs_text/history/metrics
  8. BM 生成 directive JSON
  9. DirectiveStore 写入 latest_directive

tick t+30:
  10. IM 再次读取最新 directive
  11. 新 directive 影响后续动作决策
```

## 8. Demo 标准

最小可跑 demo 达到以下效果即可：

1. 不启用 BM 时，IM 能正常进行 SunTzu 对局。
2. 手动写入 stub directive，IM 能在 prompt 中读取并参考。
3. IM 通过 JSON 字段触发 BM。
4. BM 后台生成 directive，不阻塞 IM。
5. 后续 IM 决策能读取 BM 生成的新 directive。
6. 日志记录：
   - `im_latency`
   - `bm_triggered`
   - `bm_latency`
   - `directive_age`
   - `directive`
   - `request_background`

## 9. 总结

该结构是在 SunTzu 原生 benchmark 外增加一层轻量协同机制：

```text
IM 负责每 30 tick 的实际动作；
BM 负责异步战略建议；
二者只通过 latest_directive 弱耦合；
观测、校验、执行全部复用 SunTzu 原生能力。
```
