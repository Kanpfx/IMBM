from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId


def get_protoss_suggestions(player):
    suggestions = []

    if (
        player.supply_left < 4
        and not player.already_pending(UnitTypeId.PYLON)
        and player._can_build(UnitTypeId.PYLON)
    ):
        suggestions.append("Supply is low! Build a Pylon immediately.")

    if player.structures.filter(lambda s: not s.is_powered and s.build_progress > 0.1).exists:
         if player._can_build(UnitTypeId.PYLON) and not player.already_pending(UnitTypeId.PYLON):
            suggestions.append("Some of your structures are unpowered! Build a Pylon nearby.")

    if (
        player.get_total_amount(UnitTypeId.PYLON) < 1
        and player._can_build(UnitTypeId.PYLON)
        and not player.already_pending(UnitTypeId.PYLON)
    ):
        suggestions.append("At least one Pylon is necessary for development and power, consider building one.")

    nexus = player.townhalls(UnitTypeId.NEXUS).ready
    if nexus.exists and nexus.first.energy >= 50:
        suggestions.append("Your Nexus has enough energy for Chrono Boost. Use it on the Nexus for more Probes or on a production building.")

    if player.get_total_amount(UnitTypeId.ASSIMILATOR) < 1 and player._can_build(UnitTypeId.ASSIMILATOR):
        suggestions.append("At least one Assimilator is necessary for gas collection, consider building one.")

    if (
        player.structures(UnitTypeId.PYLON).exists
        and player.get_total_amount(UnitTypeId.GATEWAY) < 1
        and player._can_build(UnitTypeId.GATEWAY)
    ):
        suggestions.append("At least one Gateway is necessary for training ground units, consider building one.")

    if (
        player.structures(UnitTypeId.GATEWAY).ready.exists
        and player.get_total_amount(UnitTypeId.CYBERNETICSCORE) < 1
        and player._can_build(UnitTypeId.CYBERNETICSCORE)
    ):
        suggestions.append("A Cybernetics Core is necessary to unlock advanced units like Stalkers, consider building one.")

    cyber_core = player.structures(UnitTypeId.CYBERNETICSCORE).ready
    if (
        cyber_core.exists
        and player.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0
        and player.can_afford(UpgradeId.WARPGATERESEARCH)
    ):
        if cyber_core.idle.exists:
            suggestions.append("Cybernetics Core is ready. Research Warpgate technology to reinforce your army faster.")
        else:
            suggestions.append("Consider researching Warpgate technology when your Cybernetics Core is idle.")

    if (
        player.structures(UnitTypeId.GATEWAY).exists
        and player.get_total_amount(UnitTypeId.ZEALOT) < 2
        and player._can_build(UnitTypeId.ZEALOT)
    ):
        suggestions.append("At least 2 Zealots are necessary for early defense, consider training one.")

    if (
        player.structures(UnitTypeId.CYBERNETICSCORE).ready.exists
        and player.get_total_amount(UnitTypeId.STALKER) < 1
        and player._can_build(UnitTypeId.STALKER)
    ):
        suggestions.append("At least one Stalker is useful for anti-air and kiting, consider training one.")

    gateway_count = player.get_total_amount(UnitTypeId.GATEWAY) + player.get_total_amount(UnitTypeId.WARPGATE)
    if 1 <= gateway_count < 3 and player._can_build(UnitTypeId.GATEWAY):
        suggestions.append("Consider building more Gateways to increase unit production.")

    zealot_count = player.get_total_amount(UnitTypeId.ZEALOT)
    stalker_count = player.get_total_amount(UnitTypeId.STALKER)

    if zealot_count + stalker_count > 10:
        ratio = zealot_count / max(1, stalker_count)
        if ratio > 0.8:
            suggestions.append("Your army has many Zealots. Produce more Stalkers for ranged support.")
        elif ratio < 0.3:
            suggestions.append("Increase Zealot production to create a stronger frontline for your Stalkers.")

    return suggestions

