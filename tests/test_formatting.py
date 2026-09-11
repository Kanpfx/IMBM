import json
import tempfile
import unittest
from pathlib import Path

from game.actions.errors import OutputFormatError
from game.actions.formatting import format_action, format_feedback
from llm.model_output import parse_model_payload
from llm.telemetry import Telemetry


class FormattingTests(unittest.TestCase):
    def test_nested_dsl_round_trip_preserves_strings_and_special_values(self):
        action = {"id": "Example", "args": {
            "composition": {"BATTLECRUISER": {"proportion": 1.0, "priority": 0}},
            "target": {"x": 10, "y": -2.5},
            "values": [True, False, None, "true", "None", "7", "main"],
            "text": 'line one\nline two\n"quoted"',
            "path": r"C:\new\test",
            "literal": r"\n",
        }}
        rendered = format_action(action)
        self.assertIn("composition={BATTLECRUISER: {proportion: 1.0", rendered)
        self.assertIn("[true, false, null", rendered)
        result = parse_model_payload("# phase\nopening\n\n# actions\n" + rendered)
        self.assertEqual(result["actions"], [action])
        self.assertEqual(result["errors"], [])

    def test_windows_line_breaks_parse_without_unescaping_values(self):
        action = {"id": "Example", "args": {"path": r"C:\new\test"}}
        result = parse_model_payload("# phase\r\nopening\r\n\r\n# actions\r\n" + format_action(action))
        self.assertEqual(result["actions"], [action])

    def test_literal_line_breaks_get_specific_feedback(self):
        with self.assertRaisesRegex(OutputFormatError, "actual line breaks"):
            parse_model_payload(r"# phase\nopening\n# actions\nExample()")

    def test_feedback_covers_all_kinds_without_dumping_json(self):
        output = '# phase\nopening\n# actions\nBroken("quoted")'
        feedback = [
            {"kind": "output_format", "submitted_output": output, "error": "Invalid sections"},
            {"kind": "action_format", "action_index": 2, "submitted_action": "Broken(", "error": "Invalid syntax"},
            {"kind": "phase", "submitted_phase": "unknown", "error": "Unknown phase"},
            {"kind": "action", "action": {"id": "BuildStructure", "args": {}}, "error": "Missing structure_id"},
        ]
        rendered = format_feedback(feedback)
        self.assertIn('     # phase\n     opening', rendered)
        self.assertIn('Broken("quoted")', rendered)
        self.assertIn('2. Action: Broken(', rendered)
        self.assertIn('BuildStructure()', rendered)
        self.assertNotIn('"submitted_output":', rendered)
        self.assertNotIn(r'\n', rendered)
        self.assertEqual(format_feedback([]), "[None]")

    def test_jsonl_round_trip_keeps_raw_reply_and_structured_feedback(self):
        reply = '# phase\nopening\n# actions\nExample(path="C:\\\\new")'
        feedback = [{"kind": "output_format", "submitted_output": reply, "error": "Example error"}]
        with tempfile.TemporaryDirectory() as directory:
            trace = Telemetry(directory=Path(directory))
            trace.model_conversation(reply=reply, validation_feedback=feedback)
            lines = (Path(directory) / "model.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        restored = json.loads(lines[0])
        self.assertEqual(restored["reply"], reply)
        self.assertEqual(restored["validation_feedback"], feedback)
        self.assertIn(
            '     # phase\n     opening',
            format_feedback(restored["validation_feedback"]),
        )
