import json
from pathlib import Path

import pandas as pd
from sc2.ids.ability_id import AbilityId


class TargetType:
    NONE = "None"
    POINT = "Point"
    UNIT = "Unit"
    POINT_OR_UNIT = "PointOrUnit"


def load_knowledge():
    # 基于文件所在目录加载资源，避免从不同工作目录启动时报路径错误。
    knowledge_dir = Path(__file__).resolve().parent
    ability_data = pd.read_csv(knowledge_dir / "TerranAbility.csv")
    with open(knowledge_dir / "data.json", "r", encoding="utf-8") as f:
        game_data = json.load(f)

    abilities = {}
    for _, item in ability_data.iterrows():
        ability = item["ability"]
        description = item["description"]
        matching_ability_data = [entry for entry in game_data["Ability"] if entry["name"] == ability]
        if len(matching_ability_data) == 0:
            target = TargetType.NONE
        else:
            target = matching_ability_data[0]["target"]
        # SC2 API 的 target 字段有时是复合结构，这里压成 verifier 使用的简单类型。
        if not isinstance(target, str):
            if "Build" in target:
                target = TargetType.POINT
            elif "BuildOnUnit" in target or "Unit" in target:
                target = TargetType.UNIT
            else:
                target = TargetType.NONE
        abilities[ability] = {
            "enabled": item["enabled"],
            "description": description,
            "target": target,
        }
    return abilities


TerranAbility = load_knowledge()


def get_ability_desc(player, text: str):
    desc = []
    for action in TerranAbility:
        if TerranAbility[action].get("enabled", False) and action in text:
            # 只输出观测中出现过的 ability，避免把整张能力表塞进 prompt。
            action_desc = TerranAbility[action]["description"]
            action_keys = TerranAbility[action]["target"]
            desc.append(f"{action}(target: {action_keys}): {action_desc}")
            try:
                cost = player.units[0]._bot_object.game_data.calculate_ability_cost(AbilityId[action])
                if cost.minerals and cost.vespene:
                    desc[-1] += f" Cost: {cost.minerals} minerals, {cost.vespene} vespene."
                elif cost.vespene:
                    desc[-1] += f" Cost: {cost.vespene} vespene."
                elif cost.minerals:
                    desc[-1] += f" Cost: {cost.minerals} minerals."
            except Exception:
                pass
    return "\n".join(desc)
