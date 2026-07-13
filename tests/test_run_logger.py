import json
import tempfile
import unittest
from pathlib import Path

from runtime.run_logger import RunLogger


class RunLoggerTest(unittest.TestCase):
    def test_writes_overview_and_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = RunLogger(directory)
            logger.initialize_overview({"map_name": "Flat32"})
            observation_file = logger.save_observation(120, "# Round state\nTime: 00:20")
            logger.save_im(120, {"tick": 120, "observation_file": observation_file})
            logger.save_bm(1, {"task_id": 1, "status": "error", "error": "bad response"})
            logger.finalize({"game_result": "Victory", "time_seconds": 20, "sbr": 0.0, "rur": 0.0})

            root = Path(directory)
            overview = json.loads((root / "overview.json").read_text(encoding="utf-8"))
            self.assertEqual(overview["config"]["map_name"], "Flat32")
            self.assertEqual(overview["result"]["game_result"], "Victory")
            self.assertEqual(overview["counts"], {"im_decisions": 1, "bm_tasks": 1, "bm_published": 0, "bm_errors": 1})
            self.assertTrue((root / "obs" / "000120.txt").exists())
            self.assertTrue((root / "im" / "000120.json").exists())
            self.assertTrue((root / "bm" / "0001.json").exists())


if __name__ == "__main__":
    unittest.main()
