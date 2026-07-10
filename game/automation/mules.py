from sc2.ids.unit_typeid import UnitTypeId


async def deploy_mules(player, mineral_patches) -> None:
    mule_units = player.units(UnitTypeId.MULE).idle
    for mule in mule_units:
        # 空闲 MULE 只派到附近矿点，避免长距离移动浪费持续时间。
        nearby_minerals = [m for m in mineral_patches if m.distance_to(mule) < 12]
        best_mineral = select_best_mineral_for_mule(player, nearby_minerals, mule)
        if best_mineral:
            mule.gather(best_mineral)


def select_best_mineral_for_mule(player, mineral_patches, orbital_command):
    if not mineral_patches:
        return None

    best_mineral = None
    best_score = -1

    for mineral in mineral_patches:
        score = 0

        # 评分综合剩余矿量、距离和当前采矿拥挤程度。
        resource_weight = mineral.mineral_contents / 1800
        score += resource_weight * 40

        distance_weight = 1 - (mineral.distance_to(orbital_command) / 12)
        score += distance_weight * 20

        current_harvesters = 0
        for unit in player.units:
            if (
                hasattr(unit, "order_target")
                and unit.order_target == mineral.tag
                and unit.type_id in [UnitTypeId.SCV, UnitTypeId.MULE]
            ):
                current_harvesters += 1

        harvester_weight = max(0, 1 - current_harvesters / 4)
        score += harvester_weight * 30

        mule_count = 0
        for unit in player.units.filter(lambda u: u.type_id == UnitTypeId.MULE):
            if hasattr(unit, "order_target") and unit.order_target == mineral.tag:
                mule_count += 1

        if mule_count >= 1:
            # 避免多个 MULE 扎堆同一个矿块。
            score -= 50

        if mineral.mineral_contents < 500:
            score -= 20

        if score > best_score:
            best_score = score
            best_mineral = mineral

    return best_mineral if best_score > 0 else None
