import unittest

from config.llm import LLMConfig
from game.actions.errors import OutputFormatError
from llm.agents.im_agent import IMAgent


class FakeLLMClient:
    async def complete(self, _messages):
        return '{"actions":[]}'


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

    async def test_im_returns_actions(self):
        agent = IMAgent(LLMConfig(max_refines=0), FakeLLMClient())
        result = await agent.run(
            "# Game state\n[None]",
            ["Protect the main base."],
            [],
            lambda actions: (actions == [], "accepted"),
        )

        self.assertEqual(result.actions, [])

    async def test_invalid_json_skips_the_decision_without_an_im_retry(self):
        client = InvalidJSONClient()
        agent = IMAgent(LLMConfig(max_refines=2), client)

        with self.assertRaisesRegex(OutputFormatError, "standard JSON object"):
            await agent.run("# Observation", [], [], lambda _actions: (True, ""))

        self.assertEqual(client.calls, 1)
