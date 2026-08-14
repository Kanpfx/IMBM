import unittest

from config.llm import LLMConfig
from llm.agents.bm_agent import BMAgent
from llm.agents.prompts import BM_ROLE


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


class CustomTacticLLMClient:
    async def complete(self, _messages):
        return '{"phase":"proxy_attack_window","guidance":["Attack now."]}'


class BMAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_bm_planning_horizon_is_twenty_game_seconds(self):
        self.assertIn("20 seconds of gameplay", BM_ROLE)
        self.assertIn("Output only one valid JSON object", BM_ROLE)
        self.assertNotIn("30 seconds of gameplay", BM_ROLE)

    async def test_bm_accepts_phase_ids_defined_only_by_the_selected_tactic(self):
        agent = BMAgent(LLMConfig(), CustomTacticLLMClient())
        result = await agent.run(
            "# Observation\n[None]",
            {
                "concept": "Execute a proxy attack.",
                "rules": [],
                "phases": [
                    {
                        "id": "proxy_attack_window",
                        "enter_when": ["The proxy force is ready."],
                        "goal": "Attack before the enemy stabilizes.",
                        "guidance": ["Attack immediately."],
                    }
                ],
            },
            [],
            "cold_start",
        )

        self.assertEqual(result.phase, "proxy_attack_window")

    async def test_bm_accepts_guidance_without_a_length_constraint(self):
        agent = BMAgent(LLMConfig(), FakeLLMClient())
        result = await agent.run(
            "# Observation\n[None]",
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
            await agent.run("# Observation\n[None]", tactic, [], "cold_start")
