import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from config.game import GameConfig
from config.llm import LLMConfig
from game.actions.execution import TrackedBehavior
from game.actions.persistent import PersistentActionRegistry
from game.actions.policy import ActionReview
from game.actions.resolver import EntityContext
from game.control.controller import LLMGameController
from game.observation.builder import Observation
from knowledge.loader import ActionCatalog
from llm.agents.model_agent import ModelResult


def result(actions=None, feedback=None):
    return ModelResult("opening_tech", actions or [], feedback or [], [], "", [], 10)


class AsyncControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = LLMGameController(
            GameConfig(model_interval_seconds=5),
            LLMConfig(model="test", base_url="https://example.invalid", api_key="test"),
            log_directory=Path(self.temp.name),
        )
        self.context = EntityContext()
        self.bot = SimpleNamespace(
            time=0.0, time_formatted="00:00", supply_workers=12,
            minerals=100, vespene=0,
            calculate_cost=Mock(return_value=SimpleNamespace(minerals=150, vespene=0)),
            tech_requirement_progress=Mock(return_value=1.0),
            start_location=object(), tactic_name="BattleCruiserRush",
            _mules=Mock(), _general_repair=Mock(), _look_for_terran_bunker=Mock(),
            register_behavior=Mock(), chat_send=AsyncMock(), can_afford=Mock(return_value=True),
        )
        builder = self.controller.observation_builder
        builder.collect_frame = Mock()
        builder.execution_context = Mock(side_effect=lambda _bot: self.context)
        builder.build = Mock(side_effect=lambda _bot, iteration: Observation(
            iteration, {}, builder._action_history_text(), self.context
        ))
        self.controller.action_exposure.build = Mock(return_value=SimpleNamespace(
            entries=[], validate=Mock()
        ))
        self.controller.adapter.compile = Mock(
            side_effect=lambda *_args: [Mock(execute=Mock(return_value=True))]
        )
        self.gate = asyncio.Event()
        self.reply = result()

        async def respond(*_args, **_kwargs):
            await self.gate.wait()
            return self.reply

        self.controller.model_agent.run = AsyncMock(side_effect=respond)

    async def asyncTearDown(self):
        await self.controller.close()
        self.temp.cleanup()

    async def frame(self, iteration, time):
        self.bot.time = time
        await self.controller.run_iteration(self.bot, iteration)
        await asyncio.sleep(0)

    def dispatch(self, actions):
        return self.controller._dispatch_actions(
            self.bot, 1, ActionReview(actions, [], []), self.context
        )

    def wrappers(self):
        return [
            call.args[0] for call in self.bot.register_behavior.call_args_list
            if isinstance(call.args[0], TrackedBehavior)
        ]

    async def test_automation_and_old_intents_continue_during_one_inflight_request(self):
        action = {"id": "GasBuildingController", "args": {"to_count": 2}}
        self.dispatch([action])
        await self.frame(1, 0)
        await self.frame(2, 10)
        await self.frame(3, 100)
        self.assertEqual(self.controller.model_agent.run.await_count, 1)
        self.assertEqual(len(self.wrappers()), 3)
        self.assertEqual(self.bot._mules.call_count, 3)
        self.assertEqual(self.controller.persistent_actions.actions, [action])

    async def test_reply_applies_on_next_frame_and_replaces_before_execution(self):
        old = {"id": "GasBuildingController", "args": {"to_count": 2}}
        new = {"id": "GasBuildingController", "args": {"to_count": 3}}
        self.dispatch([old])
        await self.frame(1, 0)
        self.reply = result([new])
        self.gate.set()
        await asyncio.sleep(0)
        self.assertEqual(self.controller.persistent_actions.actions, [old])
        self.controller.adapter.compile.reset_mock()
        await self.frame(2, 1)
        self.assertEqual(self.controller.persistent_actions.actions, [new])
        for call in self.controller.adapter.compile.call_args_list:
            self.assertEqual(call.args[0], [new])
        self.assertEqual(self.controller.model_agent.run.await_count, 1)
        await self.frame(3, 4)
        self.assertEqual(self.controller.model_agent.run.await_count, 1)
        await self.frame(4, 20)
        self.assertEqual(self.controller.model_agent.run.await_count, 2)

    async def test_empty_reply_and_request_failure_preserve_worker_and_macro_targets(self):
        worker = {"id": "BuildWorkers", "args": {"to_count": 80}}
        macro = {"id": "GasBuildingController", "args": {"to_count": 2}}
        self.dispatch([worker, macro])
        await self.frame(1, 0)
        self.gate.set()
        await asyncio.sleep(0)
        await self.frame(2, 1)
        self.assertEqual(self.controller.automation.worker_target, 80)
        self.assertEqual(self.controller.persistent_actions.actions, [macro])
        self.controller.model_agent.run.side_effect = RuntimeError("offline")
        await self.frame(3, 10)
        await self.frame(4, 11)
        self.assertEqual(self.controller.automation.worker_target, 80)
        self.assertEqual(self.controller.persistent_actions.actions, [macro])
        self.assertIn("offline", self.controller.observation_builder._action_history_text())

    async def test_reply_revalidates_unit_against_current_frame(self):
        self.context = EntityContext(
            own_entities={"1": SimpleNamespace(type_id=SimpleNamespace(name="MARINE"))},
            grids={"ground": object()},
        )
        await self.frame(1, 0)
        self.reply = result([{"id": "KeepUnitSafe", "args": {"unit": "1", "grid": "ground"}}])
        self.context = EntityContext(grids={"ground": object()})
        self.gate.set()
        await asyncio.sleep(0)
        await self.frame(2, 1)
        self.assertEqual(self.controller.persistent_actions.actions, [])
        self.assertEqual(self.wrappers(), [])
        self.assertIn("`failed`", self.controller.observation_builder._action_history_text())


    async def test_identical_controls_do_not_create_new_records(self):
        worker = {"id": "BuildWorkers", "args": {"to_count": 40}}
        macro = {"id": "GasBuildingController", "args": {"to_count": 2}}
        self.assertEqual(len(self.dispatch([worker, macro])), 2)
        repeated = self.dispatch([worker, macro])
        self.assertTrue(all(item["status"] == "active" and item["unchanged"] for item in repeated))
        self.controller._sync_active(self.bot)
        text = self.controller.observation_builder._action_history_text()
        self.assertEqual(text.count("GasBuildingController(to_count=2)"), 1)
        self.assertEqual(text.count("BuildWorkers(to_count=40)"), 1)

    async def test_execution_resource_checks_are_left_to_ares(self):
        action = {"id": "BuildStructure", "args": {"structure_id": "BARRACKS"}}
        self.dispatch([action])
        wrapper = self.wrappers()[0]
        self.bot.can_afford.return_value = False
        self.assertTrue(wrapper.execute(self.bot, {}, None))
        wrapper.behavior.execute.assert_called_once()
        self.assertEqual(self.controller.deferred_actions.actions, [])

    async def test_execution_exception_removes_failed_continuous_intent(self):
        action = {"id": "GasBuildingController", "args": {"to_count": 2}}
        self.dispatch([action])
        await self.frame(1, 0)
        wrapper = self.wrappers()[0]
        wrapper.behavior.execute.side_effect = ValueError("invalid target")
        self.assertFalse(wrapper.execute(self.bot, {}, None))
        self.assertEqual(self.controller.persistent_actions.actions, [])
        self.assertIn("`failed` | invalid target",
                      self.controller.observation_builder._action_history_text())

    async def test_invalid_new_task_does_not_remove_old_control(self):
        action = {"id": "GasBuildingController", "args": {"to_count": 2}}
        self.dispatch([action])
        self.controller.adapter.compile.side_effect = ValueError("invalid arguments")
        states = self.dispatch([{"id": "GasBuildingController", "args": {"to_count": 3}}])
        self.assertEqual(states[0]["status"], "failed")
        self.assertEqual(self.controller.persistent_actions.actions, [action])

    async def test_near_resource_shortfall_queues_and_retries_once(self):
        from sc2.position import Point2

        self.context.positions["main"] = Point2((10, 10))
        self.bot.can_afford.return_value = False
        action = {"id": "BuildStructure", "args": {"structure_id": "BARRACKS", "base_location": "main"}}
        states = self.dispatch([action])
        self.assertEqual(states[0]["status"], "queued")
        self.dispatch([action])
        self.assertEqual(len(self.controller.deferred_actions.actions), 1)
        self.assertEqual(self.wrappers(), [])
        self.bot.can_afford.return_value = True
        self.controller._run_queued_actions(self.bot, 2, self.context)
        self.controller._run_queued_actions(self.bot, 3, self.context)
        self.assertEqual(len(self.wrappers()), 1)
        self.assertEqual(self.controller.deferred_actions.actions, [])
        self.assertNotIn("`queued` |", self.controller.observation_builder._action_history_text())

    async def test_large_shortfall_is_not_submitted_or_failed(self):
        self.bot.minerals = 0
        self.bot.can_afford.return_value = False
        self.assertEqual(self.dispatch([{"id": "BuildStructure", "args": {"structure_id": "BARRACKS"}}]), [])
        self.assertEqual(self.controller.deferred_actions.actions, [])
        self.assertEqual(self.wrappers(), [])
        self.assertIn("exceeds queue tolerance", self.controller._feedback[-1]["error"])

    async def test_temporary_technology_shortfall_does_not_fail_queued_action(self):
        self.bot.can_afford.return_value = False
        action = {"id": "BuildStructure", "args": {"structure_id": "BARRACKS"}}
        self.dispatch([action])
        self.bot.tech_requirement_progress.return_value = 0
        self.controller._run_queued_actions(self.bot, 2, self.context)
        self.assertEqual(self.controller.deferred_actions.actions, [action])
        self.assertEqual(self.controller._feedback, [])

    async def test_resource_wait_expires_without_execution_failure(self):
        self.bot.can_afford.return_value = False
        self.dispatch([{"id": "BuildStructure", "args": {"structure_id": "BARRACKS"}}])
        self.controller._run_queued_actions(self.bot, 182, self.context)
        self.assertEqual(self.controller.deferred_actions.actions, [])
        self.assertNotIn("| `queued` |", self.controller.observation_builder._action_history_text())
        self.assertNotIn("| `failed` |", self.controller.observation_builder._action_history_text())
        self.assertIn("wait ended", self.controller._feedback[-1]["error"])

    async def test_pending_construction_clears_wait_without_another_build(self):
        self.bot.can_afford.return_value = False
        self.dispatch([{"id": "BuildStructure", "args": {"structure_id": "SUPPLYDEPOT"}}])
        self.bot.structure_pending = Mock(return_value=1)
        self.controller._run_queued_actions(self.bot, 2, self.context)
        self.assertEqual(self.controller.deferred_actions.actions, [])
        self.assertEqual(self.wrappers(), [])
        self.assertIn("already in progress", self.controller.observation_builder._action_history_text())

    async def test_tech_up_does_not_require_final_unit_resources(self):
        self.bot.can_afford.return_value = False
        self.bot.minerals = 0
        states = self.dispatch([{"id": "TechUp", "args": {"desired_tech": "BATTLECRUISER"}}])
        self.assertEqual(states[0]["status"], "accepted")
        self.assertEqual(len(self.wrappers()), 1)

    async def test_false_result_alone_is_not_failure(self):
        self.dispatch([{"id": "BuildStructure", "args": {"structure_id": "BARRACKS"}}])
        wrapper = self.wrappers()[0]
        wrapper.behavior.execute.return_value = False
        self.assertFalse(wrapper.execute(self.bot, {}, None))
        self.assertIn("Ares started no new work", self.controller._feedback[-1]["error"])
        self.assertNotIn("| `failed` |", self.controller.observation_builder._action_history_text())

    async def test_idle_continuous_controller_remains_active(self):
        action = {"id": "GasBuildingController", "args": {"to_count": 2}}
        self.dispatch([action])
        await self.frame(1, 0)
        wrapper = self.wrappers()[0]
        wrapper.behavior.execute.return_value = False
        self.bot.can_afford.return_value = False
        self.assertFalse(wrapper.execute(self.bot, {}, None))
        self.assertEqual(self.controller.persistent_actions.actions, [action])
        self.assertEqual(self.controller._feedback, [])

    async def test_runtime_failure_during_request_reaches_next_request(self):
        await self.frame(1, 0)
        self.controller._record_failure(self.bot, 2, "BuildStructure", "no placement")
        self.gate.set()
        await asyncio.sleep(0)
        await self.frame(2, 1)
        await self.frame(3, 10)
        feedback = self.controller.model_agent.run.call_args.args[3]
        self.assertTrue(any(item["error"] == "no placement" for item in feedback))

    async def test_close_cancels_pending_and_discards_finished_results(self):
        for finished in (False, True):
            with self.subTest(finished=finished):
                if finished:
                    self.controller._closed = False
                    self.controller._next_model_time = 0
                    self.gate.clear()
                await self.frame(1, 0)
                task = self.controller._pending
                if finished:
                    self.reply = result([{"id": "BuildWorkers", "args": {"to_count": 90}}])
                    self.gate.set()
                    await asyncio.sleep(0)
                await self.controller.close()
                self.assertTrue(task.done())
                await self.frame(2, 10)
                self.assertIsNone(self.controller._pending)
                self.assertEqual(self.controller.automation.worker_target, 20)


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        self.registry = PersistentActionRegistry(ActionCatalog.load())

    def test_new_individual_task_preserves_unaffected_group_members(self):
        group = {
            "id": "PathGroupToTarget",
            "args": {"group": ["1", "2"], "target": "enemy_main", "grid": "ground"},
        }
        self.registry.replace(group)
        self.registry.replace({"id": "KeepUnitSafe", "args": {"unit": "1", "grid": "ground"}})
        self.assertEqual(self.registry.actions[0]["args"]["group"], ["2"])
        self.assertEqual(self.registry.actions[1]["args"]["unit"], "1")

    def test_one_time_command_replaces_old_task_for_same_unit(self):
        self.registry.replace({"id": "KeepUnitSafe", "args": {"unit": "1", "grid": "ground"}})
        self.registry.replace({"id": "AMove", "args": {"unit": "1", "target": "enemy_main"}})
        self.assertEqual(self.registry.actions, [])

    def test_macro_placement_change_replaces_previous_global_target(self):
        old = {"id": "ProductionController", "args": {"base_location": "main"}}
        new = {"id": "ProductionController", "args": {"base_location": "natural"}}
        self.registry.replace(old)
        self.registry.replace(new)
        self.assertEqual(self.registry.actions, [new])


    def test_missing_group_member_does_not_stop_other_members(self):
        action = {"id": "PathGroupToTarget",
                  "args": {"group": ["1", "2"], "target": "main", "grid": "ground"}}
        self.registry.replace(action)
        failed = self.registry.prune_missing_actors({"2": object()})
        self.assertEqual(len(failed), 1)
        self.assertEqual(self.registry.actions[0]["args"]["group"], ["2"])
