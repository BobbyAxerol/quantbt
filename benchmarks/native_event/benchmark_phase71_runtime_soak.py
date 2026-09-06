#!/usr/bin/env python3
"""Phase 71 warm-service WFO soak, RSS plateau, and teardown evidence."""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_phase65_native_wfo import (  # noqa: E402
    _PreparedThresholdStrategy,
    _build_runtime,
    _folds,
    _rss_mb,
    _signal_cube,
)
from quantbt.core.runtime_governance import RuntimeBudgetV1  # noqa: E402
from quantbt.backends.native_wfo import NativeWfoRuntimeV2  # noqa: E402
from tools.measurement_contract import (  # noqa: E402
    build_work_counters,
    capture_measurement_identity,
    throughput_per_second,
    typed_array_sha256,
)


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase71_runtime_soak.json"


def run(*, bars: int, candidates: int, repeats: int, workers: int) -> dict:
    folds = _folds(bars, 4)
    frame, ir_runner, initial_runtime = _build_runtime(
        bars=bars,
        folds=folds,
        workers=workers,
        schedule="fixed_matrix_v1",
    )
    initial_runtime.close()
    budget = RuntimeBudgetV1(
        max_bars=bars,
        max_workers=workers,
        max_commands=bars * candidates * len(folds),
        max_orders=bars * candidates * len(folds),
        max_active_orders=bars * candidates * len(folds),
        max_fills=bars * candidates * len(folds),
        max_audit_rows=candidates * len(folds),
        max_native_memory_bytes=512 * 1024 * 1024,
        max_metric_rows=candidates * len(folds),
    )
    runtime = NativeWfoRuntimeV2(
        ir_runner,
        folds,
        workers=workers,
        optimizer_schedule="fixed_matrix_v1",
        runtime_budget=budget,
    )
    thresholds = np.linspace(-0.002, 0.002, candidates)
    params = tuple({"threshold": float(value)} for value in thresholds)
    prepared = _PreparedThresholdStrategy.prepare(frame["close"].to_numpy(dtype=np.float64))
    cube = _signal_cube(prepared, folds, params)
    # The cube is fold-major. Pass candidate IDs explicitly so a small smoke
    # workload cannot be misread as candidate-major when candidates < folds.
    batch = runtime.prepare_per_fold(
        cube,
        candidate_ids=np.arange(candidates, dtype=np.uint64),
    )
    first = runtime.score_prepared_batch(batch)
    expected = first.terminal_fingerprint

    rss_samples: list[float] = []
    durations: list[float] = []
    deterministic = True
    for iteration in range(repeats):
        started = perf_counter()
        current = runtime.score_prepared_batch(batch)
        durations.append(perf_counter() - started)
        deterministic = deterministic and current.terminal_fingerprint == expected
        if iteration % max(1, repeats // 10) == 0 or iteration == repeats - 1:
            gc.collect()
            rss_samples.append(_rss_mb())

    before_reset = runtime.diagnostics()
    runtime.reset()
    after_reset = runtime.diagnostics()
    replay = runtime.score_prepared_batch(batch)
    reset_parity = replay.terminal_fingerprint == expected
    runtime.cancel()
    canceled = runtime.score_prepared_batch(batch)
    cancellation_passed = set(canceled.status.tolist()) == {7}
    runtime.clear_cancellation()
    recovery = runtime.score_prepared_batch(batch)
    recovery_parity = recovery.terminal_fingerprint == expected
    batch.close()
    runtime.close()

    tail = rss_samples[len(rss_samples) // 2 :] or rss_samples
    tail_spread = max(tail) - min(tail) if tail else 0.0
    plateau_limit = max(8.0, (tail[0] if tail else 0.0) * 0.05)
    median_seconds = float(np.median(np.asarray(durations, dtype=np.float64)))
    work_counters = build_work_counters(
        supplied_market_bars=bars,
        candidate_count=candidates,
        scenario_count=1,
        symbol_count=1,
        folds=folds,
        warmup_bar_visits=0,
    )
    return {
        "schema": "quantbt-phase71-runtime-soak-v1",
        "workload": {
            "bars": bars,
            "candidates": candidates,
            "folds": len(folds),
            "repeats": repeats,
            "workers": workers,
        },
        "timing_seconds": {
            "median_warm_score": median_seconds,
            "min_warm_score": float(min(durations)),
            "max_warm_score": float(max(durations)),
        },
        "work_counters": work_counters,
        "throughput_candidate_test_bar_visits_per_second": throughput_per_second(
            work_counters["actual_simulation_bar_visits"], median_seconds
        ),
        "throughput_logical_full_tape_candidate_fold_bars_per_second": throughput_per_second(
            work_counters["logical_full_tape_candidate_fold_bar_visits"], median_seconds
        ),
        "throughput_candidate_fold_bars_per_second": throughput_per_second(
            work_counters["actual_simulation_bar_visits"], median_seconds
        ),
        "rss_mb": {
            "samples": rss_samples,
            "tail_spread": float(tail_spread),
            "plateau_limit": float(plateau_limit),
        },
        "evidence": {
            "rss_plateau": bool(tail_spread <= plateau_limit),
            "warm_deterministic": bool(deterministic),
            "reset_parity": bool(reset_parity),
            "generation_incremented": bool(
                int(after_reset["worker_generation"]) == int(before_reset["worker_generation"]) + 1
            ),
            "cancellation_typed": bool(cancellation_passed),
            "post_cancel_recovery_parity": bool(recovery_parity),
            "closed": bool(runtime.closed),
        },
        "copy_contract": {
            "intent_copy_per_warm_score_bytes": 0,
            "market_copy_per_warm_score_bytes": 0,
        },
        "runtime_diagnostics": after_reset,
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="warm prepared WFO batch once, then measure repeated score_prepared_batch calls",
            data_sha256=typed_array_sha256(
                frame.index.view("int64"),
                frame["open"].to_numpy(dtype=np.float64),
                frame["high"].to_numpy(dtype=np.float64),
                frame["low"].to_numpy(dtype=np.float64),
                frame["close"].to_numpy(dtype=np.float64),
                frame["volume"].to_numpy(dtype=np.float64),
            ),
            intent_sha256=typed_array_sha256(cube),
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=4096)
    parser.add_argument("--candidates", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(
        bars=args.bars,
        candidates=args.candidates,
        repeats=args.repeats,
        workers=args.workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
