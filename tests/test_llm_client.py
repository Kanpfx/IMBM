import unittest

from tools.llm_client import LLMClient


class LLMClientTests(unittest.TestCase):
    def test_prepared_messages_start_with_no_thinking_constraint(self):
        messages = [{"role": "user", "content": "{}"}]

        prepared = LLMClient.prepare_messages(messages)

        self.assertEqual(prepared[0]["role"], "system")
        self.assertIn("Do not use extended thinking", prepared[0]["content"])
        self.assertEqual(prepared[1:], messages)
