"""Extract high-value immediate-model SFT examples from IMBM run logs.

Example:
    python utils/filter_im_sft.py --logs logs --output datasets/im_sft.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:  # Supports both `python -m` and direct `python utils/...` invocation.
    from utils.sft_filter_common import (
        find_metric_at_tick,
        future_components,
        load_periodic_metrics,
        make_run_id,
        make_sft_record,
        read_json,
        select_candidates,
        standardize_and_score,
        write_jsonl,
    )
except ModuleNotFoundError:
    from sft_filter_common import (
        find_metric_at_tick,
        future_components,
        load_periodic_metrics,
        make_run_id,
        make_sft_record,
        read_json,
        select_candidates,
        standardize_and_score,
        write_jsonl,
    )


IM_WEIGHTS = {
    "unit_value": 1.0,
    "structure_value": 0.8,
    "supply_army": 0.8,
    "n_workers": 0.5,
    "n_townhalls": 0.8,
    "supply_block_ratio": -1.0,
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Filter high-value IM SFT examples from IMBM logs.")
    result.add_argument("--logs", type=Path, default=Path("logs"), help="Root directory containing run logs.")
    result.add_argument("--output", type=Path, required=True, help="Output ShareGPT-compatible JSONL path.")
    result.add_argument("--report", type=Path, help="Optional JSON report path.")
    result.add_argument("--lookahead-seconds", type=float, default=30.0)
    result.add_argument("--min-lookahead-seconds", type=float, default=20.0)
    result.add_argument("--decay", type=float, default=0.95)
    result.add_argument("--decay-seconds", type=float, default=5.0)
    result.add_argument("--min-score", type=float, default=0.0)
    result.add_argument("--window-seconds", type=float, default=30.0)
    result.add_argument("--top-k-per-bucket", type=int, default=20)
    result.add_argument("--max-per-run", type=int, default=80)
    return result


def _is_valid_im(record: dict) -> bool:
    calls = record.get("calls")
    verifier = record.get("verifier")
    actions = record.get("result", {}).get("actions")
    if not isinstance(calls, list) or not calls or not isinstance(verifier, list) or not verifier:
        return False
    if not isinstance(actions, list) or not actions:
        return False
    if verifier[-1].get("schema_error"):
        return False
    return all(action.get("is_valid", True) and not action.get("error") for action in actions if isinstance(action, dict)) and all(
        isinstance(action, dict) for action in actions
    )


def collect(args: argparse.Namespace) -> tuple[list[dict], Counter]:
    candidates: list[dict] = []
    rejected: Counter = Counter()
    log_root = args.logs.resolve()
    for overview_path in log_root.rglob("overview.json"):
        run_dir = overview_path.parent
        overview = read_json(overview_path)
        if not overview or overview.get("result", {}).get("game_result") != "Victory":
            rejected["not_victory"] += 1
            continue
        periodic_metrics = load_periodic_metrics(run_dir)
        if not periodic_metrics:
            rejected["missing_periodic_metrics"] += 1
            continue
        config = overview.get("config", {})
        for im_path in sorted((run_dir / "im").glob("*.json")):
            record = read_json(im_path)
            if not record or not _is_valid_im(record):
                rejected["invalid_im_record"] += 1
                continue
            tick = record.get("tick")
            calls = record["calls"]
            if not isinstance(tick, int) or not isinstance(calls[0].get("prompt"), str) or not isinstance(calls[-1].get("response"), str):
                rejected["missing_im_prompt_or_response"] += 1
                continue
            anchor = find_metric_at_tick(run_dir, periodic_metrics, tick)
            if not anchor:
                rejected["missing_anchor_metric"] += 1
                continue
            raw = future_components(
                anchor,
                periodic_metrics,
                args.lookahead_seconds,
                args.min_lookahead_seconds,
                args.decay,
                args.decay_seconds,
                (
                    "unit_mineral_value",
                    "unit_vespene_value",
                    "structure_mineral_value",
                    "structure_vespene_value",
                    "supply_army",
                    "n_workers",
                    "n_townhalls",
                    "supply_block_ratio",
                ),
            )
            if raw is None:
                rejected["insufficient_lookahead"] += 1
                continue
            raw["unit_value"] = raw.pop("unit_mineral_value", 0.0) + raw.pop("unit_vespene_value", 0.0)
            raw["structure_value"] = raw.pop("structure_mineral_value", 0.0) + raw.pop("structure_vespene_value", 0.0)
            candidates.append(
                {
                    "id": f"{make_run_id(log_root, run_dir)}/im/{tick:06d}",
                    "run_id": make_run_id(log_root, run_dir),
                    "tick": tick,
                    "time_seconds": anchor["time_seconds"],
                    "config": config,
                    "prompt": calls[0]["prompt"],
                    "response": calls[-1]["response"],
                    "components": raw,
                    "score": 0.0,
                }
            )
    return candidates, rejected


def run(args: argparse.Namespace) -> dict:
    candidates, rejected = collect(args)
    # Add value dimensions after the helper's generic metric scan.
    for candidate in candidates:
        candidate["components"].setdefault("unit_value", 0.0)
        candidate["components"].setdefault("structure_value", 0.0)
    standardize_and_score(candidates, IM_WEIGHTS)
    selected = select_candidates(
        candidates, args.min_score, args.window_seconds, args.top_k_per_bucket, args.max_per_run
    )
    write_jsonl(args.output, (make_sft_record(candidate, "im") for candidate in selected))
    report = {"candidates": len(candidates), "selected": len(selected), "rejected": dict(rejected)}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    args = parser().parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
