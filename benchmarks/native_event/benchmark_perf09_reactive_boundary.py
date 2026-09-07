"""Paired PERF-09 public reactive WFO preparation benchmark.

The benchmark keeps the same Python strategy, candidate matrix, callback work,
market tape, and reset-flat account contract on both sides.  Only run-local
calendar/task preparation is toggled through the non-public compatibility
constructor used by the test corpus.  It never compares R3B with sequential
TPE as though they were the same sampler contract.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from typing import Mapping

import numpy as np
import optuna

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
BENCHMARK_DIR = ROOT / "benchmarks" / "native_event"
for _path in (SOURCE_ROOT, ROOT, BENCHMARK_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from quantbt.backends.reactive_wfo import ReactivePreparedWfoRuntimeV1  # noqa: E402
from quantbt.backends.reactive_wfo_support import ReactiveWfoRuntimeConfigV1  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, typed_array_sha256  # noqa: E402

from benchmark_phase76_reactive_wfo import (  # noqa: E402
    ROOT,
    _BatchFactory,
    _Factory,
    _candidate_matrix,
    _config as _phase76_config,
    _endpoint,
    _frame,
    _memory_snapshot,
    _param_ranges,
    _result_fingerprint,
)


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/perf_09_reactive_boundary.json"


def _config(frame, *, mode: str, schedule: str, trials: int):
    base = _phase76_config(frame, trials=trials)
    selector = {
        "mode_1_decay": "robust_decay",
        "mode_4_is_only_robust": "is_only_robust",
    }[mode]
    values = {
        "optimization_mode": mode,
        "optimization_schedule": schedule,
        "candidate_selection_metric": selector,
        "top_is_fraction": 1.0,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "is_subperiods": 8 if mode == "mode_4_is_only_robust" else 2,
    }
    return replace(base, **values)


def _run(
    *,
    frame,
    candidates,
    mode: str,
    schedule: str,
    prepared_calendar: bool,
) -> dict[str, object]:
    r3b = schedule == "throughput_batch_v1"
    runtime_config = ReactiveWfoRuntimeConfigV1(
        optimizer_schedule=schedule,
        candidate_batch_size=len(candidates) if r3b else 1,
    )
    factory = _BatchFactory(python_work=0) if r3b else _Factory(python_work=0)
    runtime = ReactivePreparedWfoRuntimeV1(
        endpoint=_endpoint(frame),
        data=frame,
        strategy_factory=factory,
        walkforward_config=_config(
            frame,
            mode=mode,
            schedule="global" if r3b else "per_fold_causal",
            trials=len(candidates),
        ),
        runtime_config=runtime_config,
        symbols=["BTCUSDT"],
        _use_prepared_wfo_preparation=prepared_calendar,
    )
    try:
        started = perf_counter()
        if r3b:
            result = runtime.backtest(candidate_matrix=candidates, param_ranges=_param_ranges(candidates))
        else:
            result = runtime.backtest(param_ranges=_param_ranges(candidates))
        elapsed = perf_counter() - started
        runtime_meta = dict(result.metadata["runtime"])
        prep_meta = dict(result.metadata["wfo_preparation"])
        adapter_meta = dict(result.metadata["prepared_strategy"])
        return {
            "elapsed_seconds": float(elapsed),
            "fingerprint": _result_fingerprint(result),
            "trial_rows": int(len(result.trial_table)),
            "candidate_rows": int(len(result.candidate_table)),
            "folds": int(len(result.folds)),
            "score_calls": int(runtime_meta["score_calls"]),
            "score_bars": int(runtime_meta["score_bars"]),
            "score_seconds": float(runtime_meta["score_seconds"]),
            "callbacks": int(runtime_meta["scalar_sessions"].get("python_callback_calls", 0)),
            "preparation": prep_meta,
            "adapter": adapter_meta,
        }
    finally:
        runtime.close()


def _measure(*, frame, candidates, mode: str, schedule: str, repeats: int) -> dict[str, object]:
    baseline = _run(
        frame=frame,
        candidates=candidates,
        mode=mode,
        schedule=schedule,
        prepared_calendar=False,
    )
    optimized_warm = _run(
        frame=frame,
        candidates=candidates,
        mode=mode,
        schedule=schedule,
        prepared_calendar=True,
    )
    if optimized_warm["fingerprint"] != baseline["fingerprint"]:
        raise AssertionError("PERF-09 prepared reactive WFO changed the public result fingerprint")

    memory_before = _memory_snapshot()
    baseline_samples = []
    optimized_samples = []
    for _ in range(repeats):
        slow = _run(
            frame=frame,
            candidates=candidates,
            mode=mode,
            schedule=schedule,
            prepared_calendar=False,
        )
        fast = _run(
            frame=frame,
            candidates=candidates,
            mode=mode,
            schedule=schedule,
            prepared_calendar=True,
        )
        if slow["fingerprint"] != baseline["fingerprint"] or fast["fingerprint"] != baseline["fingerprint"]:
            raise AssertionError("PERF-09 repeated reactive WFO result changed under a fixed seed")
        baseline_samples.append(slow)
        optimized_samples.append(fast)
    memory_after = _memory_snapshot()

    baseline_seconds = [float(value["elapsed_seconds"]) for value in baseline_samples]
    optimized_seconds = [float(value["elapsed_seconds"]) for value in optimized_samples]
    representative = optimized_samples[len(optimized_samples) // 2]
    slow_median = float(median(baseline_seconds))
    fast_median = float(median(optimized_seconds))
    return {
        "mode": mode,
        "schedule": schedule,
        "repeats": int(repeats),
        "baseline_median_seconds": slow_median,
        "optimized_median_seconds": fast_median,
        "speedup": float(slow_median / fast_median),
        "baseline_median_milliseconds": slow_median * 1_000.0,
        "optimized_median_milliseconds": fast_median * 1_000.0,
        "score_bars": int(representative["score_bars"]),
        "score_calls": int(representative["score_calls"]),
        "folds": int(representative["folds"]),
        "trial_rows": int(representative["trial_rows"]),
        "candidate_rows": int(representative["candidate_rows"]),
        "prepared_task_window_hits": int(representative["adapter"].get("prepared_task_window_hits", 0)),
        "prepared_task_window_fallbacks": int(representative["adapter"].get("prepared_task_window_fallbacks", 0)),
        "baseline_prepared_task_window_hits": int(
            baseline_samples[len(baseline_samples) // 2]["adapter"].get("prepared_task_window_hits", 0)
        ),
        "baseline_prepared_task_window_fallbacks": int(
            baseline_samples[len(baseline_samples) // 2]["adapter"].get("prepared_task_window_fallbacks", 0)
        ),
        "prepared_shard_hits": int(
            dict(representative["preparation"].get("window_registry", {})).get("shard_lookup_hits", 0)
        ),
        "fingerprint": representative["fingerprint"],
        "rss_pss_before": memory_before,
        "rss_pss_after": memory_after,
        "rss_pss_delta": {key: int(memory_after[key] - memory_before[key]) for key in memory_before},
    }


def _markdown(payload: Mapping[str, object]) -> str:
    rows = list(payload["rows"])
    table = [
        "| Workload | Baseline | PERF-09 | Speedup | Score bars | Task fast hits |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        table.append(
            "| `{mode}` / `{schedule}` | {slow:.3f} ms | {fast:.3f} ms | {speed:.2f}x | {bars:,} | {hits:,} |".format(
                mode=row["mode"],
                schedule=row["schedule"],
                slow=float(row["baseline_median_milliseconds"]),
                fast=float(row["optimized_median_milliseconds"]),
                speed=float(row["speedup"]),
                bars=int(row["score_bars"]),
                hits=int(row["prepared_task_window_hits"]),
            )
        )
    return "\n".join(
        [
            "# PERF-09 Reactive Boundary Closure",
            "",
            "## Contract",
            "",
            "- Same public Rust reactive WFO strategy, parameter candidates, callback work, tape, reset-flat accounts and deterministic seed on both sides.",
            "- Mode 4 uses `per_fold_causal`; R3B is reported separately under its declared global fixed-matrix throughput contract.",
            "- The baseline only disables private run-local calendar/task preparation. It does not alter strategy behavior, account lifecycle, task count or Optuna/R3B sampling contract.",
            "- JSON RSS/PSS is an in-process plateau diagnostic, not isolated memory attribution.",
            "",
            "## Result",
            "",
            *table,
            "",
        ]
    )


def run(*, bars: int, candidates: int, repeats: int) -> dict[str, object]:
    if importlib.util.find_spec("_quantbt_native") is None:
        raise RuntimeError("PERF-09 requires the matching quantbt-native development wheel")
    if bars < 720 or not 2 <= candidates <= 64 or repeats <= 0:
        raise ValueError("requires bars >= 720, candidates in 2..=64, and repeats > 0")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    frame = _frame(bars)
    matrix = _candidate_matrix(candidates)
    rows = [
        _measure(
            frame=frame,
            candidates=matrix,
            mode="mode_4_is_only_robust",
            schedule="certified_sequential_v1",
            repeats=repeats,
        ),
        _measure(
            frame=frame,
            candidates=matrix,
            mode="mode_1_decay",
            schedule="throughput_batch_v1",
            repeats=repeats,
        ),
    ]
    return {
        "schema": "quantbt-perf-09-reactive-boundary-v1",
        "workload": {"bars": int(bars), "candidates": int(candidates), "repeats": int(repeats), "symbols": 1},
        "rows": rows,
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure=(
                "one untimed baseline/prepared public reactive WFO pair for each workload, "
                "then alternating paired baseline/prepared repeats with the same tape, candidates, "
                "strategy factory, account contract, seed, and retention"
            ),
            data_sha256=typed_array_sha256(
                frame.index.asi8,
                frame[["open", "high", "low", "close", "volume", "funding_rate"]].to_numpy(
                    dtype=np.float64
                ),
            ),
            intent_sha256=typed_array_sha256(
                np.asarray([bars, candidates, repeats], dtype=np.int64),
                np.asarray(
                    [
                        "mode_4_is_only_robust",
                        "certified_sequential_v1",
                        "mode_1_decay",
                        "throughput_batch_v1",
                    ],
                    dtype="U32",
                ),
                np.asarray(
                    [
                        item["direction"] for item in matrix
                    ],
                    dtype=np.float64,
                ),
                np.asarray(
                    [
                        item["quantity"] for item in matrix
                    ],
                    dtype=np.float64,
                ),
            ),
        ),
        "evidence": {
            "exact_public_fingerprints": True,
            "mode4_prepared_shards": int(rows[0]["prepared_shard_hits"]) > 0,
            "prepared_task_fast_path": all(int(row["prepared_task_window_hits"]) > 0 for row in rows),
            "no_baseline_task_fast_path": all(
                int(row["baseline_prepared_task_window_hits"]) == 0 for row in rows
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(bars=args.bars, candidates=args.candidates, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
