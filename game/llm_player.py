from game.automation.mules import deploy_mules, select_best_mineral_for_mule
from game.automation.workers import distribute_workers
from game.base_player import BasePlayer
from runtime.logging import log_current_iteration
from game.suggestions.protoss import get_protoss_suggestions
from game.suggestions.service import collect_suggestions
from game.suggestions.terran import get_terran_suggestions
from game.suggestions.zerg import get_zerg_suggestions


class LLMPlayer(BasePlayer):
    """供 IM/BM 玩家复用自动化、建议和日志能力的 adapter。"""

    def __init__(self, config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)

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
        raise NotImplementedError("LLMPlayer is a shared adapter; use ImBmPlayer for game decisions.")
