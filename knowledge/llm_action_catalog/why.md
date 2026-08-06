我检查了当前 `why` 的 `BattleCruiserRush`（提交 `2ff4a5c`）。它是一套“快速 BC 科技 + BC 空袭 + Marine 跟进”的开局插件，不是单独的完整 Bot；完整运行还依赖 `MyBot` 的通用采矿、MULE、维修、侦察等逻辑。

## 简化流程

```text
Ares 从 terran_builds.yml 选择 BattleCruiserRush
  ↓
MyBot 动态加载 BattleCruiserRush 类
  ↓
Build Runner 执行快速 Fusion Core + Starport Tech Lab 开局
  ↓
开局完成后，BattleCruiserRush 开启 BC/Marine 宏观计划
  ↓
第一艘 BC 出现：BC 直接向攻击目标推进/跳跃
  ↓
Marine 从守家坡口改为跟随同一攻击目标
  ↓
BC 低血量回家；其余 BC 用空中网格绕危险区域
```

YAML 开局是：

```yaml
BattleCruiserRush:
  ConstantWorkerProductionTill: 0
  PersistentWorker: False
  OpeningBuildOrder:
    - 12 supply
    - 12 gas
    - 12 barracks
    - 15 factory
    - 15 orbital
    - 15 gas
    - 17 starport
    - 19 supply
    - 19 fusioncore
    - 19 starporttechlab
```

它的目标不是标准扩张后再转 BC，而是尽快到 `Starport + Tech Lab + Fusion Core`。开局中仍显式造少量 SCV 和 Marine；开局完成后才由宏观控制器恢复持续造工人和扩张。[开局 YAML](https://github.com/raspersc2/why/blob/2ff4a5c3ec87fd3f574e92b03f93c532b0be53fd/terran_builds.yml#L95)

## 选择与生命周期 API

`why` 的顶层 `MyBot(AresBot)` 使用：

| API | 层级 | 作用 |
|---|---|---|
| `AresBot` | Ares 框架 | Bot 生命周期和管理器入口 |
| `build_order_runner.chosen_opening` | Ares Build Runner | 获得 YAML 选中的开局名 |
| `build_order_runner.build_completed` | Ares Build Runner | 判断 YAML 是否执行完 |
| `load_opening()` + `importlib` | 项目自定义 | 按名称动态加载 `bot.openings.battle_cruiser_rush.BattleCruiserRush` |
| `on_start` / `on_step` / `on_unit_created` | python-sc2 生命周期，经 Ares 继承 | 初始化、逐帧策略、单位出生事件 |
| `register_behavior()` | Ares | 将当前帧要执行的行为提交给 Ares |

`terran_builds.yml` 对每个正常对局种族都把 BC Rush 放进候选循环，且 `BuildSelection: WinrateBased`；因此它是多开局池中的一个候选，而不是唯一策略。另有一个特殊兜底：若 Terran 敌人把建筑全飞走、游戏超过 6 分钟，`MyBot` 会切换到 `BattleCruiserRush` 防止平局。[顶层调度](https://github.com/raspersc2/why/blob/2ff4a5c3ec87fd3f574e92b03f93c532b0be53fd/bot/main.py#L55)

## BC Rush 自己使用的 Ares 宏观 API

开局完成后，它的兵种比例是 `80% BATTLECRUISER + 20% MARINE`，没有显式升级列表。

| API | 用法 |
|---|---|
| `MacroPlan` | 聚合本帧所有宏观行为 |
| `ProductionController` | 按 BC/Marine 比例补生产建筑 |
| `AutoSupply` | 自动补人口 |
| `GasBuildingController(100)` | 尽可能补气矿，服务 BC 的高气体需求 |
| `UpgradeCCs(ORBITALCOMMAND)` | 将指挥中心升级为轨道指挥中心 |
| `SpawnController(..., freeflow_mode=True)` | 根据比例自由分配资源造 BC/Marine |
| `BuildWorkers` | 一矿 20 工人、多矿最多 60 工人 |
| `ExpansionController(100)` | 允许扩张；但仅在已有/正在生产 BC 时加入计划 |
| `UpgradeController([])` | 结构上保留升级入口，但当前列表为空，实际不研究科技 |
| `cy_unit_pending(ai, BATTLECRUISER)` | 判断是否有 BC 在建，用于控制“升级/扩张是否开放” |

关键参数是：

```python
add_hellions=False
add_upgrades=pending_bcs
can_expand=pending_bcs
freeflow_mode=True
upgrade_to_pfs=False
```

也就是说，它不会额外补 Hellion、不会转 Planetary Fortress；只要开始稳定生产 BC，才进入正常运营和扩张。[BC 开局类](https://github.com/raspersc2/why/blob/2ff4a5c3ec87fd3f574e92b03f93c532b0be53fd/bot/openings/battle_cruiser_rush.py) [通用宏观计划](https://github.com/raspersc2/why/blob/2ff4a5c3ec87fd3f574e92b03f93c532b0be53fd/bot/openings/opening_base.py#L79)

对我们的动作表有一个直接结论：`UpgradeCCs` 必须保留。它是这种真实规则 Bot 用到的 Ares 宏观接口；在我们当前版本的 Ares 中应标为源码发现的接口，而不能因文档覆盖不足而遗漏。

## BC 微操：Ares API

BC 控制是独立的 `BattleCruiserCombat`，每艘 BC 每帧构造一个 `CombatManeuver`：

| API | 用途 |
|---|---|
| `mediator.get_own_army_dict[BATTLECRUISER]` | 获取己方 BC 集合 |
| `mediator.get_units_in_range` | 查询每艘 BC 半径 13 内的敌人 |
| `mediator.get_air_avoidance_grid` | 空中避险网格 |
| `mediator.get_air_grid` | 空中移动/寻路网格 |
| `mediator.is_position_safe` | 判断当前位置是否危险 |
| `mediator.find_closest_safe_spot` | 在目标附近找安全落点 |
| `CombatManeuver` | 组合单位的候选行为 |
| `KeepUnitSafe` | 根据危险网格避险 |
| `PathUnitToTarget` | 走空中网格前往目标或撤退点 |
| `UseAbility` | 执行 Tactical Jump |
| `register_behavior` | 注册该 BC 的 maneuver |

具体决策很简单：

1. 总是先加入 `KeepUnitSafe(air_avoidance_grid)`。
2. 若 `EFFECT_TACTICALJUMP` 可用且离目标距离大于 50：
   - 在目标附近找安全点；
   - `UseAbility(EFFECT_TACTICALJUMP, safe_spot)`。
3. 若 BC 生命低于 `225`：
   - `PathUnitToTarget(..., main_base_ramp.top_center)`，撤回家。
4. 否则：
   - 若当前位置不安全，再加入一次基于 `air_grid` 的避险；
   - 向攻击目标路径移动。

它并没有复杂的 BC 集火、目标优先级或 Jump 回撤逻辑，主要依赖 Ares 的空中危险网格来规避防空区域。[BC 微操实现](https://github.com/raspersc2/why/blob/2ff4a5c3ec87fd3f574e92b03f93c532b0be53fd/bot/combat/battle_cruiser_combat.py)

## Marine 与攻击目标：Ares API

第一艘 BC 出现前，Marine 的目标是己方主矿坡口；第一艘 BC 出现后，Marine 改为向 BC 的攻击目标推进。

攻击目标来自基类：

1. 有超过 5 个可攻击的地面敌军：攻击其中心。
2. 有敌方建筑且时间超过 120 秒：攻击离我方最近的建筑。
3. 敌人主基地未侦察或时间不足 150 秒：去敌方主基地。
4. 否则：轮询各扩张点扫图。

Marine 采用 `Bio → GroundRangeCombat` 链路，使用：

- `mediator.get_squads(role=ATTACKING)`：按半径聚成小队。
- `get_position_of_main_squad`：非主力小队向主力汇合。
- `get_units_from_role`：取得攻击角色的生化单位。
- `get_units_in_range`：查询小队附近敌人。
- `can_win_fight`：以战斗模拟结果控制交战/撤退。
- `ShootTargetInRange`、`StutterUnitForward`、`StutterUnitBack`、`KeepUnitSafe`、`PathUnitToTarget`、`AMove`：实际地面微操。

因此这套开局并非“只派 BC”；它是 BC 先开路，Marine 以战斗模拟约束跟进。

另外，`BattleCruiserRush` 也初始化并逐帧调用 `Reapers` 控制器，但 YAML 不生产 Reaper，所以正常 BC Rush 中通常没有实际效果。这是项目复用结构留下的调用，不应误判成 BC Rush 的核心战术。

## 直接使用的 python-sc2 API

Ares 之外，实际仍大量直接使用 python-sc2：

| 类别 | API | 位置与用途 |
|---|---|---|
| 枚举与数据 | `UnitTypeId`、`AbilityId`、`UpgradeId`、`Point2`、`Unit`、`Units` | 单位、能力、目标和集合类型 |
| 单位状态 | `unit.abilities`、`health`、`position`、`tag`、`is_cloaked`、`is_revealed`、`is_burrowed`、`is_visible`、`is_memory`、`is_snapshot` | BC 是否可跳跃、敌人过滤 |
| Bot 状态 | `enemy_units`、`enemy_structures`、`time`、`state.visibility`、`enemy_start_locations`、`expansion_locations_list`、`main_base_ramp` | 攻击目标选择 |
| 单位原始命令 | `unit(AbilityId, target)` | MULE、SCV 维修、补给站降下等 |
| 单位命令 | `unit.move(target, queue=...)`、`unit.attack(target)` | SCV 环绕侦察、攻击代理建筑 |
| 单位集合 | `filter()`、`closest_to()`、`center` | 敌军筛选与目标选择 |

顶层每帧还始终执行：

- `Mining(workers_per_gas=...)`
- 轨道指挥中心 `CALLDOWNMULE`
- 受损单位的 SCV 维修：`EFFECT_REPAIR_SCV`
- 对 Terran 的 SCV 环形侦察、代理建筑攻击
- 每 16 帧直接对补给站调用 `MORPH_SUPPLYDEPOT_LOWER`

这些是所有开局共享的底层管理，并非 BC Rush 类本身定义的动作。[共享逻辑](https://github.com/raspersc2/why/blob/2ff4a5c3ec87fd3f574e92b03f93c532b0be53fd/bot/main.py)

最后，`cy_unit_pending`、`cy_distance_to_squared` 等 `cython_extensions` 是高性能辅助查询，不是 Ares 动作，也不应放入我们给 LLM 的动作表。
