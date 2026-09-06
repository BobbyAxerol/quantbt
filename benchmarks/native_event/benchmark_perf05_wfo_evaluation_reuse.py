#!/usr/bin/env python3
"""PERF-05 public WFO evaluation-reuse evidence.

This runner measures the narrow, run-local score cache that may reuse an
already-complete prepared-native execution during later report-only candidate
analysis.  It never times a cache as a substitute for an adaptive Optuna trial.
The five-mode matrix is recorded separately because Mode 2 remains proxy-owned
and Mode 5 need not have a later exact execution to reuse.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quantbt import QuantBTEndpoint  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, typed_array_sha256  # noqa: E402
from benchmarks.native_event.benchmark_phase74_public_wfo import (  # noqa: E402
    _market,
    _parity,
    _rss_mb,
    _run as _run_mode1,
)


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/perf_05_wfo_evaluation_reuse.json"
_NATIVE_MODES = (
    "mode_1_decay",
    "mode_3_flat_minima",
    "mode_4_is_only_robust",
    "mode_5_full_robust",
)
_ALL_MODES = ("mode_1_decay", "mode_2_sbb", "mode_3_flat_minima", "mode_4_is_only_robust", "mode_5_full_robust")


def _median(values: list[float]) -> float:
    return float(np.median(np.asarray(values, dtype=np.float64)))


def _strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    bars = np.arange(len(test_index), dtype=np.int64)
    direction = float(params["direction"])
    return pd.Series(
        direction * np.where((bars // 9) % 2 == 0, 1.0, -1.0),
        index=test_index,
        dtype=float,
    )


def _mode_config(mode: str, *, reuse_policy: str) -> dict[str, object]:
    common: dict[str, object] = {
        "top_is_fraction": 1.0,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "scoring_trading_days": 365,
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
        "profile_walkforward": True,
        "wfo_execution_reuse": reuse_policy,
        "wfo_execution_reuse_max_entries": 4_096,
    }
    if mode == "mode_2_sbb":
        return {
            **common,
            "scoring_backend": "proxy",
            "sbb_samples": 8,
            "sbb_block_length": 3,
        }
    metric = {
        "mode_1_decay": "robust_decay",
        "mode_3_flat_minima": "is_plateau_robust",
        "mode_4_is_only_robust": "is_only_robust",
        "mode_5_full_robust": "full_robust",
    }[mode]
    return {
        **common,
        "candidate_selection_metric": metric,
        "scoring_backend": "endpoint",
        "native_prepared_wfo": "require",
        "native_prepared_wfo_workers": 1,
        "is_subperiods": 1 if mode == "mode_5_full_robust" else 2,
    }


def _run_mode_matrix(data: pd.DataFrame, *, mode: str, reuse_policy: str, trials: int):
    full_sample = mode == "mode_5_full_robust"
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="full_sample_is" if full_sample else "2020-07-01",
        split_frequency="single" if full_sample else "quarterly",
        window_mode="expanding" if full_sample else "rolling",
        train_window=None if full_sample else "180D",
        target_mode="signal_notional",
        optimization_mode=mode,
        optimization_config=_mode_config(mode, reuse_policy=reuse_policy),
        optuna_trials=trials,
        random_seed=31,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        target_runtime="rust",
    )
    started = perf_counter()
    result = endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"direction": [-1.0, 1.0]},
    )
    return result, float(perf_counter() - started)


def _mode_result_parity(left, right) -> bool:
    left_wf = left.metadata["walk_forward"]
    right_wf = right.metadata["walk_forward"]
    if left_wf["params"] != right_wf["params"] or left_wf["best_trial"] != right_wf["best_trial"]:
        return False
    if not np.allclose(left.equity.to_numpy(), right.equity.to_numpy(), rtol=0.0, atol=1e-10):
        return False
    if not np.allclose(left.positions.to_numpy(), right.positions.to_numpy(), rtol=0.0, atol=1e-12):
        return False
    return bool(left_wf["trial_table"].equals(right_wf["trial_table"]))


def _runtime_summary(result) -> dict[str, object]:
    runtime = dict(result.metadata["walk_forward"].get("wfo_evaluation_runtime", {}) or {})
    return {
        "resolved_policy": runtime.get("resolved_policy"),
        "reason": runtime.get("reason"),
        "cache_hits": int(runtime.get("cache_hits", 0)),
        "cache_misses": int(runtime.get("cache_misses", 0)),
        "cache_stores": int(runtime.get("cache_stores", 0)),
        "cache_evictions": int(runtime.get("cache_evictions", 0)),
        "terminal_score_bars_reused": int(runtime.get("terminal_score_bars_reused", 0)),
        "terminal_score_bars_executed": int(runtime.get("terminal_score_bars_executed", 0)),
        "adaptive_read_bypasses": int(runtime.get("adaptive_read_bypasses", 0)),
        "attempt_rows_retained": int(runtime.get("attempt_rows_retained", 0)),
        "cache_entries_released": bool(runtime.get("cache_entries_released", False)),
    }


def _mode_matrix(data: pd.DataFrame, *, trials: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for mode in _ALL_MODES:
        baseline, baseline_seconds = _run_mode_matrix(data, mode=mode, reuse_policy="off", trials=trials)
        # The proxy-owned Mode 2 and current no-rerun Mode 5 intentionally use
        # auto. The bounded native modes with actual post-study score replay
        # prove the exact reuse gate under require.
        policy = "auto" if mode in {"mode_2_sbb", "mode_5_full_robust"} else "require"
        reused, reused_seconds = _run_mode_matrix(data, mode=mode, reuse_policy=policy, trials=trials)
        runtime = _runtime_summary(reused)
        parity = _mode_result_parity(baseline, reused)
        if not parity:
            raise RuntimeError(f"PERF-05 mode parity failed for {mode}")
        if mode == "mode_2_sbb":
            if runtime["resolved_policy"] != "disabled":
                raise RuntimeError("Mode 2 unexpectedly enabled native execution reuse")
        elif mode == "mode_5_full_robust":
            if runtime["resolved_policy"] != "disabled":
                raise RuntimeError("Mode 5 unexpectedly retained an unusable execution cache")
        elif runtime["resolved_policy"] != "enabled_then_released":
            raise RuntimeError(f"PERF-05 native reuse was not active for {mode}: {runtime}")
        rows.append(
            {
                "mode": mode,
                "baseline_seconds": baseline_seconds,
                "reuse_seconds": reused_seconds,
                "exact_public_parity": parity,
                "runtime": runtime,
            }
        )
    return rows


def _markdown(payload: dict[str, Any]) -> str:
    lanes = payload["lanes"]
    matrix = payload["mode_matrix"]
    return "\n".join(
        (
            "# PERF-05 WFO Evaluation Reuse Benchmark",
            "",
            "The cache is intentionally narrow: an adaptive Optuna objective always executes and",
            "stores its completed terminal metrics; only later report-only candidate analysis may",
            "reuse the exact same prepared-native economic execution. It is run-local and released",
            "before the public result returns.",
            "",
            "## Mode 1 Cache Economics",
            "",
            "| Lane | Median public WFO | vs off | Median scorer | vs off | Hits | Reused score bars | Stores | Evictions |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            *(
                f"| {name} | {row['full_seconds_median']:.6f} s | {row['full_speedup_pct_vs_off']:+.2f}% | "
                f"{row['score_seconds_median']:.6f} s | {row['score_speedup_pct_vs_off']:+.2f}% | "
                f"{row['runtime']['cache_hits']} | {row['runtime']['terminal_score_bars_reused']} | "
                f"{row['runtime']['cache_stores']} | {row['runtime']['cache_evictions']} |"
                for name, row in lanes.items()
            ),
            "",
            "The lanes share the same W0 callback, seed, Optuna interaction, selector, final",
            "stitched account, and report adaptation. Timing is descriptive rather than a release",
            "threshold: cache lookup hashes and repeated Python strategy generation remain real work.",
            "",
            "## Five-Mode Contract Matrix",
            "",
            "| Mode | Baseline / reuse parity | Reuse state | Hits | Notes |",
            "|---|---|---|---:|---|",
            *(
                f"| {row['mode']} | {row['exact_public_parity']} | {row['runtime']['resolved_policy']} | "
                f"{row['runtime']['cache_hits']} | {row['runtime']['reason']} |"
                for row in matrix
            ),
            "",
            "Mode 2 remains the existing deterministic proxy/resampling authority; no native",
            "terminal-score cache is enabled for it. Mode 5 can legitimately show zero hits because",
            "its full-IS selector may not rerun an identical candidate execution after the study.",
            "",
            f"RSS peak: `{payload['rss_mb']['peak']:.3f} MiB`; tail spread: "
            f"`{payload['rss_mb']['tail_spread']:.3f} MiB`; released cache evidence: "
            f"`{payload['evidence']['cache_released']}`.",
            "",
            "This is not a generic WFO, reactive, portfolio, package, or Mode 2 throughput claim.",
            "See `docs/performance/perf_05_wfo_evaluation_reuse.md` for eligibility and rollback.",
            "",
        )
    )


def run(*, bars: int, trials: int, repeats: int) -> dict[str, Any]:
    if bars < 1_000:
        raise ValueError("bars must be >= 1000")
    if trials < 2 or repeats < 2:
        raise ValueError("trials and repeats must both be >= 2")
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("PERF-05 benchmark requires the optimization extra") from exc
    data = _market(bars)
    # Warm the same public lane before sampling.  The three capacity cases are
    # actual endpoint executions, not synthetic cache probes.
    for policy, capacity in (("off", 4_096), ("require", 1), ("require", 4_096)):
        _run_mode1(data, policy="require", trials=trials, reuse_policy=policy, reuse_max_entries=capacity)

    definitions = {
        "zero_hit_policy_off": ("off", 4_096),
        "mixed_bounded_lru": ("require", 1),
        "high_hit_run_local": ("require", 4_096),
    }
    samples: dict[str, list[dict[str, object]]] = {name: [] for name in definitions}
    rss_samples: list[float] = []
    lane_names = tuple(definitions)
    for repeat_id in range(repeats):
        reference = None
        # Alternate order to avoid presenting a warm/thermal ordering artifact
        # as a cache speedup or regression.
        ordered_names = lane_names if repeat_id % 2 == 0 else tuple(reversed(lane_names))
        for name in ordered_names:
            policy, capacity = definitions[name]
            gc.collect()
            result, elapsed = _run_mode1(
                data,
                policy="require",
                trials=trials,
                reuse_policy=policy,
                reuse_max_entries=capacity,
            )
            if reference is None:
                reference = result
            elif not _parity(reference, result):
                raise RuntimeError(f"PERF-05 public Mode 1 parity failed for {name}")
            profile = dict(result.metadata["walk_forward"].get("performance_profile", {}) or {})
            samples[name].append(
                {
                    "elapsed": float(elapsed),
                    "score_seconds": float(profile.get("score_seconds", 0.0)),
                    "runtime": _runtime_summary(result),
                }
            )
        rss_samples.append(_rss_mb())

    lanes: dict[str, dict[str, object]] = {}
    for name, rows in samples.items():
        final = rows[-1]
        lanes[name] = {
            "full_seconds_median": _median([float(row["elapsed"]) for row in rows]),
            "score_seconds_median": _median([float(row["score_seconds"]) for row in rows]),
            "runtime": dict(final["runtime"]),
        }
    baseline_lane = lanes["zero_hit_policy_off"]
    baseline_full = float(baseline_lane["full_seconds_median"])
    baseline_score = float(baseline_lane["score_seconds_median"])
    for row in lanes.values():
        # Positive means faster than the no-cache public baseline. The raw
        # medians remain alongside this derived convenience field.
        row["full_speedup_pct_vs_off"] = 100.0 * (
            baseline_full - float(row["full_seconds_median"])
        ) / baseline_full
        row["score_speedup_pct_vs_off"] = 100.0 * (
            baseline_score - float(row["score_seconds_median"])
        ) / baseline_score
    mode_matrix = _mode_matrix(data.iloc[: max(1_000, min(len(data), 1_200))], trials=2)
    tail = rss_samples[len(rss_samples) // 2 :] or rss_samples
    tail_spread = max(tail) - min(tail) if tail else 0.0
    payload: dict[str, Any] = {
        "schema": "quantbt-perf-05-wfo-evaluation-reuse-v1",
        "scope": "public Mode 1 prepared-native terminal metric reuse plus five-mode contract matrix",
        "workload": {"bars": bars, "trials": trials, "repeats": repeats, "symbols": 1},
        "lanes": lanes,
        "mode_matrix": mode_matrix,
        "rss_mb": {
            "samples": rss_samples,
            "peak": float(max(rss_samples)),
            "tail_spread": float(tail_spread),
        },
        "evidence": {
            "all_public_mode1_parity": True,
            "high_hit_lane_has_hits": lanes["high_hit_run_local"]["runtime"]["cache_hits"] > 0,
            "adaptive_reads_bypassed": lanes["high_hit_run_local"]["runtime"]["adaptive_read_bypasses"] > 0,
            "cache_released": all(
                bool(row["runtime"]["cache_entries_released"])
                for row in lanes.values()
            ),
            "mode_matrix_parity": all(bool(row["exact_public_parity"]) for row in mode_matrix),
            "mode2_proxy_preserved": next(
                row for row in mode_matrix if row["mode"] == "mode_2_sbb"
            )["runtime"]["resolved_policy"] == "disabled",
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="one unrecorded public WFO run for each zero/mixed/high cache lane",
            data_sha256=typed_array_sha256(
                data.index.asi8,
                data["open"].to_numpy(),
                data["high"].to_numpy(),
                data["low"].to_numpy(),
                data["close"].to_numpy(),
                data["volume"].to_numpy(),
            ),
            intent_sha256=typed_array_sha256(
                np.asarray([lanes[name]["runtime"]["cache_hits"] for name in definitions], dtype=np.int64),
                np.asarray([lanes[name]["runtime"]["cache_stores"] for name in definitions], dtype=np.int64),
            ),
        ),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_048)
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(bars=args.bars, trials=args.trials, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(bool(value) for value in payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
