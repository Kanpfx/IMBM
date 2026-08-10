import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from agents.bm_agent import BMResult
from config.game import GameConfig
from config.llm import LLMConfig
from core.controller import LLMGameController
from core.observation import Observation
from core.policy import ActionReview, ValidationIssue
from runtime.directive import DirectiveStore
from runtime.resolver import EntityContext


class FakeTelemetry:
    def __init__(self):
        self.events = []

    def event(self, name, **fields):
        self.events.append((name, fields))


class ImmediateBM:
    def __init__(self):
        self.calls = []

    async def run(self, observation, tactic, action_entries, trigger_reason, **_kwargs):
        self.calls.append((observation, tactic, action_entries, trigger_reason))
        return BMResult("opening_tech", ("Build the opening infrastructure.",))


class BlockingBM(ImmediateBM):
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()

    async def run(self, observation, tactic, action_entries, trigger_reason, **kwargs):
        self.calls.append((observation, tactic, action_entries, trigger_reason))
        await self.release.wait()
        return BMResult("opening_tech", ("Build the opening infrastructure.",))


class FlakyBM(ImmediateBM):
    async def run(self, observation, tactic, action_entries, trigger_reason, **_kwargs):
        self.calls.append((observation, tactic, action_entries, trigger_reason))
        if len(self.calls) == 1:
            raise ValueError("invalid first response")
        return BMResult("opening_tech", ("Build the opening infrastructure.",))


class RetryingPolicy:
    def review(self, _bot, actions, _context, _phase, _surface):
        valid = []
        issues = []
        for index, action in enumerate(actions):
            if action["id"] == "Good" or action["args"].get("fixed"):
                valid.append(action)
            else:
                issues.append(
                    ValidationIssue(
                        index,
                        action,
                        "Parameter error: invalid value, parameter 'value' must be fixed",
                    )
                )
        return ActionReview(valid, issues, [])


class TwoAttemptCorrector:
    def __init__(self):
        self.calls = 0

    async def run(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return [{"id": "Bad", "args": {"fixed": False}}]
        return [{"id": "Bad", "args": {"fixed": True}}]


class NeverFixedCorrector:
    def __init__(self):
        self.calls = 0

    async def run(self, *_args, **_kwargs):
        self.calls += 1
        return [{"id": "Bad", "args": {"fixed": False}}]


class SimpleCatalog:
    @staticmethod
    def get(action_id):
        return {"id": action_id}


def make_controller(bm, *, enabled=True):
    controller = object.__new__(LLMGameController)
    controller.enable_bm = enabled
    controller.game_config = GameConfig()
    controller.directive_store = DirectiveStore()
    controller.bm_pending = None
    controller._last_bm_started_iteration = -(10**9)
    controller.bm = bm
    controller.tactic = {
        "concept": "Build Battlecruisers.",
        "rules": [],
        "phases": [{"id": "opening_tech"}],
    }
    controller.bm_action_entries = [{"id": "macro.build_structure"}]
    controller.telemetry = FakeTelemetry()
    return controller


def observation(iteration):
    return Observation(iteration, {}, "# Round state\n[Empty]", EntityContext())


class ControllerBMTests(unittest.IsolatedAsyncioTestCase):
    def test_quick_counts_includes_pending_battlecruiser(self):
        class Bot:
            units = []
            structures = []

            @staticmethod
            def already_pending(unit_type):
                return 1 if unit_type.name == "BATTLECRUISER" else 0

        counts = LLMGameController._quick_counts(Bot())

        self.assertEqual(counts["pending:BATTLECRUISER"], 1)

    async def test_cold_start_can_be_awaited_before_the_first_im_decision(self):
        bm = ImmediateBM()
        controller = make_controller(bm)

        await controller._await_first_bm(
            observation(0), 0, controller.bm_action_entries
        )
        directive = controller.directive_store.read(0)
        self.assertIsNotNone(directive)
        self.assertEqual(directive.phase, "opening_tech")
        self.assertEqual(directive.guidance, ("Build the opening infrastructure.",))
        self.assertEqual(bm.calls[0][2], controller.bm_action_entries)
        self.assertEqual(bm.calls[0][3], "cold_start")

    async def test_cold_start_retries_without_starting_im_after_invalid_bm(self):
        bm = FlakyBM()
        controller = make_controller(bm)

        with patch("core.controller.asyncio.sleep", new=AsyncMock()):
            await controller._await_first_bm(
                observation(0), 0, controller.bm_action_entries
            )

        self.assertEqual(len(bm.calls), 2)
        self.assertEqual(bm.calls[0][3], "cold_start")
        self.assertEqual(bm.calls[1][3], "guidance_expired")
        self.assertIsNotNone(controller.directive_store.read(0))

    async def test_refresh_starts_at_240_iterations_and_keeps_the_old_directive(self):
        bm = ImmediateBM()
        controller = make_controller(bm)
        await controller._maybe_start_bm(
            observation(0), 0, controller.bm_action_entries
        )
        await controller._await_pending_bm(0)
        original = controller.directive_store.read(0)

        await controller._maybe_start_bm(
            observation(239), 239, controller.bm_action_entries
        )
        self.assertIsNone(controller.bm_pending)
        await controller._maybe_start_bm(
            observation(240), 240, controller.bm_action_entries
        )

        self.assertIsNotNone(controller.bm_pending)
        self.assertEqual(controller.directive_store.read(240), original)
        await controller._await_pending_bm(240)
        self.assertEqual(bm.calls[-1][3], "periodic_refresh")

    async def test_an_inflight_bm_call_is_not_preempted(self):
        bm = BlockingBM()
        controller = make_controller(bm)
        await controller._maybe_start_bm(
            observation(0), 0, controller.bm_action_entries
        )
        original_task = controller.bm_pending.task

        await controller._maybe_start_bm(
            observation(240),
            240,
            controller.bm_action_entries,
            trigger_reason="periodic_refresh",
        )

        self.assertIs(controller.bm_pending.task, original_task)
        bm.release.set()
        await controller._await_pending_bm(240)

    async def test_disabled_bm_never_starts_a_task(self):
        controller = make_controller(ImmediateBM(), enabled=False)

        await controller._maybe_start_bm(
            observation(0), 0, controller.bm_action_entries
        )

        self.assertIsNone(controller.bm_pending)


class ControllerCorrectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_correction_attempts_keep_originally_valid_actions(self):
        controller = object.__new__(LLMGameController)
        controller.policy = RetryingPolicy()
        controller.corrector = TwoAttemptCorrector()
        controller.llm_config = LLMConfig(max_refines=2)
        controller.game_config = GameConfig()
        controller.telemetry = FakeTelemetry()
        controller.catalog = SimpleCatalog()

        review = await controller._review_im_actions(
            bot=None,
            actions=[
                {"id": "Good", "args": {}},
                {"id": "Bad", "args": {"fixed": False}},
            ],
            observation=observation(20),
            guidance=[],
            entries=[],
            phase="opening_tech",
            surface=None,
            iteration=20,
        )

        self.assertEqual(controller.corrector.calls, 2)
        self.assertEqual(
            review.actions,
            [
                {"id": "Good", "args": {}},
                {"id": "Bad", "args": {"fixed": True}},
            ],
        )
        self.assertFalse(review.issues)

    async def test_action_still_invalid_after_two_attempts_is_discarded(self):
        controller = object.__new__(LLMGameController)
        controller.policy = RetryingPolicy()
        controller.corrector = NeverFixedCorrector()
        controller.llm_config = LLMConfig(max_refines=2)
        controller.game_config = GameConfig()
        controller.telemetry = FakeTelemetry()
        controller.catalog = SimpleCatalog()

        review = await controller._review_im_actions(
            bot=None,
            actions=[
                {"id": "Good", "args": {}},
                {"id": "Bad", "args": {"fixed": False}},
            ],
            observation=observation(20),
            guidance=[],
            entries=[],
            phase="opening_tech",
            surface=None,
            iteration=20,
        )

        self.assertEqual(controller.corrector.calls, 2)
        self.assertEqual(review.actions, [{"id": "Good", "args": {}}])
        self.assertTrue(review.issues)
