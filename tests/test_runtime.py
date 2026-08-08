import unittest

from knowledge.loader import ActionCatalog
from config.policy import PHASE_ACTIONS
from config.game import GameConfig
from core.policy import PolicyValidator
from runtime.ares_adapter import AresActionAdapter, InstructionError
from runtime.deferred_actions import DeferredActionQueue
from runtime.directive import BMDirective, DirectiveStore
from runtime.resolver import EntityContext
from tools.json_tools import parse_json_object


class RuntimeTests(unittest.TestCase):
    def test_phase_actions_are_all_catalog_eligible(self):
        catalog = ActionCatalog.load()
        for action_ids in PHASE_ACTIONS.values():
            for action_id in action_ids:
                self.assertEqual(catalog.get(action_id)["llm_exposure"], "eligible")
                self.assertIn("availability", catalog.get(action_id))

    def test_adapter_rejects_disabled_catalog_actions(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)

        with self.assertRaisesRegex(InstructionError, "not enabled for LLM output"):
            adapter._validate_shape({"id": "macro.speed_mining", "args": {}})

    def test_policy_accepts_short_action_names(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())

        accepted, reason = validator.verify(
            bot=None,
            actions=[
                {"id": "GasBuildingController", "args": {"to_count": 1}}
            ],
            context=EntityContext(),
            phase="opening_factory",
        )

        self.assertTrue(accepted, reason)

    def test_directive_store_honors_ttl(self):
        store = DirectiveStore()
        directive = BMDirective("opening_factory", ("Build tech.",), 10, 20)
        store.write(directive)
        self.assertEqual(store.read(20), directive)
        self.assertIsNone(store.read(21))

    def test_json_parser_accepts_plain_and_fenced_objects(self):
        self.assertEqual(parse_json_object('{"actions":[]}'), {"actions": []})
        self.assertEqual(
            parse_json_object('```json\n{"actions":[]}\n```'), {"actions": []}
        )
        self.assertEqual(
            parse_json_object('Here is the result: {"actions":[]}'),
            {"actions": []},
        )

    def test_adapter_resolves_scalar_values_and_derived_group_tags(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        unit = type(
            "Unit", (), {"tag": 42, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()}
        )()
        context = EntityContext(own_entities={"1": unit}, positions={"main": object()})

        gas = adapter._resolve_arguments(
            catalog.get("macro.gas_building_controller"),
            {"to_count": 2},
            context,
        )
        group = adapter._resolve_arguments(
            catalog.get("combat.group.a_move_group"),
            {"group": ["1"], "target": "main"},
            context,
        )

        self.assertEqual(gas["to_count"], 2)
        self.assertEqual(group["group_tags"], {42})

    def test_adapter_resolves_numeric_and_bracketed_observation_ids(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        own = type(
            "Unit", (), {"tag": 42, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()}
        )()
        enemy = type("Unit", (), {"tag": 99})()
        context = EntityContext(
            own_entities={"1": own},
            enemy_entities={"2": enemy},
            positions={"main": object()},
        )

        self.assertIs(context.resolve_entity(1, own_only=True), own)
        self.assertIs(context.resolve_entity("[1]", own_only=True), own)
        action = adapter._resolve_arguments(
            catalog.get("AMove"), {"unit": 1, "target": 2}, context
        )

        self.assertIs(action["unit"], own)
        self.assertIs(action["target"], enemy)

    def test_policy_normalizes_numeric_group_ids_without_correction(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        units = {
            str(tag): type(
                "Unit", (), {"tag": tag, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()}
            )()
            for tag in (1, 2)
        }

        review = validator.review(
            bot=None,
            actions=[
                {"id": "AMoveGroup", "args": {"group": [1, "[2]"], "target": "main"}}
            ],
            context=EntityContext(own_entities=units, positions={"main": object()}),
            phase="bc_pressure",
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(review.actions[0]["args"]["group"], ["1", "2"])
        self.assertTrue(review.normalizations)

    def test_adapter_resolves_the_restricted_bc_rush_composition(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        context = EntityContext(positions={"main": object()})
        kwargs = adapter._resolve_arguments(
            catalog.get("macro.spawn_controller"),
            {
                "army_composition_dict": {
                    "BATTLECRUISER": {"proportion": 0.8, "priority": 0},
                    "MARINE": {"proportion": 0.2, "priority": 1},
                }
            },
            context,
        )

        self.assertEqual(
            {unit.name for unit in kwargs["army_composition_dict"]},
            {"BATTLECRUISER", "MARINE"},
        )

    def test_adapter_fills_bc_runtime_details_without_exposing_them_to_im(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        battlecruiser = type(
            "Unit", (), {"tag": 42, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()}
        )()
        context = EntityContext(
            own_entities={"bc1": battlecruiser},
            positions={"enemy_main": object()},
            grids={"air": object()},
        )

        move = adapter._resolve_arguments(
            catalog.get("MoveSafely"),
            {"unit": "bc1", "target": "enemy_main"},
            context,
        )
        jump = adapter._resolve_arguments(
            catalog.get("TacticalJump"),
            {"unit": "bc1", "target": "enemy_main"},
            context,
        )

        self.assertIs(move["grid"], context.grids["air"])
        self.assertEqual(jump["ability"].name, "EFFECT_TACTICALJUMP")

    def test_policy_rejects_bc_actions_for_non_battlecruisers_or_unready_jump(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        marine = type(
            "Unit",
            (),
            {"tag": 42, "type_id": type("Type", (), {"name": "MARINE"})(), "abilities": []},
        )()
        context = EntityContext(
            own_entities={"m1": marine}, positions={"main": object()}, grids={"air": object()}
        )

        review = validator.review(
            bot=None,
            actions=[{"id": "TacticalJump", "args": {"unit": "m1", "target": "main"}}],
            context=context,
            phase="bc_pressure",
        )

        self.assertFalse(review.accepted)
        self.assertIn("BATTLECRUISER", review.message)

        battlecruiser = type(
            "Unit",
            (),
            {
                "tag": 43,
                "type_id": type("Type", (), {"name": "BATTLECRUISER"})(),
                "abilities": [],
            },
        )()
        review = validator.review(
            bot=None,
            actions=[{"id": "TacticalJump", "args": {"unit": "bc1", "target": "main"}}],
            context=EntityContext(
                own_entities={"bc1": battlecruiser},
                positions={"main": type("Point", (), {"x": 1, "y": 1})()},
                grids={"air": object()},
            ),
            phase="bc_pressure",
        )

        self.assertFalse(review.accepted)
        self.assertIn("not ready", review.message)

    def test_policy_rejects_scv_combat_micro(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        scv = type(
            "Unit", (), {"tag": 99, "type_id": type("Type", (), {"name": "SCV"})()}
        )()

        review = validator.review(
            bot=None,
            actions=[{"id": "AMove", "args": {"unit": "scv1", "target": "main"}}],
            context=EntityContext(
                own_entities={"scv1": scv},
                positions={"main": type("Point", (), {"x": 1, "y": 1})()},
            ),
            phase="bc_pressure",
        )

        self.assertFalse(review.accepted)
        self.assertIn("combat units", review.message)

    def test_policy_rejects_refinery_for_build_structure(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        point = type("Point", (), {"x": 1, "y": 1})()
        accepted, reason = validator.verify(
            bot=None,
            actions=[
                {
                    "id": "macro.build_structure",
                    "args": {"base_location": "main", "structure_id": "REFINERY"},
                }
            ],
            context=EntityContext(positions={"main": point}),
            phase="opening_factory",
        )

        self.assertFalse(accepted)
        self.assertIn("gas_building_controller", reason)

    def test_policy_review_keeps_valid_actions_when_a_sibling_is_invalid(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        point = type("Point", (), {"x": 1, "y": 1})()

        review = validator.review(
            bot=None,
            actions=[
                {"id": "GasBuildingController", "args": {"to_count": 1}},
                {
                    "id": "BuildStructure",
                    "args": {"base_location": "main", "structure_id": "REFINERY"},
                },
            ],
            context=EntityContext(positions={"main": point}),
            phase="opening_factory",
        )

        self.assertFalse(review.accepted)
        self.assertEqual(review.actions, [{"id": "GasBuildingController", "args": {"to_count": 1}}])
        self.assertIn("gas_building_controller", review.message)

    def test_policy_clamps_a_point_slightly_outside_the_playable_area(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        unit = type(
            "Unit",
            (),
            {"tag": 42, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()},
        )()
        area = type("Area", (), {"x": 0, "y": 0, "width": 100, "height": 100})()
        bot = type("Bot", (), {"game_info": type("Info", (), {"playable_area": area})()})()

        review = validator.review(
            bot=bot,
            actions=[
                {
                    "id": "AMove",
                    "args": {"unit": "1", "target": {"x": -1, "y": 30}},
                }
            ],
            context=EntityContext(own_entities={"1": unit}),
            phase="bc_pressure",
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(review.actions[0]["args"]["target"], {"x": 0.0, "y": 30.0})
        self.assertTrue(review.normalizations)

    def test_policy_normalizes_bc_rush_techlab_shorthand_before_execution(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())

        review = validator.review(
            bot=None,
            actions=[
                {
                    "id": "TechUp",
                    "args": {"desired_tech": "TECHLAB", "base_location": "main"},
                }
            ],
            context=EntityContext(
                positions={"main": type("Point", (), {"x": 1, "y": 1})()}
            ),
            phase="opening_air_tech",
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(
            review.actions[0]["args"]["desired_tech"], "STARPORTTECHLAB"
        )
        self.assertTrue(review.normalizations)

    def test_adapter_rejects_abstract_techlab_before_ares_execution(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)

        with self.assertRaisesRegex(InstructionError, "concrete technology target"):
            adapter._resolve_arguments(
                catalog.get("TechUp"),
                {"desired_tech": "TECHLAB", "base_location": "main"},
                EntityContext(
                    positions={"main": type("Point", (), {"x": 1, "y": 1})()}
                ),
            )

    def test_resource_blocked_macro_action_is_deferred_and_retried(self):
        catalog = ActionCatalog.load()
        queue = DeferredActionQueue(catalog, ttl_iterations=10)
        bot = type("Bot", (), {"affordable": False})()
        bot.can_afford = lambda _target: bot.affordable
        action = {
            "id": "BuildStructure",
            "args": {"base_location": "main", "structure_id": "SUPPLYDEPOT"},
        }

        self.assertTrue(queue.should_defer(bot, action))
        self.assertTrue(queue.enqueue(action, iteration=10))
        self.assertEqual(queue.pop_ready(bot, iteration=11), ([], []))
        bot.affordable = True
        self.assertEqual(queue.pop_ready(bot, iteration=12), ([action], []))
