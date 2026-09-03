import unittest

from config.llm import LLMConfig
from llm.agents.im_agent import IMAgent

TACTIC = {
    "id": "TestTactic",
    "concept": "Test the single IM.",
    "rules": [],
    "phases": [
        {
            "id": "opening",
            "enter_when": ["The game has started."],
            "goal": "Begin the plan.",
            "guidance": ["Take one useful action."],
        }
    ],
}


class FakeLLMClient:
    def __init__(self, reply='{"phase":"opening","actions":[]}'):
        self.reply = reply
        self.calls = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.reply


class IMAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_defaults_keep_transport_retries(self):
        self.assertEqual(LLMConfig().temperature, 0.1)
        self.assertEqual(LLMConfig().transport_retries, 2)

    async def test_im_returns_phase_and_actions_in_one_call(self):
        client = FakeLLMClient(
            '{"phase":"opening","actions":[{"id":"BuildWorkers","args":{"to_count":20}}]}'
        )
        agent = IMAgent(LLMConfig(), client)

        result = await agent.run("# Game state\n[None]", TACTIC, [])

        self.assertEqual(result.phase, "opening")
        self.assertEqual(result.actions[0]["id"], "BuildWorkers")
        self.assertFalse(result.validation_feedback)
        self.assertEqual(len(client.calls), 1)

    async def test_invalid_json_is_feedback_without_an_im_retry(self):
        client = FakeLLMClient('{"phase":"opening","actions": [')
        agent = IMAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertIsNone(result.phase)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.validation_feedback[0]["kind"], "output_format")
        self.assertIn("submitted_output", result.validation_feedback[0])
        self.assertEqual(len(client.calls), 1)

    async def test_invalid_phase_preserves_actions_and_records_feedback(self):
        client = FakeLLMClient(
            '{"phase":"invented","actions":[{"id":"BuildWorkers","args":{"to_count":20}}]}'
        )
        agent = IMAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertIsNone(result.phase)
        self.assertEqual(result.actions[0]["id"], "BuildWorkers")
        self.assertEqual(result.validation_feedback[0]["kind"], "phase")

    async def test_previous_feedback_is_part_of_the_next_user_message_only(self):
        client = FakeLLMClient()
        agent = IMAgent(LLMConfig(), client)
        feedback = [
            {
                "kind": "action",
                "action": {"id": "Unknown", "args": {}},
                "error": "unknown action",
            }
        ]

        await agent.run("# Observation", TACTIC, [], feedback)

        messages = client.calls[0]
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("<previous_validation_feedback>", messages[1]["content"])
        self.assertIn("unknown action", messages[1]["content"])
