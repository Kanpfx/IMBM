import unittest
from config.game import GameConfig
from game.actions.adapter import AresActionAdapter, InstructionError
from game.actions.errors import OutputFormatError
from game.actions.formatting import format_action
from game.actions.policy import PolicyValidator
from game.actions.resolver import EntityContext
from knowledge.loader import ActionCatalog
from llm.model_output import parse_model_payload
from game.actions.exposure import ActionExposure
from knowledge.loader import ActionCatalog
from game.actions.formatting import format_action


class ActionRuntimeTests(unittest.TestCase):


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


    def test_policy_enforces_action_limit(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(
            catalog,
            GameConfig(max_actions_per_decision=1),
        )

        review = validator.review(
            bot=None,
            actions=[
                {"id": "GasBuildingController", "args": {"to_count": 1}},
                {"id": "BuildWorkers", "args": {"to_count": 20}},
            ],
            context=EntityContext(),
        )

        self.assertEqual(
            review.actions,
            [{"id": "GasBuildingController", "args": {"to_count": 1}}],
        )
        self.assertIn("action limit exceeded", review.message)

    def test_model_parser_accepts_headed_dsl_and_complex_values(self):
        payload = parse_model_payload(
            """```text
# PHASE
'OPENING_TECH'

# ACTIONS
- AMoveGroup(Group=[101,u2],Target={x:1.5,y:-2});
SpawnController(army_composition_dict={BATTLECRUISER:{proportion:1.0,priority:0}})
SetSomething(enabled=TRUE,value=null)
```"""
        )

        self.assertEqual(payload["phase"], "OPENING_TECH")
        self.assertEqual(
            payload["actions"][0],
            {
                "id": "AMoveGroup",
                "args": {"Group": [101, "u2"], "Target": {"x": 1.5, "y": -2}},
            },
        )
        self.assertEqual(
            payload["actions"][1]["args"]["army_composition_dict"],
            {"BATTLECRUISER": {"proportion": 1.0, "priority": 0}},
        )
        self.assertEqual(
            payload["actions"][2]["args"], {"enabled": True, "value": None}
        )
        self.assertEqual(payload["errors"], [])


    def test_split_dsl_names_reach_existing_case_and_separator_normalization(self):
        validator = PolicyValidator(ActionCatalog.load(), GameConfig())
        main = type("Point", (), {"x": 1, "y": 1})()
        for action in (
            "bUiLd Structure(BASE location=MAIN, Structure ID=supply depot)",
            "build-structure(base-location=main, structure-id=SUPPLY-DEPOT)",
            'BUILD_STRUCTURE(BaseLocation="MAIN", StructureID="supply depot")',
        ):
            with self.subTest(action=action):
                payload = parse_model_payload("# PHASE\nopening\n# ACTIONS\n" + action)
                self.assertEqual(payload["errors"], [])
                review = validator.review(
                    None, payload["actions"], EntityContext(positions={"main": main})
                )
                self.assertTrue(review.accepted, review.message)
                self.assertEqual(review.actions, [{
                    "id": "BuildStructure",
                    "args": {"base_location": "main", "structure_id": "SUPPLYDEPOT"},
                }])
        payload = parse_model_payload(
            '# phase\nopening\n# actions\nExample(note="Keep These Words", x=-2.5)\n'
            'Build Workers(to count=20, TO_COUNT=30)\nUnsafe(value=lookup(1))'
        )
        self.assertEqual(payload["actions"][0]["args"], {"note": "Keep These Words", "x": -2.5})
        self.assertEqual(len(payload["errors"]), 2)

    def test_model_parser_keeps_valid_siblings_and_reports_bad_lines(self):
        payload = parse_model_payload(
            """# phase
opening

# actions
BuildWorkers(to_count=20)
Unsafe(unit=lookup(101))
AttackTarget(unit=101,target=203)"""
        )

        self.assertEqual(
            [action["id"] for action in payload["actions"]],
            ["BuildWorkers", "AttackTarget"],
        )
        self.assertEqual(payload["errors"][0]["index"], 1)
        self.assertIn("unsupported value expression", payload["errors"][0]["error"])

    def test_model_parser_requires_unique_headed_sections(self):
        with self.assertRaisesRegex(OutputFormatError, "# phase"):
            parse_model_payload("# actions")
        with self.assertRaisesRegex(OutputFormatError, "# actions"):
            parse_model_payload("# phase\nopening")
        with self.assertRaisesRegex(OutputFormatError, "found 2"):
            parse_model_payload("# phase\na\n# phase\nb\n# actions")

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


    def test_policy_rejects_refinery_for_build_structure(self):
        catalog = ActionCatalog.load()
        validator = PolicyValidator(catalog, GameConfig())
        point = type("Point", (), {"x": 1, "y": 1})()
        review = validator.review(
            bot=None,
            actions=[
                {
                    "id": "macro.build_structure",
                    "args": {"base_location": "main", "structure_id": "REFINERY"},
                }
            ],
            context=EntityContext(positions={"main": point}),
        )

        self.assertFalse(review.accepted)
        self.assertIn("GasBuildingController", review.message)

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


    def test_group_and_individual_actions_cannot_claim_the_same_unit(self):
        from types import SimpleNamespace
        from sc2.position import Point2

        unit = SimpleNamespace(tag=1, type_id=SimpleNamespace(name="MARINE"))
        context = EntityContext(
            own_entities={"1": unit},
            positions={"main": Point2((10, 10))},
            grids={"ground": object()},
        )
        policy = PolicyValidator(ActionCatalog.load(), GameConfig())
        group = {"id": "AMoveGroup", "args": {"group": ["1"], "target": "main"}}
        individual = {"id": "KeepUnitSafe", "args": {"unit": "1", "grid": "ground"}}
        for actions in ([group, individual], [individual, group]):
            review = policy.review(None, actions, context)
            self.assertEqual(len(review.actions), 1)
            self.assertEqual(len(review.issues), 1)
            self.assertIn("higher-priority action", review.issues[0].reason)


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


class FormattingTests(unittest.TestCase):
    def test_nested_dsl_round_trip_preserves_strings_and_special_values(self):
        action = {"id": "Example", "args": {
            "composition": {"BATTLECRUISER": {"proportion": 1.0, "priority": 0}},
            "target": {"x": 10, "y": -2.5},
            "values": [True, False, None, "true", "None", "7", "main"],
            "text": 'line one\nline two\n"quoted"',
            "path": r"C:\new\test",
            "literal": r"\n",
        }}
        rendered = format_action(action)
        self.assertIn("composition={BATTLECRUISER: {proportion: 1.0", rendered)
        self.assertIn("[true, false, null", rendered)
        result = parse_model_payload("# phase\nopening\n\n# actions\n" + rendered)
        self.assertEqual(result["actions"], [action])
        self.assertEqual(result["errors"], [])

    def test_windows_line_breaks_parse_without_unescaping_values(self):
        action = {"id": "Example", "args": {"path": r"C:\new\test"}}
        result = parse_model_payload("# phase\r\nopening\r\n\r\n# actions\r\n" + format_action(action))
        self.assertEqual(result["actions"], [action])

    def test_literal_line_breaks_get_specific_feedback(self):
        with self.assertRaisesRegex(OutputFormatError, "actual line breaks"):
            parse_model_payload(r"# phase\nopening\n# actions\nExample()")

class PartialGroupValidationTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from sc2.position import Point2
        self.unit = SimpleNamespace(tag=1, type_id=SimpleNamespace(name="MARINE"), is_structure=False, abilities=[])
        self.catalog = ActionCatalog.load()
        self.policy = PolicyValidator(self.catalog, GameConfig())
        self.context = EntityContext(
            own_entities={"1": self.unit}, known_own_aliases={"1", "2"},
            positions={"main": Point2((10, 10))}, grids={"ground": object()},
        )

    def surface(self, name):
        from game.actions.exposure import ActionSurface
        entry = self.catalog.get(name)
        return ActionSurface([entry], frozenset([entry["id"]]), {}, self.context)

    def test_disappeared_member_is_removed_but_unknown_id_is_rejected(self):
        action = {"id": "AMoveGroup", "args": {"group": [1, 2], "target": "main"}}
        review = self.policy.review(None, [action], self.context, self.surface("AMoveGroup"))
        self.assertTrue(review.accepted, review.message)
        self.assertEqual(review.actions[0]["args"]["group"], ["1"])
        self.assertEqual(review.notices[0].action, "unit 2")
        self.assertIn("disappeared", review.notices[0].reason)
        self.assertIsNotNone(ActionExposure(self.catalog)._group(self.catalog.get("AMoveGroup"), self.context))
        action["args"]["group"] = [1, 999]
        review = self.policy.review(None, [action], self.context, self.surface("AMoveGroup"))
        self.assertFalse(review.accepted)
        self.assertIn("unknown or unavailable unit ID", review.message)
        action["args"]["group"] = [2]
        self.assertFalse(self.policy.review(None, [action], self.context, self.surface("AMoveGroup")).accepted)

    def test_missing_wrong_type_and_unavailable_ability_have_distinct_reasons(self):
        from types import SimpleNamespace
        action = {"id": "TacticalJump", "args": {"unit": "2", "target": "main"}}
        review = self.policy.review(None, [action], self.context, self.surface("TacticalJump"))
        self.assertIn("unit disappeared", review.message)
        action["args"]["unit"] = "1"
        review = self.policy.review(None, [action], self.context, self.surface("TacticalJump"))
        self.assertIn("unit type mismatch", review.message)
        self.unit.type_id = SimpleNamespace(name="BATTLECRUISER")
        review = self.policy.review(None, [action], self.context, self.surface("TacticalJump"))
        self.assertIn("ability currently unavailable", review.message)
        self.assertNotIn("available values from", review.message)

    def test_empty_nearby_enemies_are_valid_for_keep_group_safe(self):
        action = {"id": "KeepGroupSafe", "args": {"group": ["1"], "close_enemy": [], "grid": "ground"}}
        entry = self.catalog.get("KeepGroupSafe")
        self.assertIsNotNone(ActionExposure(self.catalog)._group(entry, self.context))
        review = self.policy.review(None, [action], self.context, self.surface("KeepGroupSafe"))
        self.assertTrue(review.accepted, review.message)
        kwargs = self.policy.adapter._resolve_arguments(entry, review.actions[0]["args"], self.context)
        self.assertEqual(kwargs["close_enemy"], [])
        action["args"]["group"] = []
        self.assertFalse(self.policy.review(None, [action], self.context, self.surface("KeepGroupSafe")).accepted)

    def test_techlab_feedback_points_to_tech_up(self):
        action = {"id": "BuildStructure", "args": {"structure_id": "TECHLAB", "base_location": "main"}}
        review = self.policy.review(None, [action], self.context)
        self.assertIn("TechUp", review.message)
        self.assertNotIn("GasBuildingController", review.message)
