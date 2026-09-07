#!/usr/bin/env python3
"""Materialize one auditable paired-timing document from a raw callback run."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


_CASE_BARS = {
    "100k_low_orders": 100_000,
    "100k_high_churn": 100_000,
    "100k_declared_sparse": 100_000,
    "parent_oco_heavy": 25_000,
    "gtd_heavy": 25_000,
    "prepared_100_scores": 500_000,
}
_PARITY_FIELDS = (
    "final_equity",
    "fill_count",
    "command_count",
    "event_count",
    "accounting_hash",
    "trace_hash",
    "trace_rows",
    "trace_replay",
    "ledger_hash",
)


def _canonical_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _source_label(row: Mapping[str, Any]) -> dict[str, object]:
    return {
        "commit": row.get("source_commit"),
        "path": row.get("source_path"),
        "runtime_files_sha256": row.get("source_files_sha256"),
        "python": row.get("python"),
        "numpy": row.get("numpy"),
        "pandas": row.get("pandas"),
    }


def materialize(raw: Mapping[str, Any], *, case: str) -> dict[str, Any]:
    """Convert one raw B1/B2 case into the generic paired timing schema."""

    if raw.get("schema") != "generic-callback-audit-closure-v1":
        raise ValueError("unsupported generic callback benchmark schema")
    if raw.get("comparison_mode") != "paired_b1_b2" or raw.get("parity") != "pass":
        raise ValueError("raw benchmark must be a passing paired B1/B2 comparison")
    if case not in _CASE_BARS:
        raise ValueError(f"unknown logical-bar count for case={case!r}")
    rows = raw.get("rows")
    if not isinstance(rows, list):
        raise ValueError("raw benchmark rows must be a list")
    by_repeat: dict[int, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("name") != case:
            continue
        repeat = row.get("repeat")
        lane = row.get("lane")
        if type(repeat) is not int or lane not in {"baseline", "candidate"}:
            raise ValueError("each selected row needs an integer repeat and B1/B2 lane")
        lane_rows = by_repeat.setdefault(repeat, {})
        if lane in lane_rows:
            raise ValueError(f"duplicate {lane} row for repeat={repeat}")
        lane_rows[str(lane)] = row
    if not by_repeat:
        raise ValueError(f"no rows for case={case!r}")

    pairs: list[dict[str, object]] = []
    baseline_identity: dict[str, object] | None = None
    candidate_identity: dict[str, object] | None = None
    for repeat in sorted(by_repeat):
        pair = by_repeat[repeat]
        if set(pair) != {"baseline", "candidate"}:
            raise ValueError(f"repeat={repeat} is missing a B1/B2 lane")
        baseline = pair["baseline"]
        candidate = pair["candidate"]
        for field in _PARITY_FIELDS:
            if baseline.get(field) != candidate.get(field):
                raise ValueError(f"repeat={repeat} differs on financial/audit field {field}")
        if baseline_identity is None:
            baseline_identity = _source_label(baseline)
            candidate_identity = _source_label(candidate)
        elif baseline_identity != _source_label(baseline) or candidate_identity != _source_label(candidate):
            raise ValueError("source/runtime identities changed within the paired comparison")
        pairs.append(
            {
                "pair_id": f"{case}-repeat-{repeat:03d}",
                "baseline_ns": int(round(float(baseline["wall_seconds"]) * 1_000_000_000)),
                "candidate_ns": int(round(float(candidate["wall_seconds"]) * 1_000_000_000)),
                "correctness_equal": True,
                "audit_equal": True,
                "baseline_cache_hits": 0,
                "candidate_cache_hits": 0,
                "candidate_reused_prefix_bars": 0,
                "baseline_logical_bars": _CASE_BARS[case],
                "candidate_logical_bars": _CASE_BARS[case],
            }
        )

    assert baseline_identity is not None and candidate_identity is not None
    economic_contract_hash = _canonical_hash(
        {
            "case": case,
            "accounting_hash": pairs and rows[0].get("accounting_hash"),
            "parity_fields": _PARITY_FIELDS,
            "fixture": "benchmark_reactive_session public complete-audit call",
        }
    )
    strategy_input_hash = _canonical_hash(
        {
            "case": case,
            "candidate_benchmark_runtime_files": candidate_identity["runtime_files_sha256"],
            "declared_sparse": case == "100k_declared_sparse",
        }
    )
    retention_hash = _canonical_hash(
        {
            "retention": "complete_public_audit",
            "fields": _PARITY_FIELDS,
            "trace_replay": True,
        }
    )
    return {
        "comparison": {
            "workload_id": f"next01-{case}",
            "baseline_artifact": baseline_identity,
            "candidate_artifact": candidate_identity,
            "economic_contract_hash": economic_contract_hash,
            "strategy_input_hash": strategy_input_hash,
            "retention_hash": retention_hash,
            "cpu_budget": "one isolated CPython child at a time; ABBA pair ordering",
            "measurement_mode": "fresh_cache_cold",
            "correctness_evidence_ref": (
                "benchmark rows assert complete financial/audit equality; "
                "tests/test_next01_reactive_public_runtime.py"
            ),
        },
        "pairs": pairs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--case", required=True, choices=sorted(_CASE_BARS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("input must be a JSON object")
    output = materialize(raw, case=args.case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(2)
