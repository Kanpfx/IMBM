def log_current_iteration(player, iteration: int):
    print(f"================ iteration {iteration} ================")
    player.logging("iteration", iteration, save_trace=True)
    player.logging("time_seconds", int(player.time), save_trace=True)
    player.logging("minerals", player.minerals, save_trace=True)
    player.logging("vespene", player.vespene, save_trace=True)

    unit_mineral_value, unit_vespene_value = 0, 0
    for unit in player.units:
        unit_value = player.calculate_unit_value(unit.type_id)
        unit_mineral_value += unit_value.minerals
        unit_vespene_value += unit_value.vespene
    player.logging("unit_mineral_value", unit_mineral_value, save_trace=True)
    player.logging("unit_vespene_value", unit_vespene_value, save_trace=True)

    structure_mineral_value, structure_vespene_value = 0, 0
    for structure in player.structures:
        structure_value = player.calculate_unit_value(structure.type_id)
        structure_mineral_value += structure_value.minerals
        structure_vespene_value += structure_value.vespene
    player.logging("structure_mineral_value", structure_mineral_value, save_trace=True)
    player.logging("structure_vespene_value", structure_vespene_value, save_trace=True)

    player.logging("supply_army", player.supply_army, save_trace=True)
    player.logging("supply_workers", player.supply_workers, save_trace=True)
    player.logging("supply_left", player.supply_left, save_trace=True)
    player.logging("n_structures", len(player.structures), save_trace=True)
    player.logging("n_visible_enemy_units", len(player.enemy_units), save_trace=True)
    player.logging("n_visible_enemy_structures", len(player.enemy_structures), save_trace=True)
    unit_types = set(unit.type_id for unit in player.units)
    structure_types = set(unit.type_id for unit in player.structures)
    player.logging("n_unit_types", len(unit_types), save_trace=True)
    player.logging("n_structure_types", len(structure_types), save_trace=True)

