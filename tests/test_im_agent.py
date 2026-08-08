import unittest

from agents.im_agent import IMAgent
from config.llm import LLMConfig


class FakeLLMClient:
    async def complete(self, _messages):
        return (
            '{"actions":[],"request_background":true,'
            '"background_reason":"Need a strategic response to enemy air tech."}'
        )


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
