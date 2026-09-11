import unittest
from config.llm import LLMConfig
from llm.agents.model_agent import ModelAgent
import json
from unittest.mock import patch
from llm.client import LLMClient


TACTIC = {
    "id": "TestTactic",
    "concept": "Test the single model.",
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
    def __init__(
        self,
        reply="# phase\nopening\n\n# actions",
    ):
        self.reply = reply
        self.calls = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.reply


class ModelAgentTests(unittest.IsolatedAsyncioTestCase):

    async def test_model_returns_phase_and_actions_in_one_call(self):
        client = FakeLLMClient(
            "# phase\nopening\n\n"
            "# actions\nBuildWorkers(to_count=20)"
        )
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Game state\n[None]", TACTIC, [])

        self.assertEqual(result.phase, "opening")
        self.assertEqual(result.actions[0]["id"], "BuildWorkers")
        self.assertFalse(result.validation_feedback)
        self.assertEqual(len(client.calls), 1)

    async def test_invalid_dsl_is_feedback_without_a_model_retry(self):
        client = FakeLLMClient("# phase\nopening")
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertIsNone(result.phase)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.validation_feedback[0]["kind"], "output_format")
        self.assertIn("submitted_output", result.validation_feedback[0])
        self.assertEqual(len(client.calls), 1)

    async def test_invalid_phase_preserves_actions_and_records_feedback(self):
        client = FakeLLMClient(
            "# phase\ninvented\n\n"
            "# actions\nBuildWorkers(to_count=20)"
        )
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertIsNone(result.phase)
        self.assertEqual(result.actions[0]["id"], "BuildWorkers")
        self.assertEqual(result.validation_feedback[0]["kind"], "phase")


    async def test_bad_action_preserves_valid_siblings_and_records_feedback(self):
        client = FakeLLMClient(
            "# phase\nopening\n\n"
            "# actions\nBuildWorkers(to_count=20)\n"
            "Unsafe(unit=lookup(1))"
        )
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertEqual([action["id"] for action in result.actions], ["BuildWorkers"])
        self.assertEqual(result.validation_feedback[0]["kind"], "action_format")
        self.assertEqual(result.validation_feedback[0]["action_index"], 2)

    async def test_previous_feedback_is_part_of_the_next_user_message_only(self):
        client = FakeLLMClient()
        agent = ModelAgent(LLMConfig(), client)
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


class LLMClientTests(unittest.TestCase):


    def test_request_uses_2048_tokens_without_provider_specific_fields(self):
        config = LLMConfig(
            model="test-model",
            base_url="https://example.com",
            api_key="test-key",
        )
        client = LLMClient(config)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read():
                return b'{"choices":[{"message":{"content":"{}"}}]}'

        with patch("llm.client.request.urlopen", return_value=Response()) as urlopen:
            client._complete_sync([{"role": "user", "content": "json"}])

        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(body["max_tokens"], 2048)
        self.assertEqual(
            set(body),
            {"model", "messages", "temperature", "max_tokens"},
        )
