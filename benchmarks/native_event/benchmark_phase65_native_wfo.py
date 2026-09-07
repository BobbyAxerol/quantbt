#!/usr/bin/env python3
"""Phase 65 prepared native WFO runtime evidence.

This benchmark deliberately compares the same bounded Strategy-IR signal
matrix and causal folds.  It reports wall-clock phases instead of hiding
Python strategy generation or pandas report construction under one headline.
The legacy side is the existing per-fold Rust batch primitive, not an
arbitrary pandas callback WFO route; generic W0 remains a separate
compatibility/oracle workload.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from tools.measurement_contract import (  # noqa: E402
    build_work_counters,
    capture_measurement_identity,
    throughput_per_second,
    typed_array_sha256,
)

from quantbt import (  # noqa: E402
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    NativeIRFold,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    RustNativeIRRunner,
)
from quantbt.backends.native_wfo import NativeWfoRuntimeV2  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase65_native_wfo.json"


def _rss_mb() -> float:
    """Return current Linux RSS rather than a process high-water mark."""

    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _frame(bars: int) -> pd.DataFrame:
    if bars < 128:
        raise ValueError("bars must be >= 128 to form four causal folds")
    index = pd.date_range("2021-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.015 * phase + 1.8 * np.sin(phase / 23.0) + 0.6 * np.sin(phase / 5.0)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.45,
            "low": np.minimum(open_, close) - 0.45,
            "close": close,
            "volume": np.full(bars, 1_000.0),
        },
        index=index,
    )


def _folds(bars: int, fold_count: int) -> tuple[NativeIRFold, ...]:
    if fold_count < 2:
        raise ValueError("fold_count must be >= 2")
    # Expanding IS / disjoint OOS test windows.  Only test_start:test_end is
    # executed by native WFO; the earlier range remains available only to the
    # caller's causally prepared feature/signal tape.
    start = max(32, bars // (fold_count + 2))
    remaining = bars - start
    test_width = remaining // fold_count
    folds: list[NativeIRFold] = []
    for fold_id in range(fold_count):
        test_start = start + fold_id * test_width
        test_end = bars if fold_id == fold_count - 1 else test_start + test_width
        train_end = test_start
        folds.append(NativeIRFold(fold_id, 0, 0, train_end, test_start, test_end))
    return tuple(folds)


@dataclass(slots=True)
class _PreparedThresholdStrategy:
    """A W2 fixture whose cache is parameter-independent and causal."""

    close: np.ndarray
    feature: np.ndarray

    @classmethod
    def prepare(cls, close: Sequence[float]) -> "_PreparedThresholdStrategy":
        values = np.ascontiguousarray(np.asarray(close, dtype=np.float64))
        lagged = np.r_[values[0], values[:-1]]
        # The feature at t uses close[t] and close[t-1] only. Execution later
        # uses next-bar lifecycle semantics in the prepared runner.
        feature = np.tanh((values - lagged) / np.maximum(np.abs(lagged), 1.0e-12))
        return cls(values, np.ascontiguousarray(feature))

    def generate_batch(
        self,
        *,
        params_matrix: Sequence[Mapping[str, Any]],
        fold_id: int,
    ) -> np.ndarray:
        thresholds = np.asarray([float(params["threshold"]) for params in params_matrix])
        # The fold offset makes the W2 cube non-trivially fold-specific while
        # retaining a fully deterministic full-tape signal contract.
        adjusted = self.feature + float(fold_id) * 1.0e-4
        return np.ascontiguousarray(np.where(adjusted[None, :] >= thresholds[:, None], 1.0, -1.0))


def _build_runtime(*, bars: int, folds: tuple[NativeIRFold, ...], workers: int, schedule: str):
    frame = _frame(bars)
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=3.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend="rust",
        )
    )
    full_runner = backend.prepare_rust_batched_runner(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        symbols=["BTC"],
        contract_size=1.0,
    )
    program = NativeStrategyIR(
        NativeStrategyKind.SIGNAL_TARGET,
        "BTC",
        parameters=NativeStrategyParameters(quantity=1.0),
    )
    ir_runner = RustNativeIRRunner(full_runner, program)
    return frame, ir_runner, NativeWfoRuntimeV2(
        ir_runner,
        folds,
        workers=workers,
        optimizer_schedule=schedule,
    )


def _timed(call: Callable[[], Any], *, repeats: int) -> tuple[float, Any]:
    values: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        values.append(perf_counter() - started)
    return float(median(values)), result


def _signal_cube(
    strategy: _PreparedThresholdStrategy,
    folds: Sequence[NativeIRFold],
    params: Sequence[Mapping[str, Any]],
) -> np.ndarray:
    return np.ascontiguousarray(
        np.stack(
            [strategy.generate_batch(params_matrix=params, fold_id=int(fold.fold_id)) for fold in folds],
            axis=0,
        ),
        dtype=np.float64,
    )


def _oracle_metrics(
    runner: RustNativeIRRunner,
    cube: np.ndarray,
    folds: Sequence[NativeIRFold],
    *,
    workers: int,
) -> dict[str, np.ndarray]:
    output: dict[str, list[np.ndarray]] = {
        "final_equity": [],
        "total_fee": [],
        "total_funding": [],
        "turnover": [],
        "fill_count": [],
        "rejected_count": [],
    }
    for fold_index, fold in enumerate(folds):
        result = runner.run_fold_batch_score(cube[fold_index], fold, workers=workers)
        for name in output:
            output[name].append(np.asarray(getattr(result, name)))
    return {name: np.ascontiguousarray(np.concatenate(values)) for name, values in output.items()}


def _native_metrics(matrix) -> dict[str, np.ndarray]:
    # The runtime sorts candidate then fold; re-sort the oracle to the same
    # order below instead of relying on its historical fold-major layout.
    return {
        "final_equity": matrix.final_equity,
        "total_fee": matrix.total_fee,
        "total_funding": matrix.total_funding,
        "turnover": matrix.turnover,
        "fill_count": matrix.fill_count,
        "rejected_count": matrix.rejected_count,
    }


def _sorted_oracle_metrics(
    values: Mapping[str, np.ndarray], candidates: int, folds: Sequence[NativeIRFold]
) -> dict[str, np.ndarray]:
    # `run_fold_batch_score` yields one candidate-major array per fold; stack
    # candidate-major then fold-major to match NativeWfoMetricMatrixV2.
    return {
        name: np.ascontiguousarray(
            values[name].reshape(len(folds), candidates).T.reshape(-1)
        )
        for name in values
    }


def _parity(
    native_matrix,
    oracle: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    native = _native_metrics(native_matrix)
    errors = {
        name: float(np.max(np.abs(np.asarray(native[name], dtype=np.float64) - oracle[name])))
        for name in ("final_equity", "total_fee", "total_funding", "turnover")
    }
    exact = {
        name: bool(np.array_equal(np.asarray(native[name]), oracle[name]))
        for name in ("fill_count", "rejected_count")
    }
    return {
        "passed": bool(all(value == 0.0 for value in errors.values()) and all(exact.values())),
        "max_abs_error": errors,
        "exact_counts": exact,
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    phases = payload["timings_seconds"]
    rows = "\n".join(
        f"| `{name}` | {value:.6f} |" for name, value in phases.items()
    )
    return "\n".join(
        (
            "# Phase 65 Native WFO Runtime Benchmark",
            "",
            "The score route is bounded single-symbol StrategyIR only. Times are",
            "median wall seconds on the local machine; they are not a generic WFO claim.",
            "",
            "| Phase | Median seconds |",
            "|---|---:|",
            rows,
            "",
            f"- Candidates: `{payload['workload']['candidates']}`",
            f"- Folds: `{payload['workload']['folds']}`",
            f"- Bars: `{payload['workload']['bars']}`",
            f"- Native worker count: `{payload['workload']['workers']}`",
            f"- Actual candidate-test-bar visits/s: `{payload['throughput_candidate_test_bar_visits_per_second']:.1f}`",
            f"- Logical full-tape candidate-fold bars/s (input-volume only): `{payload['throughput_logical_full_tape_candidate_fold_bars_per_second']:.1f}`",
            f"- Persistent runtime / prior fold-oracle score ratio: `{payload['persistent_runtime_vs_legacy_fold_oracle_speedup']:.3f}x`",
            f"- Exact prior fold-batch oracle parity: `{payload['parity']['passed']}`",
            f"- Score path market/candidate execution copies: `{payload['copy_contract']['market_copy_bytes']}` / `{payload['copy_contract']['candidate_execution_copy_bytes']}` bytes",
            "",
            "`intent_ingest` is the one controlled Python-to-Rust copy. `native_score_and_metrics`",
            "keeps command compilation, execution, and scalar metric reduction fused in Rust;",
            "`cold_report` is intentionally measured separately.",
            "",
        )
    )


def run(*, bars: int, candidates: int, fold_count: int, workers: int, repeats: int, optimizer_trials: int) -> dict[str, Any]:
    if candidates <= 0 or repeats <= 0 or optimizer_trials < 0:
        raise ValueError("candidates/repeats must be > 0 and optimizer_trials must be >= 0")
    cold_rss = _rss_mb()
    folds = _folds(bars, fold_count)
    started = perf_counter()
    frame, ir_runner, runtime = _build_runtime(
        bars=bars,
        folds=folds,
        workers=workers,
        schedule="fixed_matrix_v1",
    )
    runtime_prepare_seconds = perf_counter() - started
    try:
        strategy_prepare_seconds, strategy = _timed(
            lambda: _PreparedThresholdStrategy.prepare(frame["close"].to_numpy(dtype=np.float64)),
            repeats=repeats,
        )
        params = tuple(
            {"threshold": float(value)}
            for value in np.linspace(-0.0015, 0.0015, candidates, dtype=np.float64)
        )
        candidate_ids = np.arange(candidates, dtype=np.uint64)
        strategy_generate_seconds, cube = _timed(
            lambda: _signal_cube(strategy, folds, params), repeats=repeats
        )
        intent_ingest_seconds, batch = _timed(
            lambda: runtime.prepare_per_fold(cube, candidate_ids=candidate_ids), repeats=repeats
        )
        native_score_seconds, matrix = _timed(
            lambda: runtime.score_prepared_batch(batch), repeats=repeats
        )
        report_seconds, report = _timed(matrix.to_frame, repeats=repeats)
        del report
        gc.collect()
        warm_rss = _rss_mb()
        legacy_fold_oracle_seconds, legacy_metrics = _timed(
            lambda: _sorted_oracle_metrics(
                _oracle_metrics(ir_runner, cube, folds, workers=workers), candidates, folds
            ),
            repeats=repeats,
        )
        parity = _parity(matrix, legacy_metrics)
        optimizer_seconds = 0.0
        optimizer_metadata: dict[str, Any] = {"executed": False}
        if optimizer_trials:
            _, _, optimizer_runtime = _build_runtime(
                bars=bars,
                folds=folds,
                workers=workers,
                schedule="certified_sequential_v1",
            )
            try:
                optimizer_seconds, optimized = _timed(
                    lambda: optimizer_runtime.optimize_prepared(
                        strategy,
                        param_ranges={"threshold": (-0.0015, 0.0015, 0.0003)},
                        n_trials=optimizer_trials,
                        seed=42,
                        top_k_audit=1,
                    ),
                    repeats=1,
                )
                optimizer_metadata = {
                    "executed": True,
                    "schedule": optimized.schedule,
                    "best_value": optimized.best_value,
                    "candidate_sequence_equivalent_to_sequential": optimized.metadata[
                        "candidate_sequence_equivalent_to_sequential"
                    ],
                    "audit_rows": 0 if optimized.audit_matrix is None else len(optimized.audit_matrix.candidate_id),
                }
            finally:
                optimizer_runtime.close()
        after_rss = _rss_mb()
        work_counters = build_work_counters(
            supplied_market_bars=bars,
            candidate_count=candidates,
            scenario_count=1,
            symbol_count=1,
            folds=folds,
            warmup_bar_visits=0,
        )
        return {
            "benchmark": "phase65_native_wfo_runtime_v2",
            "scope": "single_symbol_strategy_ir_signal_target_v1_reset_flat_per_oos_fold",
            "workload": {
                "bars": bars,
                "candidates": candidates,
                "folds": len(folds),
                "workers": workers,
                "repeats": repeats,
                "optimizer_trials": optimizer_trials,
            },
            "timings_seconds": {
                "runtime_prepare": float(runtime_prepare_seconds),
                "strategy_prepare": float(strategy_prepare_seconds),
                "strategy_generate": float(strategy_generate_seconds),
                "intent_ingest": float(intent_ingest_seconds),
                "native_score_and_metrics": float(native_score_seconds),
                "legacy_fold_oracle": float(legacy_fold_oracle_seconds),
                "cold_report": float(report_seconds),
                "optimizer_end_to_end": float(optimizer_seconds),
            },
            "work_counters": work_counters,
            "throughput_candidate_test_bar_visits_per_second": throughput_per_second(
                work_counters["actual_simulation_bar_visits"], native_score_seconds
            ),
            "throughput_logical_full_tape_candidate_fold_bars_per_second": throughput_per_second(
                work_counters["logical_full_tape_candidate_fold_bar_visits"], native_score_seconds
            ),
            "throughput_candidate_fold_bars_per_second": throughput_per_second(
                work_counters["actual_simulation_bar_visits"], native_score_seconds
            ),
            "persistent_runtime_vs_legacy_fold_oracle_speedup": float(
                legacy_fold_oracle_seconds / native_score_seconds
            ),
            "copy_contract": {
                "market_copy_bytes": int(matrix.metadata["market_copy_bytes"]),
                "candidate_execution_copy_bytes": int(matrix.metadata["candidate_execution_copy_bytes"]),
                "intent_ingest_bytes": int(batch.intent_ingest_bytes),
            },
            "runtime": {
                **dict(runtime.diagnostics()),
                "active_worker_count": int(matrix.metadata["active_worker_count"]),
                "worker_tasks": list(matrix.metadata["worker_tasks"]),
            },
            "rss_mb": {
                "cold_after_import": float(cold_rss),
                "warm_after_score": float(warm_rss),
                "after_optimizer": float(after_rss),
                "warm_incremental": float(warm_rss - cold_rss),
            },
            "optimizer": optimizer_metadata,
            "measurement_identity": capture_measurement_identity(
                root=ROOT,
                warmup_procedure="warm prepared signal cube, intent batch, and score matrix before repeated median timing",
                data_sha256=typed_array_sha256(
                    frame.index.view("int64"),
                    frame["open"].to_numpy(dtype=np.float64),
                    frame["high"].to_numpy(dtype=np.float64),
                    frame["low"].to_numpy(dtype=np.float64),
                    frame["close"].to_numpy(dtype=np.float64),
                    frame["volume"].to_numpy(dtype=np.float64),
                ),
                intent_sha256=typed_array_sha256(candidate_ids, cube),
            ),
            "parity": parity,
        }
    finally:
        runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=4_096)
    parser.add_argument("--candidates", type=int, default=64)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--optimizer-trials", type=int, default=16)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(
        bars=args.bars,
        candidates=args.candidates,
        fold_count=args.folds,
        workers=args.workers,
        repeats=args.repeats,
        optimizer_trials=args.optimizer_trials,
    )
    if not payload["parity"]["passed"]:
        raise SystemExit(f"native WFO parity failed: {payload['parity']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
