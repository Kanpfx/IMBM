import unittest

from agents.im_agent import IMAgent
from config.llm import LLMConfig
from core.action_errors import OutputFormatError


class FakeLLMClient:
    async def complete(self, _messages):
        return (
            '{"actions":[],"request_background":true,'
            '"background_reason":"Need a strategic response to enemy air tech."}'
        )


class InvalidJSONClient:
    def __init__(self):
        self.calls = 0

    async def complete(self, _messages):
        self.calls += 1
        return '{"actions": ['


class IMAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_defaults_favor_stable_responses(self):
        config = LLMConfig()
        self.assertEqual(config.temperature, 0.1)
        self.assertEqual(config.max_refines, 2)

    async def test_im_returns_actions_and_background_request(self):
        agent = IMAgent(LLMConfig(max_refines=0), FakeLLMClient())
        result = await agent.run(
            "# Game state\n[none]",
            ["Protect the main base."],
            [],
            lambda actions: (actions == [], "accepted"),
        )

        self.assertEqual(result.actions, [])
        self.assertTrue(result.request_background)
        self.assertIn("enemy air tech", result.background_reason)

    async def test_invalid_json_skips_the_decision_without_an_im_retry(self):
        client = InvalidJSONClient()
        agent = IMAgent(LLMConfig(max_refines=2), client)

        with self.assertRaisesRegex(OutputFormatError, "standard JSON object"):
            await agent.run("# Observation", [], [], lambda _actions: (True, ""))

        self.assertEqual(client.calls, 1)
