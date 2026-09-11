import unittest

from config.game import GameConfig
from game.actions.policy import ActionReview, ValidationIssue
from game.actions.resolver import EntityContext
from game.control.controller import LLMGameController
from game.observation.builder import Observation


class SelectivePolicy:
    def review(self, _bot, actions, _context, _surface):
        valid = []
        issues = []
        for index, action in enumerate(actions):
            if action["id"] == "Good":
                valid.append(action)
            else:
                issues.append(
                    ValidationIssue(index, action, "unknown or invalid action")
                )
        return ActionReview(valid, issues, ["normalized"])


def observation(iteration=30):
    return Observation(iteration, {}, "# Round state\n[None]", EntityContext())


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_chat_prints_a_header_and_one_message_per_action(self):
        class Bot:
            def __init__(self):
                self.messages = []

            async def chat_send(self, message, team_only=False):
                self.messages.append((message, team_only))

        bot = Bot()
        action = {
            "id": "BuildStructure",
            "args": {"base_location": "main", "structure_id": "BARRACKS"},
        }
        header = (
            "[model iteration=30] t=00:12 M=150 G=0 supply=14/23 "
            "phase=opening_tech model=4.29s"
        )

        await LLMGameController._chat_model_decision(bot, header, [action])

        self.assertEqual(
            bot.messages,
            [
                (header, True),
                (
                    "Action 1: BuildStructure(base_location=main, "
                    "structure_id=BARRACKS)",
                    True,
                ),
            ],
        )

    def test_review_keeps_valid_siblings_without_another_model_turn(self):
        controller = object.__new__(LLMGameController)
        controller.policy = SelectivePolicy()
        controller.game_config = GameConfig()

        review = controller._review_model_actions(
            None,
            [
                {"id": "Good", "args": {}},
                {"id": "Bad", "args": {}},
            ],
            observation(),
            None,
        )

        self.assertEqual(review.actions, [{"id": "Good", "args": {}}])
        self.assertEqual(review.issues[0].action["id"], "Bad")
        self.assertEqual(review.normalizations, ["normalized"])

    def test_feedback_is_replaced_and_cleared_instead_of_accumulated(self):
        controller = object.__new__(LLMGameController)
        controller._previous_validation_feedback = [
            {"kind": "phase", "error": "old error"}
        ]
        issue = ValidationIssue(
            0,
            {"id": "Bad", "args": {}},
            "unknown or invalid action",
        )

        current = controller._replace_validation_feedback([], [issue])

        self.assertEqual(current, controller._previous_validation_feedback)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["kind"], "action")
        self.assertNotIn("old error", str(current))

        cleared = controller._replace_validation_feedback([], [])
        self.assertEqual(cleared, [])
        self.assertEqual(controller._previous_validation_feedback, [])

    async def test_failed_model_decision_restores_default_worker_target(self):
        previous_override = {
            "id": "BuildWorkers",
            "args": {"to_count": 80},
        }

        class Automation:
            def __init__(self):
                self.worker_target = 80
                self.override = previous_override
                self.registered = False

            async def run(self, _bot, _iteration):
                return None

            def replace_worker_override(self, action):
                previous = self.override
                changed = previous != action
                self.override = action
                self.worker_target = (
                    action["args"]["to_count"] if action is not None else 20
                )
                return previous, changed

            def register_worker_production(self, _bot):
                self.registered = True

        class ObservationBuilder:
            def __init__(self):
                self.expired = []

            def collect_frame(self, _bot):
                return None

            def build(self, _bot, iteration):
                return observation(iteration)

            def record_expired_actions(self, actions, game_time):
                self.expired.append((actions, game_time))

        class ModelAgent:
            async def run(self, *_args, **_kwargs):
                raise RuntimeError("request failed")

        class Telemetry:
            def observation(self, **_fields):
                return None

            def event(self, *_args, **_fields):
                return None

        controller = object.__new__(LLMGameController)
        controller.automation = Automation()
        controller.observation_builder = ObservationBuilder()
        controller.llm_config = type("Config", (), {"configured": True})()
        controller.game_config = GameConfig()
        controller.action_exposure = type(
            "Exposure",
            (),
            {
                "build": lambda _self, _bot, _context: type(
                    "Surface", (), {"entries": []}
                )()
            },
        )()
        controller.deferred_actions = type(
            "DeferredActions",
            (),
            {"pop_ready": lambda _self, _bot, _iteration: ([], [])},
        )()
        controller.model_agent = ModelAgent()
        controller.telemetry = Telemetry()
        controller.tactic = {}
        controller._previous_validation_feedback = []
        controller._run_persistent_actions = lambda _bot, _iteration: None
        bot = type("Bot", (), {"time_formatted": "00:12"})()

        await controller.run_iteration(bot, 60)

        self.assertEqual(controller.automation.worker_target, 20)
        self.assertTrue(controller.automation.registered)
        self.assertEqual(
            controller.observation_builder.expired,
            [([previous_override], "00:12")],
        )
