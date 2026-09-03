import unittest

from config.game import GameConfig
from game.actions.adapter import AresActionAdapter, InstructionError
from game.actions.deferred import DeferredActionQueue
from game.actions.errors import OutputFormatError
from game.actions.formatting import format_action, format_indexed_actions
from game.actions.persistent import PersistentActionRegistry
from game.actions.policy import PolicyValidator
from game.actions.resolver import EntityContext
from knowledge.loader import ActionCatalog
from llm.json_tools import parse_im_payload, parse_json_object


class ActionRuntimeTests(unittest.TestCase):
    def test_readable_action_format_uses_call_syntax(self):
        action = {
            "id": "BuildStructure",
            "args": {"base_location": "main", "structure_id": "BARRACKS"},
        }
        expected = "BuildStructure(base_location=main, structure_id=BARRACKS)"

        self.assertEqual(format_action(action), expected)
        self.assertEqual(
            format_indexed_actions([action]),
            [f"actions[0]={expected}"],
        )
        self.assertEqual(format_indexed_actions([]), ["actions=[]"])

    def test_decision_intervals_keep_im_actions_for_the_full_cycle(self):
        config = GameConfig()

        self.assertEqual(config.im_interval_iterations, 30)
        self.assertEqual(config.persistent_action_iterations, 30)

    def test_adapter_rejects_disabled_catalog_actions(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)

        for action_id in (
            "macro.mining",
            "macro.auto_supply",
            "macro.speed_mining",
            "macro.restore_power",
            "macro.macro_plan",
            "macro.protoss_static_defence",
        ):
            with self.subTest(action_id=action_id):
                with self.assertRaisesRegex(
                    InstructionError, "not currently listed in `<available_actions>`"
                ):
                    adapter._validate_shape({"id": action_id, "args": {}})

    def test_static_macro_options_match_the_fixed_ares_source(self):
        from ares.behaviors.macro.addon_swap import ADDON_TYPES
        from ares.behaviors.macro.tech_up import BUILD_TECHLAB_FROM
        from ares.consts import (
            ADD_ONS,
            ALL_STRUCTURES,
            GATEWAY_UNITS,
            TECHLAB_TYPES,
            UnitRole,
        )
        from ares.dicts.aoe_ability_to_range import AOE_ABILITY_SPELLS_INFO
        from ares.dicts.structure_to_building_size import STRUCTURE_TO_BUILDING_SIZE
        from ares.dicts.unit_tech_requirement import UNIT_TECH_REQUIREMENT
        from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
        from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
        from sc2.ids.unit_typeid import UnitTypeId
        from sc2.ids.upgrade_id import UpgradeId

        catalog = ActionCatalog.load()

        def options(action_id, parameter_name):
            entry = catalog.get(action_id)
            parameter = next(
                item for item in entry["params"] if item["name"] == parameter_name
            )
            return parameter["options"]

        self.assertEqual(
            options("AddonSwap", "structure_needing_addon"),
            ["BARRACKS", "FACTORY", "STARPORT"],
        )
        self.assertEqual(
            options("AddonSwap", "addon_required"),
            sorted(item.name for item in ADDON_TYPES | set(ADD_ONS)),
        )
        self.assertEqual(
            options("BuildStructure", "structure_id"),
            sorted(item.name for item in STRUCTURE_TO_BUILDING_SIZE),
        )
        self.assertEqual(
            options("UpgradeCCs", "to"),
            ["ORBITALCOMMAND", "PLANETARYFORTRESS"],
        )
        self.assertEqual(
            options("AddonSwap", "precise_addon_structure_id"),
            sorted(item.name for item in ADD_ONS),
        )
        self.assertEqual(
            options("UseAOEAbility", "ability_id"),
            sorted(item.name for item in AOE_ABILITY_SPELLS_INFO),
        )
        self.assertEqual(
            options("PickUpCargo", "cargo_switch_to_role"),
            sorted(item.name for item in UnitRole),
        )
        self.assertEqual(
            options("PickUpAndDropCargo", "cargo_switch_to_role"),
            sorted(item.name for item in UnitRole),
        )
        trainable_units = sorted(item.name for item in UNIT_TRAINED_FROM)
        self.assertEqual(
            options("ProductionController", "army_composition_dict"),
            trainable_units,
        )
        self.assertEqual(
            options("SpawnController", "army_composition_dict"),
            trainable_units,
        )
        self.assertEqual(
            options("UpgradeController", "upgrade_list"),
            sorted(item.name for item in UPGRADE_RESEARCHED_FROM),
        )

        def valid_tech_source(source):
            if source in TECHLAB_TYPES:
                return source in BUILD_TECHLAB_FROM
            return source in UNIT_TECH_REQUIREMENT

        tech_options = []
        for target in UnitTypeId:
            if target in ALL_STRUCTURES:
                valid = target in UNIT_TECH_REQUIREMENT
            elif target in UNIT_TRAINED_FROM:
                sources = (
                    {UnitTypeId.GATEWAY}
                    if target in GATEWAY_UNITS
                    else set(UNIT_TRAINED_FROM[target])
                )
                valid = bool(sources) and all(
                    valid_tech_source(source) for source in sources
                )
            else:
                valid = False
            if valid:
                tech_options.append(target.name)
        tech_options.extend(
            target.name
            for target in UpgradeId
            if (source := UPGRADE_RESEARCHED_FROM.get(target)) is not None
            and valid_tech_source(source)
        )
        self.assertEqual(
            options("TechUp", "desired_tech"),
            sorted(set(tech_options)),
        )

    def test_policy_accepts_short_action_names(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())

        accepted, reason = validator.verify(
            bot=None,
            actions=[{"id": "GasBuildingController", "args": {"to_count": 1}}],
            context=EntityContext(),
        )

        self.assertTrue(accepted, reason)

    def test_json_parser_accepts_plain_and_fenced_objects(self):
        self.assertEqual(parse_json_object('{"actions":[]}'), {"actions": []})
        self.assertEqual(
            parse_json_object('```json\n{"actions":[]}\n```'), {"actions": []}
        )
        self.assertEqual(
            parse_json_object('Here is the result: {"actions":[]}'),
            {"actions": []},
        )

    def test_im_parser_accepts_common_wrappers_and_requires_actions(self):
        expected = {"phase": None, "actions": []}
        raw = '{"actions":[]}'

        self.assertEqual(parse_im_payload(raw), expected)
        self.assertEqual(parse_im_payload(f"```json\n{raw}\n```"), expected)
        self.assertEqual(parse_im_payload(f"Result:\n{raw}\nDone."), expected)
        with self.assertRaisesRegex(OutputFormatError, "standard JSON object"):
            parse_im_payload('{"actions":[]')
        with self.assertRaisesRegex(OutputFormatError, "actions"):
            parse_im_payload('{"actions":"none"}')

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
            "Unit",
            (),
            {"tag": 42, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()},
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

    def test_adapter_normalizes_supported_terran_upgrade_names(self):
        from sc2.ids.upgrade_id import UpgradeId

        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        context = EntityContext(positions={"main": object()})

        resolved = adapter._resolve_arguments(
            catalog.get("UpgradeController"),
            {
                "upgrade_list": ["CombatShield", "ConcussiveShells"],
                "base_location": "main",
            },
            context,
        )

        self.assertEqual(
            resolved["upgrade_list"],
            [UpgradeId.SHIELDWALL, UpgradeId.PUNISHERGRENADES],
        )

    def test_adapter_rejects_upgrade_without_ares_research_mapping(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        context = EntityContext(positions={"main": object()})

        with self.assertRaisesRegex(
            InstructionError, "supported by Ares UpgradeController"
        ):
            adapter._resolve_arguments(
                catalog.get("UpgradeController"),
                {
                    "upgrade_list": ["COMBATDRUGS"],
                    "base_location": "main",
                },
                context,
            )

    def test_adapter_resolves_numeric_and_bracketed_observation_ids(self):
        catalog = ActionCatalog.load()
        adapter = AresActionAdapter(catalog)
        own = type(
            "Unit",
            (),
            {"tag": 42, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()},
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

    def test_policy_normalizes_numeric_group_ids_without_another_model_turn(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        units = {
            str(tag): type(
                "Unit",
                (),
                {"tag": tag, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()},
            )()
            for tag in (1, 2)
        }

        review = validator.review(
            bot=None,
            actions=[
                {"id": "AMoveGroup", "args": {"group": [1, "[2]"], "target": "main"}}
            ],
            context=EntityContext(own_entities=units, positions={"main": object()}),
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
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(
            review.actions[0]["args"]["army_composition_dict"],
            {
                "BATTLECRUISER": {"proportion": 0.8, "priority": 0},
                "MARINE": {"proportion": 0.2, "priority": 1},
            },
        )

    def test_policy_drops_zero_weight_units_without_another_model_turn(self):
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
            "Unit",
            (),
            {"tag": 42, "type_id": type("Type", (), {"name": "BATTLECRUISER"})()},
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
            {
                "tag": 42,
                "type_id": type("Type", (), {"name": "MARINE"})(),
                "abilities": [],
            },
        )()
        context = EntityContext(
            own_entities={"m1": marine},
            positions={"main": object()},
            grids={"air": object()},
        )

        review = validator.review(
            bot=None,
            actions=[{"id": "TacticalJump", "args": {"unit": "m1", "target": "main"}}],
            context=context,
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
        )

        self.assertFalse(review.accepted)
        self.assertEqual(
            review.actions, [{"id": "GasBuildingController", "args": {"to_count": 1}}]
        )
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
        bot = type(
            "Bot", (), {"game_info": type("Info", (), {"playable_area": area})()}
        )()

        review = validator.review(
            bot=bot,
            actions=[
                {
                    "id": "AMove",
                    "args": {"unit": "1", "target": {"x": -1, "y": 30}},
                }
            ],
            context=EntityContext(own_entities={"1": unit}),
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
        )

        self.assertTrue(review.accepted, review.message)
        self.assertEqual(review.actions[0]["args"]["desired_tech"], "STARPORTTECHLAB")
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

        self.assertEqual(queue.resource_status(bot, action), DeferredActionQueue.QUEUED)
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

    def test_macro_controllers_persist_without_a_macro_plan(self):
        catalog = ActionCatalog.load()
        registry = PersistentActionRegistry(catalog, duration_iterations=30)

        for action_id in (
            "ExpansionController",
            "GasBuildingController",
            "ProductionController",
            "SpawnController",
            "UpgradeCCs",
            "UpgradeController",
        ):
            with self.subTest(action_id=action_id):
                self.assertTrue(registry.is_persistent({"id": action_id, "args": {}}))
