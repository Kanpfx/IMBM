# why-modified

一个使用大语言模型控制《星际争霸 II》Terran Bot 的实验项目。

项目基于 [raspersc2/why](https://github.com/raspersc2/why) 改造，使用固定版本的
[Ares](https://github.com/AresSC2/ares-sc2) 作为底层框架。

当前运行时仅使用 LLM 决策，不再执行 why 原有的 Opening 脚本。现阶段主要支持
BattleCruiserRush，后续目标是扩展到完整动作空间和多战术对战。

## 控制流程

```text
SC2/Ares 游戏状态
    → 统一观测
    → 模型选择战术阶段并生成具体 Function DSL 动作
    → 动作校验
    → 注册为 Ares Behavior
```

- **模型**：读取游戏观测、完整战术卡和当前动作表，输出阶段及可执行动作。
- **运行时**：负责动作展示、参数校验、实体解析、资源等待和 Behavior 注册。
- **自动化**：每帧处理采矿、补给和基础工人生产，不使用 Ares `MacroPlan`；
  模型可用 `BuildWorkers` 临时覆盖默认的 20 工人目标。

模型产生的其他宏观动作经过统一校验和资源等待后直接注册。需要连续运行的
生产、扩张、采气和升级控制器会保持到下一个模型决策周期。格式、阶段或动作校验错误
不会触发额外模型调用，而是作为反馈加入下一轮模型输入。

## 项目结构

```text
game/           SC2 游戏运行、观测、控制和动作执行
llm/            模型 Agent、Prompt、模型客户端和遥测
config/         环境变量、模型及调度配置
knowledge/      动作目录、战术卡和原始建造表参考
scripts/        实验脚本、Ladder 工具和日志查看器
tests/          单元测试
ares-sc2/       固定版本的 Ares Git 子模块
logs/           每局游戏的观测、模型对话、动作、Replay 和元数据
run.py          本地游戏入口
```

原 why 建造表保留在 `knowledge/terran_builds.yml`，仅作为战术整理参考。
观测压缩和 Group 引用的后续设想见
[`observation_design.md`](observation_design.md)。

## 环境准备

项目要求 Python 3.11 或 3.12。当前开发环境使用 Conda `StarWM`。

初始化 Ares 子模块：

```powershell
git submodule update --init --recursive
```

安装项目依赖：

```powershell
poetry install
```

复制模型配置：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
LLM_MODEL=模型名称
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=API密钥
```

`LLM_KNOWLEDGE_ROOT` 为可选配置，仅在动作和战术目录位于项目外部时使用。

## 运行游戏

默认示例：在 `PylonAIE_v4` 上对抗 VeryHard Terran AI，并使用
BattleCruiserRush 战术。

```powershell
python run.py `
  --map_name IncorporealAIE_v4 `
  --difficulty VeryHard `
  --build_mode RandomBuild `
  --enemy_race Terran `
  --tactic BattleCruiserRush
```

`--build_mode` 指定内置 AI 的建造模式；`--tactic` 指定模型使用的战术卡，
名称对应 `knowledge/llm_tactic_catalog/` 中的 JSON 文件名。

查看全部参数：

```powershell
conda run -n StarWM python run.py --help
```

## 运行测试

```powershell
$env:PYTHONPATH = "$PWD\ares-sc2\src;$PWD\ares-sc2"
conda run -n StarWM python -m unittest discover -s tests -v
```

## 辅助工具

- `scripts/run.sh`：集群任务入口。
- `scripts/run_exp.sh`：启动本地 vLLM 并运行实验。
- `scripts/ladder.py`：Ladder 对局连接工具。
- `scripts/日志查看器.html`：直接在浏览器中打开并选择 `logs/<时间戳>/` 目录，查看观测、模型、动作、事件、元数据和控制台日志。

每局运行结果默认写入 `logs/<时间戳>/`。
