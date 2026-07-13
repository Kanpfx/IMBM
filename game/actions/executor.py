import json

from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit


async def execute_actions(player, actions):
    for action in actions:
        try:
            # 执行前再次校验，防止模型 refine 后或游戏状态变化造成非法动作。
            action_check_result, action_check_msg = player.check_action(action)
            if not action_check_result:
                action["is_valid"] = False
                action["error"] = action_check_msg
            else:
                for unit_id in action["units"]:
                    ability = AbilityId[action["action"]]
                    target = None
                    curr_unit = player.get_unit_by_id(unit_id)
                    available_abilities = await player.get_available_abilities([curr_unit])
                    assert ability in available_abilities[0], f"Unit {unit_id} cannot perform action {action['action']}"
                    if "target_unit" in action:
                        target = player.get_unit_by_id(action["target_unit"])
                        assert target is not None, f"Unit with id {action['target_unit']} not found"
                    elif "target_position" in action:
                        target = Point2(action["target_position"])
                        # 人族主生产建筑需要给 addon 预留空间。
                        need_addon = ability in [
                            AbilityId.TERRANBUILD_BARRACKS,
                            AbilityId.TERRANBUILD_FACTORY,
                            AbilityId.TERRANBUILD_STARPORT,
                        ]
                        if "BUILD_" in ability.name:
                            # 建筑目标点可能不可放置，交给 placement 做就近修正。
                            target = await player.find_placement(
                                ability,
                                target,
                                max_distance=100,
                                random_alternative=False,
                                addon_place=need_addon,
                            )
                        assert target is not None, f"Invalid target position: {action['target_position']}"
                    curr_unit(ability=ability, target=target)
                    # 在游戏内发送简短动作日志，方便看 replay 时定位模型决策。
                    target_str = "None"
                    if isinstance(target, Unit):
                        target_str = target.name
                    elif isinstance(target, Point2):
                        target_str = f"({int(target.x)}, {int(target.y)})"
                    await player.chat_send(f"{action['action']}({curr_unit.name} -> {target_str})")
                    cost = player.calculate_cost(ability)
                    player.resource_cost += cost.minerals + cost.vespene
        except Exception as e:
            # 单个动作失败不终止整批动作，避免一次错误拖垮本轮决策。
            action["is_valid"] = False
            action["error"] = str(e)

    valid_actions = [action for action in actions if action.get("is_valid", True)]
    player.last_action.extend([json.dumps(action, ensure_ascii=False) for action in valid_actions])
