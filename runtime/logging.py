def log_current_iteration(player, iteration: int):
    unit_mineral_value, unit_vespene_value = 0, 0
    for unit in player.units:
        unit_value = player.calculate_unit_value(unit.type_id)
        unit_mineral_value += unit_value.minerals
        unit_vespene_value += unit_value.vespene
    structure_mineral_value, structure_vespene_value = 0, 0
    for structure in player.structures:
        structure_value = player.calculate_unit_value(structure.type_id)
        structure_mineral_value += structure_value.minerals
        structure_vespene_value += structure_value.vespene
    enemy_unit_mineral_value, enemy_unit_vespene_value = 0, 0
    for unit in player.enemy_units:
        unit_value = player.calculate_unit_value(unit.type_id)
        enemy_unit_mineral_value += unit_value.minerals
        enemy_unit_vespene_value += unit_value.vespene
    enemy_structure_mineral_value, enemy_structure_vespene_value = 0, 0
    for structure in player.enemy_structures:
        structure_value = player.calculate_unit_value(structure.type_id)
        enemy_structure_mineral_value += structure_value.minerals
        enemy_structure_vespene_value += structure_value.vespene
    unit_types = set(unit.type_id for unit in player.units)
    structure_types = set(unit.type_id for unit in player.structures)
    return {
        "iteration": iteration,
        "time_seconds": round(float(player.time), 2),
        "minerals": player.minerals,
        "vespene": player.vespene,
        "resource_spent": player.resource_cost,
        "unit_mineral_value": unit_mineral_value,
        "unit_vespene_value": unit_vespene_value,
        "structure_mineral_value": structure_mineral_value,
        "structure_vespene_value": structure_vespene_value,
        "supply_army": player.supply_army,
        "supply_workers": player.supply_workers,
        "supply_used": player.supply_used,
        "supply_cap": player.supply_cap,
        "supply_left": player.supply_left,
        "supply_blocked": int(player.supply_used == player.supply_cap),
        "supply_block_ratio": round(player.sbr.mean, 4),
        "n_units": len(player.units),
        "n_workers": sum(unit.name in player.miner_units for unit in player.units),
        "n_townhalls": len(player.townhalls),
        "n_structures": len(player.structures),
        "n_visible_enemy_units": len(player.enemy_units),
        "n_visible_enemy_structures": len(player.enemy_structures),
        "visible_enemy_unit_mineral_value": enemy_unit_mineral_value,
        "visible_enemy_unit_vespene_value": enemy_unit_vespene_value,
        "visible_enemy_structure_mineral_value": enemy_structure_mineral_value,
        "visible_enemy_structure_vespene_value": enemy_structure_vespene_value,
        "n_unit_types": len(unit_types),
        "n_structure_types": len(structure_types),
    }

