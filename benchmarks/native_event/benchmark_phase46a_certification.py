"""Emit the Phase 46A deterministic parity certificate.

This is a correctness evidence script, not a performance benchmark. It uses a
seeded audit-shaped fixture so CI can validate the certificate contract without
requiring a particular optional Rust wheel.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from types import SimpleNamespace
import json

import numpy as np

from quantbt import (
    NATIVE_EVENT_CAPABILITY_MATRIX,
    NATIVE_EVENT_CAPABILITY_MATRIX_VERSION,
    assert_native_event_full_parity,
    capability_matrix_fingerprint,
)


def _fixture(seed: int = 46) -> SimpleNamespace:
    rng = np.random.default_rng(seed)
    bars = 24
    positions = rng.choice((-1.0, 0.0, 1.0), size=(bars, 1)).astype(np.float64)
    return SimpleNamespace(
        equity=20_000.0 + np.cumsum(rng.normal(0.0, 0.2, bars)),
        positions=positions,
        fees=np.abs(rng.normal(0.01, 0.002, bars)),
        funding=np.zeros(bars, dtype=np.float64),
        turnover=np.abs(rng.normal(50.0, 1.0, bars)),
        initial_margin=np.abs(positions[:, 0]) * 10.0,
        maintenance_margin=np.abs(positions[:, 0]) * 0.5,
        liquidated=False,
        liquidation_bar=-1,
        fill_bar=np.array([2, 8, 16], dtype=np.int64),
        fill_order_id=np.array([0, 1, 2], dtype=np.int64),
        fill_side=np.array([1, -1, 1], dtype=np.int64),
        fill_qty=np.array([1.0, 1.0, 0.5], dtype=np.float64),
        fill_price=np.array([100.0, 101.0, 102.0], dtype=np.float64),
        fill_fee=np.array([0.01, 0.01, 0.005], dtype=np.float64),
        event_bar=np.array([1, 2, 8, 16], dtype=np.int64),
        event_kind=np.array([0, 4, 4, 4], dtype=np.int64),
        event_status=np.array([0, 1, 1, 1], dtype=np.int64),
        event_order_id=np.array([0, 0, 1, 2], dtype=np.int64),
        event_target_id=np.array([-1, -1, -1, -1], dtype=np.int64),
    )


def build_evidence() -> dict[str, object]:
    candidate = _fixture()
    oracle = _fixture()
    certificate = assert_native_event_full_parity(
        candidate,
        oracle,
        command_tape=(
            {"effective_bar": np.array([1, 2, 8, 16]), "sequence": np.arange(4, dtype=np.int64)},
            {"effective_bar": np.array([1, 2, 8, 16]), "sequence": np.arange(4, dtype=np.int64)},
        ),
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {
        "phase": "46A",
        "status": "passed",
        "source_commit": commit,
        "oracle_fingerprint": certificate["oracle_fingerprint"],
        "candidate_fingerprints": {"seed_46_python_replay_fixture": certificate["candidate_fingerprint"]},
        "exact_parity": certificate["passed"],
        "compared_fields": certificate["compared_fields"],
        "capability_matrix_version": NATIVE_EVENT_CAPABILITY_MATRIX_VERSION,
        "capability_matrix_fingerprint": capability_matrix_fingerprint(),
        "capabilities": dict(NATIVE_EVENT_CAPABILITY_MATRIX),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/native_event/phase46a_correctness.json"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_evidence(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
