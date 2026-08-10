import unittest

from agents.prompts import im_messages
from config.game import GameConfig
from core.action_exposure import ActionExposure
from core.policy import PolicyValidator
from knowledge.loader import ActionCatalog
from runtime.resolver import EntityContext


class Unit:
    def __init__(
        self,
        name,
        *,
        abilities=(),
        is_structure=False,
        has_cargo=False,
    ):
        self.type_id = type("Type", (), {"name": name})()
        self.abilities = [type("Ability", (), {"name": item})() for item in abilities]
        self.is_structure = is_structure
        self.has_cargo = has_cargo


class ActionExposureTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ActionCatalog.load()
        self.exposure = ActionExposure(self.catalog)

    def test_surface_uses_live_entities_instead_of_a_tactical_phase(self):
        context = EntityContext(
            own_entities={
                "1": Unit("SCV"),
                "2": Unit("COMMANDCENTER", is_structure=True),
                "3": Unit("MARINE"),
            },
            enemy_entities={"9": Unit("ZERGLING")},
            positions={"main": object(), "enemy_main": object()},
            grids={"ground": object()},
        )

        surface = self.exposure.build(object(), context)

        self.assertIn("macro.build_structure", surface.action_ids)
        self.assertIn("macro.expansion_controller", surface.action_ids)
        self.assertIn("macro.tech_up", surface.action_ids)
        self.assertIn("combat.individual.a_move", surface.action_ids)
        self.assertIn("combat.individual.attack_target", surface.action_ids)
        self.assertNotIn("combat.bc.tactical_jump", surface.action_ids)
        self.assertNotIn("combat.individual.ghost_snipe", surface.action_ids)
        self.assertNotIn("macro.spawn_controller", surface.action_ids)

    def test_actor_ability_group_and_production_requirements_are_dynamic(self):
        context = EntityContext(
            own_entities={
                "1": Unit("REAPER"),
                "2": Unit(
                    "BATTLECRUISER", abilities=("EFFECT_TACTICALJUMP",)
                ),
                "3": Unit("MARINE"),
                "4": Unit("STARPORT", is_structure=True),
            },
            enemy_entities={"9": Unit("ZERGLING")},
            positions={"main": object(), "enemy_main": object()},
            grids={"ground": object(), "air": object()},
        )

        surface = self.exposure.build(object(), context)

        self.assertIn("combat.individual.reaper_grenade", surface.action_ids)
        self.assertIn("combat.bc.tactical_jump", surface.action_ids)
        self.assertIn("combat.group.a_move_group", surface.action_ids)
        self.assertIn("macro.spawn_controller", surface.action_ids)
        self.assertNotIn("combat.individual.ghost_snipe", surface.action_ids)
        self.assertEqual(
            surface.parameter_domains["combat.bc.tactical_jump"]["unit"],
            frozenset({"2"}),
        )

    def test_enemy_dependent_actions_are_hidden_without_visible_enemies(self):
        context = EntityContext(
            own_entities={"1": Unit("MARINE")},
            positions={"main": object(), "enemy_main": object()},
        )

        surface = self.exposure.build(object(), context)

        self.assertIn("combat.individual.a_move", surface.action_ids)
        self.assertNotIn("combat.individual.attack_target", surface.action_ids)
        self.assertNotIn(
            "combat.individual.shoot_target_in_range", surface.action_ids
        )

    def test_group_actions_require_at_least_two_current_units(self):
        one = EntityContext(own_entities={"1": Unit("MARINE")})
        two = EntityContext(
            own_entities={"1": Unit("MARINE"), "2": Unit("REAPER")},
            positions={"main": object()},
        )

        self.assertNotIn(
            "combat.group.a_move_group",
            self.exposure.build(object(), one).action_ids,
        )
        self.assertIn(
            "combat.group.a_move_group",
            self.exposure.build(object(), two).action_ids,
        )

    def test_policy_acceptance_no_longer_depends_on_phase(self):
        point = type("Point", (), {"x": 1, "y": 1})()
        unit = Unit("SCV")
        unit.tag = 1
        context = EntityContext(
            own_entities={"1": unit},
            positions={"main": point},
        )
        surface = self.exposure.build(object(), context)
        validator = PolicyValidator(self.catalog, GameConfig())
        action = {"id": "AMove", "args": {"unit": "1", "target": "main"}}

        opening = validator.review(
            None, [action], context, "opening_tech", surface
        )
        unrelated = validator.review(
            None, [action], context, "some_other_tactic_phase", surface
        )

        self.assertTrue(opening.accepted, opening.message)
        self.assertTrue(unrelated.accepted, unrelated.message)

    def test_prompt_still_exposes_required_parameters_only(self):
        context = EntityContext(
            own_entities={
                "1": Unit("SCV"),
                "2": Unit("COMMANDCENTER", is_structure=True),
            },
            positions={"main": object()},
        )
        surface = self.exposure.build(object(), context)

        prompt = im_messages("# Observation", [], surface.entries)[-1]["content"]

        self.assertIn("`BuildStructure(base_location: Point, structure_id: UnitType)`", prompt)
        self.assertNotIn("`max_on_route`", prompt)
