from sc2.ids.unit_typeid import UnitTypeId


def get_terran_suggestions(player):
    suggestions = []
    if (
        player.supply_left < 5
        and not player.already_pending(UnitTypeId.SUPPLYDEPOT)
        and player._can_build(UnitTypeId.SUPPLYDEPOT)
    ):
        suggestions.append("Supply is low! Build a Supply Depot immediately.")
    if (
        player.get_total_amount(UnitTypeId.SUPPLYDEPOT) < 1
        and player._can_build(UnitTypeId.SUPPLYDEPOT)
        and not player.already_pending(UnitTypeId.SUPPLYDEPOT)
    ):
        suggestions.append("At least one Supply Depot is necessary for development, consider building one.")
    if (
        player.get_total_amount(UnitTypeId.MULE) < 5
        and not player.already_pending(UnitTypeId.MULE)
        and player.townhalls(UnitTypeId.ORBITALCOMMAND).ready.exists
    ):
        suggestions.append("MULE can boost your economy, consider calling one from your Command Center.")
    if player.get_total_amount(UnitTypeId.REFINERY) < 1 and player._can_build(UnitTypeId.REFINERY):
        suggestions.append("At least one Refinery is necessary for gas collection, consider building one.")
    if (
        player.structures(UnitTypeId.SUPPLYDEPOT).exists
        and player.get_total_amount(UnitTypeId.BARRACKS) < 1
        and player.structures(UnitTypeId.SUPPLYDEPOT).ready.exists
    ):
        suggestions.append("At least one Barracks is necessary for attacking units, consider building one.")
    barracks = player.structures(UnitTypeId.BARRACKS).ready
    if (
        barracks.exists
        and player.get_total_amount(UnitTypeId.BARRACKSTECHLAB) < 1
        and player._can_build(UnitTypeId.BARRACKSTECHLAB)
    ):
        if barracks.idle.exists:
            suggestions.append("At least one Barracks Tech Lab is necessary for advanced units, consider building one.")
        else:
            suggestions.append(
                "Consider building a Barracks Tech Lab when one of your Barracks is idle to unlock advanced units."
            )
    if (
        player.structures(UnitTypeId.BARRACKS).ready.exists
        and player.get_total_amount(UnitTypeId.MARINE) < 2
        and player._can_build(UnitTypeId.MARINE)
    ):
        suggestions.append("At least 2 Marines are necessary for defensing, consider training one.")
    if (
        player.structures(UnitTypeId.BARRACKSTECHLAB).ready.exists
        and player.get_total_amount(UnitTypeId.MARAUDER) < 1
        and player._can_build(UnitTypeId.MARAUDER)
    ):
        suggestions.append("At least one Marauder is necessary for defensing, consider training one.")
    if player.get_total_amount(UnitTypeId.BARRACKS) == 1 and player._can_build(UnitTypeId.BARRACKS):
        suggestions.append("Consider building a second Barracks to increase unit production.")
    if (
        player.structures(UnitTypeId.BARRACKS).ready.amount >= 2
        and player.structures(UnitTypeId.BARRACKSTECHLAB).ready.exists
        and player.get_total_amount(UnitTypeId.FACTORY) == 0
        and player._can_build(UnitTypeId.FACTORY)
    ):
        suggestions.append("Consider building a Factory to unlock mechanical units.")
    if (
        player.structures(UnitTypeId.FACTORY).ready.exists
        and player.get_total_amount(UnitTypeId.FACTORYTECHLAB) == 0
        and player._can_build(UnitTypeId.FACTORYTECHLAB)
    ):
        suggestions.append("Consider upgrade Factory Tech Lab to train powerful units.")
    if player.structures(UnitTypeId.FACTORYTECHLAB).ready.exists and player.get_total_amount(UnitTypeId.SIEGETANK) < 3:
        suggestions.append("Consider train Siege Tank to increase your army's firepower.")
    cc = player.townhalls(UnitTypeId.COMMANDCENTER).ready
    if cc.exists:
        main_cc = cc.first
        if main_cc.is_idle and player._can_build(UnitTypeId.ORBITALCOMMAND) and player.get_total_amount(UnitTypeId.SCV) >= 16:
            suggestions.append("Upgrade Command Center to Orbital Command for better economy.")
    if (
        player.get_total_amount(UnitTypeId.ORBITALCOMMAND) == 1
        and player.get_total_amount(UnitTypeId.COMMANDCENTER) == 0
        and player._can_build(UnitTypeId.COMMANDCENTER)
    ):
        suggestions.append("Consider building another Command Center to expand your base at another resource location.")

    marine_count = player.get_total_amount(UnitTypeId.MARINE)
    marauder_count = player.get_total_amount(UnitTypeId.MARAUDER)

    if marine_count + marauder_count > 10:
        ratio = marauder_count / max(1, marine_count)
        if ratio < 0.5:
            suggestions.append("Increase Marauder production for better tanking.")
        elif ratio > 2.5:
            suggestions.append("Produce more Marines for DPS against light units.")

    return suggestions

