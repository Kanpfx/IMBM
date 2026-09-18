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
- **运行时**：负责动作展示、参数校验、当前实体解析、持续指令替换和 Behavior 注册。
- **自动化**：每帧处理采矿、补给、维修、MULE、降补给站、既有反地堡侦察和工人生产，
  不使用 Ares `MacroPlan`。工人目标默认 20；模型用 `BuildWorkers` 设置后会持续保留。

模型调用采用单请求在途模式，游戏在等待回复期间继续执行自动化和已有指令。
调用间隔按游戏时间计算，默认约 5.36 秒（原 60 次回调、GameStep=2 的名义间隔）；
没有请求积压或补发。回复在游戏回调中用最新状态校验，再替换同一控制事项的旧指令。
未提及的持续指令保持生效；完全相同的重复指令不额外登记。游戏结束后丢弃未应用回复。

动作状态为 `accepted`（已接受）、`active`（生效中）、`queued`（等待）、`failed`（失败）。
已接受不代表目标已完成；Ares 负责执行时的资源、科技和建造条件判断。
瞬时建造动作缺矿不超过 120、缺气不超过 60 时进入原版延迟队列，等待上限恢复为 180 次游戏回调。
到期退出队列并反馈给模型重新决策，不判为执行失败；初始资源缺口过大则不提交。
重试时若已有同类建造在途，结束对应等待，避免额外建造。TechUp 交给 Ares 推进前置步骤，不按最终单位造价拦截。
Ares 返回 `False` 时记录“未启动新工作”并提供反馈，不一律判失败；格式、实体和执行异常仍会报错。
相同持续指令不重复注册，但记录为仍在生效；日志显示当前有效指令和队列数量。
常规补给由自动化负责，ProductionController 管理生产设施，SpawnController 负责出兵。

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
  --map_name AutomatonLE `
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

### 展示与记录格式

模型提示词、游戏内消息和控制台中的动作统一显示为 `ActionName(argument=value)`。
错误反馈使用“错误原因 + 提交内容”的分条文本；日志查看器也将结构化记录转换为可读字段和 DSL 动作。

内部动作、反馈仍使用字典和列表，日志使用 JSON/JSONL。查看器只在读取文件时解码 JSON，
直接显示字符串中的真实换行，不对反斜杠做全局替换。原始输入和回复保留原样；
DSL 解析支持实际的 LF/CRLF 换行，字面量反斜杠换行会作为格式错误反馈。

### Debug 日志

保留现有 JSONL 文件：`model.jsonl` 按 request、response、parsed、validated 阶段记录，
`accepted_actions.jsonl` 记录最终处理，`events.jsonl` 记录网络尝试和后续执行，`obs.jsonl` 保存原观测，
`console.log` 保留控制台原文和异常堆栈。用 decision_id / attempt_id / action_id 关联决策、重试和指令。
查看器分区展示原始 messages、原始输出、提取结果、校验报告、执行和系统事件；完整 API 响应默认折叠。
tokens 使用服务端 usage，缺失时显示“未提供”；旧日志仍可读取，不补造元数据。
