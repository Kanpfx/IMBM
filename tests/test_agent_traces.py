import unittest

from agents.background import BmAgent
from agents.immediate import ImAgent


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def call(self, prompt, history=None, **kwargs):
        response = self.responses.pop(0)
        messages = list(history or []) + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ]
        return response, messages


class AgentTraceTest(unittest.TestCase):
    def test_im_trace_records_verifier_refine(self):
        client = FakeClient(
            [
                "```\n{\"actions\": [{\"action\": \"bad\"}], \"request_background\": false, \"background_reason\": \"\"}\n```",
                "```\n{\"actions\": [], \"request_background\": false, \"background_reason\": \"\"}\n```",
            ]
        )
        agent = ImAgent("Terran", model_name="test", generation_config={}, llm_client=client)
        calls = 0

        def verifier(actions):
            nonlocal calls
            calls += 1
            return (calls > 1, "invalid action" if calls == 1 else "")

        agent.run("observation", verifier=verifier)

        self.assertEqual([item["stage"] for item in agent.last_trace["calls"]], ["initial", "refine_1"])
        self.assertFalse(agent.last_trace["verifier"][0]["actions_ok"])

    def test_bm_trace_records_critic(self):
        client = FakeClient(
            [
                "```\n[\"Train Marines\"]\n```",
                "```\n{\"errors\": [], \"error_number\": 0}\n```",
            ]
        )
        agent = BmAgent("Terran", model_name="test", generation_config={}, llm_client=client)
        agent.run("observation")

        self.assertEqual([item["stage"] for item in agent.last_trace["calls"]], ["plan", "critic_1"])
        self.assertEqual(agent.last_trace["critics"], [{"round": 1, "error_number": 0, "errors": []}])


if __name__ == "__main__":
    unittest.main()
