import unittest

from game.actions.adapter import AresActionAdapter
from game.actions.resolver import EntityContext
from game.control.automation import AutomationController
from game.control.macro_plan import MacroPlanController
from knowledge.loader import ActionCatalog


def composition(unit_name):
    return {unit_name: {"proportion": 1.0, "priority": 0}}


class Bot:
    def __init__(self):
        self.start_location = object()
        self.registered = []

    def register_behavior(self, behavior):
        self.registered.append(behavior)


class MacroPlanControllerTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ActionCatalog.load()
        self.adapter = AresActionAdapter(self.catalog)
        self.controller = MacroPlanController(self.catalog)
        self.context = EntityContext(positions={"main": object()})

    def test_effective_plan_uses_why_priority_and_im_worker_override(self):
        actions = [
            {"id": "ExpansionController", "args": {"to_count": 2}},
            {"id": "BuildWorkers", "args": {"to_count": 35}},
            {
                "id": "SpawnController",
                "args": {"army_composition_dict": composition("MARINE")},
            },
            {"id": "GasBuildingController", "args": {"to_count": 2}},
            {
                "id": "ProductionController",
                "args": {
                    "army_composition_dict": composition("MARINE"),
                    "base_location": "main",
                },
            },
            {"id": "UpgradeCCs", "args": {"to": "ORBITALCOMMAND"}},
            {
                "id": "UpgradeController",
                "args": {
                    "upgrade_list": ["TERRANINFANTRYWEAPONSLEVEL1"],
                    "base_location": "main",
                },
            },
        ]
        macro, other = self.controller.replace_cycle(actions)
        bot = Bot()

        plan = self.controller.register(bot, self.adapter, self.context)

        self.assertEqual(macro, actions)
        self.assertEqual(other, [])
        self.assertEqual(bot.registered, [plan])
        self.assertEqual(
            [type(behavior).__name__ for behavior in plan.macros],
            [
                "ProductionController",
                "AutoSupply",
                "GasBuildingController",
                "UpgradeCCs",
                "UpgradeController",
                "SpawnController",
                "BuildWorkers",
                "ExpansionController",
            ],
        )
        self.assertEqual(plan.macros[-2].to_count, 35)

    def test_im_slot_persists_until_the_next_output_then_defaults_resume(self):
        self.controller.replace_cycle(
            [{"id": "BuildWorkers", "args": {"to_count": 35}}]
        )

        first = self.controller.register(Bot(), self.adapter, self.context)
        same_cycle = self.controller.register(Bot(), self.adapter, self.context)
        self.controller.replace_cycle([])
        next_cycle = self.controller.register(Bot(), self.adapter, self.context)

        self.assertEqual(first.macros[-1].to_count, 35)
        self.assertEqual(same_cycle.macros[-1].to_count, 35)
        self.assertEqual(next_cycle.macros[-1].to_count, 20)

    def test_first_im_spawn_overrides_other_spawn_requests_in_the_same_slot(self):
        first = {
            "id": "SpawnController",
            "args": {"army_composition_dict": composition("MARINE")},
        }
        second = {
            "id": "SpawnController",
            "args": {"army_composition_dict": composition("HELLION")},
        }

        macro, other = self.controller.replace_cycle([first, second])
        plan = self.controller.register(Bot(), self.adapter, self.context)
        spawns = [
            item for item in plan.macros if type(item).__name__ == "SpawnController"
        ]

        self.assertEqual(macro, [first])
        self.assertEqual(other, [])
        self.assertEqual(len(spawns), 1)
        self.assertEqual(next(iter(spawns[0].army_composition_dict)).name, "MARINE")

    def test_opening_tasks_remain_in_the_direct_im_execution_path(self):
        action = {
            "id": "BuildStructure",
            "args": {"base_location": "main", "structure_id": "BARRACKS"},
        }

        macro, other = self.controller.replace_cycle([action])

        self.assertEqual(macro, [])
        self.assertEqual(other, [action])


class AutomationControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_mining_is_registered_as_a_behavior(self):
        class AutomationBot(Bot):
            supply_workers = 12
            tactic_name = "BattleCruiserRush"

            def _mules(self):
                pass

            def _general_repair(self):
                pass

            def _look_for_terran_bunker(self):
                pass

        bot = AutomationBot()

        await AutomationController().run(bot, iteration=1)

        self.assertEqual([type(item).__name__ for item in bot.registered], ["Mining"])
