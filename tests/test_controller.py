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
    async def test_im_chat_prints_a_header_and_one_message_per_action(self):
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
            "[IM iteration=30] t=00:12 M=150 G=0 supply=14/23 "
            "phase=opening_tech im=4.29s"
        )

        await LLMGameController._chat_im_decision(bot, header, [action])

        self.assertEqual(
            bot.messages,
            [
                (header, True),
                (
                    "actions[0]=BuildStructure(base_location=main, "
                    "structure_id=BARRACKS)",
                    True,
                ),
            ],
        )

    def test_review_keeps_valid_siblings_without_another_model_turn(self):
        controller = object.__new__(LLMGameController)
        controller.policy = SelectivePolicy()
        controller.game_config = GameConfig()

        review = controller._review_im_actions(
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

    def test_action_limit_errors_are_returned_as_feedback_candidates(self):
        class AcceptAllPolicy:
            def review(self, _bot, actions, _context, _surface):
                return ActionReview(list(actions), [], [])

        controller = object.__new__(LLMGameController)
        controller.policy = AcceptAllPolicy()
        controller.game_config = GameConfig(max_actions_per_decision=2)
        actions = [{"id": "Good", "args": {"index": i}} for i in range(3)]

        review = controller._review_im_actions(None, actions, observation(), None)

        self.assertEqual(review.actions, actions[:2])
        self.assertEqual(review.issues[0].action, actions[2])
        self.assertIn("action limit exceeded", review.issues[0].text())
