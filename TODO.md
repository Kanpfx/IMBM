先给一个最重要的修正：当前自动化确实来源于 why，方向没有错；但迁移时丢掉了 why 的两个关键约束：

1. 原版 BC Rush 在 Opening 完成前由 `BuildOrderRunner` 精确执行开局，完成后才启用通用宏观自动化。
2. 通用宏观自动化被放进有序 `MacroPlan`，按优先级依次尝试；某个行为成功或要求保留资源后，当帧后续行为不会继续执行。

当前代码则在启动时直接标记 Opening 完成，并把 `Mining / BuildWorkers(80) / AutoSupply` 作为彼此独立的 Behavior 每帧注册。看起来用了相同组件，但不再保留原来的阶段门控与顺序仲裁。这是当前资源抢占的主要来源。[why 的 BC Rush 实现](https://github.com/raspersc2/why/blob/main/bot/openings/battle_cruiser_rush.py)、[why 的通用 MacroPlan](https://github.com/raspersc2/why/blob/main/bot/openings/opening_base.py)。

## 1. 哪些完全自动化，哪些自动化保底但允许 IM 覆盖

我建议按“决策”和“执行”区分，而不是简单按功能名字区分。

| 功能 | 建议所有者 | 说明 |
|---|---|---|
| 采矿单位具体分配、重新分矿 | 完全自动化 | IM 不应逐个给 SCV 分矿 |
| 建筑选址、选择建造 SCV | 完全自动化 | IM 决定造什么、在哪里附近；Ares 决定精确位置 |
| 路径规划、避障、影响网格 | 完全自动化 | 属于动作执行细节 |
| Behavior 逐帧重注册 | 完全自动化 | IM 只提交一次意图 |
| 补给站升降 | 完全自动化 | 除非以后加入堵口战术 |
| 基础单位空闲处理 | 完全自动化 | 但不能擅自改变战略任务 |
| 工人逃生、低血量单位保命 | 自动化保底，可覆盖 | 安全层拥有紧急优先级 |
| 日常维修 | 自动化保底，可覆盖 | 要限制维修 SCV 数量和资源投入 |
| 补人口 | 自动化保底，受资源仲裁 | 不应再要求 IM 每次提交 `AutoSupply` |
| 造工人 | 自动化执行，IM 控制目标 | IM 决定目标工人数、是否暂停；代码负责维持 |
| 气矿采集 | 自动化执行，IM 控制目标 | IM 决定气矿数和每矿工人数 |
| MULE | 自动化保底，保留扫描覆盖 | 当前自动消耗所有 50 能量会剥夺 IM 使用 Scan 的机会 |
| 生产单位 | 自动化执行，IM 控制组成与预算 | IM 设置 80/20 目标，代码持续执行 |
| 扩张 | IM 决策，自动化执行 | IM 决定何时扩、目标基地数；Ares 负责落点 |
| 科技、建筑、升级 | IM 决策，自动化执行 | 这是核心战略空间 |
| 战斗目标、进攻/防守/撤退 | IM 决策，Ares 微操 | IM 给任务，Ares 逐帧走位和集火 |
| Tactical Jump、Yamato、Scan | IM 决策或明确战术规则 | 具有明显战略后果，不宜无条件自动使用 |
| 紧急基地防御 | 自动化保底，可由 IM 接管 | 防止 IM 低频时完全不响应突袭 |

### 对当前自动化的具体评价

[automation.py](E:/Documents/SC2/Bots/why_modified/game/control/automation.py) 中：

- `Mining`：应该保留自动化，但从 IM 动作面删除；IM 只控制 gas/mineral 策略参数。
- `BuildWorkers(to_count=80)`：不应作为无条件自动化。
  - why 原实现是一矿约 20 工人，多矿时按基地数增长，上限默认 60。
  - 当前开局即追求 80 SCV，会持续侵占 BC 科技资源。
  - 应改为代码维护的 `worker_target`，默认规则只是保底，IM 可以设置或暂停。
- `AutoSupply`：适合保留自动化，但必须进入统一宏观优先级和资源预留，且从 IM 动作面删除。
- `_mules()`：可以自动化，但需要为 Scan 保留能量或允许 IM 设置能量策略。
- `_general_repair()`：可以保留，但应限制维修投入，并允许紧急战斗任务覆盖。
- `_look_for_terran_bunker()`：适合作为 Terran 对局保底侦察，但长期多战术架构中应变成规则插件，而不是核心控制器固定逻辑。
- 降补给站：可完全自动化。

最重要的不是删除自动化，而是恢复 why 原本的“优先级序列”语义。原版 `MacroPlan` 每帧只让最高优先级的可执行宏观行为消费资源；当前是多个 Behavior 独立执行。

## 2. 当前动作提交时，有没有携带资源消耗、条件和参数选项

### 2.1 模型目前没有拿到明确资源成本

当前动作表没有为模型提供类似：

```json
{
  "structure_id": "FACTORY",
  "cost": {"minerals": 150, "vespene": 100},
  "requires": ["BARRACKS"],
  "available_now": true
}
```

IM 主要看到：

- 当前矿、气、人口。
- 动作名称和描述。
- 必填参数。
- 部分实时允许的单位 ID、目标 ID、技能。
- 战术卡里提到的建筑名称和部分 BC 成本。

运行时确实会使用真实成本，但这是模型输出之后发生的：

- `bot.can_afford(...)`
- `bot.calculate_cost(...)`
- Ares/Python-SC2 的科技条件
- `DeferredActionQueue`

而且目前 Deferred Queue 只显式计算三类动作：

- `BuildStructure`
- `TechUp`
- `UpgradeCCs`

`SpawnController`、`BuildWorkers`、`AutoSupply`、`ProductionController` 的消费没有进入统一的外部预算，因为它们是在 Ares Behavior 内部自行判断和消费。

### 2.2 BuildStructure 没有向模型明确列出所有可选建筑

当前 Prompt 中大致是：

```text
BuildStructure(base_location: Point, structure_id: UnitType)
```

`structure_id` 只说明“建筑类型”，但没有动态列出：

```text
Allowed: SUPPLYDEPOT, BARRACKS, FACTORY...
```

也没有列出每种建筑的成本和前置科技。

当前之所以能造出正确建筑，主要依靠四层机制：

1. 战术卡和 BM 明确提到了 `SUPPLYDEPOT / BARRACKS / FACTORY / STARPORT / FUSIONCORE`。
2. 模型自身具备《星际争霸 II》常识，知道这些枚举名称和大致科技路径。
3. Policy 会将字符串转为 `UnitTypeId`，并拒绝不是建筑的类型；Refinery 还被特别要求使用 `GasBuildingController`。
4. Ares 负责检查科技进度、建筑尺寸、放置位置和选择 SCV。

所以它现在是“模型凭知识选名称，运行时负责兜底”，而不是“动作表完整告诉模型当前能造什么”。

### 2.3 当前还有一些重要的隐藏副作用

Prompt 只展示必填参数，很多可选参数和运行时固定参数并不展示。例如：

- `SpawnController` 的 `freeflow_mode` 被运行时固定为 `true`。
- 这意味着它可能持续使用空闲生产建筑花掉可用资源。
- `ProductionController` 有自己的银行阈值和生产扩张逻辑。
- `AutoSupply` 在需要补人口但买不起时可以返回 `true`，用于阻断原版 `MacroPlan` 后续消费。

模型不知道这些完整副作用，却要负责整体资源规划，这是架构信息不对称。

### 建议的动作成本描述

不必把完整科技树全部塞进 Prompt。只需要对当前动态可用候选提供：

```text
BuildStructure:
- SUPPLYDEPOT: 100M/0G，当前可建
- BARRACKS: 150M/0G，当前可建
- FACTORY: 150M/100G，需要已完成 Barracks，当前不可建
```

对于非固定成本 Controller，不能伪装成一个固定成本动作，应标注其消费模式：

```text
SpawnController:
- 持续消费型
- 可消耗全部可用资源
- 当前预算上限：200M/100G
- 资源优先级：低于 first_bc_reservation
```

这样资源仲裁器才能理解区别：

- 固定成本动作
- 持续消费策略
- 不消耗资源的单位命令
- 会预留资源的高优先级动作

## 3. IM 应该以什么频率运行，是否拆散 BM 指导

当前 `GameStep=2` 时，每 10 个 `on_step` 调用一次 IM，大约不到 1 游戏秒一次。这对于 LLM 过密。

建议先使用：

- 常规 IM：每 50～70 iterations，约 4.5～6.3 游戏秒。
- 无敌情的纯宏观阶段：可放宽到 8～10 游戏秒。
- 战斗中：仍不建议每秒调用 LLM，而是由 Ares 持续执行战斗意图。
- 以下事件立即触发一次 IM：
  - 首次发现敌军。
  - 敌军进入基地。
  - 当前目标死亡或消失。
  - 单位任务完成。
  - BC 低于保命阈值。
  - 关键建筑完成或被摧毁。
  - 队列动作连续失败。
  - 阶段发生变化。

因此更合理的是：

```text
低频定时 IM + 事件触发 IM + 每帧代码执行器
```

### 是否需要把 BM 的三条指导拆散

我不建议机械地把三条指导依次喂给 IM。

例如：

1. 完成 Starport。
2. 保持 Marine 防守。
3. 为 BC 预留资源。

它们本身可能需要并行处理，强行拆成三个连续任务反而丢失全局关系。

更合适的是：

- BM 保留 1～3 条带优先级的指导。
- IM 每轮只选择当前可推进的一小部分。
- 代码保存未完成意图。
- 后续 IM 根据新观测确认、调整或替换，而不是重复创建。
- 执行器持续执行已接受的意图，不依赖 IM 每秒重发。

也就是说，不拆散指导文本，而是把 IM 的输出转成可持续的任务状态。

## 4. 意图去重应该由代码完成

这一点我同意你的判断。

相邻观测产生相同决策通常不是错误，反而说明模型判断稳定。不能因为重复就报错或要求模型学习“不要重复”。

正确行为应该是静默合并：

- 如果相同意图已经 `active`：刷新 lease，不重新注册历史。
- 如果相同意图已经 `queued`：保留原队列位置和资源预留。
- 如果目标已经由观测确认完成：静默丢弃。
- 如果参数变化：用新目标覆盖旧目标。
- 不触发 Correction Agent。
- 不把重复记录成 validation error。

但去重键不能对所有动作都使用完整 JSON，需要按语义设计：

```text
BuildWorkers(40)       → 槽位 macro.worker_target
BuildWorkers(50)       → 覆盖同一槽位

SpawnController(80/20) → 槽位 macro.army_composition

KeepUnitSafe(unit=12)  → 槽位 unit:12:movement

BuildStructure(Factory)→ 独立建造任务，可有任务 ID
```

重复输出等于模型为现有意图续约，而不是重新创建动作。

## 5. 新动作和持久动作应该采用覆盖关系

你第 5 点应该是指“相同单位的新动作覆盖旧动作”，我认为这是正确方向。

建议引入 Control Slot：

```text
unit:<tag>:movement
unit:<tag>:attack
unit:<tag>:ability
macro:workers
macro:supply
macro:gas
macro:army_composition
macro:expansion
```

基本覆盖规则：

1. 新 IM 动作覆盖同一槽位的旧 Persistent Action。
2. Group 动作展开为组内各单位的控制槽位。
3. 未被新动作覆盖的单位继续原任务。
4. 新 Group 动作只接管它包含的单位。
5. 旧 Deferred Action 如果对应意图已被替换，应标记 `superseded`，不能以后突然执行。
6. 自动化只使用没有被上层意图占用的槽位。
7. 紧急安全动作可以临时抢占进攻动作。
8. 抢占结束后是恢复旧任务还是要求重新决策，需要由动作类型声明。

例如：

```text
旧：BC 12 → AMove enemy_main
新：BC 12 → KeepUnitSafe air_grid
```

新动作应取消旧移动意图，而不是让两个 Behavior 同时注册。

但资源类不能只按单位覆盖，需要按宏观域覆盖：

```text
旧：BuildWorkers(80)
新：BuildWorkers(30)
```

应当修改同一个 worker target，而不是同时存在两个目标。

## 6. 多种动作状态已经存在，但完成判据没有完全起作用

你记得没错。目前确实有：

- `queued`
- `active`
- `completed`
- `failed`
- `expired`

问题是状态名比实际语义更强。

当前行为是：

- 一次性动作成功注册给 Ares 后，马上记为 `completed`。
- 持久动作到固定迭代期限后，记为 `completed`。
- 持久动作重新注册抛异常时，记为 `failed`。
- Deferred 动作超过 TTL，记为 `expired`。
- 历史只保留最近 10 条。

所以现在的 `completed` 实际可能表示：

```text
已提交给 Ares
或
持久注册期结束
```

不一定表示：

```text
Factory 已经开始建造
单位已经抵达目的地
目标单位已经死亡
工人数已经达到 40
```

建议区分两种状态轴：

### 执行状态

```text
accepted → registered → executing → stopped
```

### 目标状态

```text
pending → progressing → achieved
                 ↘ failed / cancelled / superseded
```

不同动作要有各自完成谓词：

- `BuildStructure(FACTORY)`：出现 Factory pending/ready。
- `BuildWorkers(40)`：工人数量达到 40。
- `AMove(enemy_main)`：单位到达范围内、目标失效或被新任务覆盖。
- `KeepUnitSafe`：单位安全并维持一段时间。
- `SpawnController`：一般没有自然完成，应作为持续 Desired State。

所以状态系统不是没起作用，而是现在主要跟踪“运行时动作容器”，还没有完整跟踪“游戏目标”。

## 7. 多个层级可以分开操控，而且不需要多个 IM

可以分层，但不一定要增加模型数量。

建议结构：

```text
BM：战略目标
    ↓
IM：中层意图
    ↓
意图调度器：去重、覆盖、优先级、资源预留
    ↓
Ares 执行器：逐帧 Behavior、路径、微操、建造位置
```

IM 的输出可以按生命周期分为四类：

1. Policy：持续策略  
   例如工人目标、气矿目标、兵种比例。

2. Task：有明确完成条件的任务  
   例如造 Factory、扩到二矿、研究升级。

3. Mission：单位或编队任务  
   例如守主矿、进攻敌方主矿、撤退维修。

4. Impulse：一次性即时动作  
   例如 Tactical Jump、Yamato、Scan。

仍然是同一个 IM，也仍然拥有完整战略自由；只是执行器不再把所有输出都当成同一种“一次性 Ares 调用”。

这里“分层”不是限制模型，而是让代码知道：

- 这个动作是否持续。
- 怎么完成。
- 如何覆盖。
- 是否消耗资源。
- 和谁冲突。

## 8. BM 需要更合适的操控层次

同意先留给后续设计。当前只需要避免让 BM 接收过量的单位 ID 和参数细节。

短期可以不改变 BM 输出格式，只给它能力摘要：

```text
当前可建 Factory
当前可扩张
当前可以生产 Marine
当前没有 Tactical Jump
```

IM 再接收完整动作参数表。

## 9. 主动触发 BM 可以暂时搁置

可以。既然当前 IM 还不能稳定判断何时需要 BM，就先保持固定周期。

但建议在协议层做一个小清理：

- 要么暂时从 IM 输出契约删除 `request_background`。
- 要么明确标记为“仅记录，不触发调度”。

现在模型被要求输出一个事实上不改变行为的字段，容易让后续开发误以为主动触发已经接通。

事件触发 IM 与主动触发 BM 是两件事。前者现在就值得做，后者可以以后再做。

## 10. BM 自由度和硬耦合可以暂时不改

对于短期 BC Rush，我同意不急着给 BM 增加大量硬约束，也不必现在把 Phase 系统完全数据驱动化。

但需要区分：

- BM 的战略自由：应保留。
- 执行层的不变量：必须由代码保证。
- `PhaseResolver` 硬编码 BC：属于技术债，不是模型自由。

例如这些不应依赖 BM 自觉遵守：

- 同一单位只能有一个当前移动任务。
- 高优先级预留资源不能被低优先级生产消费。
- 已被替换的 Deferred Action 不能复活。
- 自动化不能和 IM 同时控制同一宏观槽位。
- 非法建筑和不存在的目标不能执行。

所以可以保持 BM 自由、保持 BC Phase 硬编码，但仍然先补齐下层仲裁。

## 我建议的实际优先顺序

下一轮架构改造建议按以下顺序：

1. 恢复类似 why `MacroPlan` 的统一宏观优先级与单帧消费仲裁。
2. 从 IM 动作面移除 `Mining` 和 `AutoSupply`；把 `BuildWorkers` 改成可覆盖的 worker target。
3. 增加意图槽位、静默去重和新动作覆盖旧动作。
4. 把 IM 间隔从 10 提高到约 50～70 iterations，并增加关键事件触发。
5. 修正 `completed` 语义，为建造、生产目标增加观测确认。
6. 给 `BuildStructure` 提供动态建筑选项、成本和前置条件。
7. 最后再实现全局资源预留和批次动作预算。

其中第 1～3 项通常就能显著减少当前日志中的重复动作和资源抢占，同时不削弱模型自由度。













