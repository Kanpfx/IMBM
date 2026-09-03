import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sc2.data import Result

from game.bot.main import MyBot
from llm.telemetry import Telemetry
from run import mirror_console


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
                "accepted_actions.jsonl",
                "events.jsonl",
            ):
                self.assertTrue((telemetry.directory / filename).is_file())

            telemetry.observation(iteration=10, observation="state")
            row = json.loads((telemetry.directory / "obs.jsonl").read_text("utf-8"))
            self.assertEqual(row["iteration"], 10)
            telemetry.im_conversation(
                iteration=10,
                request=[{"role": "user", "content": "decide"}],
                reply='{"phase":"opening","actions":[]}',
                valid=True,
            )
            conversation = json.loads(
                (telemetry.directory / "im.jsonl").read_text("utf-8")
            )
            self.assertEqual(conversation["iteration"], 10)
            self.assertFalse((telemetry.directory / "bm.jsonl").exists())
            self.assertFalse((telemetry.directory / "correction.jsonl").exists())

    def test_match_result_updates_metadata_without_touching_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = Telemetry({"model": "test"}, Path(temp_dir))
            accepted_path = telemetry.directory / "accepted_actions.jsonl"
            original_actions = accepted_path.read_text("utf-8")

            telemetry.update_metadata(result="Victory", game_time_seconds=480.0)

            metadata = json.loads(
                (telemetry.directory / "metadata.json").read_text("utf-8")
            )
            self.assertEqual(
                metadata,
                {
                    "model": "test",
                    "result": "Victory",
                    "game_time_seconds": 480.0,
                },
            )
            self.assertEqual(accepted_path.read_text("utf-8"), original_actions)

    def test_console_log_mirrors_stdout_and_stderr_verbatim(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "console.log"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.object(sys, "stdout", stdout), patch.object(
                sys, "stderr", stderr
            ), mirror_console(path):
                print("standard output")
                sys.stderr.write("standard error\n")

            self.assertEqual(stdout.getvalue(), "standard output\n")
            self.assertEqual(stderr.getvalue(), "standard error\n")
            self.assertEqual(
                path.read_text("utf-8"), "standard output\nstandard error\n"
            )

    def test_bot_result_metadata_contains_basic_match_summary(self):
        score = type(
            "Score",
            (),
            {
                "collected_minerals": 1200,
                "collected_vespene": 600,
                "killed_value_units": 450,
                "killed_value_structures": 300,
                "idle_worker_time": 2.5,
            },
        )()
        bot = type(
            "Bot",
            (),
            {
                "state": type("State", (), {"score": score})(),
                "_last_iteration": 900,
                "time": 480.25,
                "time_formatted": "08:00",
                "minerals": 325,
                "vespene": 175,
                "supply_used": 94,
                "supply_cap": 110,
                "supply_workers": 52,
                "supply_army": 42,
            },
        )()

        metadata = MyBot._result_metadata(bot, Result.Victory)

        self.assertEqual(metadata["result"], "Victory")
        self.assertEqual(metadata["final_iteration"], 900)
        self.assertEqual(metadata["game_time_seconds"], 480.2)
        self.assertNotIn("victory", metadata)
        self.assertNotIn("game_time_formatted", metadata)
        self.assertEqual(metadata["final_resources"]["workers"], 52)
        self.assertEqual(metadata["score"]["collected_vespene"], 600)
