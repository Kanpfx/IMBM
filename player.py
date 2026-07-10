from agents import BmAgent, ImAgent
from game.automation.combat import auto_combat
from game.llm_player import LLMPlayer
from runtime.directive import Directive, DirectiveStore

import asyncio
import time
import random


class ImBmPlayer(LLMPlayer):
    """IM/BM 双模型玩家：IM 同步决策，BM 异步生成战略指令。"""

    def __init__(
        self,
        config,
        *args,
        enable_bm=False,
        bm_model_name=None,
        bm_generation_config=None,
        bm_llm_client=None,
        **kwargs,
    ):
        # 跳过 LLMPlayer 的旧 agent 初始化，只复用 BasePlayer 的游戏基础设施。
        from game.base_player import BasePlayer
        BasePlayer.__init__(self, config, *args, **kwargs)

        # IM 直接产出动作，替代旧链路里的 planner + executor。
        im_agent_config = {
            "model_name": self.model_name,
            "generation_config": self.generation_config,
            "llm_client": self.llm_client,
            "include_observation": getattr(config, "observation", False),
        }
        self.include_observation = getattr(config, "observation", False)
        self.im_agent = ImAgent(config.own_race, **im_agent_config)

        # BM 可选开启，后台产出自然语言战略指令。
        self.enable_bm = enable_bm
        self.bm_agent = None
        if enable_bm:
            bm_agent_config = {
                "model_name": bm_model_name,
                "generation_config": bm_generation_config,
                "llm_client": bm_llm_client,
            }
            self.bm_agent = BmAgent(config.own_race, **bm_agent_config)

        # DirectiveStore 是 IM/BM 之间唯一共享状态，避免异步任务直接改主循环。
        self.directive_store = DirectiveStore()

        # 记录正在运行的 BM 任务，防止重复启动或过期指令长期生效。
        self.bm_task = None
        self.bm_task_reason = ""
        self.directive_ttl = 360

        # 这些状态原本由 LLMPlayer 初始化；这里手动补齐。
        self.next_decision_time = -1
        self.scv_auto_attack_distance = 4
        self.scv_auto_attack_time = 240

    def _directive_to_plan_text(self, directive: Directive | None) -> str | None:
        """把 BM 指令转换成 IM prompt 中的 Given Tasks 文本。"""
        if directive is None or not directive.data:
            return None
        items = [f"{i+1}. {cmd}" for i, cmd in enumerate(directive.data)]
        return "### Given Tasks\n" + "\n".join(items)

    def _active_bm_task(self) -> bool:
        return self.bm_task is not None and not self.bm_task.done()

    def _current_iteration(self, fallback: int) -> int:
        try:
            return self.state.game_loop // 4
        except Exception:
            return fallback

    async def _run_bm_background(self, obs_text: str, iteration: int, trigger_reason: str):
        start_time = time.time()
        try:
            loop = asyncio.get_running_loop()
            suggestions = self.get_suggestions()
            # BM 的 LLM 调用放到 executor，避免阻塞 python-sc2 的异步主循环。
            plan_data, bm_think, bm_chat_history = await loop.run_in_executor(
                None,
                lambda: self.bm_agent.run(
                    obs_text=obs_text,
                    background_request=trigger_reason,
                    suggestions=suggestions,
                ),
            )
            # 指令带 TTL，IM 只读取当前 tick 仍然有效的最新结果。
            issued_at_tick = iteration
            valid_until_tick = issued_at_tick + self.directive_ttl
            directive = Directive(
                data=plan_data,
                issued_at_tick=issued_at_tick,
                valid_until_tick=valid_until_tick,
                source="BM",
            )
            self.directive_store.write(directive)
            self.logging("bm_latency", round(time.time() - start_time, 4), save_trace=True)
            self.logging("bm_trigger_reason", trigger_reason, save_trace=True)
            self.logging("bm_plan", plan_data, save_trace=True)
            self.logging("bm_think", bm_think, save_trace=True, print_log=False)
            self.logging("bm_chat_history", bm_chat_history, save_trace=True, print_log=False)
            self.logging("directive", directive.to_dict(), save_trace=True)
        except asyncio.CancelledError:
            self.logging("bm_cancelled", trigger_reason, save_trace=True)
            raise
        except Exception as exc:
            self.logging("bm_error", str(exc), level="error", save_trace=True)

    async def _maybe_start_bm(
        self,
        iteration: int,
        obs_text: str,
        request_background: bool,
        background_reason: str,
        directive_before_im: Directive | None,
        latest_directive: Directive | None,
    ):
        if not self.enable_bm or self.bm_agent is None:
            return

        reasons = []
        if request_background:
            reasons.append("im_request")
        elif latest_directive is None:
            reasons.append("cold_start")
        elif directive_before_im is None or not latest_directive.is_valid(iteration):
            reasons.append("guidance_expired")

        trigger_reason = ",".join(reasons)
        if not trigger_reason:
            return

        if self._active_bm_task():
            if request_background and not self.bm_task_reason.startswith("im_request"):
                # IM 主动请求的优先级更高，可以取消普通后台刷新。
                self.bm_task.cancel()
                self.logging("bm_cancelled_for_im_request", self.bm_task_reason, save_trace=True)
            else:
                self.logging("bm_triggered", False, save_trace=True)
                self.logging("bm_skip_reason", "bm_already_running", save_trace=True)
                return

        if background_reason:
            trigger_reason += f": {background_reason}"

        self.logging("bm_triggered", True, save_trace=True)
        self.logging("bm_trigger_reason", trigger_reason, save_trace=True)
        self.bm_task_reason = trigger_reason
        self.bm_task = asyncio.create_task(
            self._run_bm_background(
                obs_text=obs_text,
                iteration=iteration,
                trigger_reason=trigger_reason,
            )
        )

    async def run(self, iteration: int):
        # 自动经济和基础防守每帧先跑，减少 LLM 决策间隔带来的空转。
        await self.distribute_workers()
        auto_combat(self)

        # 沿用 SunTzu 的决策门控：资源足够且到达间隔时才调用模型。
        if self.config.enable_random_decision_interval:
            decision_iteration = random.randint(24, 36)
            decision_minerals = random.randint(130, 200)
        else:
            decision_iteration = 30
            decision_minerals = 170

        if (
            iteration % decision_iteration == 0
            and self.minerals >= decision_minerals
            or iteration == self.next_decision_time
        ):
            self.next_decision_time = iteration + 9 * decision_iteration

            self.log_current_iteration(iteration)
            obs_text = await self.obs_to_text()

            # 每次 IM 决策前读取一次有效 BM 指令。
            latest_directive = self.directive_store.latest()
            active_directive = self.directive_store.read(iteration)
            plan_text = self._directive_to_plan_text(active_directive)
            directive_age = active_directive.age(iteration) if active_directive else None
            self.logging("directive_age", directive_age, save_trace=True)
            if active_directive:
                self.logging("directive", active_directive.to_dict(), save_trace=True, print_log=False)
                self.logging("plan_text", plan_text, save_trace=True, print_log=False)

            # IM 同步返回动作；动作会在 agent 内经过 schema/refine 和 verifier。
            im_start_time = time.time()
            (
                predicted_observation,
                actions,
                request_background,
                background_reason,
                im_think,
                im_chat_history,
            ) = self.im_agent.run(
                obs_text,
                plan_text=plan_text,
                verifier=self.verify_actions,
            )
            self.logging("im_latency", round(time.time() - im_start_time, 4), save_trace=True)
            if self.include_observation:
                self.logging("predicted_observation", predicted_observation, save_trace=True, print_log=False)
            self.logging("request_background", request_background, save_trace=True)
            self.logging("background_reason", background_reason, save_trace=True)
            self.logging("actions", actions, save_trace=True)
            self.logging("im_think", im_think, save_trace=True, print_log=False)
            self.logging("im_chat_history", im_chat_history, save_trace=True, print_log=False)

            # 执行动作前仍会在 BasePlayer wrapper 内做最终校验。
            await self.run_actions(actions)

            # 决策结束后根据 IM 请求或指令过期情况触发 BM。
            await self._maybe_start_bm(
                iteration=iteration,
                obs_text=obs_text,
                request_background=request_background,
                background_reason=background_reason,
                directive_before_im=active_directive,
                latest_directive=latest_directive,
            )

        elif iteration % 10 == 0:
            self.log_current_iteration(iteration)
