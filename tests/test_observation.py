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

    def test_observation_aggregates_workers_and_hides_internal_details(self):
        builder = ObservationBuilder(TagIdMapper())
        observation = builder.build(Bot(), iteration=0)

        self.assertTrue(observation.text.startswith("<overview>\n"))
        self.assertIn("</overview>", observation.text)
        self.assertIn("<own_state>", observation.text)
        self.assertIn("<enemy_state>", observation.text)
        self.assertIn("<recent_history>", observation.text)
        self.assertNotIn("<match>", observation.text)
        self.assertNotIn("<resources_and_supply>", observation.text)
        self.assertNotIn("<economy>", observation.text)
        self.assertNotIn("<military_summary>", observation.text)
        self.assertNotIn("<situation_alerts>", observation.text)
        self.assertIn("<units>", observation.text)
        self.assertIn("<structures>", observation.text)
        self.assertIn("<production_and_technology>", observation.text)
        self.assertNotIn("<infrastructure>", observation.text)
        self.assertNotIn("<current_capabilities>", observation.text)
        self.assertNotIn("<available_technology_steps>", observation.text)
        self.assertIn("<visible_units>", observation.text)
        self.assertIn("<visible_structures>", observation.text)
        self.assertIn("<enemy_memory>", observation.text)
        self.assertIn("<recently_seen_units>", observation.text)
        self.assertIn("<known_structures>", observation.text)
        self.assertNotIn("<last_known_units>", observation.text)
        self.assertIn("<state_changes>", observation.text)
        self.assertIn("<action_history>", observation.text)
        self.assertNotIn("<action_feedback>", observation.text)
        self.assertNotIn("## ", observation.text)
        self.assertIn("Time: 00:00", observation.text)
        self.assertIn(
            "Matchup: Terran (you) vs Protoss (enemy)",
            observation.text,
        )
        self.assertIn("Map size: 128 x 128", observation.text)
        self.assertIn("Resources: 50 minerals, 0 vespene", observation.text)
        self.assertIn(
            "Income: 900 minerals/min, 300 vespene/min",
            observation.text,
        )
        self.assertIn(
            "Supply: 12/15 (workers 2, army 1, free 3)",
            observation.text,
        )
        self.assertIn("  Situational hints:", observation.text)
        self.assertIn(
            "Economy: 1 base ready, 0 under construction; 2 workers, 0 idle",
            observation.text,
        )
        self.assertIn("Saturation: main 2/16", observation.text)
        self.assertIn("Army: 1 supply (1 Marine)", observation.text)
        self.assertIn(
            "Visible enemy: 1 unit, 0 structures (1 Stalker)",
            observation.text,
        )
        self.assertIn(
            "[0,1] SCV\n"
            "      Status: collecting resources automatically\n"
            "      Location: near our main",
            observation.text,
        )
        self.assertIn("[4] Stalker", observation.text)
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
        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn("[3] Battlecruiser", observation.text)
        self.assertIn("Health: 440/550 (80%)", observation.text)
        self.assertIn("Position: (10, 10), near our main", observation.text)
        self.assertIn("Energy: 125/200", observation.text)
        self.assertIn("Tactical Jump: ready", observation.text)
        self.assertIn("Yamato Cannon: ready", observation.text)
        self.assertIn("[5] Starport", observation.text)

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
        observation = builder.build(Bot(), iteration=10)

        self.assertIn(
            "| 05:10 | `macro.build_structure(structure_id=SUPPLYDEPOT, "
            "base_location=main)` | `complete` |",
            observation.text,
        )

    def test_queued_history_updates_in_place_when_complete_or_expired(self):
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

        observation = builder.build(Bot(), iteration=10)

        self.assertIn(
            "| 05:10 | `BuildStructure(structure_id=FACTORY, base_location=main)` "
            "| `complete` |",
            observation.text,
        )
        self.assertIn(
            "| 05:11 | `TechUp(desired_tech=STARPORT, base_location=main)` "
            "| `expired` |",
            observation.text,
        )
        self.assertEqual(
            observation.text.count(
                "BuildStructure(structure_id=FACTORY, base_location=main)"
            ),
            1,
        )

    def test_persistent_history_uses_active_expired_and_failed_states(self):
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
        builder.record_expired_actions([active], time="05:20")
        builder.record_failed_actions([failed], time="05:20")

        observation = builder.build(Bot(), iteration=10)

        self.assertIn("`active`: Ongoing control currently in effect", observation.text)
        self.assertIn("| Time | Action | Status |", observation.text)
        self.assertIn(
            '| 05:10 | `KeepUnitSafe(unit="1", grid=ground)` | `expired` |',
            observation.text,
        )
        self.assertIn(
            '| 05:11 | `PathUnitToTarget(unit="2", grid=ground, target=main)` | `failed` |',
            observation.text,
        )

    def test_compact_units_keep_their_semantic_locations(self):
        bot = Bot()
        near_main = Unit(218, "MARINE")
        near_enemy = Unit(361, "MARINE")
        near_enemy.position = Point(90, 90)
        reaper = Unit(400, "REAPER")
        mules = [Unit(401, "MULE"), Unit(402, "MULE")]
        bot.units.extend([near_main, near_enemy, reaper, *mules])

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn(
            "[2,3] Marine\n" "      Status: active\n" "      Location: near our main",
            observation.text,
        )
        self.assertIn(
            "[4] Marine\n" "      Status: active\n" "      Location: near enemy main",
            observation.text,
        )
        self.assertIn("[6,7] MULE", observation.text)
        self.assertNotIn("MULEs", observation.text)
        self.assertLess(
            observation.text.index("[5] Reaper"),
            observation.text.index("[2,3] Marine"),
        )

    def test_enemy_location_is_based_on_each_enemy_tag(self):
        bot = Bot()
        other_enemy = Unit(99, "ZEALOT")
        other_enemy.position = Point(90, 90)
        bot.enemy_units.append(other_enemy)
        bot.mediator.get_ground_enemy_near_bases = {bot.structures[0].tag: {88}}

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn(
            "[4] Stalker\n      Status: visible; near our main", observation.text
        )
        self.assertIn(
            "[5] Zealot\n      Status: visible; near enemy main", observation.text
        )
        self.assertIn("Enemy ground units are close to our main.", observation.text)

    def test_empty_enemy_sections_explain_visibility_scope(self):
        bot = Bot()
        bot.enemy_units = []

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertEqual(observation.text.count("[None visible]"), 2)

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

    def test_compact_structures_group_by_status_and_location_with_health_list(self):
        bot = Bot()
        near_main = [
            Unit(700, "SUPPLYDEPOT"),
            Unit(701, "SUPPLYDEPOT"),
        ]
        near_main[0].health = 400
        near_main[0].health_max = 400
        near_main[1].health = 250
        near_main[1].health_max = 400
        near_enemy = Unit(702, "SUPPLYDEPOT")
        near_enemy.position = Point(90, 90)
        near_enemy.health = 400
        near_enemy.health_max = 400
        building = Unit(703, "SUPPLYDEPOT", progress=0.5)
        building.health = 200
        building.health_max = 400
        bot.structures.extend([*near_main, near_enemy, building])

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn(
            "[4,5] Supply Depot\n"
            "      Status: ready\n"
            "      Health: [400/400, 250/400]\n"
            "      Location: near our main",
            observation.text,
        )
        self.assertIn(
            "[6] Supply Depot\n"
            "      Status: ready\n"
            "      Health: [400/400]\n"
            "      Location: near enemy main",
            observation.text,
        )
        self.assertIn(
            "[7] Supply Depot\n"
            "      Status: building (50%)\n"
            "      Health: [200/400]\n"
            "      Location: near our main",
            observation.text,
        )
        self.assertNotIn("Supply Depots", observation.text)
        self.assertLess(
            observation.text.index("[3] Command Center"),
            observation.text.index("[4,5] Supply Depot"),
        )

    def test_structure_changes_distinguish_building_from_ready(self):
        bot = Bot()
        builder = ObservationBuilder(TagIdMapper())
        builder.build(bot, iteration=0)

        factory = Unit(700, "FACTORY", progress=0.25)
        bot.structures.append(factory)
        building = builder.build(bot, iteration=10)
        self.assertIn("Status: building (25%)", building.text)
        self.assertIn("Our Factory started building.", building.text)
        self.assertNotIn("Our Factory became ready.", building.text)

        factory.build_progress = 1.0
        ready = builder.build(bot, iteration=20)
        self.assertIn("Status: ready", ready.text)
        self.assertIn("Our Factory became ready.", ready.text)
        self.assertNotIn("Our Factory completed.", ready.text)

    def test_pending_units_are_reported_generically(self):
        bot = Bot()
        bot.pending["BATTLECRUISER"] = 1
        bot.pending["MARINE"] = 2
        bot.pending["SUPPLYDEPOT"] = 1
        bot.pending["REFINERY"] = 1

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn(
            "Production in progress: 1 Battlecruiser; 2 Marines.", observation.text
        )
        self.assertNotIn("Production in progress: 1 Refinery", observation.text)
        self.assertNotIn("Production in progress: 1 Supply Depot", observation.text)

    def test_situational_hints_cover_supply_risk_and_clear_when_resolved(self):
        bot = Bot()
        bot.supply_used = 15
        builder = ObservationBuilder(TagIdMapper())

        blocked = builder.build(bot, iteration=0)
        self.assertIn("Supply is blocked.", blocked.text)

        bot.supply_cap = 23
        resolved = builder.build(bot, iteration=10)
        self.assertNotIn("Supply is blocked.", resolved.text)

    def test_situational_hints_remember_recent_key_structure_damage(self):
        bot = Bot()
        bot.time = 10.0
        bot.structures[0].health = 1500
        bot.structures[0].health_max = 1500
        builder = ObservationBuilder(TagIdMapper())
        builder.collect_frame(bot)

        bot.time = 11.0
        bot.structures[0].health = 1400
        builder.collect_frame(bot)
        observation = builder.build(bot, iteration=10)

        self.assertIn(
            "Our Command Center near our main is under attack.", observation.text
        )

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
        prompt = model_messages(
            "# Round state\n[None]",
            {
                "id": "Test",
                "concept": "Test.",
                "rules": [],
                "phases": [
                    {
                        "id": "phase",
                        "enter_when": ["Always."],
                        "goal": "Test.",
                        "guidance": ["Act."],
                    }
                ],
            },
            entries,
        )[-1]["content"]

        self.assertIn("- `AMove(unit: Unit, target: Point | Unit)`", prompt)
        self.assertIn(
            ": Attack-move a unit toward a target.",
            prompt,
        )
        self.assertIn("<argument_definitions>", prompt)
        self.assertIn("The following definitions explain each argument type and its accepted value formats", prompt)
        self.assertIn("All `proportion` values must sum to `1.0`.", prompt)
        self.assertIn(
            "- `Unit`: One unit or structure ID from the current observation.",
            prompt,
        )
        self.assertIn(
            "- `BuildStructure(base_location: Point, structure_id: UnitType)`",
            prompt,
        )
        self.assertNotIn("  - `unit` (Unit):", prompt)
        self.assertNotIn("  - `target` (Point | Unit):", prompt)
        self.assertIn("- `TacticalJump(", prompt)
        self.assertIn("- `MoveSafely(", prompt)
        self.assertNotIn("- `UseAbility(", prompt)
        self.assertNotIn("<action name=", prompt)
        self.assertNotIn("<parameter name=", prompt)

        self.assertNotIn("combat.individual.a_move", prompt)
        self.assertNotIn("success_at_distance", prompt)
        self.assertNotIn("group_tags", prompt)
        self.assertNotIn("Union[Point2, Unit]", prompt)

    def test_previous_validation_feedback_follows_action_history(self):
        tactic = {
            "id": "Test",
            "concept": "Test.",
            "rules": [],
            "phases": [
                {
                    "id": "phase",
                    "enter_when": ["Always."],
                    "goal": "Test.",
                    "guidance": ["Act."],
                }
            ],
        }
        feedback = [
            {
                "kind": "action",
                "action": {"id": "BuildStructure", "args": {}},
                "error": "missing structure_id",
            }
        ]

        observation = "<recent_history>\n<action_history>\n[None]\n</action_history>\n</recent_history>"
        prompt = model_messages(observation, tactic, [], feedback)[-1]["content"]

        self.assertEqual(prompt.count("<previous_validation_feedback>"), 1)
        self.assertEqual(prompt.count("</previous_validation_feedback>"), 1)
        self.assertIn("1. Action: BuildStructure()", prompt)
        self.assertIn("BuildStructure()", prompt)
        self.assertNotIn('"kind":', prompt)
        self.assertIn("missing structure_id", prompt)
        self.assertLess(
            prompt.index("</action_history>"),
            prompt.index("<previous_validation_feedback>"),
        )
        self.assertLess(
            prompt.index("</previous_validation_feedback>"),
            prompt.index("</recent_history>"),
        )

    def test_catalog_corrects_verified_ares_documentation_errors(self):
        catalog = ActionCatalog.load()

        self.assertEqual(
            catalog.get("combat.group.keep_group_safe")["description"],
            "Move threatened units to safety; attack when possible.",
        )
        self.assertEqual(
            catalog.get("combat.individual.use_ability")["description"],
            "Use an ability, optionally on a target.",
        )
        self.assertEqual(
            catalog.get("macro.upgrade_c_cs")["description"],
            "Upgrade a Command Center to Orbital or Planetary.",
        )
        drop_target = next(
            param
            for param in catalog.get("combat.individual.drop_cargo")["params"]
            if param["name"] == "target"
        )
        self.assertIn("container's current position", drop_target["description"])
