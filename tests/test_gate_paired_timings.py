from __future__ import annotations

import copy

import pytest

from tools.gate_paired_timings import evaluate
from tools.materialize_generic_callback_pairs import materialize


def _document(count: int = 100) -> dict:
    pairs = []
    for ordinal in range(count):
        baseline = 1_000_000_000 + ordinal * 1000
        pairs.append(
            {
                "pair_id": f"pair-{ordinal:03d}",
                "baseline_ns": baseline,
                "candidate_ns": int(baseline * 0.75),
                "correctness_equal": True,
                "audit_equal": True,
                "baseline_cache_hits": 0,
                "candidate_cache_hits": 0,
                "candidate_reused_prefix_bars": 0,
                "baseline_logical_bars": 100_000,
                "candidate_logical_bars": 100_000,
            }
        )
    return {
        "comparison": {
            "workload_id": "test-workload",
            "baseline_artifact": "B1",
            "candidate_artifact": "B2",
            "economic_contract_hash": "economics",
            "strategy_input_hash": "strategy",
            "retention_hash": "audit",
            "cpu_budget": "one sequential process",
            "measurement_mode": "fresh_cache_cold",
            "correctness_evidence_ref": "tests/test_gate_paired_timings.py",
        },
        "pairs": pairs,
    }


def test_gate_accepts_a_paired_fresh_cache_cold_pass() -> None:
    report = evaluate(_document(), target_ratio=0.80, p95_budget=1.05, bootstrap_samples=500)

    assert report["p50_outcome"] == "MET_P50_TARGET"
    assert report["p95_outcome"] == "WITHIN_OBSERVED_P95_BUDGET"
    assert report["median_paired_runtime_ratio"] < 0.80


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda document: document["pairs"][0].__setitem__("audit_equal", False), "audit_equal"),
        (lambda document: document["pairs"][0].__setitem__("candidate_cache_hits", 1), "candidate_cache_hits"),
        (lambda document: document["pairs"][0].__setitem__("candidate_logical_bars", 99), "logical work"),
    ],
)
def test_gate_rejects_invalid_fresh_evidence(mutator, message: str) -> None:
    document = copy.deepcopy(_document())
    mutator(document)

    with pytest.raises(ValueError, match=message):
        evaluate(document, target_ratio=0.80, p95_budget=1.05, bootstrap_samples=500)


def test_gate_reports_insufficient_tail_sample_count() -> None:
    report = evaluate(_document(30), target_ratio=0.80, p95_budget=1.05, bootstrap_samples=500)

    assert report["p50_outcome"] == "MET_P50_TARGET"
    assert report["p95_outcome"] == "INCONCLUSIVE_TAIL_SAMPLE_COUNT"


def test_materializer_preserves_only_exact_raw_pairs() -> None:
    baseline = {
        "name": "100k_low_orders",
        "repeat": 0,
        "lane": "baseline",
        "wall_seconds": 1.0,
        "final_equity": 100.0,
        "fill_count": 2,
        "command_count": 2,
        "event_count": 4,
        "accounting_hash": "accounting",
        "trace_hash": "trace",
        "trace_rows": 10,
        "trace_replay": {"pass": True},
        "ledger_hash": "ledger",
        "source_commit": "baseline",
        "source_path": "/baseline",
        "source_files_sha256": {"runtime": "baseline"},
        "python": "3.12",
        "numpy": "2",
        "pandas": "2",
    }
    candidate = dict(baseline, lane="candidate", wall_seconds=0.75, source_commit="candidate", source_path="/candidate")
    raw = {
        "schema": "generic-callback-audit-closure-v1",
        "comparison_mode": "paired_b1_b2",
        "parity": "pass",
        "rows": [baseline, candidate],
    }

    document = materialize(raw, case="100k_low_orders")

    assert document["pairs"][0]["baseline_ns"] == 1_000_000_000
    assert document["pairs"][0]["candidate_ns"] == 750_000_000
    assert document["pairs"][0]["audit_equal"] is True


def test_materializer_rejects_a_financial_mismatch() -> None:
    baseline = {
        "name": "100k_low_orders", "repeat": 0, "lane": "baseline", "wall_seconds": 1.0,
        "final_equity": 100.0, "fill_count": 2, "command_count": 2, "event_count": 4,
        "accounting_hash": "accounting", "trace_hash": "trace", "trace_rows": 10,
        "trace_replay": {"pass": True}, "ledger_hash": "ledger", "source_commit": "baseline",
        "source_path": "/baseline", "source_files_sha256": {"runtime": "baseline"},
        "python": "3.12", "numpy": "2", "pandas": "2",
    }
    candidate = dict(baseline, lane="candidate", wall_seconds=0.75, final_equity=101.0)
    raw = {
        "schema": "generic-callback-audit-closure-v1",
        "comparison_mode": "paired_b1_b2",
        "parity": "pass",
        "rows": [baseline, candidate],
    }

    with pytest.raises(ValueError, match="final_equity"):
        materialize(raw, case="100k_low_orders")
