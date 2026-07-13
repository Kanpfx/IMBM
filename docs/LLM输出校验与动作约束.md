# IM/BM 的 LLM 输出校验与动作约束

本文描述当前活跃 IM/BM 主链路中，LLM 输出从生成到进入 StarCraft II 引擎期间会经历的全部限制。这里的“限制”分为三类：

- **软约束**：写在 prompt 或 suggestions 中，模型可以违反；系统不会直接拒绝。
- **校验/修正**：发现问题后把错误回传给模型，要求重答；超过次数后允许本轮以空动作降级。
- **硬拒绝**：动作不会进入游戏命令队列，或会在执行阶段被标为无效。

当前路径为：

```text
BM 输出战略指令 ──> BM 自审 ──> DirectiveStore（时效/新旧过滤）
                                      │
当前观测 + 有效 Directive ──> IM JSON ──> JSON/schema 校验 ──> 动作语义校验
                                                                    │
                                                              IM 修正（最多 2 次）
                                                                    │
                                                           执行前二次校验
                                                                    │
                                                python-sc2 可用能力检查 / 建筑落点 / SC2 引擎
```

## 1. 先说明：观测和 prompt 不是 verifier

`game/observation/` 会将当前游戏状态压缩为文本，并把短 ID 映射到真实 SC2 `tag`。其中 `Unit abilities` 和 `Structure abilities` 会记录每个已完成单位当前可见的能力，并写入 `player._id_to_abilities`。后续 verifier 用这个映射检查“模型是否命令了当前观测中有该能力的单位”。

这是一项重要的输入约束，但不是安全边界：观测在模型思考期间可能过时，且能力观测调用使用了 `ignore_resource_requirements=True`。因此资源、人口和真实可用能力仍必须由后续层重新检查。

IM prompt 中还有五条执行规则，例如“不重复使用同一单位”“资源不足时只做最重要部分”；BM prompt 中还有种族规则、资源总额、生产队列、避免冗余建筑等规则。这些都是**软约束**，不会由通用 verifier 完整逐条验证。

## 2. LLMClient：JSON 外形与请求重试

相关代码：`utils/llm.py`、`utils/format.py`。

每次 IM、BM 初始调用或 refine 调用均使用 `need_json=True`。客户端会：

1. 从回复中提取最后一个三反引号代码块；代码块语言标记可以存在，因为提取器只取首行之后的内容。
2. 使用 `json.loads()` 解析该代码块。
3. 只要求根对象是 JSON `dict` 或 `list`；不检查字段、字段类型、动作能力或游戏状态。
4. 调用失败、没有代码块、JSON 解析失败或根类型不对时，每隔 5 秒重试，最多 5 次。
5. 五次都失败后返回代码块包裹的 `[]`，以避免调用方异常退出。

注意点：

- 这层不要求 IM 是对象、BM 是字符串列表；两者的精确形状由下一层决定。
- 只读取**最后一个**代码块。回复中若有多个代码块，前面的内容不会被解析。
- 客户端的空列表兜底对 BM 是可解析的；对 IM 会在 IM schema 层失败，最终变成“本轮无动作并请求 BM”。
- 这层不使用 OpenAI API 的 `response_format` / JSON Schema，因此模型仍可返回任意文本；约束靠本地解析和重试实现。

## 3. BM：战略输出的约束与缺口

相关代码：`agents/background.py`、`agents/prompts/background.py`。

### 3.1 输出约定与软规则

BM 应输出一个 JSON 字符串列表，每个元素是一条中期自然语言战略命令。prompt 明确要求：不直接输出可执行动作；IM 负责翻译为动作。规则包含：

- 命令应为自然语言；
- 总资源不超过当前矿物/气体；
- 不建冗余或当前不需要的建筑；
- 不使用当前不支持的能力；
- 生产队列容量按 5 处理；
- 追加种族规则和 `get_suggestions()` 的局面建议。

这些规则都只是 prompt 内容。BM 的战略文本不会逐条同资源、科技树、生产队列或敌情进行程序化验证。

### 3.2 critic/refine

BM 生成计划后必定调用 critic。critic 根据同一份观测、计划和规则返回：

```json
{
  "errors": ["..."],
  "error_number": 0
}
```

当 `error_number != 0` 时，BM 带着原计划和错误列表重新生成；最多执行 2 轮 critic/refine。若最后一轮仍有错误，代码直接返回最后版本，**不会因 critic 未通过而拒绝这份计划**。

### 3.3 BM 的实际失败处理

BM 的 `_safe_parse()` 虽定义了“保守战略”回退值，但当前 `run()`、`gene_new_plan()` 和 `refine_plan_until_ready()` 都没有调用它。因此以下情况会抛异常：计划不是列表、critic 不是可解析对象、refine 结果不能 JSON 解析等。

该异常会被 `ImBmPlayer._run_bm_background()` 捕获并记录 `bm_error`，但不会写入新 Directive；IM 将继续使用仍有效的旧指令，或在没有指令时自行决策并再次触发 BM。也就是说，BM 失败是“无新战略”的降级，不会中断游戏主循环。

## 4. DirectiveStore：不是内容校验，而是时效与并发过滤

相关代码：`runtime/directive.py`、`player.py`。

BM 结果封装为 `Directive(data, issued_at_tick, valid_until_tick, source)`。当前 TTL 是 360 tick。

- `read(iteration)` 只返回仍在有效期内的最新指令；过期指令对 IM 不可见。
- `write()` 只接受 `issued_at_tick` 不早于已存指令的结果，避免慢完成的旧 BM 覆盖较新的计划。
- 读写加锁，读取时复制 `data`，避免调用方修改内部对象。
- 不检查 `data` 是否真的是非空字符串列表，也不验证计划是否能被 IM 实现。

因此 DirectiveStore 解决的是异步结果的**新旧与时效问题**，不是战略正确性 verifier。

## 5. IM：JSON schema、预测观测与修正循环

相关代码：`agents/immediate.py`、`agents/prompts/immediate.py`。

### 5.1 最低输出 schema

IM 必须在代码块中返回一个 JSON 对象。程序要求：

```json
{
  "actions": [],
  "request_background": false,
  "background_reason": ""
}
```

- 根对象必须是 `dict`。
- `actions` 若存在必须是 `list`；缺失时被默认为空列表。
- `request_background` 使用 Python `bool(...)` 强制转换；例如非空字符串 `"false"` 会变成 `true`，并非严格 JSON boolean 校验。
- `background_reason` 使用 `str(...)` 强制转换；不要求其在请求 BM 时非空，也不校验理由是否真属战略不确定性。

`-observation` 开启时额外强制 `predicted_observation`：必须非空，并包含 10 个固定段标题（Round state、Own units、Unit abilities、Own structures、Structure abilities、Visible enemy units、Visible enemy structures、Action history、Map information、Ability description）。默认不开启，因此默认 IM 不需要预测观测，也不会校验该字段。

### 5.2 schema/refine 流程

初始回复先经过上述解析。若没有代码块、JSON 不合法、根类型错误、`actions` 非列表，或开启预测观测时预测格式不合格：

1. 将解析错误附加到历史；
2. 要求 IM 以完整 schema 重写；
3. 最多进行 2 次 agent 级重试。

每一次 agent 级调用内部仍会经过 LLMClient 最多 5 次 JSON 请求重试。若最终仍不合格，`_safe_parse()` 返回空 `actions`，并强制 `request_background=true`、理由为 IM 无法解析。主循环不会因 IM 格式错误崩溃。

### 5.3 动作校验失败后的 refine

一旦 IM schema 可解析，`player.py` 始终把 `self.verify_actions` 传入 IM。若动作校验返回失败，IM 会得到完整错误信息并被要求“只返回完整 refined JSON”。schema 错误与动作错误共用最多 2 次 agent 级重试预算；不是“schema 两次再动作两次”。

如果某次旧回复已经请求了 BM，后续 refine 即使不再请求，代码仍保留这个请求信号。这保证格式/动作修正不会丢失已发现的战略不确定性。

## 6. 动作 verifier：真正的游戏前硬约束

相关代码：`game/verifier/action_verifier.py`、`game/verifier/schemas.py`、`knowledge/abilities.py`。

`verify_actions(actions)` 接受动作列表；空列表会通过校验。每个动作先调用 `check_action()`，通过的动作再累加整个批次的资源与人口成本。

### 6.1 单动作结构与目标约束

每个动作必须是对象，且至少有：

```json
{
  "action": "ABILITY_NAME",
  "units": [123]
}
```

能力名必须在 `knowledge/TerranAbility.csv` 加载出的能力表中。能力表再根据 `knowledge/data.json` 的 target 信息确定目标类型：

| target 类型 | 额外字段 | 限制 |
|---|---|---|
| `None` | 无 | 不允许多余字段 |
| `Point` | `target_position` | 必须是两个整数 `[x, y]` |
| `Unit` | `target_unit` | 必须是当前可见映射中的整数短 ID |
| `PointOrUnit` | 两者之一 | 不能同时给出，必须恰好给出一个 |

所有未被该目标类型允许的字段都会导致整条动作失败。`target_unit` 必须能映射回当前 `all_units` 中的实际单位；点目标在这一层只检查形状，不检查地图边界、可走性、距离或可建造性。

### 6.2 施法单位与能力约束

对 `units` 数组中的每个 ID，都会检查：

- 必须是非空整数列表；
- ID 必须存在于短 ID 映射和当前能力映射；
- 映射后的真实单位仍存在，且归我方所有；
- 该单位在当前观测的 `_id_to_abilities` 中拥有此能力；
- SCV 若正在建造，不能被下达其他动作。

这会拒绝幻觉单位、敌方单位、已消失单位，以及“观测中没有该能力”的命令。

### 6.3 人口、资源与局部规则

单条动作会按 `calculate_cost(AbilityId) * len(units)` 检查矿物和瓦斯；有 supply cost 时检查可用人口。Supply Depot、Pylon、Overlord 在剩余人口不少于 8 时会被拒绝。Protoss Pylon 还会拒绝距已有 Pylon 小于 5 的点。

批次层会重新累计所有**单条通过**动作的矿物、瓦斯、人口，并检查总额不超过当前持有量。这避免每一条各自可负担、合起来却超支的情况。

## 7. 执行前二次校验与 SC2 引擎

相关代码：`game/actions/executor.py`、`game/actions/placement.py`。

动作从 IM 通过 verifier 到真正执行之间，游戏状态可能改变。因此 `execute_actions()` 会对每条动作再次调用 `player.check_action()`。失败时把动作标记为 `is_valid=false` 并记录错误，不发送该条命令；同一批的其他动作仍继续执行。

通过二次校验后还有三层实际约束：

1. 对每个施法单位重新调用 `get_available_abilities([unit])`，并断言目标能力仍真实可用。
2. 点目标若是建造能力，会调用 `find_placement()`；它检查目标点，随后在最大距离 100 内搜索可放置点。Terran Barracks、Factory、Starport 还会预留 addon 空间。找不到有效点则该动作失败。
3. 最终由 python-sc2/SC2 接收 `unit(ability, target)`。任意异常会被捕获，动作标为无效并写入日志。

执行成功的动作会记录 `valid_actions` 和历史；失败动作不进入历史。执行阶段**不会再次请求 IM 修正**，下一次决策才可能产生替代动作。

## 8. 当前没有覆盖到的限制

以下事项仅受 prompt 约束，或完全未被当前 verifier 覆盖：

- 不同动作之间是否重复使用同一个单位；prompt 禁止，但程序没有全局去重检查。
- 同一动作 `units` 列表内是否重复 ID；程序未去重，成本会按列表长度累计。
- 多条生产/研究命令是否超过具体建筑的队列容量。
- 科技树前置条件、建筑依赖、冷却/能量等所有细粒度条件；部分会在真实可用能力检查或 SC2 引擎处失败，但 verifier 不给出完整、稳定的预检说明。
- 点目标的地图边界、敌我可见性、攻击距离、路径可达性；建造点只在执行阶段修正。
- BM 指令是否与当前局面匹配、是否互相矛盾、是否可被 IM 翻译。
- `request_background` 是否真的只在战略问题下使用，以及 `background_reason` 是否有信息量。

## 9. 约束强度总结

| 层级 | 对象 | 处理结果 | 强度 |
|---|---|---|---|
| Prompt / suggestions | IM、BM | 引导模型 | 软约束 |
| LLMClient JSON | IM、BM | 最多 5 次调用重试，之后空 JSON | 结构最低保障 |
| BM critic | 战略字符串列表 | 最多 2 轮修正，仍可返回有错误计划 | 软校验 |
| DirectiveStore | BM 指令 | 过滤过期/较旧结果 | 时效约束 |
| IM schema | IM JSON 对象 | 最多 2 次 agent 级修正，失败则空动作+请求 BM | 强格式约束 |
| `verify_actions` | 动作列表 | 把错误反馈 IM；批次不通过则要求重答 | 强预检 |
| `check_action` | 单条动作 | 拒绝无效条目 | 硬拒绝 |
| `execute_actions` | 即将发送的动作 | 二次校验、真实能力与建筑落点检查 | 最终本地防线 |
| SC2 引擎 | 实际命令 | 接受或由异常/引擎状态拒绝 | 最终权威 |

当前最可靠的安全边界是“动作执行前二次校验 + 真实 SC2 能力/落点检查”。BM critic 和 prompt 规则主要提高策略质量，不能保证战略命令、单位去重或生产队列绝对正确。
