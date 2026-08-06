import unittest

from agents.correction_agent import CorrectionAgent
from config.llm import LLMConfig


class FakeLLMClient:
    async def complete(self, _messages):
        return '{"actions":[]}'


class CorrectionAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_correction_agent_returns_a_repaired_action_list(self):
        agent = CorrectionAgent(LLMConfig(), FakeLLMClient())

        actions = await agent.run(
            "# Observation\n[Empty]",
            ["Start air technology."],
            [],
            [{"id": "UnknownAction", "args": {}}],
            ["Action 1: unknown action id: UnknownAction"],
        )

        self.assertEqual(actions, [])
