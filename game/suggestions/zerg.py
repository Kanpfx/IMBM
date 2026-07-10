from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId


def get_zerg_suggestions(player):
    suggestions = []

    if (
        player.supply_left < 3
        and player.supply_cap < 200
        and not player.already_pending(UnitTypeId.OVERLORD)
        and player._can_build(UnitTypeId.OVERLORD)
    ):
        suggestions.append("Supply is low! Morph an Overlord immediately.")

    if (
        player.get_total_amount(UnitTypeId.SPAWNINGPOOL) < 1
        and not player.already_pending(UnitTypeId.SPAWNINGPOOL)
        and player._can_build(UnitTypeId.SPAWNINGPOOL)
    ):
        suggestions.append("A Spawning Pool is required to create Zerglings, build one.")

    if (
        player.structures(UnitTypeId.SPAWNINGPOOL).ready.exists
        and player.get_total_amount(UnitTypeId.QUEEN) < player.townhalls.amount
        and player._can_build(UnitTypeId.QUEEN)
    ):
        suggestions.append("Build a Queen for each Hatchery to inject larva and defend.")

    queens_with_energy = player.units(UnitTypeId.QUEEN).filter(lambda q: q.energy >= 25)
    hatcheries_needing_inject = player.townhalls.ready.filter(lambda h: not h.has_buff(BuffId.QUEENSPAWNLARVATIMER))
    if queens_with_energy.exists and hatcheries_needing_inject.exists:
        suggestions.append("Your Queen has energy! Use 'Inject Larva' on a Hatchery to boost production.")

    if player.get_total_amount(UnitTypeId.EXTRACTOR) < 1 and player._can_build(UnitTypeId.EXTRACTOR):
        suggestions.append("At least one Extractor is necessary for gas collection, consider building one.")

    if (
        player.structures(UnitTypeId.SPAWNINGPOOL).ready.exists
        and player.get_total_amount(UnitTypeId.ZERGLING) < 6
        and player._can_build(UnitTypeId.ZERGLING)
    ):
        suggestions.append("At least 6 Zerglings are necessary for early defense, consider training some.")

    if player.townhalls.amount < 2 and player._can_build(UnitTypeId.HATCHERY):
        suggestions.append("Consider building a second Hatchery to expand your economy and production.")

    if (
        player.structures(UnitTypeId.SPAWNINGPOOL).ready.exists
        and player.get_total_amount(UnitTypeId.ROACHWARREN) == 0
        and player._can_build(UnitTypeId.ROACHWARREN)
    ):
        suggestions.append("Consider building a Roach Warren to unlock Roaches, a strong armored unit.")

    if (
        player.structures(UnitTypeId.ROACHWARREN).ready.exists
        and player.get_total_amount(UnitTypeId.ROACH) < 5
        and player._can_build(UnitTypeId.ROACH)
    ):
        suggestions.append("Roaches are strong against many early units, consider training some.")

    if (
        player.structures(UnitTypeId.SPAWNINGPOOL).ready.exists
        and player.get_total_amount(UnitTypeId.LAIR) == 0
        and player.townhalls(UnitTypeId.HATCHERY).idle.exists
        and player._can_build(UnitTypeId.LAIR)
    ):
        suggestions.append("Upgrade a Hatchery to a Lair to unlock powerful mid-game units and upgrades.")

    if (
        player.structures(UnitTypeId.LAIR).ready.exists
        and player.get_total_amount(UnitTypeId.HYDRALISKDEN) == 0
        and player._can_build(UnitTypeId.HYDRALISKDEN)
    ):
        suggestions.append("Build a Hydralisk Den to unlock Hydralisks, a versatile ranged unit.")

    if player.structures(UnitTypeId.HYDRALISKDEN).ready.exists and player.get_total_amount(UnitTypeId.HYDRALISK) < 5:
        suggestions.append("Consider training Hydralisks to strengthen your army's anti-air and ranged capabilities.")

    zergling_count = player.get_total_amount(UnitTypeId.ZERGLING)
    roach_count = player.get_total_amount(UnitTypeId.ROACH)

    if zergling_count + roach_count > 20:
        roach_supply = roach_count * 2
        zergling_supply = zergling_count * 0.5
        total_supply = roach_supply + zergling_supply

        if total_supply > 0:
            roach_ratio = roach_supply / total_supply
            if roach_ratio < 0.3:
                suggestions.append("Your army is Zergling-heavy. Add Roaches for a stronger frontline.")
            elif roach_ratio > 0.8:
                suggestions.append("Your army is Roach-heavy. Add Zerglings for more DPS and to surround enemies.")

    return suggestions

