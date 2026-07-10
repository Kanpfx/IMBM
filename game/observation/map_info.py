def round_state_to_text(player):
    text = ""
    text += "Time: {}\n".format(player.time_formatted)
    text += "Race: {}\n".format(player.race.name)
    text += "Minerals: {}\n".format(player.minerals)
    text += "Vespene: {}\n".format(player.vespene)
    text += "Supply army: {}\n".format(player.supply_army)
    text += "Supply workers: {}\n".format(player.supply_workers)
    text += "Supply unused: {}\n".format(player.supply_cap - player.supply_used)
    text += "Map size: {}".format(player.map_name)
    return text.strip()


def action_history_to_text(player):
    if len(player.last_action) == 0:
        return "[Empty]"
    # 只保留最近动作，给模型上下文但不无限膨胀 prompt。
    return "\n".join(player.last_action[-10:])


def miner_to_text(player):
    center = player.start_location
    miners = []
    num_workers = len([unit for unit in player.units if unit.name in player.miner_units])
    # 矿点数量随工人数缩放，避免早期/后期 prompt 长度失衡。
    cloest_miners = player.mineral_field.closest_n_units(center, 100)
    cloest_miners = [mineral for mineral in cloest_miners if mineral.mineral_contents > 0]
    cloest_miners = cloest_miners[: 2 * num_workers]
    for mineral in cloest_miners:
        miners.append(f"[{player.tag_to_id(mineral.tag)}]({int(mineral.position.x)}, {int(mineral.position.y)})")
    if len(miners) == 0:
        return "No mineral fields found"
    return "Closest mineral fields: " + ", ".join(miners)


def gas_to_text(player):
    gases = []
    # 气矿只保留离出生点最近的一批，足够支持扩张和采气判断。
    cloest_gases = player.vespene_geyser.closest_n_units(player.start_location, 100)
    cloest_gases = [gas for gas in cloest_gases if gas.vespene_contents > 0]
    cloest_gases = cloest_gases[:10]
    for gas in cloest_gases:
        gases.append(f"[{player.tag_to_id(gas.tag)}]({int(gas.position.x)}, {int(gas.position.y)})")
    if len(gases) == 0:
        return "No vespene geysers found"
    return "Closest vespene geysers: " + ", ".join(gases)
