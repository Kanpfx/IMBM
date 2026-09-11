import unittest
from game.observation.builder import ObservationBuilder
from game.observation.state import TagIdMapper
from knowledge.loader import ActionCatalog
from llm.agents.prompts import MODEL_ROLE, model_messages


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
        self.is_memory = False
        self.age = 0.0
        self.orders = []
        self.position = Point(10, 10)


class Mediator:
    get_own_nat = None
    get_ground_enemy_near_bases = {}
    get_flying_enemy_near_bases = {}


class Bot:
    def __init__(self):
        self.units = [Unit(497, "SCV"), Unit(641, "SCV"), Unit(217, "MARINE")]
        command_center = Unit(102, "COMMANDCENTER", idle=True)
        command_center.assigned_harvesters = 2
        command_center.ideal_harvesters = 16
        self.structures = [command_center]
        self.enemy_units = [Unit(88, "STALKER")]
        self.enemy_structures = []
        self.workers = self.units[:2]
        self.townhalls = [command_center]
        self.gas_buildings = []
        self.minerals = 50
        self.vespene = 0
        self.supply_used = 12
        self.supply_cap = 15
        self.supply_workers = 2
        self.supply_army = 1
        self.time_formatted = "00:00"
        self.enemy_race = type("Race", (), {"name": "Protoss"})()
        self.race = type("Race", (), {"name": "Terran"})()
        self.game_info = type("GameInfo", (), {"map_size": Point(128, 128)})()
        score = type(
            "Score",
            (),
            {
                "collection_rate_minerals": 900,
                "collection_rate_vespene": 300,
                "killed_value_units": 0,
                "killed_value_structures": 0,
                "lost_minerals_army": 0,
                "lost_vespene_army": 0,
            },
        )()
        self.state = type("State", (), {"score": score})()
        self.start_location = Point(1, 1)
        self.enemy_start_locations = [Point(100, 100)]
        self.mediator = Mediator()
        self.pending = {}

    def already_pending(self, unit_type):
        return self.pending.get(unit_type.name, 0)


class ObservationTests(unittest.TestCase):
    def test_observation_ids_remain_stable_beyond_one_thousand_entities(self):
        mapper = TagIdMapper()
        aliases = [mapper.alias(tag) for tag in range(1100)]

        self.assertEqual(len(set(aliases)), 1100)
        self.assertEqual(mapper.alias(42), aliases[42])


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
        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn("[3] Battlecruiser", observation.text)
        self.assertIn("Health: 440/550 (80%)", observation.text)
        self.assertIn("Position: (10, 10), near our main", observation.text)
        self.assertIn("Energy: 125/200", observation.text)
        self.assertIn("Tactical Jump: ready", observation.text)
        self.assertIn("Yamato Cannon: ready", observation.text)
        self.assertIn("[5] Starport", observation.text)


    def test_post_execution_failure_updates_accepted_history(self):
        builder = ObservationBuilder(TagIdMapper())
        action = {
            "id": "BuildStructure",
            "args": {"structure_id": "FACTORY", "base_location": "main"},
        }
        builder.record_registered_actions([action], time="05:10")
        builder.record_failed_actions([action], time="05:20", reason="insufficient resources")
        text = builder.build(Bot(), iteration=10).text
        self.assertIn("`failed` | insufficient resources", text)
        self.assertEqual(text.count("BuildStructure(structure_id=FACTORY, base_location=main)"), 1)

    def test_active_history_survives_recent_history_limit_and_replacement(self):
        builder = ObservationBuilder(TagIdMapper())
        old = {"id": "GasBuildingController", "args": {"to_count": 2}}
        new = {"id": "GasBuildingController", "args": {"to_count": 3}}
        builder.sync_active_actions([old], "05:10")
        for index in range(15):
            builder.record_registered_actions(
                [{"id": "AMove", "args": {"unit": str(index), "target": "main"}}]
            )
        text = builder.build(Bot(), iteration=10).text
        self.assertIn("GasBuildingController(to_count=2)` | `active`", text)
        builder.sync_active_actions([new], "05:20")
        text = builder.build(Bot(), iteration=20).text
        self.assertNotIn("GasBuildingController(to_count=2)", text)
        self.assertIn("GasBuildingController(to_count=3)` | `active`", text)
        for obsolete in ("`queued`", "`expired`", "`complete`"):
            self.assertNotIn(obsolete, text)


    def test_enemy_memory_uses_non_actionable_ids(self):
        bot = Bot()
        remembered = Unit(91, "DARKTEMPLAR")
        remembered.is_visible = True
        remembered.is_memory = True
        remembered.age = 7.8
        remembered_second = Unit(93, "DARKTEMPLAR")
        remembered_second.is_visible = True
        remembered_second.is_memory = True
        remembered_second.age = 12.2
        snapshot = Unit(92, "BARRACKS")
        snapshot.is_visible = False
        bot.enemy_units.extend((remembered, remembered_second))
        bot.enemy_structures.append(snapshot)

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn(
            "<recently_seen_units>\n"
            "      [*,*] Darktemplars\n"
            "        Status: last seen 7-12s ago\n"
            "        Location: near our main",
            observation.text,
        )
        self.assertIn(
            "<known_structures>\n"
            "      [*] Barracks\n"
            "        Status: last known\n"
            "        Last known position: (10, 10), near our main",
            observation.text,
        )
        self.assertEqual(len(observation.context.enemy_entities), 1)


    def test_production_and_technology_is_generic(self):
        bot = Bot()
        barracks = Unit(700, "BARRACKS", idle=True)
        factory = Unit(701, "FACTORY", progress=0.64)
        engineering_bay = Unit(702, "ENGINEERINGBAY")
        supply_depot = Unit(703, "SUPPLYDEPOT")
        refinery = Unit(704, "REFINERY")
        bot.structures.extend(
            [barracks, factory, engineering_bay, supply_depot, refinery]
        )

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn("Production in progress: [None].", observation.text)
        self.assertIn("Research in progress: [None].", observation.text)
        self.assertIn("Completed upgrades: [None].", observation.text)
        self.assertIn(
            "Available technology steps: Factory, Ghost Academy, Sensor Tower.",
            observation.text,
        )
        self.assertIn("Construction: Factory (64%)", observation.text)
        self.assertNotIn("Production unlocked:", observation.text)
        self.assertNotIn("Idle production:", observation.text)

    def test_prompt_combines_observation_tactic_actions_and_output_contract(self):
        tactic = {
            "id": "BattleCruiserRush",
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
        messages = model_messages(
            "# Round state\n[None]",
            tactic,
            entries,
            max_actions_per_decision=4,
        )
        prompt = messages[-1]["content"]

        self.assertEqual(messages[0]["content"], MODEL_ROLE)
        self.assertNotIn("<task>", prompt)
        self.assertIn("# Round state", prompt)
        self.assertNotIn("<observation>", prompt)
        self.assertNotIn("</observation>", prompt)
        self.assertIn("<global_rules>", prompt)
        self.assertIn("1. Automation continuously maintains", prompt)
        self.assertIn("11. The game continues while you decide", prompt)
        self.assertIn("Omitting an active instruction keeps it active", prompt)
        self.assertIn("One-time action.", prompt)
        self.assertIn("<tactical_reference>", prompt)
        self.assertIn("**Tactic ID:** `BattleCruiserRush`", prompt)
        self.assertIn("**Tactic concept:** Build Battlecruisers.", prompt)
        self.assertIn("**Global tactic rules:**", prompt)
        self.assertIn(
            '<phase index="1">\n    **Phase ID:** `opening_tech`', prompt
        )
        self.assertIn("**Phase ID:** `opening_tech`", prompt)
        self.assertIn('<phase index="2">', prompt)
        self.assertIn("**Phase ID:** `first_bc_preparation`", prompt)
        self.assertIn("**Selection criteria:**", prompt)
        self.assertIn("**Objective:** Start production.", prompt)
        self.assertIn("**Guidance:**", prompt)
        self.assertIn("</phase>", prompt)
        self.assertIn("</tactical_reference>", prompt)
        self.assertNotIn("<decision_context>", prompt)
        self.assertIn("<actions_reference>", prompt)
        self.assertIn("<argument_definitions>", prompt)
        self.assertIn("<available_actions>", prompt)
        self.assertIn("- `BuildStructure(", prompt)
        self.assertIn("<output_contract>", prompt)
        self.assertIn("<output_contract>\n  Output constraints are as follows:", prompt)
        self.assertIn("  ```text\n  # phase\n  PHASE_ID\n\n  # actions", prompt)
        self.assertIn("  ActionName(argument=value,...)", prompt)
        self.assertIn("  ```\n</output_contract>", prompt)
        self.assertIn("Use bare names for enums and landmarks", prompt)
        self.assertIn("Avoid repeating an action that is already active", prompt)
        self.assertIn("Strongly prefer group actions", prompt)
        self.assertIn("return 0-4 currently available actions", prompt)
        self.assertNotIn("return 0-8 currently available actions", prompt)
        self.assertLess(prompt.index("<tactical_reference>"), prompt.index("<actions_reference>"))
        self.assertLess(prompt.index("<actions_reference>"), prompt.index("# Round state"))
        self.assertLess(prompt.index("# Round state"), prompt.index("<output_contract>"))
        self.assertTrue(
            prompt.endswith(
                "Return your decision for the current observation."
            )
        )
        self.assertNotIn('"actions": [', prompt)
        self.assertIn("<previous_validation_feedback>", prompt)
        self.assertIn("  [None]\n</previous_validation_feedback>", prompt)
        self.assertNotIn("Valid example:", prompt)
