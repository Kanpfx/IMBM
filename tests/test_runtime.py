import unittest

from knowledge.loader import ActionCatalog
from config.game import GameConfig
from core.action_errors import OutputFormatError
from core.policy import PolicyValidator
from runtime.ares_adapter import AresActionAdapter, InstructionError
from runtime.deferred_actions import DeferredActionQueue
from runtime.directive import BMDirective, DirectiveStore
from runtime.persistent_actions import PersistentActionRegistry
from runtime.resolver import EntityContext
from tools.json_tools import parse_im_payload, parse_json_object


class RuntimeTests(unittest.TestCase):
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
            phase="opening_tech",
        )

        self.assertTrue(accepted, reason)

    def test_directive_store_honors_ttl(self):
        store = DirectiveStore()
        directive = BMDirective("opening_tech", ("Build tech.",), 10, 20)
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

    def test_im_parser_accepts_common_wrappers_and_requires_the_full_contract(self):
        expected = {
            "actions": [],
            "request_background": False,
            "background_reason": "",
        }
        raw = (
            '{"actions":[],"request_background":false,'
            '"background_reason":""}'
        )

        self.assertEqual(parse_im_payload(raw), expected)
        self.assertEqual(parse_im_payload(f"```json\n{raw}\n```"), expected)
        self.assertEqual(parse_im_payload(f"Result:\n{raw}\nDone."), expected)
        with self.assertRaisesRegex(OutputFormatError, "standard JSON object"):
            parse_im_payload('{"actions":[]')
        with self.assertRaisesRegex(OutputFormatError, "request_background"):
            parse_im_payload(
                '{"actions":[],"request_background":"false",'
                '"background_reason":""}'
            )

    def test_catalog_and_policy_apply_basic_case_and_separator_tolerance(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        main = type("Point", (), {"x": 1, "y": 1})()

        self.assertEqual(catalog.get("build-structure")["id"], "macro.build_structure")
        review = validator.review(
            bot=None,
            actions=[
                {
                    "ID": "build structure",
                    "ARGS": {
                        "BaseLocation": "MAIN",
                        "Structure-ID": "factory",
                    },
                }
            ],
            context=EntityContext(positions={"main": main}),
            phase="opening_tech",
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(review.actions[0]["id"], "BuildStructure")
        self.assertEqual(
            review.actions[0]["args"],
            {"base_location": "main", "structure_id": "FACTORY"},
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

    def test_adapter_resolves_a_generic_army_composition(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        context = EntityContext(positions={"main": object()})
        kwargs = adapter._resolve_arguments(
            catalog.get("macro.spawn_controller"),
            {
                "army_composition_dict": {
                    "ZEALOT": {"proportion": 0.6, "priority": 0},
                    "STALKER": {"proportion": 0.4, "priority": 1},
                }
            },
            context,
        )

        self.assertEqual(
            {unit.name for unit in kwargs["army_composition_dict"]},
            {"ZEALOT", "STALKER"},
        )
        self.assertTrue(kwargs["freeflow_mode"])

    def test_policy_normalizes_flat_composition_shorthand(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())

        review = validator.review(
            bot=None,
            actions=[
                {
                    "id": "SpawnController",
                    "args": {"army_composition_dict": {"MARINE": 1.0}},
                }
            ],
            context=EntityContext(),
            phase="first_bc_preparation",
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(
            review.actions[0]["args"]["army_composition_dict"],
            {"MARINE": {"proportion": 1.0, "priority": 0}},
        )
        self.assertTrue(review.normalizations)

    def test_policy_normalizes_composition_weights_and_missing_priorities(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())

        review = validator.review(
            bot=None,
            actions=[
                {
                    "id": "SpawnController",
                    "args": {
                        "army_composition_dict": {
                            "bc": {"proportion": 8},
                            "marine": {"proportion": 2},
                        }
                    },
                }
            ],
            context=EntityContext(),
            phase="bc_pressure",
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(
            review.actions[0]["args"]["army_composition_dict"],
            {
                "BATTLECRUISER": {"proportion": 0.8, "priority": 0},
                "MARINE": {"proportion": 0.2, "priority": 1},
            },
        )

    def test_policy_drops_zero_weight_units_without_correction(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())

        review = validator.review(
            bot=None,
            actions=[
                {
                    "id": "SpawnController",
                    "args": {
                        "army_composition_dict": {
                            "BATTLECRUISER": {"proportion": 1.0, "priority": 0},
                            "MARINE": {"proportion": 0.0, "priority": 1},
                        }
                    },
                }
            ],
            context=EntityContext(),
            phase="bc_pressure",
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(
            review.actions[0]["args"]["army_composition_dict"],
            {"BATTLECRUISER": {"proportion": 1.0, "priority": 0}},
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
        self.assertIn("Parameter error: invalid value", review.message)
        self.assertIn("currently ready", review.message)

    def test_policy_allows_worker_micro_outside_a_phase_whitelist(self):
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

        self.assertTrue(review.accepted, review.message)

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
            phase="opening_tech",
        )

        self.assertFalse(accepted)
        self.assertIn("GasBuildingController", reason)

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
            phase="opening_tech",
        )

        self.assertFalse(review.accepted)
        self.assertEqual(review.actions, [{"id": "GasBuildingController", "args": {"to_count": 1}}])
        self.assertIn("GasBuildingController", review.message)

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

    def test_policy_normalizes_starport_techlab_separators_before_execution(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())

        review = validator.review(
            bot=None,
            actions=[
                {
                    "id": "TechUp",
                    "args": {
                        "desired_tech": "starport-techlab",
                        "base_location": "main",
                    },
                }
            ],
            context=EntityContext(
                positions={"main": type("Point", (), {"x": 1, "y": 1})()}
            ),
            phase="opening_tech",
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

    def test_resource_filter_queues_small_shortfalls_and_blocks_large_ones(self):
        catalog = ActionCatalog.load()
        queue = DeferredActionQueue(
            catalog,
            ttl_iterations=10,
            mineral_tolerance=120,
            vespene_tolerance=60,
        )
        cost = type("Cost", (), {"minerals": 150, "vespene": 100})()
        bot = type("Bot", (), {"minerals": 100, "vespene": 50})()
        bot.can_afford = lambda _target: False
        bot.calculate_cost = lambda _target: cost
        action = {
            "id": "BuildStructure",
            "args": {"base_location": "main", "structure_id": "FACTORY"},
        }

        self.assertEqual(
            queue.resource_status(bot, action), DeferredActionQueue.QUEUED
        )
        bot.minerals = 0
        bot.vespene = 0
        self.assertEqual(
            queue.resource_status(bot, action), DeferredActionQueue.BLOCKED
        )

    def test_persistent_action_is_registered_until_the_next_decision(self):
        catalog = ActionCatalog.load()
        registry = PersistentActionRegistry(catalog, duration_iterations=10)
        action = {
            "id": "KeepUnitSafe",
            "args": {"unit": "1", "grid": "ground"},
        }

        class Adapter:
            def __init__(self):
                self.calls = 0

            def compile_and_register(self, _bot, actions, _context):
                self.calls += len(actions)

        adapter = Adapter()
        registry.remember(action, iteration=0)
        for iteration in range(1, 10):
            completed, failed = registry.run(
                object(), iteration, adapter, EntityContext()
            )
            self.assertEqual(completed, [])
            self.assertEqual(failed, [])

        completed, failed = registry.run(object(), 10, adapter, EntityContext())

        self.assertEqual(adapter.calls, 9)
        self.assertEqual(completed, [action])
        self.assertEqual(failed, [])
