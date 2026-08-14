import unittest

from game.control.automation import AutomationController


class Bot:
    def __init__(self):
        self.start_location = object()
        self.supply_workers = 12
        self.tactic_name = "BattleCruiserRush"
        self.registered = []

    def register_behavior(self, behavior):
        self.registered.append(behavior)

    def _mules(self):
        pass

    def _general_repair(self):
        pass

    def _look_for_terran_bunker(self):
        pass


class AutomationControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_economy_automation_runs_without_a_macro_plan(self):
        bot = Bot()
        controller = AutomationController()

        await controller.run(bot, iteration=1)
        controller.register_worker_production(bot)

        self.assertEqual(
            [type(item).__name__ for item in bot.registered],
            ["Mining", "AutoSupply", "BuildWorkers"],
        )
        self.assertEqual(bot.registered[-1].to_count, 20)

    async def test_im_worker_target_overrides_only_the_current_cycle(self):
        controller = AutomationController(default_worker_target=20)
        action = {"id": "BuildWorkers", "args": {"to_count": 35}}

        previous, changed = controller.replace_worker_override(action)
        overridden_bot = Bot()
        controller.register_worker_production(overridden_bot)

        self.assertIsNone(previous)
        self.assertTrue(changed)
        self.assertEqual(overridden_bot.registered[-1].to_count, 35)

        previous, changed = controller.replace_worker_override(None)
        default_bot = Bot()
        controller.register_worker_production(default_bot)

        self.assertEqual(previous, action)
        self.assertTrue(changed)
        self.assertEqual(default_bot.registered[-1].to_count, 20)

    def test_repeated_worker_override_does_not_create_a_state_transition(self):
        controller = AutomationController()
        action = {"id": "BuildWorkers", "args": {"to_count": 30}}

        controller.replace_worker_override(action)
        previous, changed = controller.replace_worker_override(action)

        self.assertEqual(previous, action)
        self.assertFalse(changed)
