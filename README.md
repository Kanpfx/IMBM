# why_modified

一个使用大语言模型控制《星际争霸 II》Terran Bot 的实验项目。

项目基于 [raspersc2/why](https://github.com/raspersc2/why) 改造，使用固定版本的
[Ares](https://github.com/AresSC2/ares-sc2) 作为底层框架，并参考
[Kanpfx/IMBM](https://github.com/Kanpfx/IMBM) 的双模型控制思路。

当前运行时仅使用 LLM 决策，不再执行 why 原有的 Opening 脚本。现阶段主要支持
BattleCruiserRush，后续目标是扩展到完整动作空间和多战术对战。

## 控制流程

```text
SC2/Ares 游戏状态
    → 统一观测
    → BM 生成短期战略指导
    → IM 生成具体 JSON 动作
    → 动作校验与纠错
    → 注册为 Ares Behavior
```

- **BM**：读取游戏观测、战术卡和当前动作表，输出阶段及短期战略指导。
- **IM**：读取同一份观测和 BM 指导，输出可执行的 Ares 动作。
- **运行时**：负责动作展示、参数校验、实体解析、资源等待和 Behavior 注册。
- **自动化**：每帧处理采矿、补给和基础工人生产，不使用 Ares `MacroPlan`；
  IM 可用 `BuildWorkers` 临时覆盖默认的 20 工人目标。

IM 产生的其他宏观动作经过统一校验和资源等待后直接注册。需要连续运行的
生产、扩张、采气和升级控制器会保持到下一个 IM 决策周期。

BM 为可选模块。启用后，第一次 BM 请求会在 IM 启动前完成，后续指导按固定周期异步刷新。

## 项目结构

```text
game/           SC2 游戏运行、观测、控制和动作执行
llm/            BM/IM Agent、Prompt、模型客户端和遥测
config/         环境变量、模型及调度配置
knowledge/      动作目录、战术卡和原始建造表参考
scripts/        实验脚本、Ladder 工具和日志查看器
tests/          单元测试
ares-sc2/       固定版本的 Ares Git 子模块
logs/           每局游戏的观测、模型对话、动作、Replay 和元数据
run.py          本地游戏入口
```

原 why 建造表保留在 `knowledge/terran_builds.yml`，仅作为战术整理参考。

## 环境准备

项目要求 Python 3.11 或 3.12。当前开发环境使用 Conda `StarWM`。

初始化 Ares 子模块：

```powershell
git submodule update --init --recursive
```

复制模型配置：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
LLM_IMBM_MODEL=模型名称
LLM_IMBM_BASE_URL=https://example.com/v1
LLM_IMBM_API_KEY=API密钥
```

`LLM_KNOWLEDGE_ROOT` 为可选配置，仅在动作和战术目录位于项目外部时使用。

## 运行游戏

默认示例：在 `PylonAIE_v4` 上对抗 VeryHard Terran AI，并使用
BattleCruiserRush 战术和 BM。

```powershell
python run.py `
  --map_name IncorporealAIE_v4 `
  --difficulty VeryHard `
  --build_mode RandomBuild `
  --enemy_race Terran `
  --tactic BattleCruiserRush `
  --enable_bm
```

不传入 `--enable_bm` 时，IM 将在没有 BM 指导的情况下独立运行。
`--bm` 和 `-bm` 均为 `--enable_bm` 的别名。

`--build_mode` 指定内置 AI 的建造模式；`--tactic` 指定 BM 使用的战术卡，
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
- `scripts/replay_view.py`：在已激活的 Conda 环境中直接运行后，会启动仅监听
  `127.0.0.1` 的本地日志查看器并自动打开浏览器。选择日志目录时，
  `replay.SC2Replay` 会通过回环地址交给本机 Python 进程，在内存中静态解析；
  不解包地图，也不会向日志目录写入 `replay_view.json`。

  ```powershell
  python scripts/replay_view.py
  ```

  解析器不会启动 StarCraft II；它从 Replay Tracker 事件近似还原单位/建筑状态，
  并从匹配的 `.SC2Map` 读取高度图、可行域和可玩边界。地图默认在所选目录、
  `ares-sc2/tests/maps/` 和项目 `maps/` 下查找；也可以把对应 `.SC2Map` 一起放在
  所选目录里。直接双击纯 HTML 仍可查看普通日志和已有 `replay_view.json`，但受浏览器
  安全限制，无法自行启动 Python Replay 解析器。

  如需兼容旧工作流，仍可显式生成单个 JSON：

  ```powershell
  poetry run python scripts/replay_view.py logs/<时间戳> --map path/to/map.SC2Map
  ```

每局运行结果默认写入 `logs/<时间戳>/`。
