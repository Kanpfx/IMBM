import unittest

from game.observation.builder import ObservationBuilder
from game.observation.state import TagIdMapper
from knowledge.loader import ActionCatalog
from llm.agents.prompts import (
    bm_messages,
    correction_messages,
    im_messages,
    refine_messages,
)


class Point:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y


class Unit:
    def __init__(
        self,
        tag: int,
        name: str,
        *,
        idle: bool = False,
        progress: float = 1.0,
        health: float = 1.0,
    ):
        self.tag = tag
        self.type_id = type("Type", (), {"name": name})()
        self.is_idle = idle
        self.build_progress = progress
        self.health_percentage = health
        self.is_attacking = False
        self.is_constructing_scv = False
        self.is_repairing = False
        self.is_visible = True
        self.orders = []
        self.position = Point(10, 10)


class Mediator:
    get_own_nat = None
    get_ground_enemy_near_bases = {}


class Bot:
    def __init__(self):
        self.units = [Unit(497, "SCV"), Unit(641, "SCV"), Unit(217, "MARINE")]
        self.structures = [Unit(102, "COMMANDCENTER", idle=True)]
        self.enemy_units = [Unit(88, "STALKER")]
        self.enemy_structures = []
        self.workers = self.units[:2]
        self.townhalls = self.structures
        self.gas_buildings = []
        self.minerals = 50
        self.vespene = 0
        self.supply_used = 12
        self.supply_cap = 15
        self.time_formatted = "00:00"
        self.enemy_race = type("Race", (), {"name": "Protoss"})()
        self.start_location = Point(1, 1)
        self.enemy_start_locations = [Point(100, 100)]
        self.mediator = Mediator()
        self.pending = {}

    def already_pending(self, unit_type):
        return self.pending.get(unit_type.name, 0)


class ObservationTests(unittest.TestCase):
    def test_shared_observation_aggregates_workers_and_hides_internal_details(self):
        builder = ObservationBuilder(TagIdMapper())
        observation = builder.build(Bot(), iteration=0, _phase="opening_tech")

        self.assertEqual(observation.text, observation.strategy_text)
        self.assertEqual(observation.text, observation.action_text)
        self.assertTrue(observation.text.startswith("<overview>\n"))
        self.assertIn("</overview>", observation.text)
        self.assertIn("<own_forces>", observation.text)
        self.assertIn("<visible_enemy>", observation.text)
        self.assertIn("<recent_history>", observation.text)
        self.assertNotIn("<situation>", observation.text)
        self.assertNotIn("<memory>", observation.text)
        self.assertNotIn("<own_units>", observation.text)
        self.assertNotIn("<own_structures>", observation.text)
        self.assertIn("## Production and technology", observation.text)
        self.assertIn("## Units", observation.text)
        self.assertIn(
            "Bases: main (active, no visible ground or air threat).",
            observation.text,
        )
        self.assertIn(
            "[497,641] SCV\nStatus: collecting resources automatically.",
            observation.text,
        )
        self.assertIn("[88] Stalker", observation.text)
        self.assertNotIn("Phase:", observation.text)
        self.assertNotIn("landmark", observation.text.lower())
        self.assertNotIn("SCV at", observation.text)
        self.assertNotIn("health 45/45", observation.text.lower())

    def test_key_units_and_structures_include_full_status(self):
        bot = Bot()
        battlecruiser = Unit(333, "BATTLECRUISER")
        battlecruiser.health = 440
        battlecruiser.health_max = 550
        battlecruiser.energy = 125
        battlecruiser.energy_max = 200
        battlecruiser.abilities = [
            type("Ability", (), {"name": "EFFECT_TACTICALJUMP"})(),
            type("Ability", (), {"name": "YAMATO_YAMATOGUN"})(),
        ]
        starport = Unit(444, "STARPORT", idle=True)
        starport.health = 1300
        starport.health_max = 1300
        bot.units.append(battlecruiser)
        bot.structures.append(starport)
        observation = ObservationBuilder(TagIdMapper()).build(
            bot, iteration=0, _phase="opening_tech"
        )

        self.assertIn("[333] Battlecruiser", observation.text)
        self.assertIn("Health: 440/550 (80%).", observation.text)
        self.assertIn("Position: (10, 10), near our main.", observation.text)
        self.assertIn("Energy: 125/200.", observation.text)
        self.assertIn("Tactical Jump: ready.", observation.text)
        self.assertIn("Yamato Cannon: ready.", observation.text)
        self.assertIn("[444] Starport", observation.text)

    def test_history_is_included_on_the_next_observation(self):
        builder = ObservationBuilder(TagIdMapper())
        builder.record_registered_actions(
            [
                {
                    "id": "macro.build_structure",
                    "args": {"structure_id": "SUPPLYDEPOT", "base_location": "main"},
                }
            ],
            time="05:10",
        )
        builder.record_validation_error("2")
        observation = builder.build(Bot(), iteration=10, _phase="opening_tech")

        self.assertIn(
            "05:10 macro.build_structure (SUPPLYDEPOT near main) status: completed",
            observation.text,
        )
        self.assertIn(
            "Previous validation error: An action used a numeric enum value.",
            observation.text,
        )

    def test_queued_history_updates_in_place_when_completed_or_expired(self):
        builder = ObservationBuilder(TagIdMapper())
        finished = {
            "id": "BuildStructure",
            "args": {"structure_id": "FACTORY", "base_location": "main"},
        }
        expired = {
            "id": "TechUp",
            "args": {"desired_tech": "STARPORT", "base_location": "main"},
        }
        builder.record_deferred_actions([finished], time="05:10")
        builder.record_deferred_actions([expired], time="05:11")
        builder.record_registered_actions([finished], time="05:20")
        builder.record_expired_actions([expired], time="05:21")

        observation = builder.build(Bot(), iteration=10, _phase="opening_tech")

        self.assertIn(
            "05:10 BuildStructure (FACTORY near main) status: completed",
            observation.text,
        )
        self.assertIn("05:11 TechUp status: expired", observation.text)
        self.assertEqual(
            observation.text.count("BuildStructure (FACTORY near main)"), 1
        )

    def test_persistent_history_uses_active_completed_and_failed_states(self):
        builder = ObservationBuilder(TagIdMapper())
        active = {
            "id": "KeepUnitSafe",
            "args": {"unit": "1", "grid": "ground"},
        }
        failed = {
            "id": "PathUnitToTarget",
            "args": {"unit": "2", "grid": "ground", "target": "main"},
        }
        builder.record_active_actions([active], time="05:10")
        builder.record_active_actions([failed], time="05:11")
        builder.record_completed_actions([active], time="05:20")
        builder.record_failed_actions([failed], time="05:20")

        observation = builder.build(Bot(), iteration=10, _phase="opening_tech")

        self.assertIn("KeepUnitSafe status: completed", observation.text)
        self.assertIn("PathUnitToTarget status: failed", observation.text)
        self.assertNotIn("status: active", observation.text)

    def test_compact_units_keep_their_semantic_locations(self):
        bot = Bot()
        near_main = Unit(218, "MARINE")
        near_enemy = Unit(361, "MARINE")
        near_enemy.position = Point(90, 90)
        bot.units.extend([near_main, near_enemy])

        observation = ObservationBuilder(TagIdMapper()).build(
            bot, iteration=0, _phase="opening_tech"
        )

        self.assertIn(
            "[217,218] Marines\nStatus: active.\nLocation: near our main.",
            observation.text,
        )
        self.assertIn(
            "[361] Marine\nStatus: active.\nLocation: near enemy main.",
            observation.text,
        )

    def test_enemy_location_is_based_on_each_enemy_tag(self):
        bot = Bot()
        other_enemy = Unit(99, "ZEALOT")
        other_enemy.position = Point(90, 90)
        bot.enemy_units.append(other_enemy)
        bot.mediator.get_ground_enemy_near_bases = {bot.structures[0].tag: {88}}

        observation = ObservationBuilder(TagIdMapper()).build(
            bot, iteration=0, _phase="opening_tech"
        )

        self.assertIn("[88] Stalker\nStatus: visible; near our main.", observation.text)
        self.assertIn(
            "[99] Zealot\nStatus: visible; near enemy main.", observation.text
        )
        self.assertIn(
            "Bases: main (active, ground threat: 1 Stalker).",
            observation.text,
        )

    def test_empty_enemy_sections_explain_visibility_scope(self):
        bot = Bot()
        bot.enemy_units = []

        observation = ObservationBuilder(TagIdMapper()).build(
            bot, iteration=0, _phase="opening_tech"
        )

        self.assertIn(
            "[Empty \u2014 no enemy units are visible now.]", observation.text
        )
        self.assertIn(
            "[Empty \u2014 no enemy structures are visible now.]", observation.text
        )

    def test_structure_changes_distinguish_building_from_ready(self):
        bot = Bot()
        builder = ObservationBuilder(TagIdMapper())
        builder.build(bot, iteration=0, _phase="opening_tech")

        factory = Unit(700, "FACTORY", progress=0.25)
        bot.structures.append(factory)
        building = builder.build(bot, iteration=10, _phase="opening_tech")
        self.assertIn("Status: building (25%).", building.text)
        self.assertIn("Our Factory started building.", building.text)
        self.assertNotIn("Our Factory became ready.", building.text)

        factory.build_progress = 1.0
        ready = builder.build(bot, iteration=20, _phase="opening_tech")
        self.assertIn("Status: ready.", ready.text)
        self.assertIn("Our Factory became ready.", ready.text)
        self.assertNotIn("Our Factory completed.", ready.text)

    def test_battlecruiser_history_survives_current_unit_loss(self):
        bot = Bot()
        builder = ObservationBuilder(TagIdMapper())
        bot.units.append(Unit(800, "BATTLECRUISER"))
        builder.build(bot, iteration=0, _phase="bc_pressure")

        bot.units = [unit for unit in bot.units if unit.type_id.name != "BATTLECRUISER"]
        observation = builder.build(bot, iteration=10, _phase="bc_pressure")

        self.assertIn(
            "Battlecruiser history: at least one Battlecruiser is ready now "
            "or was ready earlier.",
            observation.text,
        )

    def test_pending_battlecruiser_is_explicit_in_production_summary(self):
        bot = Bot()
        bot.pending["BATTLECRUISER"] = 1

        observation = ObservationBuilder(TagIdMapper()).build(
            bot, iteration=0, _phase="first_bc_transition"
        )

        self.assertIn("In production or pending: 1 Battlecruiser.", observation.text)

    def test_prompts_use_named_sections_and_give_bm_the_complete_tactic(self):
        tactic = {
            "concept": "Build Battlecruisers.",
            "rules": ["Stay safe."],
            "phases": [
                {
                    "id": "opening_tech",
                    "enter_when": ["The Factory has not started."],
                    "goal": "Start production.",
                    "guidance": ["Build a Depot."],
                },
                {
                    "id": "first_bc_preparation",
                    "enter_when": ["The Factory has started."],
                    "goal": "Start air technology.",
                    "guidance": ["Build a Starport."],
                },
            ],
        }
        catalog = ActionCatalog.load()
        entries = catalog.prompt_entries({"macro.build_structure"})
        bm = bm_messages("# Round state\n[Empty]", tactic, entries, "cold start")
        im = im_messages("# Round state\n[Empty]", ["Build a Depot."], [])

        self.assertIn("<task>", bm[-1]["content"])
        self.assertIn("The game has just started.", bm[-1]["content"])
        self.assertIn("<observation>", bm[-1]["content"])
        self.assertIn("<tactical_card", bm[-1]["content"])
        self.assertIn("Concept: Build Battlecruisers.", bm[-1]["content"])
        self.assertIn("Phase `opening_tech`", bm[-1]["content"])
        self.assertIn("Phase `first_bc_preparation`", bm[-1]["content"])
        self.assertIn("Enter when:", bm[-1]["content"])
        self.assertIn("Guidance:", bm[-1]["content"])
        self.assertIn("<action_reference>", bm[-1]["content"])
        self.assertIn("- `BuildStructure(", bm[-1]["content"])
        self.assertIn("<output_contract>", bm[-1]["content"])
        self.assertIn('"phase":"opening_tech"', bm[-1]["content"])
        self.assertIn("<observation>", im[-1]["content"])
        self.assertIn("<decision_context>", im[-1]["content"])
        self.assertIn("Strategic guidance:", im[-1]["content"])
        self.assertIn("Decision rules:", im[-1]["content"])
        self.assertIn("<action_reference>", im[-1]["content"])
        self.assertIn("Available actions:", im[-1]["content"])
        self.assertIn("<output_contract>", im[-1]["content"])
        self.assertNotIn("<priority>", im[-1]["content"])
        self.assertNotIn("<rule>", im[-1]["content"])

    def test_action_cards_use_short_names_and_required_params_only(self):
        catalog = ActionCatalog.load()
        entries = catalog.prompt_entries(
            {
                "combat.individual.a_move",
                "combat.bc.move_safely",
                "combat.bc.tactical_jump",
                "macro.build_structure",
                "macro.production_controller",
            }
        )
        prompt = im_messages("# Round state\n[Empty]", [], entries)[-1]["content"]

        self.assertIn("- `AMove(unit: Unit, target: Point | Unit)`", prompt)
        self.assertIn("— A-Move a unit to a target.", prompt)
        self.assertIn("Argument types:", prompt)
        self.assertIn("Composition format for `army_composition_dict`:", prompt)
        self.assertIn(
            '"BATTLECRUISER": {"proportion": 0.8, "priority": 0}',
            prompt,
        )
        self.assertIn(
            "- Unit: One unit ID from Observation.",
            prompt,
        )
        self.assertIn(
            "  - `unit` (Unit):",
            prompt,
        )
        self.assertIn(
            "  - `target` (Point | Unit):",
            prompt,
        )
        self.assertIn(
            "- `BuildStructure(base_location: Point, structure_id: UnitType)`",
            prompt,
        )
        self.assertIn("- `TacticalJump(", prompt)
        self.assertIn("- `MoveSafely(", prompt)
        self.assertNotIn("- `UseAbility(", prompt)
        self.assertNotIn("<action name=", prompt)
        self.assertNotIn("<parameter name=", prompt)
        self.assertNotIn("combat.individual.a_move", prompt)
        self.assertNotIn("success_at_distance", prompt)
        self.assertNotIn("group_tags", prompt)
        self.assertNotIn("Union[Point2, Unit]", prompt)

    def test_correction_and_refine_prompts_keep_only_section_tags(self):
        catalog = ActionCatalog.load()
        entries = catalog.prompt_entries({"macro.build_structure"})
        correction = correction_messages(
            "<state_summary>\nstate\n</state_summary>",
            ["Build the Factory."],
            entries,
            [{"id": "BuildStructure", "args": {}}],
            ["Action 1: missing required argument"],
        )[-1]["content"]

        self.assertIn("<correction_context>", correction)
        self.assertIn("Strategic guidance:", correction)
        self.assertIn("Rejected actions:", correction)
        self.assertIn("Validation errors:", correction)
        self.assertIn("Repair rules:", correction)
        self.assertIn("<action_reference>", correction)
        self.assertIn("Available actions:", correction)
        self.assertIn("<output_contract>", correction)
        self.assertNotIn("<error>", correction)
        self.assertNotIn("<rule>", correction)

        refined = refine_messages([], "actions must be a list", '{"actions":[]}')
        self.assertEqual(refined[0]["content"], "Previous output was rejected.")
        self.assertIn("<correction_request>", refined[1]["content"])
        self.assertIn("Validation error: actions must be a list", refined[1]["content"])
        self.assertIn('Required JSON shape: {"actions":[]}', refined[1]["content"])
        self.assertNotIn("### Validation Error", refined[1]["content"])

    def test_catalog_corrects_verified_ares_documentation_errors(self):
        catalog = ActionCatalog.load()

        self.assertEqual(
            catalog.get("combat.group.keep_group_safe")["description"],
            "Keep every unit in a group safe, optionally attacking a nearby "
            "enemy when its weapon is ready.",
        )
        self.assertEqual(
            catalog.get("combat.individual.use_ability")["description"],
            "Order a unit to cast a specified ability, optionally at a target.",
        )
        self.assertEqual(
            catalog.get("macro.upgrade_c_cs")["description"],
            "Upgrade an idle Terran Command Center to an Orbital Command or "
            "Planetary Fortress.",
        )
        drop_target = next(
            param
            for param in catalog.get("combat.individual.drop_cargo")["params"]
            if param["name"] == "target"
        )
        self.assertIn("container's current position", drop_target["description"])
