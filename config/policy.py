"""Small, explicit initial action surface for the BC Rush experiment."""

from __future__ import annotations


COMMON_MACRO = {
    "macro.build_structure",
    "macro.gas_building_controller",
    "macro.tech_up",
    "macro.upgrade_c_cs",
    "macro.production_controller",
    "macro.spawn_controller",
}
COMMON_MICRO = {
    "combat.individual.a_move",
    "combat.individual.attack_target",
    "combat.individual.shoot_target_in_range",
    "combat.individual.stutter_unit_back",
    "combat.individual.stutter_unit_forward",
    "combat.bc.move_safely",
    "combat.bc.tactical_jump",
}
COMBAT_MICRO_ACTIONS = COMMON_MICRO - {
    "combat.bc.move_safely",
    "combat.bc.tactical_jump",
}
COMBAT_UNIT_TYPES = {"BATTLECRUISER", "MARINE"}

PHASE_ACTIONS: dict[str, set[str]] = {
    "opening_factory": COMMON_MACRO,
    "opening_air_tech": COMMON_MACRO,
    "first_battlecruiser": COMMON_MACRO | COMMON_MICRO,
    "bc_pressure": COMMON_MACRO
    | COMMON_MICRO
    | {
        "macro.expansion_controller",
        "combat.group.a_move_group",
        "combat.group.keep_group_safe",
        "combat.group.path_group_to_target",
    },
}


def allowed_actions(phase: str) -> set[str]:
    return PHASE_ACTIONS.get(phase, set())
