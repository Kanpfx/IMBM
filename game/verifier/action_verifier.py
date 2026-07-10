import json

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from knowledge.abilities import TargetType, TerranAbility
from utils.format import extract_code
from game.verifier.schemas import BASE_ACTION_KEYS


def verify_actions(player, actions):
    if isinstance(actions, str):
        try:
            actions = json.loads(extract_code(actions))
        except json.JSONDecodeError:
            return False, "Action must be a json list wrapped with triple backticks and without comments"
    if not isinstance(actions, list):
        return False, "Action must be a list"

    errors = []
    cost_minerals, cost_vespene, cost_supply = 0, 0, 0
    # 单个动作先独立校验，再累计资源消耗做整批动作校验。
    for action in actions:
        ok, message_or_cost = check_action(player, action)
        if not ok:
            errors.append(json.dumps(action, indent=2, ensure_ascii=False) + "\n>> Error: " + message_or_cost)
        else:
            cost_minerals += message_or_cost[0]
            cost_vespene += message_or_cost[1]
            cost_supply += message_or_cost[2]

    if player.minerals < cost_minerals:
        errors.append(">>>> Total actions error: minerals is not enough for executing all actions")
    if player.vespene < cost_vespene:
        errors.append(">>>> Total actions error: vespene is not enough for executing all actions")
    if player.supply_left < cost_supply:
        errors.append(">>>> Total actions error: supply is not enough for executing all actions")

    if errors:
        return False, "\n\n".join(errors)
    return True, ""


def check_action(player, action: dict):
    if not isinstance(action, dict):
        return False, "Action must be a dictionary"

    # 先根据 ability 的 target 类型确定 action 应该携带哪些字段。
    for key in BASE_ACTION_KEYS:
        if key not in action:
            return False, f"Missing required key: {key}"
    action_name = action["action"]
    if action_name not in TerranAbility:
        return False, f"Unknown action: {action['action']}"

    target_type = TerranAbility[action_name]["target"]
    if target_type == TargetType.NONE:
        required_keys = BASE_ACTION_KEYS
    elif target_type == TargetType.POINT:
        required_keys = BASE_ACTION_KEYS + ["target_position"]
    elif target_type == TargetType.UNIT:
        required_keys = BASE_ACTION_KEYS + ["target_unit"]
    else:
        required_keys = BASE_ACTION_KEYS

    if target_type != TargetType.POINT_OR_UNIT:
        unused_keys = [key for key in action.keys() if key not in required_keys]
        for key in required_keys:
            if key not in action:
                return False, f"Missing required key: {key}"
    else:
        if "target_position" in action and "target_unit" in action:
            return False, "Cannot have both `target_position` and `target_unit`"
        if "target_position" not in action and "target_unit" not in action:
            return False, "Missing required key: target_position or target_unit"
        unused_keys = [key for key in action.keys() if key not in BASE_ACTION_KEYS + ["target_position", "target_unit"]]
    if unused_keys:
        return False, f"Unused keys: {unused_keys}"

    if not isinstance(action_name, str):
        return False, "`action` must be a string"
    if not (isinstance(action["units"], list) and len(action["units"]) > 0):
        return False, "`units` must be a non-empty list of integers"
    if "target_position" in action:
        if not (
            isinstance(action["target_position"], list)
            and len(action["target_position"]) == 2
            and all(isinstance(i, int) for i in action["target_position"])
        ):
            return False, "`target_position` must be a list of two integers"
    if "target_unit" in action:
        if not isinstance(action["target_unit"], int):
            return False, "`target_unit` must be an integer"
        if action["target_unit"] not in player._id_to_tag:
            return False, f"Unit with id {action['target_unit']} not found"
        target_unit = player.get_unit_by_id(action["target_unit"])
        if target_unit is None:
            return False, f"Unit with id {action['target_unit']} not found"

    if len(action["units"]) == 0:
        return False, "`units` must not be an empty list"
    # LLM 使用短 ID；这里映射回真实单位，并检查单位是否拥有该能力。
    for unit_id in action["units"]:
        if not isinstance(unit_id, int):
            return False, "`units` must be a list of integers"
        if unit_id not in player._id_to_tag:
            return False, f"Unit with id {unit_id} not found"
        if unit_id not in player._id_to_abilities:
            return False, f"Unit with id {unit_id} not found"
        unit = player.get_unit_by_id(unit_id)
        if not unit:
            return False, f"Unit {unit_id} doesn't exist"
        if not unit.is_mine:
            return False, f"Unit {unit_id} is not mine"
        if action_name not in player._id_to_abilities[unit_id]:
            return False, f"[{unit_id}]{unit.name} cannot perform action {action_name}"
        if unit.is_constructing_scv:
            return False, f"[{unit_id}]{unit.name} is constructing, cannot perform other actions"

    if action_name == "TERRANBUILD_SUPPLYDEPOT":
        # 供给充足时拒绝继续补人口建筑，减少低价值动作。
        if player.supply_cap - player.supply_used >= 8:
            return False, "There is still enough supply count, no need to build new Supply Depot."
    if action_name == "PROTOSSBUILD_PYLON":
        if player.supply_cap - player.supply_used >= 8:
            return False, "There is still enough supply count, no need to build new Pylon."
    if action_name == "LARVATRAIN_OVERLORD":
        if player.supply_cap - player.supply_used >= 8:
            return False, "There is still enough supply count, no need to build new Overlord."

    cost = player.calculate_cost(AbilityId[action_name]) * len(action["units"])
    supply_cost = 0
    # 这里校验单动作资源；verify_actions 会继续校验整批动作总资源。
    if player.minerals < cost.minerals:
        return False, f"Minerals is not enough for action {action_name}"
    if player.vespene < cost.vespene:
        return False, f"Vespene is not enough for action {action_name}"
    try:
        supply_cost = player.calculate_supply_cost(AbilityId[action_name]) * len(action["units"])
        if player.supply_left < supply_cost:
            return False, f"Supply is not enough for action {action_name}"
    except KeyError:
        pass

    if player.config.own_race == "Protoss":
        if action_name == "PROTOSSBUILD_PYLON":
            # 水晶塔过近会浪费空间，提前拒绝明显低价值放置。
            pylons = player.units(UnitTypeId.PYLON)
            close_pylons = pylons.closer_than(5, action["target_position"])
            if close_pylons:
                close_pylons_pos = [f"({int(p.position.x)}, {int(p.position.y)})" for p in close_pylons]
                return False, f"Too close to other Pylons at positions: " + ", ".join(close_pylons_pos)

    return True, [cost.minerals, cost.vespene, supply_cost]
