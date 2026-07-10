from knowledge.abilities import TerranAbility


async def abilities_to_text(player, units):
    units = [unit for unit in units if unit.build_progress == 1.0]
    n_units = len(units)
    units_ability_ids = await player.get_available_abilities(units, ignore_resource_requirements=True)
    units_ability_names = [[ability_id.name for ability_id in units_ability_ids[i]] for i in range(n_units)]
    unit_hash_table = {}
    for i in range(n_units):
        unit = units[i]
        ability_names = units_ability_names[i]
        ability_names = [name for name in ability_names if name != "NULL_NULL"]
        unknown_abilities = [name for name in ability_names if name not in TerranAbility]
        if unknown_abilities:
            print(f"Unit {unit.name} has unknown abilities: {unknown_abilities}")
            import pdb; pdb.set_trace()
        if unit.name in player.miner_units:
            ability_names = [name for name in ability_names if name not in ["MOVE_MOVE", "ATTACK_ATTACK"]]
        ability_names = [name for name in ability_names if TerranAbility[name].get("enabled", False)]
        player._id_to_abilities[player.tag_to_id(unit.tag)] = ability_names

        unit_hash = unit.name + "|" + ", ".join(ability_names)
        if unit_hash not in unit_hash_table:
            unit_hash_table[unit_hash] = []
        unit_hash_table[unit_hash].append(str(player.tag_to_id(unit.tag)))

    text = ""
    for unit_hash, ids in unit_hash_table.items():
        unit_name, abilities = unit_hash.split("|")
        ids = ", ".join(ids)
        if abilities:
            text += f"{unit_name}[{ids}]: {abilities}\n"

    text = text.strip()
    if not text:
        text = "[Empty]"
    return text

