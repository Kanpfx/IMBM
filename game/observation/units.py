import math

from sc2.position import Point2


async def units_to_text(player, units):
    if len(units) == 0:
        return "[Empty]"

    units_text = []

    other_units = units
    if units.first.is_mine:
        # 采矿/自动攻击工人聚合展示，避免 prompt 被大量重复工人淹没。
        for mining_type in player.miner_units:
            mining_judge = lambda unit: unit.name == mining_type and not (unit.is_constructing_scv or unit.is_repairing or unit.is_attacking)
            mining_units = units.filter(mining_judge)
            if len(mining_units) > 0:
                mining_ids = [player.tag_to_id(unit.tag) for unit in mining_units]
                mining_ids = ", ".join(map(str, mining_ids))
                mining_text = f"[{mining_ids}]{mining_type}\nState: collecting resources automatically"
                units_text.append(mining_text)
            other_units = [unit for unit in other_units if not mining_judge(unit)]

            attacking_judge = lambda unit: unit.name == mining_type and unit.is_attacking
            attacking_units = units.filter(attacking_judge)
            if len(attacking_units) > 0:
                attacking_ids = [player.tag_to_id(unit.tag) for unit in attacking_units]
                attacking_ids = ", ".join(map(str, attacking_ids))
                attacking_text = f"[{attacking_ids}]{mining_type}\nState: attacking enemies automatically"
                units_text.append(attacking_text)
            other_units = [unit for unit in other_units if not attacking_judge(unit)]

    distance_to_start = lambda unit: int((unit.position.x - player.start_location.x) ** 2 + (unit.position.y - player.start_location.y) ** 2) // 4
    # 其余单位按离主基地距离排序，给模型稳定的空间阅读顺序。
    other_units = sorted(other_units, key=lambda unit: (distance_to_start(unit), unit.name))
    units_text += [await unit_to_text(player, unit) for unit in other_units]
    units_text = "\n".join(units_text)
    return units_text


async def structures_to_text(player, structures):
    if len(structures) == 0:
        return "[Empty]"
    structures = [s for s in structures]
    sorted_structures = []
    current_x, current_y = player.start_location.x, player.start_location.y
    # 建筑按近邻路径排序，比随机顺序更容易让模型理解基地布局。
    while structures:
        closest_structure = min(structures, key=lambda s: math.sqrt((s.position.x - current_x) ** 2 + (s.position.y - current_y) ** 2))
        sorted_structures.append(closest_structure)
        structures.remove(closest_structure)
        current_x, current_y = closest_structure.position.x, closest_structure.position.y
    return "\n".join([await unit_to_text(player, structure) for structure in sorted_structures])


async def unit_to_text(player, unit):
    text = ""

    if unit.build_progress == 1.0:
        text += f"[{player.tag_to_id(unit.tag)}]{unit.name}\n"
    else:
        text += f"[{player.tag_to_id(unit.tag)}]{unit.name}(building {int(unit.build_progress * 100)}%)\n"
    text += f"Position: ({int(unit.position.x)}, {int(unit.position.y)})\n"

    if unit.build_progress == 1.0:
        if int(unit.health_max) and unit.build_progress == 1.0:
            text += f"Health: {int(unit.health)}/{int(unit.health_max)} ({int(unit.health_percentage * 100)}%)\n"
        if unit.shield_max > 0.0:
            text += f"Shield: {int(unit.shield)}/{int(unit.shield_max)}\n"
        if unit.energy_max > 0.0:
            text += f"Energy: {int(unit.energy)}/{int(unit.energy_max)}\n"
        if unit.is_mine:
            states = unit_state_to_text(player, unit)
            if states:
                text += f"State: {states}\n"

            if unit.is_structure:
                assigned = unit.assigned_harvesters
                ideal = unit.ideal_harvesters
                surplus = unit.surplus_harvesters
                if ideal > 0:
                    if surplus > 0:
                        text += f"Harvesters: {assigned}/{ideal} (no more harvesters accepted, surplus {surplus})\n"
                    elif surplus == 0:
                        text += f"Harvesters: {assigned}/{ideal} (no more harvesters accepted)\n"
                    else:
                        text += f"Harvesters: {assigned}/{ideal}\n"

            production_list = []
            unit_orders = unit.orders
            for unit_order in unit_orders:
                if "Train " in unit_order.ability.friendly_name:
                    production_list.append(unit_order.ability.friendly_name[6:])
            if production_list:
                text += f"Production list: {', '.join(production_list)}\n"
    return text.strip()


def unit_state_to_text(player, unit):
    order_target = unit.order_target or ""
    order_target_name = ""
    if order_target:
        if isinstance(order_target, Point2):
            order_target = f"({int(order_target.x)}, {int(order_target.y)})"
        elif isinstance(order_target, int):
            target_unit = player.get_unit_by_tag(order_target)
            if target_unit:
                order_target_name = player.get_unit_by_tag(order_target).name
                order_target = player.tag_to_id(order_target)

    states = []
    if unit.is_moving:
        if order_target:
            states.append(f"moving to [{order_target}]{order_target_name}")
        else:
            states.append("moving")
    if unit.is_attacking:
        if order_target:
            states.append(f"attacking [{order_target}]{order_target_name}")
        else:
            states.append("attacking")
    if unit.is_repairing:
        if order_target:
            states.append(f"repairing [{order_target}]{order_target_name}")
        else:
            states.append("repairing")

    if unit.is_idle:
        states.append("idle")
    if unit.is_flying:
        states.append("flying")
    if unit.is_transforming:
        states.append("transforming")
    if unit.is_patrolling:
        states.append("patrolling")
    if unit.tag in player.tag_to_health and unit.health < player.tag_to_health[unit.tag]:
        # 通过上一帧血量判断是否正在受击，弥补原始状态字段不足。
        states.append("under attack")

    if unit.is_constructing_scv:
        if order_target:
            states.append(f"constructing [{order_target}]{order_target_name}")
        else:
            states.append("constructing")

    return "|".join(states)
