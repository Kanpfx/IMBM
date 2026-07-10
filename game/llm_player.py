import random

from archive.legacy_suntzu.agents import ActionAgent, PlanAgent, RagAgent, SingleAgent
from game.automation.combat import auto_combat
from game.automation.mules import deploy_mules, select_best_mineral_for_mule
from game.automation.workers import distribute_workers
from game.base_player import BasePlayer
from runtime.logging import log_current_iteration
from game.suggestions.protoss import get_protoss_suggestions
from game.suggestions.service import collect_suggestions
from game.suggestions.terran import get_terran_suggestions
from game.suggestions.zerg import get_zerg_suggestions


class LLMPlayer(BasePlayer):
    """旧 SunTzu 单模型/Planner 链路的兼容 adapter。"""

    def __init__(self, config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)

        agent_config = {
            "model_name": self.model_name,
            "generation_config": self.generation_config,
            "llm_client": self.llm_client,
        }

        if config.enable_rag:
            self.rag_agent = RagAgent(config.own_race, **agent_config)
        if config.enable_plan or config.enable_plan_verifier:
            self.plan_agent = PlanAgent(config.own_race, **agent_config)
            self.action_agent = ActionAgent(config.own_race, **agent_config)
        else:
            self.agent = SingleAgent(config.own_race, **agent_config)

        self.plan_verifier = "llm" if config.enable_plan_verifier else None
        self.action_verifier = self.verify_actions if self.config.enable_action_verifier else None

        self.next_decision_time = -1
        self.scv_auto_attack_distance = 4
        self.scv_auto_attack_time = 240

    async def distribute_workers(self, resource_ratio: float = 2.0) -> None:
        return await distribute_workers(self, resource_ratio)

    async def _deploy_mules(self, mineral_patches) -> None:
        return await deploy_mules(self, mineral_patches)

    def _select_best_mineral_for_mule(self, mineral_patches, orbital_command):
        return select_best_mineral_for_mule(self, mineral_patches, orbital_command)

    def get_terran_suggestions(self):
        return get_terran_suggestions(self)

    def get_protoss_suggestions(self):
        return get_protoss_suggestions(self)

    def get_zerg_suggestions(self):
        return get_zerg_suggestions(self)

    def get_suggestions(self):
        return collect_suggestions(self)

    def log_current_iteration(self, iteration: int):
        return log_current_iteration(self, iteration)

    async def run(self, iteration: int):
        await self.distribute_workers()
        auto_combat(self)

        # 当前 IM/BM 主链路会在 player.py 覆盖 run；这里保留旧链路行为。
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

            if self.config.enable_plan or self.config.enable_plan_verifier:
                suggestions = self.get_suggestions()
                self.logging("suggestions", suggestions, save_trace=True, print_log=False)

                plans, plan_think, plan_chat_history = self.plan_agent.run(obs_text, verifier=self.plan_verifier, suggestions=suggestions)
                self.logging("plans", plans, save_trace=True)
                self.logging("plan_think", plan_think, save_trace=True, print_log=False)
                self.logging("plan_chat_history", plan_chat_history, save_trace=True, print_log=False)

                actions, action_think, action_chat_history = self.action_agent.run(obs_text, plans, verifier=self.action_verifier)
                self.logging("actions", actions, save_trace=True)
                self.logging("action_think", action_think, save_trace=True, print_log=False)
                self.logging("action_chat_history", action_chat_history, save_trace=True, print_log=False)
            else:
                actions, action_think, action_chat_history = self.agent.run(obs_text, verifier=self.action_verifier)
                self.logging("actions", actions, save_trace=True)
                self.logging("action_think", action_think, save_trace=True, print_log=False)
                self.logging("action_chat_history", action_chat_history, save_trace=True, print_log=False)

            await self.run_actions(actions)

        elif iteration % 10 == 0:
            self.log_current_iteration(iteration)
