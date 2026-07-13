"""Extract high-value background-model SFT examples from IMBM run logs.

Example:
    python utils/filter_bm_sft.py --logs logs --output datasets/bm_sft.jsonl
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


BM_WEIGHTS = {
    "n_townhalls": 1.2,
    "n_workers": 1.0,
    "structure_value": 1.0,
    "n_structure_types": 0.8,
    "supply_army": 0.8,
    "unit_value": 0.6,
    "supply_block_ratio": -1.0,
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Filter high-value BM SFT examples from IMBM logs.")
    result.add_argument("--logs", type=Path, default=Path("logs"), help="Root directory containing run logs.")
    result.add_argument("--output", type=Path, required=True, help="Output ShareGPT-compatible JSONL path.")
    result.add_argument("--report", type=Path, help="Optional JSON report path.")
    result.add_argument("--lookahead-seconds", type=float, default=90.0)
    result.add_argument("--min-lookahead-seconds", type=float, default=60.0)
    result.add_argument("--decay", type=float, default=0.95)
    result.add_argument("--decay-seconds", type=float, default=5.0)
    result.add_argument("--min-score", type=float, default=0.0)
    result.add_argument("--window-seconds", type=float, default=60.0)
    result.add_argument("--top-k-per-bucket", type=int, default=8)
    result.add_argument("--max-per-run", type=int, default=20)
    return result


def _directive_was_used(run_dir: Path, trigger_tick: int) -> bool:
    for im_path in (run_dir / "im").glob("*.json"):
        record = read_json(im_path)
        directive = record.get("directive") if record else None
        if isinstance(directive, dict) and directive.get("issued_at_tick") == trigger_tick:
            return True
    return False


def _plan_calls(record: dict) -> tuple[dict | None, dict | None]:
    calls = record.get("calls")
    if not isinstance(calls, list):
        return None, None
    initial = next((call for call in calls if call.get("stage") == "plan"), None)
    final = next(
        (call for call in reversed(calls) if call.get("stage") == "plan" or str(call.get("stage", "")).startswith("refine_")),
        None,
    )
    return initial, final


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
        for bm_path in sorted((run_dir / "bm").glob("*.json")):
            record = read_json(bm_path)
            if not record or record.get("status") != "published" or not record.get("final_plan"):
                rejected["invalid_bm_record"] += 1
                continue
            critics = record.get("critics")
            if not isinstance(critics, list) or not critics or critics[-1].get("error_number") != 0:
                rejected["critic_not_ready"] += 1
                continue
            tick = record.get("trigger_tick")
            initial_call, final_call = _plan_calls(record)
            if (
                not isinstance(tick, int)
                or not initial_call
                or not final_call
                or not isinstance(initial_call.get("prompt"), str)
                or not isinstance(final_call.get("response"), str)
            ):
                rejected["missing_bm_prompt_or_response"] += 1
                continue
            if not _directive_was_used(run_dir, tick):
                rejected["directive_not_used"] += 1
                continue
            anchor = find_metric_at_tick(run_dir, periodic_metrics, tick, prefer_bm_trigger=True)
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
                    "n_townhalls",
                    "n_workers",
                    "n_structure_types",
                    "supply_army",
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
                    "id": f"{make_run_id(log_root, run_dir)}/bm/{record.get('task_id', bm_path.stem)}",
                    "run_id": make_run_id(log_root, run_dir),
                    "tick": tick,
                    "time_seconds": anchor["time_seconds"],
                    "config": config,
                    "prompt": initial_call["prompt"],
                    "response": final_call["response"],
                    "components": raw,
                    "score": 0.0,
                }
            )
    return candidates, rejected


def run(args: argparse.Namespace) -> dict:
    candidates, rejected = collect(args)
    for candidate in candidates:
        candidate["components"].setdefault("unit_value", 0.0)
        candidate["components"].setdefault("structure_value", 0.0)
    standardize_and_score(candidates, BM_WEIGHTS)
    selected = select_candidates(
        candidates, args.min_score, args.window_seconds, args.top_k_per_bucket, args.max_per_run
    )
    write_jsonl(args.output, (make_sft_record(candidate, "bm") for candidate in selected))
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
