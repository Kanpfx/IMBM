import unittest

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
