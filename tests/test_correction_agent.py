import unittest

from agents.correction_agent import CorrectionAgent
from config.llm import LLMConfig


class FakeLLMClient:
    async def complete(self, _messages):
        return '{"actions":[]}'


class FakeTelemetry:
    def __init__(self):
        self.events = []

    def event(self, name, **fields):
        self.events.append((name, fields))


class CorrectionAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_correction_agent_returns_a_repaired_action_list(self):
        agent = CorrectionAgent(LLMConfig(), FakeLLMClient())
        telemetry = FakeTelemetry()

        actions = await agent.run(
            "# Observation\n[Empty]",
            ["Start air technology."],
            [],
            [{"id": "UnknownAction", "args": {}}],
            ["Action 1: unknown action id: UnknownAction"],
            trace=telemetry,
            iteration=20,
        )

        self.assertEqual(actions, [])
        self.assertEqual(telemetry.events[0][0], "im_correction")
        self.assertEqual(telemetry.events[0][1]["iteration"], 20)
        self.assertTrue(telemetry.events[0][1]["valid"])
        self.assertIn("request", telemetry.events[0][1])
        self.assertIn("reply", telemetry.events[0][1])
