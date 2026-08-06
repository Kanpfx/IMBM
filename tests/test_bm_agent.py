import unittest

from agents.bm_agent import BMAgent
from config.llm import LLMConfig


class FakeLLMClient:
    async def complete(self, _messages):
        return '{"guidance":["Start air technology."]}'


class BMAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_bm_accepts_guidance_without_a_length_constraint(self):
        agent = BMAgent(LLMConfig(), FakeLLMClient())
        result = await agent.run(
            "# Observation\n[Empty]",
            {"concept": "Build Battlecruisers.", "rules": ["Stay safe."]},
            {"id": "opening_factory", "goal": "Start production.", "guidance": []},
            "cold_start",
        )

        self.assertEqual(result, ["Start air technology."])
