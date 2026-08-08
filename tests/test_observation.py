import unittest

from agents.prompts import bm_messages, im_messages
from config.policy import allowed_actions
from core.observation import ObservationBuilder
from core.state import TagIdMapper
from knowledge.loader import ActionCatalog


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

    @staticmethod
    def already_pending(_unit_type):
        return 0


class ObservationTests(unittest.TestCase):
    def test_shared_observation_aggregates_workers_and_hides_internal_details(self):
        builder = ObservationBuilder(TagIdMapper())
        observation = builder.build(Bot(), iteration=0, _phase="opening_factory")

        self.assertEqual(observation.text, observation.strategy_text)
        self.assertEqual(observation.text, observation.action_text)
        self.assertIn("## Game state", observation.text)
        self.assertIn("### Recent changes", observation.text)
        self.assertIn("## Own situation", observation.text)
        self.assertIn(
            "[497] [641] SCV\nStatus: collecting resources automatically.",
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
            bot, iteration=0, _phase="opening_factory"
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
            ]
        )
        builder.record_validation_error("2")
        observation = builder.build(Bot(), iteration=10, _phase="opening_factory")

        self.assertIn("Sent once: macro.build_structure (SUPPLYDEPOT near main)", observation.text)
        self.assertIn(
            "Previous validation error: An action used a numeric enum value.",
            observation.text,
        )

    def test_compact_units_keep_their_semantic_locations(self):
        bot = Bot()
        near_main = Unit(218, "MARINE")
        near_enemy = Unit(361, "MARINE")
        near_enemy.position = Point(90, 90)
        bot.units.extend([near_main, near_enemy])

        observation = ObservationBuilder(TagIdMapper()).build(
            bot, iteration=0, _phase="opening_factory"
        )

        self.assertIn(
            "[217] [218] Marines\nStatus: active.\nLocation: near our main.",
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
            bot, iteration=0, _phase="opening_factory"
        )

        self.assertIn("[88] Stalker\nStatus: visible; near our main.", observation.text)
        self.assertIn("[99] Zealot\nStatus: visible; near enemy main.", observation.text)

    def test_empty_enemy_sections_explain_visibility_scope(self):
        bot = Bot()
        bot.enemy_units = []

        observation = ObservationBuilder(TagIdMapper()).build(
            bot, iteration=0, _phase="opening_factory"
        )

        self.assertIn("[Empty \u2014 no enemy units are visible now.]", observation.text)
        self.assertIn("[Empty \u2014 no enemy structures are visible now.]", observation.text)

    def test_prompts_use_named_sections_and_give_bm_the_complete_tactic(self):
        tactic = {
            "concept": "Build Battlecruisers.",
            "rules": ["Stay safe."],
            "phases": [
                {
                    "id": "opening_factory",
                    "enter_when": ["The Factory has not started."],
                    "goal": "Start production.",
                    "guidance": ["Build a Depot."],
                },
                {
                    "id": "opening_air_tech",
                    "enter_when": ["The Factory has started."],
                    "goal": "Start air technology.",
                    "guidance": ["Build a Starport."],
                },
            ],
        }
        catalog = ActionCatalog.load()
        entries = catalog.prompt_entries(allowed_actions("opening_factory"))
        bm = bm_messages("# Round state\n[Empty]", tactic, entries, "cold start")
        im = im_messages("# Round state\n[Empty]", ["Build a Depot."], [])

        self.assertIn("# Your current task", bm[-1]["content"])
        self.assertIn("The game has just started.", bm[-1]["content"])
        self.assertIn("# Observation", bm[-1]["content"])
        self.assertIn("# Complete tactical card", bm[-1]["content"])
        self.assertIn("## Core idea", bm[-1]["content"])
        self.assertIn("### Phase `opening_factory`", bm[-1]["content"])
        self.assertIn("### Phase `opening_air_tech`", bm[-1]["content"])
        self.assertIn("#### Enter when", bm[-1]["content"])
        self.assertIn("#### Complete guidance", bm[-1]["content"])
        self.assertIn("# Available actions", bm[-1]["content"])
        self.assertIn("`BuildStructure(base_location, structure_id)`:", bm[-1]["content"])
        self.assertIn("# JSON format and example", bm[-1]["content"])
        self.assertIn('"phase":"opening_factory"', bm[-1]["content"])
        self.assertIn("# Objective", im[-1]["content"])
        self.assertIn("# Observation", im[-1]["content"])
        self.assertIn("# Strategic guidance to follow", im[-1]["content"])
        self.assertIn("# Rules", im[-1]["content"])
        self.assertIn("# Available actions", im[-1]["content"])
        self.assertIn("# JSON format and example", im[-1]["content"])

    def test_action_cards_use_short_names_and_required_params_only(self):
        catalog = ActionCatalog.load()
        entries = catalog.prompt_entries(allowed_actions("bc_pressure"))
        prompt = im_messages("# Round state\n[Empty]", [], entries)[-1]["content"]

        self.assertIn("`AMove(unit, target)`: A-Move a unit to a target.", prompt)
        self.assertIn(
            "# Argument type legend",
            prompt,
        )
        self.assertIn(
            "- `[Unit]`: One unit ID from Observation.",
            prompt,
        )
        self.assertIn(
            "- `unit` [Unit]: The unit that will attack-move.",
            prompt,
        )
        self.assertIn(
            "- `target` [Point | Unit]: Where the unit is going.",
            prompt,
        )
        self.assertIn(
            "`BuildStructure(base_location, structure_id)`:", prompt
        )
        self.assertIn(
            "`TacticalJump(unit, target)`: Tactical Jump a ready Battlecruiser to a destination.",
            prompt,
        )
        self.assertIn(
            "`MoveSafely(unit, target)`: Move a Battlecruiser to a destination using safe air pathing.",
            prompt,
        )
        self.assertNotIn("`UseAbility(ability, unit)`", prompt)
        self.assertNotIn("combat.individual.a_move", prompt)
        self.assertNotIn("success_at_distance", prompt)
        self.assertNotIn("group_tags", prompt)
        self.assertNotIn("Union[Point2, Unit]", prompt)

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
