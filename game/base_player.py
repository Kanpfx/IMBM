import json
import os
import time

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units

from game.actions.executor import execute_actions
from game.actions.placement import find_placement as find_building_placement
from knowledge.abilities import get_ability_desc as build_ability_desc
from game.observation.abilities import abilities_to_text as build_abilities_text
from game.observation.builder import build_observation_text
from game.observation.map_info import action_history_to_text, gas_to_text, miner_to_text, round_state_to_text
from game.observation.units import structures_to_text as build_structures_text
from game.observation.units import unit_state_to_text as build_unit_state_text
from game.observation.units import unit_to_text as build_unit_text
from game.observation.units import units_to_text as build_units_text
from runtime.metrics import IterativeMean
from utils.format import extract_first_number
from utils.logger import setup_logger
from game.verifier.action_verifier import check_action as validate_action
from game.verifier.action_verifier import verify_actions as validate_actions


class BasePlayer(BotAI):
    """BotAI 的薄封装：统一日志、短 ID 映射，并挂接各功能模块。"""

    def __init__(self, config, player_name, model_name, generation_config, llm_client, log_path="logs", enable_logging=True):
        super().__init__()

        self.config = config
        self.player_name = player_name
        self.model_name = model_name
        self.generation_config = generation_config
        self.llm_client = llm_client
        map_size = str(extract_first_number(config.map_name))
        self.map_name = f"{map_size}x{map_size}"

        time_str = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
        self.real_model_name = self.model_name.split("/")[-1]

        self.enable_logging = enable_logging
        if enable_logging:
            self.log_path = f"{log_path}/{self.real_model_name}/{time_str}"
            os.makedirs(f"{self.log_path}/observation", exist_ok=True)
            self.logger = setup_logger(f"{player_name}_{self.real_model_name}", log_dir=self.log_path)

        self._tag_to_id = {}
        self._id_to_tag = {}
        self._id_to_abilities = {}
        self.next_id = 1

        # LLM 只看到短 ID，不直接暴露 python-sc2 的长 tag。
        self.last_action = []
        self.trace = {}
        self.tag_to_health = {}

        self.sbr = IterativeMean()
        self.resource_cost = 0

        self.miner_units = ["SCV", "Probe", "Drone"]

    def logging(self, key: str, value, level="info", save_trace=False, save_file=False, print_log=True):
        if not self.enable_logging:
            return
        idx = self.state.game_loop // 4
        if level in ["info", "warning", "error"] and print_log:
            text = f"({idx}) {key}: {str(value)}"
            if level == "info":
                self.logger.info(text)
            elif level == "warning":
                self.logger.warning(text)
            elif level == "error":
                self.logger.error(text)

        if save_trace:
            # trace.json 按游戏 tick 聚合，便于复盘每轮模型决策。
            if idx not in self.trace:
                self.trace[idx] = {}
            self.trace[idx][key] = value
            if idx % 500 == 0:
                with open(f"{self.log_path}/trace.json", "w", encoding="utf-8") as f:
                    json.dump(self.trace, f, indent=2, ensure_ascii=False)

        if save_file:
            with open(f"{self.log_path}/observation/{idx}-{key}.txt", "w", encoding="utf-8") as f:
                if isinstance(value, list) or isinstance(value, dict):
                    value = json.dumps(value, indent=2, ensure_ascii=False)
                f.write(value)

    async def on_end(self, game_result):
        game_result = game_result.name
        self.logging("game_result", game_result, save_trace=True)
        self.logging("SBR", round(self.sbr.mean, 4), save_trace=True)

        time_cost = self.time_formatted.split(":")
        time_cost = int(time_cost[0]) * 60 + int(time_cost[1])
        self.logging("time_cost", time_cost, save_trace=True)
        self.logging("RUR", round(self.resource_cost / time_cost, 4), save_trace=True)

        with open(f"{self.log_path}/trace.json", "w", encoding="utf-8") as f:
            json.dump(self.trace, f, indent=2, ensure_ascii=False)

    def update_tag_to_health(self):
        self.tag_to_health = {unit.tag: unit.health for unit in self.units}
        self.tag_to_health.update({unit.tag: unit.health for unit in self.structures})

    def get_lowest_health_enemy(self, units: Units):
        if not units.exists:
            return None
        return min(units, key=lambda unit: unit.health + unit.shield)

    def _can_build(self, unit_type):
        return self.can_afford(unit_type) and not self.already_pending(unit_type)

    def get_total_amount(self, unit_type: UnitTypeId):
        unit_amount = self.units(unit_type).amount
        structures_amount = self.structures(unit_type).amount
        pending_amount = self.already_pending(unit_type)
        return unit_amount + structures_amount + pending_amount

    async def on_step(self, iteration: int):
        if len(self.units) == 0 or len(self.townhalls) == 0:
            return
        # 供给阻塞比例是实验指标之一，每帧先更新。
        self.sbr.update(int(self.supply_used == self.supply_cap))

        await self.run(iteration)

        if iteration % 15 == 0:
            self.update_tag_to_health()

    async def run(self, iteration: int):
        raise NotImplementedError

    def verify_actions(self, actions):
        # 保留类方法接口，实际校验逻辑放在 game.verifier。
        return validate_actions(self, actions)

    def check_action(self, action: dict):
        return validate_action(self, action)

    def get_building_units(self):
        building_units = []
        for unit in self.units:
            if unit.build_progress < 1.0:
                building_units.append(unit)
        return [unit.name for unit in building_units]

    def tag_to_id(self, tag: int):
        if tag not in self._tag_to_id:
            # 短 ID 取 tag 末三位并处理冲突，兼顾可读性和稳定性。
            next_id = tag % 1000
            while next_id in self._id_to_tag:
                next_id = (next_id + 1) % 1000
            self._tag_to_id[tag] = next_id
            self._id_to_tag[next_id] = tag
        return self._tag_to_id[tag]

    def id_to_tag(self, _id: int):
        return self._id_to_tag[_id]

    def get_unit_by_tag(self, tag: int):
        return self.all_units.find_by_tag(tag)

    def get_unit_by_id(self, _id: int):
        tag = self.id_to_tag(_id)
        return self.get_unit_by_tag(tag)

    async def find_placement(
        self,
        building,
        near,
        max_distance: int = 20,
        random_alternative: bool = True,
        placement_step: int = 2,
        addon_place: bool = False,
    ):
        return await find_building_placement(
            self,
            building,
            near,
            max_distance=max_distance,
            random_alternative=random_alternative,
            placement_step=placement_step,
            addon_place=addon_place,
        )

    async def run_actions(self, actions):
        # 保留类方法接口，实际执行逻辑放在 game.actions。
        return await execute_actions(self, actions)

    async def obs_to_text(self):
        # 保留类方法接口，实际观测构造放在 game.observation。
        return await build_observation_text(self)

    def get_ability_desc(self, text: str):
        return build_ability_desc(self, text)

    def round_state_to_text(self):
        return round_state_to_text(self)

    def action_history_to_text(self):
        return action_history_to_text(self)

    async def units_to_text(self, units: Units):
        return await build_units_text(self, units)

    async def structures_to_text(self, structures: Units):
        return await build_structures_text(self, structures)

    async def unit_to_text(self, unit):
        return await build_unit_text(self, unit)

    async def abilities_to_text(self, units: Units):
        return await build_abilities_text(self, units)

    def unit_state_to_text(self, unit):
        return build_unit_state_text(self, unit)

    def miner_to_text(self):
        return miner_to_text(self)

    def gas_to_text(self):
        return gas_to_text(self)
