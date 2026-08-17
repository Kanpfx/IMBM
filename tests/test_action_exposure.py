import unittest

from config.game import GameConfig
from game.actions.exposure import ActionExposure
from game.actions.policy import PolicyValidator
from game.actions.resolver import EntityContext
from knowledge.loader import ActionCatalog
from llm.agents.prompts import im_messages


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
                "2": Unit("BATTLECRUISER", abilities=("EFFECT_TACTICALJUMP",)),
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

    def test_transport_actions_only_expose_supported_containers(self):
        context = EntityContext(
            own_entities={
                "1": Unit("MARINE"),
                "2": Unit("MEDIVAC"),
                "3": Unit("NYDUSNETWORK", is_structure=True, has_cargo=True),
            },
            positions={"main": object()},
            grids={"ground": object()},
        )

        surface = self.exposure.build(object(), context)

        self.assertEqual(
            surface.parameter_domains["combat.individual.pick_up_cargo"]["unit"],
            frozenset({"2"}),
        )
        self.assertEqual(
            surface.parameter_domains["combat.individual.pick_up_and_drop_cargo"][
                "unit"
            ],
            frozenset({"2"}),
        )
        self.assertEqual(
            surface.parameter_domains["combat.individual.drop_cargo"]["unit"],
            frozenset({"3"}),
        )

    def test_spawn_controller_catalog_lists_actual_production_sources(self):
        entry = self.catalog.get("macro.spawn_controller")

        self.assertEqual(
            set(entry["availability"]["types"]),
            {
                "BARRACKS",
                "FACTORY",
                "STARPORT",
                "GATEWAY",
                "WARPGATE",
                "ROBOTICSFACILITY",
                "STARGATE",
                "HATCHERY",
                "LAIR",
                "HIVE",
                "LARVA",
            },
        )

    def test_enemy_dependent_actions_are_hidden_without_visible_enemies(self):
        context = EntityContext(
            own_entities={"1": Unit("MARINE")},
            positions={"main": object(), "enemy_main": object()},
        )

        surface = self.exposure.build(object(), context)

        self.assertIn("combat.individual.a_move", surface.action_ids)
        self.assertNotIn("combat.individual.attack_target", surface.action_ids)
        self.assertNotIn("combat.individual.shoot_target_in_range", surface.action_ids)

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

    def test_policy_acceptance_has_no_phase_input(self):
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

        review = validator.review(None, [action], context, surface)

        self.assertTrue(review.accepted, review.message)

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

        self.assertIn(
            "`BuildStructure(base_location: Point, structure_id: UnitType)`", prompt
        )
        self.assertNotIn("`max_on_route`", prompt)

    def test_prompt_lists_live_candidates_once_in_argument_types(self):
        context = EntityContext(
            own_entities={
                "497": Unit("SCV"),
                "641": Unit("SCV"),
                "12": Unit("MARINE"),
                "353": Unit("COMMANDCENTER", is_structure=True),
            },
            enemy_entities={"99": Unit("ZERGLING")},
            positions={"main": object(), "enemy_main": object()},
            grids={"ground": object(), "air": object()},
        )
        surface = self.exposure.build(object(), context)

        prompt = im_messages("# Observation", [], surface.entries)[-1]["content"]

        self.assertIn(
            "- `Unit`: One unit or structure ID from the current observation.\n"
            "  - Allowed values: `MARINE[12]`; `SCV[497,641]`; "
            "`enemy ZERGLING[99]`.",
            prompt,
        )
        self.assertNotIn("COMMANDCENTER[353]", prompt)
        self.assertIn("- `Grid`:", prompt)
        self.assertIn("  - Allowed values: `air`, `ground`.", prompt)
        self.assertEqual(prompt.count("SCV[497,641]"), 1)
        self.assertIn("<argument_types>", prompt)
        self.assertIn("</argument_types>", prompt)
        self.assertIn("<available_actions>", prompt)
        self.assertIn("</available_actions>", prompt)
        self.assertNotIn("<action_reference>", prompt)
        self.assertNotIn("Argument types:", prompt)
        self.assertNotIn("Available actions:", prompt)
        self.assertNotIn("Availability [", prompt)
        self.assertNotIn("Current actors:", prompt)
        self.assertNotIn("Current group candidates:", prompt)
        self.assertNotIn(
            "  - `unit` (Unit): The unit that will attack-move. Allowed:", prompt
        )
