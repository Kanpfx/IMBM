"""Shared, dependency-free helpers for extracting SFT examples from run logs."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        pass
    return records


def load_periodic_metrics(run_dir: Path) -> list[dict[str, Any]]:
    """Load one periodic record per tick; BM-trigger duplicates are excluded."""
    by_tick: dict[int, dict[str, Any]] = {}
    for record in read_jsonl(run_dir / "metrics.jsonl"):
        if record.get("sample_type") != "periodic":
            continue
        tick = record.get("iteration")
        if isinstance(tick, int):
            by_tick[tick] = record
    return sorted(by_tick.values(), key=lambda item: item["iteration"])


def find_metric_at_tick(
    run_dir: Path, periodic_metrics: list[dict[str, Any]], tick: int, prefer_bm_trigger: bool = False
) -> dict[str, Any] | None:
    """Find the exact anchor snapshot. BM may use its dedicated trigger snapshot."""
    if prefer_bm_trigger:
        for record in read_jsonl(run_dir / "metrics.jsonl"):
            if record.get("sample_type") == "bm_trigger" and record.get("iteration") == tick:
                return record
    return next((record for record in periodic_metrics if record.get("iteration") == tick), None)


def metric_value(record: dict[str, Any], key: str) -> float:
    value = record.get(key, 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def future_components(
    anchor: dict[str, Any],
    periodic_metrics: list[dict[str, Any]],
    horizon_seconds: float,
    min_lookahead_seconds: float,
    decay: float,
    decay_seconds: float,
    component_keys: Iterable[str],
) -> dict[str, float] | None:
    """Discount true adjacent-state deltas after one anchor snapshot."""
    anchor_time = metric_value(anchor, "time_seconds")
    anchor_tick = anchor.get("iteration")
    future = [
        record
        for record in periodic_metrics
        if record.get("iteration", -1) > anchor_tick
        and 0 < metric_value(record, "time_seconds") - anchor_time <= horizon_seconds
    ]
    if not future or metric_value(future[-1], "time_seconds") - anchor_time < min_lookahead_seconds:
        return None

    result = {key: 0.0 for key in component_keys}
    previous = anchor
    for current in future:
        elapsed = metric_value(current, "time_seconds") - anchor_time
        weight = decay ** (elapsed / decay_seconds)
        for key in result:
            delta = metric_value(current, key) - metric_value(previous, key)
            if key == "supply_block_ratio":
                delta = max(0.0, delta)
            result[key] += weight * delta
        previous = current
    return result


def standardize_and_score(
    candidates: list[dict[str, Any]], weights: dict[str, float]
) -> None:
    """Apply per-component z-scores so mineral values do not dominate populations."""
    if not candidates:
        return
    for key, weight in weights.items():
        values = [candidate["components"][key] for candidate in candidates]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        stddev = math.sqrt(variance)
        for candidate, value in zip(candidates, values):
            zscore = 0.0 if stddev == 0 else (value - mean) / stddev
            candidate["score"] += weight * zscore


def select_candidates(
    candidates: list[dict[str, Any]],
    min_score: float,
    window_seconds: float,
    top_k_per_bucket: int,
    max_per_run: int,
) -> list[dict[str, Any]]:
    """Keep high-value, de-duplicated examples while preserving stage/config coverage."""
    filtered = [candidate for candidate in candidates if candidate["score"] >= min_score]
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for candidate in filtered:
        config = candidate["config"]
        bucket = (
            config.get("own_race", ""),
            config.get("map_name", ""),
            config.get("difficulty", ""),
            int(candidate["time_seconds"] // window_seconds),
        )
        buckets[bucket].append(candidate)

    selected: list[dict[str, Any]] = []
    for group in buckets.values():
        group.sort(key=lambda item: item["score"], reverse=True)
        selected.extend(group[:top_k_per_bucket])

    selected.sort(key=lambda item: item["score"], reverse=True)
    selected_by_run: Counter[str] = Counter()
    seen_pairs: set[str] = set()
    deduplicated: list[dict[str, Any]] = []
    for candidate in selected:
        if selected_by_run[candidate["run_id"]] >= max_per_run:
            continue
        pair = (candidate["prompt"] + "\0" + candidate["response"]).encode("utf-8")
        pair_hash = hashlib.sha256(pair).hexdigest()
        if pair_hash in seen_pairs:
            continue
        seen_pairs.add(pair_hash)
        selected_by_run[candidate["run_id"]] += 1
        deduplicated.append(candidate)
    return deduplicated


def make_sft_record(candidate: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "conversations": [
            {"from": "human", "value": candidate["prompt"]},
            {"from": "gpt", "value": candidate["response"]},
        ],
        "metadata": {
            "source": source,
            "run_id": candidate["run_id"],
            "tick": candidate["tick"],
            "time_seconds": candidate["time_seconds"],
            "quality_score": round(candidate["score"], 6),
        },
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            json.dump(record, file, ensure_ascii=False)
            file.write("\n")


def make_run_id(log_root: Path, run_dir: Path) -> str:
    return run_dir.relative_to(log_root).as_posix()

