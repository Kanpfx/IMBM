import json
import tempfile
import unittest
from pathlib import Path

from sc2.data import Result

from game.bot.main import MyBot
from llm.telemetry import Telemetry


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

            telemetry.observation(iteration=10, resources={"minerals": 50})
            row = json.loads((telemetry.directory / "obs.jsonl").read_text("utf-8"))
            self.assertEqual(row["iteration"], 10)

    def test_match_result_updates_metadata_without_touching_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = Telemetry({"model": "test"}, Path(temp_dir))
            accepted_path = telemetry.directory / "accepted_actions.jsonl"
            original_actions = accepted_path.read_text("utf-8")

            telemetry.update_metadata(result="Victory", victory=True)

            metadata = json.loads(
                (telemetry.directory / "metadata.json").read_text("utf-8")
            )
            self.assertEqual(
                metadata,
                {"model": "test", "result": "Victory", "victory": True},
            )
            self.assertEqual(accepted_path.read_text("utf-8"), original_actions)

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
        self.assertTrue(metadata["victory"])
        self.assertEqual(metadata["final_iteration"], 900)
        self.assertEqual(metadata["game_time_formatted"], "08:00")
        self.assertEqual(metadata["final_resources"]["workers"], 52)
        self.assertEqual(metadata["score"]["collected_vespene"], 600)
