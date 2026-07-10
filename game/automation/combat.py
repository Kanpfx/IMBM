from sc2.ids.unit_typeid import UnitTypeId


def auto_combat(player):
    for unit in player.units:
        if unit.type_id in [UnitTypeId.MULE] or unit.is_constructing_scv:
            continue
        enemies_in_range = player.enemy_units.in_attack_range_of(unit)
        if enemies_in_range.exists:
            # 有射程内敌人时自动集火最低血量目标。
            target = player.get_lowest_health_enemy(enemies_in_range)
            if target:
                unit.attack(target)
        else:
            # 前期只允许基地附近 SCV 自动防守，避免工人被远程拉走。
            near_by_enemies = player.enemy_units.closer_than(player.scv_auto_attack_distance, unit.position)
            near_by_enemies = near_by_enemies.closer_than(player.scv_auto_attack_distance, player.start_location)
            target_enemy = player.get_lowest_health_enemy(near_by_enemies)
            if unit.type_id in [UnitTypeId.SCV] and player.time < player.scv_auto_attack_time and target_enemy:
                unit.attack(target_enemy)
