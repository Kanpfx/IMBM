import unittest

from config.llm import LLMConfig
from llm.agents.correction_agent import CorrectionAgent


class FakeLLMClient:
    def __init__(self, reply='{"actions":[]}'):
        self.reply = reply

    async def complete(self, _messages):
        return self.reply


class FakeTelemetry:
    def __init__(self):
        self.corrections = []

    def correction_conversation(self, **fields):
        self.corrections.append(fields)


class CorrectionAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_correction_agent_returns_a_repaired_action_list(self):
        agent = CorrectionAgent(LLMConfig(), FakeLLMClient())
        telemetry = FakeTelemetry()

        actions = await agent.run(
            "# Observation\n[None]",
            ["Start air technology."],
            [],
            [{"id": "UnknownAction", "args": {}}],
            ["Action 1: unknown action id: UnknownAction"],
            trace=telemetry,
            iteration=20,
            attempt=2,
        )

        self.assertEqual(actions, [])
        correction = telemetry.corrections[0]
        self.assertEqual(correction["iteration"], 20)
        self.assertEqual(correction["attempt"], 2)
        self.assertTrue(correction["valid"])
        self.assertIn("request", correction)
        self.assertIn("reply", correction)
        self.assertIn("**Validation error:**", correction["request"][-1]["content"])
        self.assertNotIn("validation_errors", correction)
        self.assertNotIn("rejected_actions", correction)

    async def test_correction_agent_discards_cross_action_replacements(self):
        client = FakeLLMClient('{"actions":[{"id":"ProductionController","args":{}}]}')
        agent = CorrectionAgent(LLMConfig(), client)
        telemetry = FakeTelemetry()

        actions = await agent.run(
            "# Observation\n[None]",
            [],
            [],
            [{"id": "Mining", "args": {}}],
            ["Mining is unavailable"],
            trace=telemetry,
            iteration=20,
        )

        self.assertEqual(actions, [])
        self.assertEqual(
            telemetry.corrections[0]["discarded_actions"],
            [{"id": "ProductionController", "args": {}}],
        )

    async def test_correction_agent_keeps_same_action_argument_repairs(self):
        client = FakeLLMClient(
            '{"actions":[{"id":"BuildStructure","args":{"structure_id":"SUPPLYDEPOT"}}]}'
        )
        agent = CorrectionAgent(LLMConfig(), client)

        actions = await agent.run(
            "# Observation\n[None]",
            [],
            [],
            [{"id": "BuildStructure", "args": {}}],
            ["missing structure_id"],
        )

        self.assertEqual(
            actions,
            [{"id": "BuildStructure", "args": {"structure_id": "SUPPLYDEPOT"}}],
        )
