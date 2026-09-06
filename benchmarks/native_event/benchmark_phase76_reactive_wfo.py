"""Phase 76 public reactive WFO scheduling and resource evidence.

The benchmark measures public W3 runs, not a hidden native helper.  It keeps
the strategy cost explicit: a lightweight strategy and a deliberately
Python-heavy strategy are reported separately, and the sequential and R3B
throughput schedules are not presented as equivalent TPE search paths.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
from typing import Any, Mapping

import numpy as np
import pandas as pd

from quantbt import (
    CandidateWakePlansV1,
    ExecutionConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
    WakePlanV1,
)
from quantbt.backends import ReactiveWfoRuntimeConfigV1
from quantbt.strategies import STRICT_CAUSAL_CACHE_CONTRACT_V1
from quantbt.walkforward import WalkForwardConfig


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase76_reactive_wfo.json"

REQUIREMENTS = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="none",
    context_mode="numeric",
)


def _memory_snapshot() -> dict[str, int]:
    path = Path("/proc/self/smaps_rollup")
    if not path.exists():
        return {"rss_bytes": 0, "pss_bytes": 0, "shared_bytes": 0, "private_bytes": 0}
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        label, _, remainder = line.partition(":")
        fields = remainder.split()
        if fields and fields[0].isdigit():
            values[label] = int(fields[0]) * 1024
    return {
        "rss_bytes": int(values.get("Rss", 0)),
        "pss_bytes": int(values.get("Pss", 0)),
        "shared_bytes": int(values.get("Shared_Clean", 0)) + int(values.get("Shared_Dirty", 0)),
        "private_bytes": int(values.get("Private_Clean", 0)) + int(values.get("Private_Dirty", 0)),
    }


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=bars, freq="1D", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.06 * phase + 3.2 * np.sin(phase / 19.0)
    open_ = np.r_[close[0], close[:-1]] + 0.1 * np.cos(phase / 7.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.9,
            "low": np.minimum(open_, close) - 0.9,
            "close": close,
            "volume": np.full(bars, 1_000.0),
            "funding_rate": np.where((phase.astype(np.int64) % 8) == 0, 0.0001, 0.0),
        },
        index=index,
    )


class _TaskStrategy:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, *, task, params: Mapping[str, Any], python_work: int) -> None:
        self.task = task
        self.params = dict(params)
        self.python_work = int(python_work)
        self.state = 0.0

    def reset(self, *, seed: int, task) -> None:
        assert int(seed) == int(task.seed)
        self.task = task
        self.state = 0.0

    def on_bar_close(self, context, out) -> None:
        bar = int(context.bar_index)
        for offset in range(self.python_work):
            self.state += ((bar + offset) % 17) * 1.0e-12
        direction = float(self.params["direction"])
        quantity = float(self.params["quantity"])
        exit_bar = min(int(self.task.end_bar) - 2, int(self.task.start_bar) + 12)
        if bar == int(self.task.start_bar):
            out.market(0, OrderSide.BUY if direction > 0.0 else OrderSide.SELL, quantity)
        elif bar == exit_bar:
            out.market(
                0,
                OrderSide.SELL if direction > 0.0 else OrderSide.BUY,
                quantity,
                reduce_only=True,
            )

    def quantbt_state_fingerprint(self):
        return (self.task.candidate_id, self.task.fold_id, round(self.state, 12))


class _PreparedStrategy:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def __init__(self, *, python_work: int) -> None:
        self.python_work = int(python_work)
        self.closed = False

    def build_strategy(self, *, params, task):
        assert not self.closed
        return _TaskStrategy(task=task, params=params, python_work=self.python_work)

    def close(self) -> None:
        self.closed = True


class _Factory:
    def __init__(self, *, python_work: int) -> None:
        self.python_work = int(python_work)

    def prepare_reactive_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-reactive-wfo-static-v1"
        return _PreparedStrategy(python_work=self.python_work)


class _BatchStrategy:
    quantbt_reactive_candidate_batch_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, *, params_matrix, tasks, python_work: int) -> None:
        self.params_matrix = tuple(dict(params) for params in params_matrix)
        self.tasks = tuple(tasks)
        self.python_work = int(python_work)
        self.state = np.zeros(len(self.params_matrix), dtype=np.float64)

    def on_wake_batch(self, context_batch, out_batch) -> CandidateWakePlansV1:
        plans = {}
        bar = int(context_batch.bar_index)
        for local_id in context_batch.candidate_ids.tolist():
            candidate_id = int(local_id)
            task = self.tasks[candidate_id]
            params = self.params_matrix[candidate_id]
            for offset in range(self.python_work):
                self.state[candidate_id] += ((bar + offset) % 17) * 1.0e-12
            direction = float(params["direction"])
            quantity = float(params["quantity"])
            exit_bar = min(int(task.end_bar) - 2, int(task.start_bar) + 12)
            writer = out_batch.writer(candidate_id)
            if bar == int(task.start_bar):
                writer.market(0, OrderSide.BUY if direction > 0.0 else OrderSide.SELL, quantity)
                plans[candidate_id] = WakePlanV1(next_bar=exit_bar)
            elif bar == exit_bar:
                writer.market(
                    0,
                    OrderSide.SELL if direction > 0.0 else OrderSide.BUY,
                    quantity,
                    reduce_only=True,
                )
                plans[candidate_id] = WakePlanV1()
            else:
                plans[candidate_id] = WakePlanV1()
        return CandidateWakePlansV1(plans)


class _BatchPreparedStrategy(_PreparedStrategy):
    def build_candidate_batch(self, *, params_matrix, tasks):
        assert not self.closed
        return _BatchStrategy(params_matrix=params_matrix, tasks=tasks, python_work=self.python_work)


class _BatchFactory(_Factory):
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-reactive-wfo-static-v1"
        return _BatchPreparedStrategy(python_work=self.python_work)


def _endpoint(frame: pd.DataFrame) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=frame["funding_rate"],
        report_level="minimal",
        audit_sink="none",
        reactive_execution_mode="fast",
        reactive_kernel_mode="single_pass",
        reactive_runtime="numeric_every_bar_v1",
        native_backend="rust",
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=1.0),
    )


def _config(frame: pd.DataFrame, *, trials: int) -> WalkForwardConfig:
    split_bar = max(366, min(len(frame) - 181, len(frame) // 2))
    return WalkForwardConfig(
        split_mode=str(frame.index[split_bar].date()),
        split_frequency="semi_yearly",
        window_mode="rolling",
        train_window="365D",
        min_train_bars=180,
        min_test_bars=60,
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_schedule="global",
        fold_boundary_position_policy="reset_flat",
        fold_account_policy="reset_flat",
        optuna_trials=int(trials),
        optuna_early_stopping=None,
        random_seed=19,
        candidate_selection_metric="robust_decay",
        top_is_fraction=0.25,
        is_subperiods=2,
        scoring_trading_days=365,
        min_trades_per_year=None,
        trade_penalty_factor=None,
    )


def _candidate_matrix(count: int) -> list[dict[str, float]]:
    return [
        {
            "direction": 1.0 if candidate % 2 else -1.0,
            "quantity": float(0.10 + 0.04 * candidate),
        }
        for candidate in range(count)
    ]


def _param_ranges(candidates: list[dict[str, float]]) -> dict[str, list[float]]:
    return {
        "direction": sorted({float(candidate["direction"]) for candidate in candidates}),
        "quantity": [float(candidate["quantity"]) for candidate in candidates],
    }


def _result_fingerprint(result) -> dict[str, object]:
    return {
        "params": dict(result.params),
        "objective": float(result.best_trial["objective"]),
        "folds": [
            {
                "fold_id": int(item.fold_id),
                "final_equity": float(item.result.equity.iloc[-1]),
                "fees": float(item.result.fees.sum()),
                "funding": float(item.result.funding.sum()),
            }
            for item in result.fold_results
        ],
    }


def _run_public(
    *,
    frame: pd.DataFrame,
    candidates: list[dict[str, float]],
    python_work: int,
    schedule: str,
    worker_mode: str = "inprocess",
):
    runtime_config = ReactiveWfoRuntimeConfigV1(
        worker_mode=worker_mode,
        optimizer_schedule=schedule,
        candidate_batch_size=len(candidates) if schedule == "throughput_batch_v1" else 1,
    )
    factory = _BatchFactory(python_work=python_work) if schedule == "throughput_batch_v1" else _Factory(python_work=python_work)
    runtime = _endpoint(frame).prepare_reactive_walk_forward(
        data=frame,
        strategy_factory=factory,
        walkforward_config=_config(frame, trials=len(candidates)),
        runtime_config=runtime_config,
        symbols=["BTCUSDT"],
    )
    try:
        started = perf_counter()
        if schedule == "throughput_batch_v1":
            result = runtime.backtest(candidate_matrix=candidates, param_ranges=_param_ranges(candidates))
        else:
            result = runtime.backtest(param_ranges=_param_ranges(candidates))
        elapsed = perf_counter() - started
        runtime_meta = dict(result.metadata["runtime"])
        batch_meta = dict(result.metadata["candidate_batch"])
        scalar_meta = dict(runtime_meta["scalar_sessions"])
        callbacks = (
            int(batch_meta.get("callbacks", 0))
            if schedule == "throughput_batch_v1"
            else int(scalar_meta.get("python_callback_calls", 0))
        )
        return {
            "elapsed_seconds": float(elapsed),
            "fingerprint": _result_fingerprint(result),
            "folds": int(len(result.fold_results)),
            "score_calls": int(runtime_meta["score_calls"]),
            "score_bars": int(runtime_meta["score_bars"]),
            "score_seconds": float(runtime_meta["score_seconds"]),
            "callbacks": callbacks,
            "gil_acquisitions": int(scalar_meta.get("gil_acquisitions", 0)),
            "candidate_batch": batch_meta,
            "runtime": runtime_meta,
        }
    finally:
        runtime.close()


def _measure_public(
    *,
    frame: pd.DataFrame,
    candidates: list[dict[str, float]],
    python_work: int,
    schedule: str,
    repeats: int,
) -> dict[str, object]:
    warm = _run_public(
        frame=frame,
        candidates=candidates,
        python_work=python_work,
        schedule=schedule,
    )
    reference = warm["fingerprint"]
    del warm
    gc.collect()
    memory_before = _memory_snapshot()
    samples: list[dict[str, object]] = []
    for _ in range(repeats):
        sample = _run_public(
            frame=frame,
            candidates=candidates,
            python_work=python_work,
            schedule=schedule,
        )
        if sample["fingerprint"] != reference:
            raise AssertionError("Phase 76 repeated public reactive WFO result changed under a fixed seed")
        samples.append(sample)
    memory_after = _memory_snapshot()
    elapsed = [float(sample["elapsed_seconds"]) for sample in samples]
    score_bars = [int(sample["score_bars"]) for sample in samples]
    score_calls = [int(sample["score_calls"]) for sample in samples]
    callbacks = [int(sample["callbacks"]) for sample in samples]
    representative = samples[len(samples) // 2]
    batch_meta = dict(representative["candidate_batch"])
    return {
        "schedule": schedule,
        "python_work_per_callback": int(python_work),
        "repeats": int(repeats),
        "median_seconds": float(median(elapsed)),
        "p95_seconds": float(np.quantile(np.asarray(elapsed), 0.95)),
        "median_milliseconds": float(median(elapsed) * 1_000.0),
        "median_score_bars": int(median(score_bars)),
        "median_score_calls": int(median(score_calls)),
        "median_callbacks": int(median(callbacks)),
        "candidate_fold_bar_visits_per_second": float(median(score_bars) / median(elapsed)),
        "score_stage_seconds": float(median(float(sample["score_seconds"]) for sample in samples)),
        "folds": int(representative["folds"]),
        "candidate_batch": batch_meta,
        "rss_pss_before": memory_before,
        "rss_pss_after": memory_after,
        "rss_pss_delta": {key: int(memory_after[key] - memory_before[key]) for key in memory_before},
        "repeat_fingerprint": reference,
    }


def _worker_probe(*, bars: int, candidates: int) -> dict[str, object]:
    frame = _frame(bars)
    result = _run_public(
        frame=frame,
        candidates=_candidate_matrix(candidates),
        python_work=0,
        schedule="certified_sequential_v1",
        worker_mode="process",
    )
    worker = dict(result["runtime"]["worker"])
    return {
        "schema": "quantbt-phase76-reactive-wfo-worker-probe-v1",
        "worker_transport": worker.get("worker_transport"),
        "worker_market_ipc_bytes_per_task": worker.get("worker_market_ipc_bytes_per_task"),
        "worker_tasks_completed": worker.get("worker_tasks_completed"),
        "worker_memory": worker.get("worker_memory"),
        "worker_scalar_sessions": worker.get("worker_scalar_sessions"),
        "parallelism": worker.get("parallelism"),
        "folds": result["folds"],
        "score_calls": result["score_calls"],
        "fingerprint": result["fingerprint"],
    }


def _run_worker_probe_subprocess(*, bars: int, candidates: int) -> dict[str, object]:
    environment = dict(os.environ)
    environment.update(
        {
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "NUMBA_NUM_THREADS": "1",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker-probe", "--bars", str(bars), "--candidates", str(candidates)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    marker = "PHASE76_WORKER_PROBE="
    lines = [line for line in completed.stdout.splitlines() if line.startswith(marker)]
    if completed.returncode != 0 or not lines:
        raise RuntimeError("Phase 76 clean COW worker probe failed:\n" + completed.stdout + "\n" + completed.stderr)
    return json.loads(lines[-1][len(marker) :])


def _markdown(payload: Mapping[str, object]) -> str:
    rows = list(payload["rows"])
    table = [
        "| Strategy work | Schedule | Public W3 median | Candidate-fold visits/s | Callbacks | Score calls |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        label = "lightweight" if int(row["python_work_per_callback"]) == 0 else "Python-heavy"
        table.append(
            "| {label} | `{schedule}` | {milliseconds:.3f} ms | {throughput:,.0f} | {callbacks:,} | {score_calls:,} |".format(
                label=label,
                schedule=row["schedule"],
                milliseconds=float(row["median_milliseconds"]),
                throughput=float(row["candidate_fold_bar_visits_per_second"]),
                callbacks=int(row["median_callbacks"]),
                score_calls=int(row["median_score_calls"]),
            )
        )
    worker = dict(payload["worker_probe"])
    return "\n".join(
        [
            "# Phase 76 Reactive WFO Evidence",
            "",
            "## Contract",
            "",
            "- Public `prepare_reactive_walk_forward(...)` only; one symbol, Rust native event, Mode 1 global, reset-flat accounts.",
            "- Each row is a warmed median over the declared repeats. Candidate-fold bar visits count scalar selection windows, not generic WFO bars.",
            "- Sequential Optuna and R3B batch schedules are different sampling contracts. This table intentionally reports no speedup ratio between them.",
            "- Repeated fixed-seed result fingerprints must match before timing. Focused tests carry exact scalar/batch selector and cold-audit parity.",
            "- RSS/PSS values in JSON are process snapshots. The clean worker probe reports COW worker PSS separately from parent RSS.",
            "",
            "## Recorded Result",
            "",
            *table,
            "",
            "## Clean COW Worker Probe",
            "",
            f"- Transport: `{worker.get('worker_transport')}`.",
            f"- Market IPC per task: `{worker.get('worker_market_ipc_bytes_per_task')}` bytes.",
            f"- Completed scalar tasks: `{worker.get('worker_tasks_completed')}`.",
            f"- Worker memory: `{worker.get('worker_memory')}`.",
            "",
            "## Scope",
            "",
            "This is explicit W3 evidence. It does not promote arbitrary callback WFO, generic `walk_forward()`, portfolio/package WFO, or `backend=\"auto\"`. The R3B batch route is measured as its own deterministic throughput contract, not as a sequential-TPE replacement.",
            "",
        ]
    )


def run(*, bars: int, candidates: int, repeats: int) -> dict[str, object]:
    if bars < 720:
        raise ValueError("Phase 76 benchmark requires at least 720 daily bars")
    if not 2 <= candidates <= 64:
        raise ValueError("Phase 76 benchmark candidates must be in 2..=64")
    if repeats <= 0:
        raise ValueError("Phase 76 benchmark repeats must be positive")
    frame = _frame(bars)
    matrix = _candidate_matrix(candidates)
    rows = []
    for python_work in (0, 96):
        for schedule in ("certified_sequential_v1", "throughput_batch_v1"):
            rows.append(
                _measure_public(
                    frame=frame,
                    candidates=matrix,
                    python_work=python_work,
                    schedule=schedule,
                    repeats=repeats,
                )
            )
    worker = _run_worker_probe_subprocess(bars=bars, candidates=min(candidates, 8))
    batch_rows = [row for row in rows if row["schedule"] == "throughput_batch_v1"]
    evidence = {
        "public_reactive_wfo_runs": len(rows) == 4,
        "repeat_determinism": True,
        "r3b_shared_market": all(
            int(dict(row["candidate_batch"]).get("market_copies_per_candidate", -1)) == 0
            and int(dict(row["candidate_batch"]).get("market_ipc_bytes_per_candidate", -1)) == 0
            for row in batch_rows
        ),
        "r3b_bounded_inflight": all(int(dict(row["candidate_batch"]).get("batch_size", 0)) == candidates for row in batch_rows),
        "clean_cow_worker": (
            worker.get("worker_transport") == "fork_copy_on_write_v1"
            and int(worker.get("worker_market_ipc_bytes_per_task", -1)) == 0
            and int(worker.get("worker_tasks_completed", 0)) > 0
        ),
    }
    return {
        "schema": "quantbt-phase76-reactive-wfo-benchmark-v1",
        "phase": 76,
        "workload": {
            "bars": int(bars),
            "candidates": int(candidates),
            "repeats": int(repeats),
            "symbols": 1,
            "optimization_mode": "mode_1_decay",
            "optimization_schedule": ["certified_sequential_v1", "throughput_batch_v1"],
            "account_policy": "segmented_reset_flat",
        },
        "rows": rows,
        "worker_probe": worker,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--worker-probe", action="store_true")
    args = parser.parse_args()
    if args.worker_probe:
        print("PHASE76_WORKER_PROBE=" + json.dumps(_worker_probe(bars=args.bars, candidates=args.candidates), sort_keys=True))
        return 0
    payload = run(bars=args.bars, candidates=args.candidates, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
