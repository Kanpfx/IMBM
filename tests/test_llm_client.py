import json
import unittest
from unittest.mock import patch

from config.llm import LLMConfig
from llm.client import LLMClient


class LLMClientTests(unittest.TestCase):
    def test_prepared_messages_do_not_add_another_system_role(self):
        messages = [
            {"role": "system", "content": "Agent role"},
            {"role": "user", "content": "{}"},
        ]

        prepared = LLMClient.prepare_messages(messages)

        self.assertEqual(prepared, messages)
        self.assertEqual(
            sum(message["role"] == "system" for message in prepared),
            1,
        )

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
