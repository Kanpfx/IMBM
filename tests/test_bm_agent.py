import unittest

from agents.bm_agent import BMAgent
from agents.prompts import BM_ROLE
from config.llm import LLMConfig


class FakeLLMClient:
    async def complete(self, _messages):
        return (
            '{"phase":"opening_tech","guidance":['
            '"Start air technology.","Keep producing SCVs.",'
            '"Avoid optional spending.","Prepare the next supply structure."]}'
        )


class InvalidPhaseLLMClient:
    async def complete(self, _messages):
        return '{"phase":"invented_phase","guidance":["Build a Factory."]}'


class BMAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_bm_planning_horizon_is_thirty_game_seconds(self):
        self.assertIn("30 seconds of gameplay", BM_ROLE)
        self.assertNotIn("60 game seconds", BM_ROLE)

    async def test_bm_accepts_guidance_without_a_length_constraint(self):
        agent = BMAgent(LLMConfig(), FakeLLMClient())
        result = await agent.run(
            "# Observation\n[Empty]",
            {
                "concept": "Build Battlecruisers.",
                "rules": ["Stay safe."],
                "phases": [
                    {
                        "id": "opening_tech",
                        "enter_when": ["The Factory has not started."],
                        "goal": "Start production.",
                        "guidance": ["Build a Depot."],
                    }
                ],
            },
            [],
            "cold_start",
        )

        self.assertEqual(result.phase, "opening_tech")
        self.assertEqual(len(result.guidance), 4)

    async def test_bm_rejects_a_phase_outside_the_tactical_card(self):
        agent = BMAgent(LLMConfig(), InvalidPhaseLLMClient())
        tactic = {
            "concept": "Build Battlecruisers.",
            "rules": [],
            "phases": [
                {
                    "id": "opening_tech",
                    "enter_when": ["The Factory has not started."],
                    "goal": "Start production.",
                    "guidance": ["Build a Depot."],
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "phase must be an ID"):
            await agent.run("# Observation\n[Empty]", tactic, [], "cold_start")
