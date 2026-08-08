import unittest

from agents.prompts import im_messages
from config.game import GameConfig
from config.policy import PHASE_ACTIONS
from core.action_exposure import BCRushActionExposure
from core.policy import PolicyValidator
from knowledge.loader import ActionCatalog
from runtime.resolver import EntityContext


class Unit:
    def __init__(
        self,
        name,
        *,
        ready=True,
        idle=False,
        abilities=(),
        has_techlab=False,
    ):
        self.type_id = type("Type", (), {"name": name})()
        self.is_ready = ready
        self.is_idle = idle
        self.abilities = [type("Ability", (), {"name": item})() for item in abilities]
        self.has_techlab = has_techlab


class Bot:
    def __init__(self, tech_progress=None, *, bc_ready=False):
        self._tech_progress = tech_progress or {}
        self._bc_ready = bc_ready
        self.townhalls = [object()]
        self.gas_buildings = []
        self.mediator = type("Mediator", (), {"get_own_expansions": [object()]})()

    def tech_requirement_progress(self, unit_type):
        return self._tech_progress.get(unit_type.name, 0.0)

    def tech_ready_for_unit(self, unit_type):
        return unit_type.name == "BATTLECRUISER" and self._bc_ready


def all_bc_action_ids():
    return set().union(*PHASE_ACTIONS.values())


class ActionExposureTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ActionCatalog.load()
        self.exposure = BCRushActionExposure(self.catalog)

    def test_opening_surface_keeps_frontier_and_hides_unavailable_late_actions(self):
        context = EntityContext(
            own_entities={
                "1": Unit("SCV"),
                "2": Unit("COMMANDCENTER", idle=True),
                "3": Unit("MARINE"),
            },
            enemy_entities={"9": Unit("ZERGLING")},
            positions={"main": object(), "enemy_main": object()},
            grids={"ground": object(), "air": object()},
        )
        bot = Bot(
            {
                "SUPPLYDEPOT": 1.0,
                "BARRACKS": 0.0,
                "FACTORY": 0.0,
                "ORBITALCOMMAND": 0.0,
            }
        )

        surface = self.exposure.build(bot, context, all_bc_action_ids())

        self.assertIn("macro.build_structure", surface.action_ids)
        self.assertIn("macro.tech_up", surface.action_ids)
        self.assertIn("combat.individual.a_move", surface.action_ids)
        self.assertNotIn("macro.spawn_controller", surface.action_ids)
        self.assertNotIn("combat.group.a_move_group", surface.action_ids)
        self.assertNotIn("combat.bc.move_safely", surface.action_ids)
        self.assertNotIn("combat.bc.tactical_jump", surface.action_ids)
        self.assertEqual(
            surface.parameter_domains["macro.build_structure"]["structure_id"],
            frozenset({"SUPPLYDEPOT"}),
        )
        self.assertEqual(
            surface.parameter_domains["macro.tech_up"]["desired_tech"],
            frozenset({"FACTORY"}),
        )

        prompt = im_messages("# Observation", [], surface.entries)[-1]["content"]
        self.assertIn("Availability [development frontier]", prompt)
        self.assertIn("Allowed now: SUPPLYDEPOT", prompt)
        self.assertIn("Current actors: [3]", prompt)

    def test_completed_bc_tech_exposes_bc_group_spawn_and_jump_actions(self):
        context = EntityContext(
            own_entities={
                "1": Unit("SCV"),
                "2": Unit("COMMANDCENTER", idle=True),
                "3": Unit("MARINE"),
                "4": Unit("MARINE"),
                "5": Unit(
                    "BATTLECRUISER", abilities=("EFFECT_TACTICALJUMP",)
                ),
                "6": Unit("BARRACKS"),
                "7": Unit("FACTORY"),
                "8": Unit("STARPORT", has_techlab=True),
                "10": Unit("FUSIONCORE"),
                "11": Unit("STARPORTTECHLAB"),
            },
            enemy_entities={"9": Unit("ZERGLING")},
            positions={"main": object(), "enemy_main": object()},
            grids={"ground": object(), "air": object()},
        )
        bot = Bot(
            {
                "SUPPLYDEPOT": 1.0,
                "BARRACKS": 1.0,
                "FACTORY": 1.0,
                "STARPORT": 1.0,
                "FUSIONCORE": 1.0,
                "ORBITALCOMMAND": 1.0,
            },
            bc_ready=True,
        )

        surface = self.exposure.build(bot, context, all_bc_action_ids())

        self.assertIn("macro.spawn_controller", surface.action_ids)
        self.assertIn("combat.group.a_move_group", surface.action_ids)
        self.assertIn("combat.bc.move_safely", surface.action_ids)
        self.assertIn("combat.bc.tactical_jump", surface.action_ids)
        self.assertEqual(
            surface.parameter_domains["combat.bc.tactical_jump"]["unit"],
            frozenset({"5"}),
        )
        self.assertEqual(
            surface.parameter_domains["macro.spawn_controller"]
            ["army_composition_dict"],
            frozenset({"MARINE", "BATTLECRUISER"}),
        )
        self.assertEqual(
            surface.parameter_domains["macro.tech_up"]["desired_tech"],
            frozenset({"BATTLECRUISER"}),
        )

    def test_policy_reuses_surface_domains_for_action_and_argument_validation(self):
        context = EntityContext(
            own_entities={
                "1": Unit("SCV"),
                "2": Unit("COMMANDCENTER", idle=True),
                "3": Unit("MARINE"),
            },
            enemy_entities={"9": Unit("ZERGLING")},
            positions={"main": type("Point", (), {"x": 1, "y": 1})()},
            grids={"ground": object()},
        )
        bot = Bot({"SUPPLYDEPOT": 1.0, "FACTORY": 0.0})
        surface = self.exposure.build(bot, context, all_bc_action_ids())
        validator = PolicyValidator(self.catalog, GameConfig())

        review = validator.review(
            bot,
            [
                {
                    "id": "BuildStructure",
                    "args": {"base_location": "main", "structure_id": "FACTORY"},
                },
                {
                    "id": "TacticalJump",
                    "args": {"unit": "3", "target": "main"},
                },
            ],
            context,
            "bc_pressure",
            surface,
        )

        self.assertFalse(review.accepted)
        self.assertEqual(len(review.issues), 2)
        self.assertIn("structure_id is not currently available", review.message)
        self.assertIn("not currently available", review.message)
