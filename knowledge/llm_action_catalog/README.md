# Ares v3.9.6 静态动作目录

本目录是项目固定使用的 Ares 接口与动作快照。接口、参数、默认值和源码路径以仓库内的 `ares-sc2` 子模块为准：

- Ares 版本：`3.9.6`
- Git commit：`0ac34b87f9471979f8de19a77020eed2d8693b26`
- 官方文档：https://aressc2.github.io/ares-sc2/api_reference/index.html

官方文档用于接口说明参考；如果文档与固定版本源码或实际实现冲突，以本地 v3.9.6 源码为准。目录中的少数描述因此修正了上游 docstring 的明显错误。

## 保留文件

- `API Reference.json`：`AresBot` 的公开入口、生命周期、查询和运行时命令。
- `Behaviors/Individual Combat Behaviors.json`：单单位战斗 Behavior。
- `Behaviors/Group Combat Behaviors.json`：编组战斗 Behavior。
- `Behaviors/Macro Behaviors.json`：宏观 Behavior。
- `Manager Mediator.json`：`ManagerMediator` 的查询与命令接口；主要供能力审计和观测设计使用，不直接作为 IM 动作。v3.9.6 中大量方法的 Python 签名是 `**kwargs`，表内已根据该版本 API docstring 展开实际关键字参数，并以 `via_kwargs: true` 标识。
- `shared_types.json`：目录参数使用的 JSON 类型约定。

运行时的 `ActionCatalog` 只加载三个 Behavior 文件。`llm_exposure: "eligible"` 的动作才可进入模型动作空间；阶段白名单还会进一步限制实际展示和执行的动作。

## 项目扩展

目录保留两个非 Ares 原生类名的项目动作。它们是对 v3.9.6 Behavior 的固定参数适配：

- `combat.bc.move_safely`：映射到 `PathUnitToTarget`，运行时注入空中路径网格。
- `combat.bc.tactical_jump`：映射到 `UseAbility`，运行时注入 `EFFECT_TACTICALJUMP`。

`macro.upgrade_c_cs` 虽未列入该版本官网 Macro API 章节，但由 v3.9.6 的 `ares.behaviors.macro` 公开导出，且当前 BC Rush 策略需要，因此经过审核后保持可用。

## 条目约定

- `source`：该文件对应的 Ares 版本和提交。
- `api.import`：可导入的 Python 类路径。
- `api.source_path`：相对项目根目录的 v3.9.6 源文件路径。
- `params[].input = "model"`：由模型提供；当前提示只展示必要参数。
- `params[].input = "runtime"`：由适配器注入，模型不可填写。
- `params[].input = "derived"`：由组合器、编组单位或 Behavior 内部状态推导，模型不可填写。
- `params[].via_kwargs = true`：该参数由 `ManagerMediator` 的 `**kwargs` 接收，名称和含义来自 v3.9.6 API 文档。
- `documentation_status`：区分官网已记录、仅源码公开、非公开源码和项目适配动作。
- `kind = "composite_behavior"`：需要手动组合，不能直接按普通动作构造。

## 固定与更新原则

这是一份固定快照，不跟随官网当前版本自动变化。升级 Ares 时，应先更新子模块，再逐项核对公开接口、构造签名、默认值、描述和项目扩展，最后统一更新所有 JSON 的 `source`。至少应验证：

1. 每个 `api.import` 都能从固定环境导入。
2. Behavior 参数与对应类的构造签名一致。
3. 每个 `api.source_path` 都存在于当前仓库。
4. 所有参数类型均在 `shared_types.json` 中定义。
5. 阶段白名单中的动作都存在且为 `eligible`。
6. 项目测试全部通过。
