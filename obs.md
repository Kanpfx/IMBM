核心建议：把 Observation 设计成“确定性生成的稀疏结构化状态”，正常控制在 1,200～1,800 字符，最大不超过约 2,500 字符。不要再使用完整自然语言叙述。

最关键的压缩原则是：

> 普通单位按“类型 × 区域 × 活动状态”聚合成组；只有高价值、受伤、具有关键技能或需要单体操作的单位保留 ID。

否则统一 Agent 仍需读取几十个 SCV、Marine、建筑 ID，长度很难真正下降。

## 一、先明确“纯观测”的边界

建议将模型输入严格拆成：

\[
\text{Agent Input}
=
o_t^{observation}
\oplus
m_t^{control}
\oplus
k^{knowledge}
\]

其中：

- \(o_t^{observation}\)：当前讨论的纯观测。
- \(m_t^{control}\)：Commitment、上一轮动作、执行残差。
- \(k^{knowledge}\)：战术表、动作表、规则知识。

纯 Observation 可以包括：

- 当前游戏直接提供的事实；
- 对这些事实进行无战略偏好的确定性聚合，例如计数、比例、区域归类；
- 最近直接观测到的变化和最后见到的信息。

不应包括：

- 战术阶段、战略建议；
- Available technology steps；
- Ares 的 rush/greedy 等专家判断；
- `can_win_fight` 等模拟器判断；
- Situation hints；
- Action history、Commitment 和执行残差；
- 动作目录及参数说明。

当前的 `situation_alerts` 和 `available technology steps` 都带有规则解释，不算纯观测；[ObservationBuilder](E:/Documents/SC2/Bots/why_modified/game/observation/builder.py:241) 中的 `action_history` 也应从 Observation 移到控制记忆。

## 二、理论上可取得的信息全集

项目通过 python-sc2 和 Ares 可以取得的信息大致如下。

| 信息类别 | 可用信息 | 处理建议 |
|---|---|---|
| 对局信息 | 游戏时间、迭代、地图、双方种族、出生点 | 保留时间和种族；地图信息只保留一次 |
| 资源 | 矿、气、收入速率 | 保留 |
| 人口 | 已用、上限、空余、工人、军队人口 | 保留，但去掉可推导冗余字段 |
| 经济 | 基地数、建造中基地、工人数、闲置工人、矿气分配、饱和缺口 | 保留 |
| 资源点 | 矿区剩余资源、气矿余量、可用矿点 | 仅保留基地级剩余资源比例 |
| 己方单位 | 类型、数量、ID、位置、血量、能量、订单、状态、角色 | 聚合；单体信息条件展开 |
| 己方建筑 | 类型、数量、建造进度、血量、位置、生产订单、附属建筑 | 数量和进度保留；位置和血量条件展开 |
| 生产状态 | 正在生产的单位、进度、生产建筑是否空闲 | 保留并聚合 |
| 科技状态 | 已完成升级、研究中升级、建筑科技状态 | 保留 |
| 技能状态 | Tactical Jump、Yamato 等是否可用 | 只保留关键单位的关键技能 |
| 敌方可见单位 | 类型、数量、位置、血量、活动状态 | 按区域聚合 |
| 敌方可见建筑 | 类型、区域、建造状态 | 保留 |
| 敌方历史证据 | 最后见到的类型、数量、区域、距今时间 | 限量保留 |
| 视野信息 | 哪些战略区域当前可见、多久未侦察 | 强烈建议新增 |
| 空间信息 | 坐标、基地、地图中心、扩张点、距离、路径 | 使用固定区域枚举；不提供完整坐标和网格 |
| 威胁信息 | 敌人是否靠近基地、空军/地面军数量 | 保留事实型聚合，不输出“疑似 rush”等判断 |
| 地图网格 | Pathing、influence、avoidance、creep | 不给 LLM，由运行时使用 |
| 作战模拟 | `can_win_fight`、安全点、路径代价 | 不属于纯观测 |
| Ares 情报判断 | Rush、Proxy、Greedy、Enemy Expanded | 不直接使用；保留其原始可见证据 |
| 时间变化 | 单位增减、建筑开工/完成、敌人首次出现、受到攻击 | 保留少量结构化事件 |
| 控制状态 | Ares role、Squad、动作历史、排队状态 | 放到执行上下文，不属于纯观测 |

## 三、最终建议保留的六类核心信息

### 1. 时间、资源与人口

这是所有宏观决策的基本约束：

```json
"time_s": 669,
"resources": {
  "minerals": 2740,
  "vespene": 740,
  "mineral_rate": 979,
  "vespene_rate": 156
},
"supply": {
  "used": 66,
  "cap": 103,
  "army": 30,
  "workers": 35
}
```

不需要同时提供 `free`，因为它可由 `cap-used` 得到。

矿气保留精确值没有明显长度成本。预测时不需要预测精确矿气，可以预测资源区间、缺口或是否可支付关键目标。

### 2. 经济状态

```json
"economy": {
  "bases_ready": 1,
  "bases_building": 0,
  "workers_idle": 0,
  "workers_on_gas": 1,
  "mineral_saturation_deficit": 2,
  "gas_saturation_deficit": 8,
  "remaining_resources_ratio": 0.76
}
```

可以删除：

- 每个工人的 ID；
- 每个矿点对应哪些工人；
- 每个基地的长篇饱和描述。

经济决策真正关心的是产能、分配、缺口和资源枯竭程度。

### 3. 己方产能、科技与军队

建议采用稀疏字典：没有出现的己方类型等于 0。

```json
"own": {
  "units": {
    "SCV": 35,
    "BATTLECRUISER": 4
  },
  "structures": {
    "COMMANDCENTER": {"ready": 1},
    "BARRACKS": {"ready": 3},
    "FACTORY": {"ready": 1},
    "STARPORT": {"ready": 1},
    "STARPORTTECHLAB": {"ready": 1},
    "FUSIONCORE": {"ready": 1}
  },
  "production": {
    "BATTLECRUISER": [0.69]
  },
  "research": {},
  "upgrades": []
}
```

这里的进度统一使用 `[0,1]`。

不再输出：

- 每座完整建筑的血量和坐标；
- `ready and idle` 等自然语言；
- “Available technology steps”；
- 所有 Supply Depot 的 ID。

只有受损的关键建筑才进入条件字段：

```json
"damaged_key_entities": [
  {
    "type": "FUSIONCORE",
    "region": "own_main",
    "health_ratio": 0.66
  }
]
```

### 4. 己方可操作单位组和关键实体

普通部队按区域聚合：

```json
"own_groups": [
  {
    "id": "g1",
    "composition": {
      "BATTLECRUISER": 4
    },
    "region": "own_natural",
    "activity": "moving",
    "health_mean": 1.0,
    "health_min": 1.0,
    "jump_ready": 4,
    "yamato_ready": 0
  }
]
```

运行时保存：

```text
g1 → [928, 573, 587, 570]
```

模型只引用 `g1`，不需要每次重复四个单位的完整信息。

仅在以下情况下保留单体 ID：

- 单位严重受伤；
- 单位与同组其他成员位置明显不同；
- 拥有关键技能且技能状态不同；
- Transport、Ghost、Raven 等需要单体控制；
- 当前可作为特殊动作目标。

例如：

```json
"key_entities": [
  {
    "id": "u573",
    "type": "BATTLECRUISER",
    "region": "enemy_main",
    "health_ratio": 0.38,
    "jump_ready": true
  }
]
```

建议设置硬上限：

- `own_groups` 最多 6 个；
- `key_entities` 最多 8 个。

### 5. 敌方直接证据与视野

敌方信息必须区分“当前可见”和“曾经看见”，不能把不存在记录解释成敌方为零。

```json
"enemy_evidence": {
  "visible_groups": [
    {
      "composition": {
        "MARINE": 8,
        "SIEGETANK": 2
      },
      "region": "own_natural",
      "activity": "attacking"
    }
  ],
  "visible_structures": {
    "enemy_main": {
      "BARRACKS": 2,
      "FACTORY": 1
    }
  },
  "last_seen": [
    {
      "type": "BANSHEE",
      "count": 2,
      "region": "map_center",
      "age_s": 18
    }
  ],
  "region_visibility": {
    "own_main": "visible",
    "own_natural": "visible",
    "enemy_main": 47,
    "enemy_natural": null
  }
}
```

`region_visibility` 的含义可以规定为：

- `"visible"`：当前可见；
- 整数：距上次可靠观察的秒数；
- `null`：从未可靠观察。

这是当前 Observation 最值得补充的信息。没有视野年龄，模型无法判断“没有敌人”究竟意味着安全，还是很久没有侦察。

敌方 belief 和敌方 build hypothesis 不放在这里；它们由 Agent 根据这些证据产生。

### 6. 最近可观测事件

保留从前后两次观测确定性计算的变化，但必须结构化、限量，不能写成长篇自然语言。

```json
"events": [
  {
    "kind": "own_count_delta",
    "type": "SCV",
    "delta": 1
  },
  {
    "kind": "own_structure_damaged",
    "type": "FUSIONCORE",
    "region": "own_main"
  },
  {
    "kind": "enemy_first_seen",
    "type": "BANSHEE",
    "region": "map_center"
  }
]
```

建议最多保留 6 个事件，优先级为：

1. 基地或关键建筑受攻击；
2. 新敌方科技/高价值单位出现；
3. 己方重要单位损失；
4. 建筑和科技完成；
5. 军队与工人数量变化。

这仍然属于 observation history，而不是 Action history。

## 四、推荐的完整 Observation 示例

用当前日志中 11:09 的状态，原 Observation 是 4,380 字符。压缩后可以近似表示为：

```json
{
  "schema_version": 1,
  "time_s": 669,
  "matchup": "TvT",
  "resources": {
    "minerals": 2740,
    "vespene": 740,
    "mineral_rate": 979,
    "vespene_rate": 156
  },
  "supply": {
    "used": 66,
    "cap": 103,
    "army": 30,
    "workers": 35
  },
  "economy": {
    "bases_ready": 1,
    "bases_building": 0,
    "workers_idle": 0,
    "workers_on_gas": 1,
    "mineral_saturation_deficit": 2
  },
  "own": {
    "units": {
      "SCV": 35,
      "BATTLECRUISER": 4
    },
    "structures": {
      "COMMANDCENTER": {"ready": 1},
      "BARRACKS": {"ready": 3},
      "FACTORY": {"ready": 1},
      "STARPORT": {"ready": 1},
      "STARPORTTECHLAB": {"ready": 1},
      "FUSIONCORE": {"ready": 1}
    },
    "production": {
      "BATTLECRUISER": [0.69],
      "SENSORTOWER": [0.37]
    },
    "damaged": [
      {
        "type": "FUSIONCORE",
        "region": "own_main",
        "health_ratio": 0.66
      }
    ]
  },
  "own_groups": [
    {
      "id": "g1",
      "composition": {
        "BATTLECRUISER": 4
      },
      "region": "own_natural",
      "health_mean": 1.0,
      "jump_ready": 4,
      "yamato_ready": 0
    }
  ],
  "enemy_evidence": {
    "visible_groups": [],
    "visible_structures": {},
    "last_seen": [],
    "region_visibility": {
      "enemy_main": null,
      "enemy_natural": null
    }
  },
  "events": [
    {
      "kind": "own_count_delta",
      "type": "SCV",
      "delta": 1
    }
  ]
}
```

即使使用完整字段名，这也会比当前 XML 自然语言短很多，而且更稳定。

## 五、规范化规则

为了便于解析、量化和预测，建议固定以下规则：

- 时间：整数游戏秒。
- 数量：非负整数。
- 比率与进度：`[0,1]`，最多两位小数。
- 收入：整数，每分钟资源。
- 区域：固定枚举，不允许自由文本。
- 单位和建筑类型：统一使用 SC2 `UnitTypeId.name`。
- 活动状态：固定枚举，例如 `idle/moving/attacking/gathering/building`。
- 未知：`null`，不能用 `0` 代替。
- 己方稀疏计数字典：字段缺失表示 0。
- 敌方字段缺失：只表示“当前没有相关证据”，不表示真实数量为 0。
- 数组顺序固定，按类型、区域或优先级排序。
- 不出现完整自然语言句子。
- 所有条件列表设置数量上限。

推荐区域枚举：

```text
own_main
own_natural
own_outer
map_center
enemy_outer
enemy_natural
enemy_main
elsewhere
unknown
```

后续可再增加 `own_third/enemy_third`，但不应无限按坐标细分。

## 六、哪些字段适合成为预测目标

Observation 可以稍完整，但真正的预测输出只需覆盖其中一部分：

| Observation 字段 | 是否预测 | 推荐预测形式 |
|---|---:|---|
| 精确游戏时间 | 否 | 已知 |
| 精确单位 ID | 否 | 不稳定且无战略价值 |
| 精确位置 | 否 | 预测区域变化 |
| 精确矿气 | 一般不预测 | 预测区间、缺口或可支付性 |
| 基地数量 | 是 | 数量变化或完成概率 |
| 科技/建筑进度 | 是 | 完成概率、预计状态 |
| 生产队列 | 是 | 单位数量增量 |
| 军队人口 | 是 | 区间或增量 |
| 兵力组成 | 是 | 数量区间 |
| 关键单位存活 | 是 | 存活/损失概率 |
| 敌方出现事件 | 是 | 事件概率 |
| 敌方精确隐藏数量 | 否 | 使用区间或假设概率 |
| 威胁区域 | 是 | 分类概率 |
| 视野年龄 | 一般不预测 | 由侦察动作确定时可预测 |
| 单位血量 | 只预测关键单位 | 区间或损失事件 |

最终最适合研究的预测目标只有五类：

1. 科技和生产里程碑；
2. 己方兵力与经济产能变化；
3. 关键单位或建筑存活；
4. 敌方威胁和新证据出现概率；
5. 战略目标是否在 \(H\) 秒内达成。

## 最终取舍

最精简、同时基本满足决策的 Observation 应只有：

1. 时间、资源和人口；
2. 经济与基地状态；
3. 己方单位、建筑、生产和科技聚合；
4. 可引用的己方单位组及少量关键实体；
5. 敌方当前证据、最后见到信息和区域视野年龄；
6. 少量结构化观测事件。

其中第 1～5 项构成当前状态，第 6 项提供短期动态。Action history、Commitment、执行残差、战术表和动作表全部放在 Observation 之外。

真正实施时，我建议先以“普通状态不超过 1,800 字符、极端状态不超过 2,500 字符”为硬约束，并优先改造 group reference；单纯重写当前 XML 文本但继续输出所有单位 ID，压缩效果不会稳定。