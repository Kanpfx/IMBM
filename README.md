# SunTzu / IMBM

这是一个使用大模型控制《星际争霸 II》的项目。当前活跃主链路是 IM/BM 双模型架构：

- IM（Immediate Model）：同步决策模型，基于当前观测和 BM 指令生成下一批可执行动作。
- BM（Background Model）：异步战略模型，在后台生成中期战略指令，通过 `DirectiveStore` 传递给 IM。

本仓库目前只保留 IM/BM 主链路作为活跃代码；旧 benchmark、采集、Elo、SFT、GUI、notebook 和旧 SunTzu agent 已统一放入 `archive/`。

## 项目特点

- 支持 `python main.py ... -bm` 启动 IM/BM 双模型控制流程。
- 保留 SunTzu 原有的观测压缩、动作校验、动作执行、自动工人、MULE 和自动还击逻辑。
- 动作校验语义保持不变；IM 的 `predicted_observation` 输出由 `-observation` 开关控制。
- 代码已按运行职责分层：agent、prompt、游戏观测、动作执行、自动逻辑、建议系统、校验器、运行时状态分别管理。

## 环境准备

### 1. 安装 StarCraft II

需要本地安装 StarCraft II，免费 Starter Edition 即可。

Windows / macOS：

1. 从 StarCraft II 官方网站安装游戏。
2. 建议在 Battle.net 启动器中把游戏语言设置为英文。

Linux：

1. 从 Blizzard `s2client-proto` 仓库下载 Linux 游戏包。
2. 设置 `SC2PATH`：

```bash
export SC2PATH="/path/to/StarCraftII"
```

### 2. 安装地图

1. 下载 `Melee` 地图包。
2. 在 StarCraft II 安装目录中创建 `Maps` 文件夹。
3. 将地图包解压到 `Maps` 文件夹中。

### 3. 安装 Python 依赖

建议使用项目对应的 Conda 环境：

```bash
pip install -r requirements.txt
```

当前普通 Python 环境如果缺少 `sc2`、`openai` 等依赖，只能通过静态编译和 `--help` 检查，不能完整启动游戏。

## 配置模型

复制环境变量模板：

```bash
cp .env_template .env
```

在 `.env` 中配置 IM 模型：

```text
IM_MODEL_NAME=...
IM_BASE_URL=...
IM_API_KEY=...
```

如果启用 `-bm`，还需要配置 BM 模型：

```text
BM_MODEL_NAME=...
BM_BASE_URL=...
BM_API_KEY=...
```

## 运行

示例：LLM 对战内置 AI，并启用 BM 后台战略模型。

```bash
python main.py \
    --map_name Flat32 \
    --difficulty Hard \
    --ai_build RandomBuild \
    --own_race Terran \
    --enemy_race Terran \
    -bm
```

默认情况下，IM 的 JSON 输出不包含 `predicted_observation` 字段。如果需要恢复预测观测输出和对应校验，添加 `-observation`：

```bash
python main.py \
    --map_name Flat32 \
    --difficulty Hard \
    --ai_build RandomBuild \
    --own_race Terran \
    --enemy_race Terran \
    -bm \
    -observation
```

查看参数：

```bash
python main.py --help
```

## 当前目录结构

| 路径 | 说明 |
|---|---|
| `main.py` | 兼容入口，只调用 `cli.main()`。 |
| `cli.py` | 解析命令行参数、读取环境变量、创建 LLM client、启动 SC2 game。 |
| `player.py` | IM/BM 主玩家循环：自动逻辑、IM 同步动作、BM 异步调度、指令读取和动作执行。 |
| `agents/` | IM/BM agent 类和 `agents/prompts/` prompt builder。 |
| `game/` | 游戏侧逻辑，包括 player adapter、观测、动作、校验、自动逻辑和建议系统。 |
| `runtime/` | 运行时横切模块：BM/IM directive、日志封装、指标统计。 |
| `knowledge/` | 静态知识加载：能力表、SC2 API 数据、ability 描述。 |
| `config/` | 环境变量、生成参数和 SC2 枚举配置。 |
| `utils/` | LLM client、格式化和通用工具函数。 |
| `docs/` | 架构说明、文件说明、改造记录和图片资源。 |
| `archive/` | 历史 SunTzu 代码、旧脚本、tokenizer 工具和缓存归档。 |

## 核心模块分层

`agents/`：

- `agents/immediate.py`：IM 调用、输出解析、schema/action refine。
- `agents/background.py`：BM 调用、plan critic/refine。
- `agents/prompts/`：IM/BM prompt 字符串和 prompt builder；IM 预测观测 schema 由 `-observation` 控制。

`game/`：

- `game/base_player.py`：底层 player adapter，挂接观测、动作、校验等功能。
- `game/llm_player.py`：LLM player adapter，挂接自动逻辑和建议系统。
- `game/observation/`：观测文本构造。
- `game/actions/`：动作执行和建筑落点查找。
- `game/verifier/`：动作 schema、资源、单位、target 和 ability 校验。
- `game/automation/`：自动工人、MULE、自动还击和早期 SCV 防守。
- `game/suggestions/`：全局建议和 Terran / Protoss / Zerg 种族建议。

`runtime/`：

- `runtime/directive.py`：BM 到 IM 的线程安全指令传递。
- `runtime/logging.py`：运行日志封装。
- `runtime/metrics.py`：迭代指标统计。

## 验证命令

静态编译：

```bash
python -m compileall main.py cli.py player.py agents game config utils runtime knowledge
```

轻量入口检查：

```bash
python main.py --help
```

轻量 import 检查：

```bash
python -c "import cli, agents.immediate, agents.background, game; print('imports-ok')"
```

完整游戏运行需要安装 StarCraft II、地图包和 Python SC2 相关依赖。

## 运行日志

每局日志写入对应的 `logs/.../<model>/<timestamp>/` 目录：

- `overview.json`：对局设置、最终胜负和 SBR/RUR，以及 IM/BM 调用计数。
- `metrics.jsonl`：每 10 tick 的数值局面快照；BM 触发时追加同结构快照，供离线筛选训练时间步。
- `obs/`：每次 IM 决策时的真实观测文本。
- `im/`：IM 的原始请求/回复、schema 与动作 verifier 结果、最终动作。
- `bm/`：BM 的原始请求/回复、critic 结果、最终 Directive，以及取消或异常记录。
- `run.log`：简短的运行摘要、warning 和 error。

原有的混合 `trace.json`、独立 `config.json` 和旧 observation 命名不再生成。

## 文档

- `docs/项目文件说明.md`：当前文件和目录职责说明。
- `docs/IMBM_CHANGES.md`：IM/BM 相对旧 SunTzu 的改造说明。
- `docs/架构细节.md`：架构细节补充。
- `docs/fig/`：README 和架构文档使用的图片。

## 归档说明

`archive/` 中的内容保留历史用途，不作为当前主链路维护重点：

- `archive/legacy_suntzu/`：旧 SunTzu agent/player。
- `archive/scripts/`：旧 benchmark、采集、Elo、SFT、GUI、notebook 和日志脚本。
- `archive/tools/`：当前主链路未使用的 tokenizer 相关工具和资源。

## 版权说明

StarCraft II 是 Blizzard Entertainment, Inc. 的商标。本项目与 Blizzard Entertainment 无官方关联。
