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
        self.race = type("Race", (), {"name": "Terran"})()
        self.start_location = Point(1, 1)
        self.enemy_start_locations = [Point(100, 100)]
        self.mediator = Mediator()
        self.pending = {}

    def already_pending(self, unit_type):
        return self.pending.get(unit_type.name, 0)


class ObservationTests(unittest.TestCase):
    def test_shared_observation_aggregates_workers_and_hides_internal_details(self):
        builder = ObservationBuilder(TagIdMapper())
        observation = builder.build(Bot(), iteration=0)

        self.assertEqual(observation.text, observation.strategy_text)
        self.assertEqual(observation.text, observation.action_text)
        self.assertTrue(observation.text.startswith("<overview>\n"))
        self.assertIn("</overview>", observation.text)
        self.assertIn("<own_state>", observation.text)
        self.assertIn("<enemy_state>", observation.text)
        self.assertIn("<recent_history>", observation.text)
        self.assertIn("<resources_and_supply>", observation.text)
        self.assertIn("<economy>", observation.text)
        self.assertIn("<military_summary>", observation.text)
        self.assertIn("<situation_alerts>", observation.text)
        self.assertIn("<units>", observation.text)
        self.assertIn("<structures>", observation.text)
        self.assertIn("<production_and_technology>", observation.text)
        self.assertNotIn("<infrastructure>", observation.text)
        self.assertNotIn("<current_capabilities>", observation.text)
        self.assertNotIn("<available_technology_steps>", observation.text)
        self.assertIn("<visible_units>", observation.text)
        self.assertIn("<known_structures>", observation.text)
        self.assertIn("<last_known_units>", observation.text)
        self.assertIn("<state_changes>", observation.text)
        self.assertIn("<action_history>", observation.text)
        self.assertNotIn("<action_feedback>", observation.text)
        self.assertNotIn("## ", observation.text)
        self.assertIn("  <match>\n    ", observation.text)
        self.assertIn("    <combat>\n      ", observation.text)
        self.assertIn("  </match>", observation.text)
        self.assertIn("Bases: 1 active, 0 building.", observation.text)
        self.assertIn("Army: 1 supply", observation.text)
        self.assertIn(
            "[497,641] SCV\n    Status: collecting resources automatically.",
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
        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

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
        observation = builder.build(Bot(), iteration=10)

        self.assertIn(
            "05:10 macro.build_structure(structure_id=SUPPLYDEPOT, "
            "base_location=main) status: completed",
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

        observation = builder.build(Bot(), iteration=10)

        self.assertIn(
            "05:10 BuildStructure(structure_id=FACTORY, base_location=main) "
            "status: completed",
            observation.text,
        )
        self.assertIn(
            "05:11 TechUp(desired_tech=STARPORT, base_location=main) "
            "status: expired",
            observation.text,
        )
        self.assertEqual(
            observation.text.count(
                "BuildStructure(structure_id=FACTORY, base_location=main)"
            ),
            1,
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

        observation = builder.build(Bot(), iteration=10)

        self.assertIn(
            "KeepUnitSafe(unit=1, grid=ground) status: completed", observation.text
        )
        self.assertIn(
            "PathUnitToTarget(unit=2, grid=ground, target=main) status: failed",
            observation.text,
        )
        self.assertIn(
            "KeepUnitSafe(unit=1, grid=ground) status: completed\n"
            "    05:11 PathUnitToTarget(unit=2, grid=ground, target=main) "
            "status: failed",
            observation.text,
        )
        self.assertNotIn("status: active", observation.text)

    def test_compact_units_keep_their_semantic_locations(self):
        bot = Bot()
        near_main = Unit(218, "MARINE")
        near_enemy = Unit(361, "MARINE")
        near_enemy.position = Point(90, 90)
        bot.units.extend([near_main, near_enemy])

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn(
            "[217,218] Marines\n    Status: active.\n    Location: near our main.",
            observation.text,
        )
        self.assertIn(
            "[361] Marine\n    Status: active.\n    Location: near enemy main.",
            observation.text,
        )

    def test_enemy_location_is_based_on_each_enemy_tag(self):
        bot = Bot()
        other_enemy = Unit(99, "ZEALOT")
        other_enemy.position = Point(90, 90)
        bot.enemy_units.append(other_enemy)
        bot.mediator.get_ground_enemy_near_bases = {bot.structures[0].tag: {88}}

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn("[88] Stalker\n    Status: visible; near our main.", observation.text)
        self.assertIn(
            "[99] Zealot\n    Status: visible; near enemy main.", observation.text
        )
        self.assertIn("Enemy ground units are close to our main.", observation.text)

    def test_empty_enemy_sections_explain_visibility_scope(self):
        bot = Bot()
        bot.enemy_units = []

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertEqual(observation.text.count("[None visible]"), 1)
        self.assertIn("[None known]", observation.text)

    def test_last_known_enemy_intelligence_is_brief(self):
        bot = Bot()
        remembered = Unit(91, "DARKTEMPLAR")
        remembered.is_visible = False
        remembered.is_memory = True
        remembered.age = 7.8
        bot.enemy_units.append(remembered)

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn("<last_known_units>", observation.text)
        self.assertIn(
            "1 Darktemplar last seen near our main, 7s ago.", observation.text
        )
        self.assertNotIn("[91]", observation.text)

    def test_unknown_last_known_enemy_is_ignored(self):
        class UnknownMemoryUnit:
            tag = 92
            type_id = None
            is_visible = False
            is_memory = True
            age = 4.0
            position = Point(10, 10)

            @property
            def name(self):
                raise KeyError(0)

        bot = Bot()
        bot.enemy_units.append(UnknownMemoryUnit())

        observation = ObservationBuilder(TagIdMapper()).build(bot, iteration=0)

        self.assertIn("<last_known_units>\n    [None]", observation.text)
        self.assertNotIn("UNKNOWN", observation.text)

    def test_structure_changes_distinguish_building_from_ready(self):
        bot = Bot()
        builder = ObservationBuilder(TagIdMapper())
        builder.build(bot, iteration=0)

        factory = Unit(700, "FACTORY", progress=0.25)
        bot.structures.append(factory)
        building = builder.build(bot, iteration=10)
        self.assertIn("Status: building (25%).", building.text)
        self.assertIn("Our Factory started building.", building.text)
        self.assertNotIn("Our Factory became ready.", building.text)

        factory.build_progress = 1.0
        ready = builder.build(bot, iteration=20)
        self.assertIn("Status: ready.", ready.text)
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
        self.assertNotIn("Construction: Factory", observation.text)
        self.assertNotIn("Production unlocked:", observation.text)
        self.assertNotIn("Idle production:", observation.text)

    def test_prompts_use_named_sections_and_give_bm_the_complete_tactic(self):
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
        bm = bm_messages("# Round state\n[None]", tactic, entries, "cold start")
        im = im_messages("# Round state\n[None]", ["Build a Depot."], [])

        self.assertNotIn("<task>", bm[-1]["content"])
        self.assertNotIn("Review the current observation", bm[-1]["content"])
        self.assertIn("<observation>", bm[-1]["content"])
        self.assertIn("<tactical_reference>", bm[-1]["content"])
        self.assertIn("**Tactic ID:** `BattleCruiserRush`", bm[-1]["content"])
        self.assertIn("**Tactic concept:** Build Battlecruisers.", bm[-1]["content"])
        self.assertIn("**Global tactic rules:**", bm[-1]["content"])
        self.assertIn('<phase_reference index="1">', bm[-1]["content"])
        self.assertIn("**Phase ID:** `opening_tech`", bm[-1]["content"])
        self.assertIn("</phase_reference>", bm[-1]["content"])
        self.assertIn('<phase_reference index="2">', bm[-1]["content"])
        self.assertIn("**Phase ID:** `first_bc_preparation`", bm[-1]["content"])
        self.assertIn("**Phase selection criteria:**", bm[-1]["content"])
        self.assertIn("**Phase objective:** Start production.", bm[-1]["content"])
        self.assertIn("**Phase guidance:**", bm[-1]["content"])
        self.assertIn("</tactical_reference>", bm[-1]["content"])
        self.assertIn("<argument_types>", bm[-1]["content"])
        self.assertIn("<available_actions>", bm[-1]["content"])
        self.assertIn("- `BuildStructure(", bm[-1]["content"])
        self.assertIn("<output_contract>", bm[-1]["content"])
        self.assertIn("**Required JSON template:**", bm[-1]["content"])
        self.assertIn('  "phase": "<phase ID>"', bm[-1]["content"])
        self.assertIn('    "<strategic priority 1>"', bm[-1]["content"])
        self.assertNotIn("Valid example:", bm[-1]["content"])
        self.assertIn("<observation>", im[-1]["content"])
        self.assertIn("<decision_context>", im[-1]["content"])
        self.assertIn("**Strategic guidance:**", im[-1]["content"])
        self.assertIn("**Decision rules:**", im[-1]["content"])
        self.assertIn("<argument_types>", im[-1]["content"])
        self.assertIn("<available_actions>", im[-1]["content"])
        self.assertIn("<output_contract>", im[-1]["content"])
        self.assertIn("**Required JSON template:**", im[-1]["content"])
        self.assertIn('      "id": "<action name>"', im[-1]["content"])
        self.assertIn(
            '        "<argument name>": "<argument value>"', im[-1]["content"]
        )
        self.assertNotIn("Valid example:", im[-1]["content"])
        self.assertNotIn("<priority>", im[-1]["content"])
        self.assertNotIn("<rule>", im[-1]["content"])
        self.assertNotRegex(
            "\n".join(message["content"] for message in [*bm, *im]),
            r"\b(?:BM|IM|IMBM)\b",
        )

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
        prompt = im_messages("# Round state\n[None]", [], entries)[-1]["content"]

        self.assertIn("- `AMove(unit: Unit, target: Point | Unit)`", prompt)
        self.assertIn(
            ": Attack-move a unit toward a target.",
            prompt,
        )
        self.assertIn("<argument_types>", prompt)
        self.assertIn("Argument types, value formats, and current constraints", prompt)
        self.assertIn("All `proportion` values must sum to `1.0`.", prompt)
        self.assertIn(
            "- `Unit`: One unit or structure ID from the current observation.",
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
        correction_prompt = correction_messages(
            "<state_summary>\nstate\n</state_summary>",
            ["Build the Factory."],
            entries,
            [{"id": "BuildStructure", "args": {}}],
            ["Action 1: missing required argument"],
        )
        correction = correction_prompt[-1]["content"]

        self.assertEqual(
            correction_prompt[0]["content"],
            "You are responsible for repairing rejected executable actions for a "
            "StarCraft II bot.\n\n"
            "Use the current observation, strategic guidance, validation errors, "
            "and available action set to correct rejected actions.\n\n"
            "Output only one valid JSON object containing the corrected `actions` "
            "list. Do not output natural-language explanations, code, extra text, "
            "chain-of-thought, `<thinking>` content, or other reasoning traces.",
        )
        self.assertIn("<strategic_guidance>", correction)
        self.assertIn("- Build the Factory.", correction)
        self.assertIn("<rejected_actions>", correction)
        self.assertIn("**Action:**", correction)
        self.assertIn("**Validation error:**", correction)
        self.assertIn("missing required argument", correction)
        self.assertNotIn("Action 1: missing required argument", correction)
        self.assertNotIn('<rejected_action index="', correction)
        self.assertNotIn("</rejected_action>", correction)
        self.assertIn("</rejected_actions>", correction)
        self.assertIn("<repair_rules>", correction)
        self.assertIn("Repair only the rejected actions", correction)
        self.assertIn("</repair_rules>", correction)
        self.assertNotIn("<correction_context>", correction)
        self.assertNotIn("**Validation errors:**", correction)
        self.assertIn("<argument_types>", correction)
        self.assertIn("<available_actions>", correction)
        self.assertIn("<output_contract>", correction)
        self.assertNotIn("<error>", correction)
        self.assertNotIn("<rule>", correction)
        self.assertNotRegex(
            "\n".join(message["content"] for message in correction_prompt),
            r"\b(?:BM|IM|IMBM)\b",
        )

        paired = correction_messages(
            "state",
            [],
            entries,
            [
                {"id": "BuildStructure", "args": {}},
                {"id": "BuildStructure", "args": {"structure_id": "REFINERY"}},
            ],
            ["missing structure_id", "REFINERY is unsupported"],
        )[-1]["content"]
        first = paired.index("**Action 1:**")
        second = paired.index("**Action 2:**")
        self.assertIn("**Validation error 1:**", paired[first:second])
        self.assertIn("**Validation error 2:**", paired[second:])
        self.assertLess(first, paired.index("missing structure_id", first, second))
        self.assertLess(second, paired.index("REFINERY is unsupported", second))

        refined = refine_messages([], "actions must be a list", '{"actions":[]}')
        self.assertEqual(refined[0]["content"], "Previous output was rejected.")
        self.assertIn("<correction_request>", refined[1]["content"])
        self.assertIn(
            "**Validation error:** actions must be a list", refined[1]["content"]
        )
        self.assertIn(
            '**Required JSON template:** {"actions":[]}', refined[1]["content"]
        )
        self.assertNotIn("### Validation Error", refined[1]["content"])

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
