import unittest

from agents.correction_agent import CorrectionAgent
from config.llm import LLMConfig


class FakeLLMClient:
    def __init__(self, reply='{"actions":[]}'):
        self.reply = reply

    async def complete(self, _messages):
        return self.reply


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

    async def test_correction_agent_discards_cross_action_replacements(self):
        client = FakeLLMClient(
            '{"actions":[{"id":"ProductionController","args":{}}]}'
        )
        agent = CorrectionAgent(LLMConfig(), client)
        telemetry = FakeTelemetry()

        actions = await agent.run(
            "# Observation\n[Empty]",
            [],
            [],
            [{"id": "Mining", "args": {}}],
            ["Mining is unavailable"],
            trace=telemetry,
            iteration=20,
        )

        self.assertEqual(actions, [])
        self.assertEqual(
            telemetry.events[0][1]["discarded_actions"],
            [{"id": "ProductionController", "args": {}}],
        )

    async def test_correction_agent_keeps_same_action_argument_repairs(self):
        client = FakeLLMClient(
            '{"actions":[{"id":"BuildStructure","args":{"structure_id":"SUPPLYDEPOT"}}]}'
        )
        agent = CorrectionAgent(LLMConfig(), client)

        actions = await agent.run(
            "# Observation\n[Empty]",
            [],
            [],
            [{"id": "BuildStructure", "args": {}}],
            ["missing structure_id"],
        )

        self.assertEqual(
            actions,
            [{"id": "BuildStructure", "args": {"structure_id": "SUPPLYDEPOT"}}],
        )
