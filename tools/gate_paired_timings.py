#!/usr/bin/env python3
"""Evaluate supplied paired timings without certifying source correctness.

This tool deliberately consumes a small, versioned evidence document rather
than importing QuantBT or running a benchmark.  The producer must establish
financial/audit parity independently before it sets the equality flags below.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any, Mapping


SCHEMA = "quantbt.paired_timing_gate.v1"
_REQUIRED_COMPARISON_FIELDS = (
    "workload_id",
    "baseline_artifact",
    "candidate_artifact",
    "economic_contract_hash",
    "strategy_input_hash",
    "retention_hash",
    "cpu_budget",
    "measurement_mode",
    "correctness_evidence_ref",
)


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _positive(row: Mapping[str, Any], key: str) -> float:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric, not bool/string")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{key} must be finite and positive")
    return number


def evaluate(
    document: Mapping[str, Any],
    *,
    target_ratio: float,
    p95_budget: float,
    bootstrap_samples: int,
) -> dict[str, Any]:
    """Validate a fresh paired comparison and return descriptive statistics."""

    if not (0.0 < target_ratio < 1.0):
        raise ValueError("target_ratio must be > 0 and < 1")
    if not (math.isfinite(p95_budget) and p95_budget >= 1.0):
        raise ValueError("p95_budget must be finite and >= 1")
    if not 500 <= bootstrap_samples <= 20_000:
        raise ValueError("bootstrap_samples must be between 500 and 20000")

    comparison = document["comparison"]
    if not isinstance(comparison, Mapping):
        raise ValueError("comparison must be an object")
    missing = [key for key in _REQUIRED_COMPARISON_FIELDS if comparison.get(key) in (None, "")]
    if missing:
        raise ValueError("comparison metadata incomplete: " + ", ".join(missing))
    if comparison["measurement_mode"] != "fresh_cache_cold":
        raise ValueError("this gate only accepts fresh_cache_cold comparisons")

    pairs = document["pairs"]
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("pairs must be a nonempty list")

    pair_ids: list[str] = []
    baseline: list[float] = []
    candidate: list[float] = []
    ratios: list[float] = []
    for row in pairs:
        if not isinstance(row, Mapping):
            raise ValueError("each pair must be an object")
        pair_id = row["pair_id"]
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError("pair_id must be a nonempty string")
        pair_ids.append(pair_id)
        for key in ("correctness_equal", "audit_equal"):
            if row.get(key) is not True:
                raise ValueError(f"pair {pair_id}: {key} is not asserted true")
        for key in (
            "baseline_cache_hits",
            "candidate_cache_hits",
            "candidate_reused_prefix_bars",
        ):
            if type(row.get(key)) is not int or row[key] != 0:
                raise ValueError(f"pair {pair_id}: fresh gate requires integer {key}=0")
        for key in ("baseline_logical_bars", "candidate_logical_bars"):
            if type(row.get(key)) is not int or row[key] <= 0:
                raise ValueError(f"pair {pair_id}: positive integer {key} required")
        if row["baseline_logical_bars"] != row["candidate_logical_bars"]:
            raise ValueError(f"pair {pair_id}: logical work differs")
        base_ns = _positive(row, "baseline_ns")
        candidate_ns = _positive(row, "candidate_ns")
        baseline.append(base_ns)
        candidate.append(candidate_ns)
        ratios.append(candidate_ns / base_ns)
    if len(set(pair_ids)) != len(pair_ids):
        raise ValueError("duplicate pair_id")

    rng = random.Random(91373)
    bootstrap = [
        statistics.median(rng.choices(ratios, k=len(ratios)))
        for _ in range(bootstrap_samples)
    ]
    interval = [_quantile(bootstrap, 0.025), _quantile(bootstrap, 0.975)]
    median_ratio = statistics.median(ratios)
    observed_p95_ratio = _quantile(candidate, 0.95) / _quantile(baseline, 0.95)
    if len(pairs) < 30:
        p50_outcome = "INCONCLUSIVE_SAMPLE_COUNT"
    elif interval[1] <= target_ratio:
        p50_outcome = "MET_P50_TARGET"
    elif interval[0] > target_ratio:
        p50_outcome = "NOT_MET_P50_TARGET"
    else:
        p50_outcome = "INCONCLUSIVE_TARGET_CI"
    if len(pairs) < 100:
        p95_outcome = "INCONCLUSIVE_TAIL_SAMPLE_COUNT"
    elif observed_p95_ratio <= p95_budget:
        p95_outcome = "WITHIN_OBSERVED_P95_BUDGET"
    else:
        p95_outcome = "P95_BUDGET_EXCEEDED"
    return {
        "schema": SCHEMA,
        "comparison": dict(comparison),
        "pair_count": len(pairs),
        "median_paired_runtime_ratio": median_ratio,
        "paired_ratio_bootstrap_ci95": interval,
        "target_ratio": target_ratio,
        "observed_p95_runtime_ratio": observed_p95_ratio,
        "p50_outcome": p50_outcome,
        "p95_outcome": p95_outcome,
        "scope": (
            "Performance statistics of supplied measurements only. Equality flags and "
            "evidence references must be independently verified. Bootstrap CI is "
            "descriptive; observed p95 is not a tail-confidence certificate."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="one comparison/workload JSON")
    parser.add_argument("--target-ratio", required=True, type=float)
    parser.add_argument("--p95-budget", type=float, default=1.05)
    parser.add_argument("--bootstrap", type=int, default=3000)
    args = parser.parse_args(argv)
    raw = args.input.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, Mapping):
        raise ValueError("input must be a JSON object")
    report = evaluate(
        document,
        target_ratio=args.target_ratio,
        p95_budget=args.p95_budget,
        bootstrap_samples=args.bootstrap,
    )
    report["input_sha256"] = sha256(raw).hexdigest()
    print(json.dumps(report, indent=2))
    return int(
        not (
            report["p50_outcome"] == "MET_P50_TARGET"
            and report["p95_outcome"] == "WITHIN_OBSERVED_P95_BUDGET"
        )
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
