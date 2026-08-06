import json
import tempfile
import unittest
from pathlib import Path

from tools.telemetry import Telemetry


class TelemetryTests(unittest.TestCase):
    def test_creates_timestamped_match_directory_and_separate_jsonl_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = Telemetry({"model": "test"}, Path(temp_dir))

            self.assertTrue(telemetry.directory.parent == Path(temp_dir))
            self.assertTrue(telemetry.directory.name.startswith("20"))
            self.assertEqual(
                json.loads((telemetry.directory / "metadata.json").read_text("utf-8")),
                {"model": "test"},
            )
            for filename in (
                "obs.jsonl",
                "im.jsonl",
                "bm.jsonl",
                "accepted_actions.jsonl",
                "events.jsonl",
            ):
                self.assertTrue((telemetry.directory / filename).is_file())

            telemetry.observation(tick=10, resources={"minerals": 50})
            row = json.loads((telemetry.directory / "obs.jsonl").read_text("utf-8"))
            self.assertEqual(row["tick"], 10)
