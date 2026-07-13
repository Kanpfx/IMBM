import argparse
import json
import tempfile
import unittest
from pathlib import Path

from utils import filter_bm_sft, filter_im_sft


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class SftFilterTest(unittest.TestCase):
    def _create_run(self, root: Path) -> Path:
        run = root / "player" / "Flat32_Medium_RandomBuild" / "im_bm" / "model" / "run"
        write_json(
            run / "overview.json",
            {
                "config": {"own_race": "Terran", "map_name": "Flat32", "difficulty": "Medium"},
                "result": {"game_result": "Victory"},
            },
        )
        metrics = []
        for tick in range(0, 81, 10):
            metrics.append(
                {
                    "iteration": tick,
                    "time_seconds": tick / 2,
                    "sample_type": "periodic",
                    "unit_mineral_value": 100 + tick * 4,
                    "unit_vespene_value": 0,
                    "structure_mineral_value": 300 + tick * 2,
                    "structure_vespene_value": 0,
                    "supply_army": 2 + tick / 20,
                    "n_workers": 12 + tick / 20,
                    "n_townhalls": 1 + int(tick >= 40),
                    "n_structure_types": 2 + int(tick >= 40),
                    "supply_block_ratio": 0.0,
                }
            )
        metrics.append({**metrics[0], "sample_type": "bm_trigger"})
        (run / "metrics.jsonl").parent.mkdir(parents=True, exist_ok=True)
        (run / "metrics.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in metrics), encoding="utf-8"
        )
        write_json(
            run / "im" / "000000.json",
            {
                "tick": 0,
                "calls": [
                    {"stage": "initial", "prompt": "im prompt", "response": "bad"},
                    {"stage": "refine_1", "prompt": "repair", "response": "im final"},
                ],
                "verifier": [{"schema_error": ""}],
                "directive": {"issued_at_tick": 0},
                "result": {"actions": [{"is_valid": True}]},
            },
        )
        write_json(
            run / "bm" / "0001.json",
            {
                "task_id": 1,
                "trigger_tick": 0,
                "status": "published",
                "final_plan": ["Build workers"],
                "critics": [{"round": 1, "error_number": 0, "errors": []}],
                "calls": [
                    {"stage": "plan", "prompt": "bm prompt", "response": "bm draft"},
                    {"stage": "critic_1", "prompt": "critic", "response": "[]"},
                ],
            },
        )
        return run

    def test_filters_emit_final_im_and_bm_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "logs"
            self._create_run(root)
            im_output = Path(directory) / "im.jsonl"
            bm_output = Path(directory) / "bm.jsonl"
            im_args = argparse.Namespace(
                logs=root,
                output=im_output,
                report=None,
                lookahead_seconds=30.0,
                min_lookahead_seconds=20.0,
                decay=0.95,
                decay_seconds=5.0,
                min_score=0.0,
                window_seconds=30.0,
                top_k_per_bucket=20,
                max_per_run=80,
            )
            bm_args = argparse.Namespace(
                logs=root,
                output=bm_output,
                report=None,
                lookahead_seconds=40.0,
                min_lookahead_seconds=30.0,
                decay=0.95,
                decay_seconds=5.0,
                min_score=0.0,
                window_seconds=60.0,
                top_k_per_bucket=8,
                max_per_run=20,
            )

            self.assertEqual(filter_im_sft.run(im_args)["selected"], 1)
            self.assertEqual(filter_bm_sft.run(bm_args)["selected"], 1)
            im_record = json.loads(im_output.read_text(encoding="utf-8"))
            bm_record = json.loads(bm_output.read_text(encoding="utf-8"))
            self.assertEqual(im_record["conversations"][1]["value"], "im final")
            self.assertEqual(bm_record["conversations"][1]["value"], "bm draft")


if __name__ == "__main__":
    unittest.main()
