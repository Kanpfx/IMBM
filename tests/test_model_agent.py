import unittest
from config.llm import LLMConfig
from llm.agents.model_agent import ModelAgent
import json
from unittest.mock import patch
from llm.client import LLMClient


TACTIC = {
    "id": "TestTactic",
    "concept": "Test the single model.",
    "rules": [],
    "phases": [
        {
            "id": "opening",
            "enter_when": ["The game has started."],
            "goal": "Begin the plan.",
            "guidance": ["Take one useful action."],
        }
    ],
}


class FakeLLMClient:
    def __init__(
        self,
        reply="# phase\nopening\n\n# actions",
    ):
        self.reply = reply
        self.calls = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.reply


class ModelAgentTests(unittest.IsolatedAsyncioTestCase):

    async def test_model_returns_phase_and_actions_in_one_call(self):
        client = FakeLLMClient(
            "# phase\nopening\n\n"
            "# actions\nBuildWorkers(to_count=20)"
        )
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Game state\n[None]", TACTIC, [])

        self.assertEqual(result.phase, "opening")
        self.assertEqual(result.actions[0]["id"], "BuildWorkers")
        self.assertFalse(result.validation_feedback)
        self.assertEqual(len(client.calls), 1)

    async def test_invalid_dsl_is_feedback_without_a_model_retry(self):
        client = FakeLLMClient("# phase\nopening")
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertIsNone(result.phase)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.validation_feedback[0]["kind"], "output_format")
        self.assertIn("submitted_output", result.validation_feedback[0])
        self.assertEqual(len(client.calls), 1)

    async def test_invalid_phase_preserves_actions_and_records_feedback(self):
        client = FakeLLMClient(
            "# phase\ninvented\n\n"
            "# actions\nBuildWorkers(to_count=20)"
        )
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertIsNone(result.phase)
        self.assertEqual(result.actions[0]["id"], "BuildWorkers")
        self.assertEqual(result.validation_feedback[0]["kind"], "phase")


    async def test_bad_action_preserves_valid_siblings_and_records_feedback(self):
        client = FakeLLMClient(
            "# phase\nopening\n\n"
            "# actions\nBuildWorkers(to_count=20)\n"
            "Unsafe(unit=lookup(1))"
        )
        agent = ModelAgent(LLMConfig(), client)

        result = await agent.run("# Observation", TACTIC, [])

        self.assertEqual([action["id"] for action in result.actions], ["BuildWorkers"])
        self.assertEqual(result.validation_feedback[0]["kind"], "action_format")
        self.assertEqual(result.validation_feedback[0]["action_index"], 2)

    async def test_previous_feedback_is_part_of_the_next_user_message_only(self):
        client = FakeLLMClient()
        agent = ModelAgent(LLMConfig(), client)
        feedback = [
            {
                "kind": "action",
                "action": {"id": "Unknown", "args": {}},
                "error": "unknown action",
            }
        ]

        await agent.run("# Observation", TACTIC, [], feedback)

        messages = client.calls[0]
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("<previous_validation_feedback>", messages[1]["content"])
        self.assertIn("unknown action", messages[1]["content"])


class LLMClientTests(unittest.TestCase):


    def test_request_uses_2048_tokens_without_provider_specific_fields(self):
        config = LLMConfig(
            model="test-model",
            base_url="https://example.com",
            api_key="test-key",
        )
        client = LLMClient(config)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read():
                return b'{"choices":[{"message":{"content":"{}"}}]}'

        with patch("llm.client.request.urlopen", return_value=Response()) as urlopen:
            client._complete_sync([{"role": "user", "content": "json"}])

        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(body["max_tokens"], 2048)
        self.assertEqual(
            set(body),
            {"model", "messages", "temperature", "max_tokens"},
        )

class TraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_raw_response_usage_and_parse_reports_are_preserved(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import AsyncMock
        from llm.telemetry import Telemetry

        raw_reply = "  # phase\nopening\n# actions\nBuild Workers(to count=20)\nUnsafe(unit=lookup(1))\n "
        payload = json.dumps({
            "id": "response-1", "model": "test",
            "choices": [{"message": {"content": raw_reply}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45},
        })
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return payload.encode("utf-8")

        with tempfile.TemporaryDirectory() as directory:
            trace = Telemetry(directory=Path(directory))
            client = LLMClient(LLMConfig(model="test", base_url="https://example.invalid", api_key="secret-key"))
            with patch("llm.client.request.urlopen", side_effect=[TimeoutError("timed out"), Response()]), patch("llm.client.asyncio.sleep", new_callable=AsyncMock):
                result = await ModelAgent(client.config, client).run("clean obs", TACTIC, [], trace=trace, iteration=7)
            rows = [json.loads(line) for line in (trace.directory / "model.jsonl").read_text(encoding="utf-8").splitlines()]
            events = [json.loads(line) for line in (trace.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["stage"] for row in rows], ["request", "response", "parsed"])
            self.assertEqual(rows[1]["reply"], raw_reply)
            self.assertEqual(rows[1]["raw_response"], payload)
            self.assertEqual(rows[1]["usage"]["completion_tokens"], 45)
            self.assertEqual(rows[1]["attempt"], 2)
            self.assertEqual(rows[2]["parse_report"]["sources"][0]["source_index"], 1)
            self.assertEqual(len(result.validation_feedback), 1)
            self.assertTrue(all(row["decision_id"] == "d7" for row in rows + events))
            self.assertTrue(any(row["event"] == "transport_error" and row["retrying"] for row in events))
            self.assertNotIn("secret-key", json.dumps(rows + events))
