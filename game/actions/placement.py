import random

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2


async def find_placement(
    player,
    building,
    near: Point2,
    max_distance: int = 20,
    random_alternative: bool = True,
    placement_step: int = 2,
    addon_place: bool = False,
):
    assert isinstance(building, (AbilityId, UnitTypeId))
    assert isinstance(near, Point2), f"{near} is no Point2 object"
    if isinstance(building, UnitTypeId):
        building_ability = player.game_data.units[building.value].creation_ability.id
    else:
        building_ability = building
    addon_check_ability = None
    if addon_place:
        # 用补给站占位检测 addon 空间，确保人族建筑右侧可用。
        addon_check_ability = player.game_data.units[UnitTypeId.SUPPLYDEPOT.value].creation_ability.id
    if await player.can_place_single(building_ability, near):
        if not addon_place or await player.can_place_single(addon_check_ability, near.offset((2.5, -0.5))):
            return near
    if max_distance == 0:
        return None
    for distance in range(placement_step, max_distance, placement_step):
        # 按方形环逐步扩张搜索，优先找离模型目标点最近的位置。
        possible_positions = [
            Point2(p).offset(near).to2
            for p in (
                [(dx, -distance) for dx in range(-distance, distance + 1, placement_step)]
                + [(dx, distance) for dx in range(-distance, distance + 1, placement_step)]
                + [(-distance, dy) for dy in range(-distance, distance + 1, placement_step)]
                + [(distance, dy) for dy in range(-distance, distance + 1, placement_step)]
            )
        ]

        res = await player.client._query_building_placement_fast(building_ability, possible_positions)
        possible = [p for r, p in zip(res, possible_positions) if r]
        if not possible:
            continue
        if addon_place:
            # 人族主生产建筑还要额外过滤 addon 位置可放的点。
            res = await player.client._query_building_placement_fast(
                addon_check_ability,
                [p.offset((2.5, -0.5)) for p in possible],
            )
            possible = [p for r, p in zip(res, possible) if r]
        if not possible:
            continue
        if random_alternative:
            return random.choice(possible)
        return min(possible, key=lambda p: p.distance_to_point2(near))

    return None
