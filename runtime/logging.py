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
    unit_types = set(unit.type_id for unit in player.units)
    structure_types = set(unit.type_id for unit in player.structures)
    return {
        "iteration": iteration,
        "time_seconds": int(player.time),
        "minerals": player.minerals,
        "vespene": player.vespene,
        "unit_mineral_value": unit_mineral_value,
        "unit_vespene_value": unit_vespene_value,
        "structure_mineral_value": structure_mineral_value,
        "structure_vespene_value": structure_vespene_value,
        "supply_army": player.supply_army,
        "supply_workers": player.supply_workers,
        "supply_left": player.supply_left,
        "n_structures": len(player.structures),
        "n_visible_enemy_units": len(player.enemy_units),
        "n_visible_enemy_structures": len(player.enemy_structures),
        "n_unit_types": len(unit_types),
        "n_structure_types": len(structure_types),
    }

