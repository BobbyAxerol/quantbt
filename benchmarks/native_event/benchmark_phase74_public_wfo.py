#!/usr/bin/env python3
"""Phase 74 apples-to-apples public WFO prepared-native evidence.

This is an end-to-end, post-warmup comparison of the ordinary
``QuantBTEndpoint.walk_forward()`` facade.  Both lanes use the same Python
strategy callback, Optuna seed/trials, Mode 1 candidate selection, close-target
Rust final account, and final report adaptation.  Only candidate/fold scoring
changes: the reference uses the historical endpoint scorer while the native
lane batches compatible fresh-account score rows through the Phase 73 runtime.
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
SOURCE_ROOT = ROOT / "src"
for path in (SOURCE_ROOT, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quantbt import QuantBTEndpoint  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, throughput_per_second, typed_array_sha256  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase74_public_wfo.json"


def _rss_mb() -> float:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _market(bars: int) -> pd.DataFrame:
    if bars < 1_000:
        raise ValueError("bars must be >= 1000 so the fixture has multiple causal folds")
    index = pd.date_range("2019-01-01", periods=bars, freq="1D", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.03 * phase + 3.0 * np.sin(phase / 17.0) + 1.1 * np.sin(phase / 4.0)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1_000.0 + phase,
        },
        index=index,
    )


def _strategy(data, params, train_index, test_index, fold):
    """Deterministic W0 callback with parameter-dependent target churn."""

    del data, train_index, fold
    amplitude = float(params["amplitude"])
    period = int(params["period"])
    bars = np.arange(len(test_index), dtype=np.int64)
    signal = amplitude * np.where((bars // period) % 2 == 0, 1.0, -1.0)
    return pd.Series(signal, index=test_index, dtype=float)


def _run(data: pd.DataFrame, *, policy: str, trials: int):
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="2021-01-01",
        split_frequency="semi_yearly",
        window_mode="rolling",
        train_window="365D",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_schedule="global",
        optimization_config={
            "candidate_selection_metric": "robust_decay",
            "top_is_fraction": 0.25,
            "scoring_backend": "endpoint",
            "native_prepared_wfo": policy,
            "native_prepared_wfo_workers": 1,
            "profile_walkforward": True,
        },
        optuna_trials=trials,
        random_seed=123,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=False,
        target_runtime="rust",
    )
    started = perf_counter()
    result = endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"amplitude": (0.2, 1.0, 0.2), "period": (5, 30, 5)},
    )
    elapsed = perf_counter() - started
    return result, float(elapsed)


def _parity(reference, native) -> bool:
    reference_wf = reference.metadata["walk_forward"]
    native_wf = native.metadata["walk_forward"]
    if reference_wf["params"] != native_wf["params"]:
        return False
    if reference_wf["best_trial"]["params"] != native_wf["best_trial"]["params"]:
        return False
    if not np.allclose(reference.equity.to_numpy(), native.equity.to_numpy(), rtol=0.0, atol=1e-10):
        return False
    if not np.allclose(
        reference.positions.to_numpy(), native.positions.to_numpy(), rtol=0.0, atol=1e-12
    ):
        return False
    columns = ["objective", "mean_is_sharpe", "mean_oos_sharpe", "mean_decay", "std_decay"]
    left = reference_wf["trial_table"][columns].to_numpy(dtype=np.float64)
    right = native_wf["trial_table"][columns].to_numpy(dtype=np.float64)
    return bool(np.allclose(left, right, rtol=0.0, atol=1e-10, equal_nan=True))


def _median(values: list[float]) -> float:
    return float(np.median(np.asarray(values, dtype=np.float64)))


def _profile_breakdown(result, elapsed: float) -> dict[str, float]:
    """Detach measured WFO phases without inventing a fine-grained timer."""

    walk_forward = result.metadata["walk_forward"]
    profile = dict(walk_forward.get("performance_profile", {}) or {})
    prepare = float(profile.get("data_alignment_fold_prepare_seconds", 0.0))
    strategy = float(profile.get("strategy_seconds", 0.0))
    scorer = float(profile.get("score_seconds", 0.0))
    native = dict(walk_forward.get("native_prepared_wfo", {}) or {})
    rust_execute = float(native.get("native_score_seconds", 0.0))
    residual = max(0.0, float(elapsed) - prepare - strategy - scorer)
    return {
        "full_facade": float(elapsed),
        "prepare_folds": prepare,
        "strategy_generate": strategy,
        "candidate_score": scorer,
        "rust_prepared_execute": rust_execute,
        # This deliberately aggregates Optuna/control, reducers/selection,
        # final reconstruction, and cold result/report adaptation rather than
        # pretending it is a precise report-only timer.
        "residual_control_reconstruction_report": residual,
    }


def _median_breakdown(rows: list[dict[str, float]]) -> dict[str, float]:
    return {key: _median([row[key] for row in rows]) for key in rows[0]}


def _markdown(payload: dict[str, Any]) -> str:
    timings = payload["timings_seconds"]
    breakdown = payload["timing_breakdown_seconds"]
    speedup = payload["speedup"]
    return "\n".join(
        (
            "# Phase 74 Public Walk-Forward Prepared-Native Benchmark",
            "",
            "This artifact is a post-warmup full-facade comparison, not a kernel-only claim.",
            "Both lanes execute the same W0 Python callback, Optuna lifecycle, Mode 1",
            "selection, Rust final stitched account, and cold result adaptation. Only candidate/fold",
            "fresh-account scoring uses the Phase 73 prepared-native runtime in the native lane.",
            "",
            "| Lane | Median full WFO | Median scorer |",
            "|---|---:|---:|",
            f"| Historical endpoint scorer | {timings['reference_full_facade_median']:.6f} s | {timings['reference_score_median']:.6f} s |",
            f"| Prepared-native scorer | {timings['native_full_facade_median']:.6f} s | {timings['native_score_median']:.6f} s |",
            "",
            "| Measured phase | Historical endpoint | Prepared-native |",
            "|---|---:|---:|",
            f"| Prepare + fold plan | {breakdown['reference']['prepare_folds']:.6f} s | {breakdown['native']['prepare_folds']:.6f} s |",
            f"| Python strategy generation | {breakdown['reference']['strategy_generate']:.6f} s | {breakdown['native']['strategy_generate']:.6f} s |",
            f"| Candidate/fold scorer | {breakdown['reference']['candidate_score']:.6f} s | {breakdown['native']['candidate_score']:.6f} s |",
            f"| Rust prepared execute within scorer | 0.000000 s | {breakdown['native']['rust_prepared_execute']:.6f} s |",
            f"| Residual control/reconstruction/report | {breakdown['reference']['residual_control_reconstruction_report']:.6f} s | {breakdown['native']['residual_control_reconstruction_report']:.6f} s |",
            "",
            f"- Full-facade speedup: `{speedup['full_facade_x']:.2f}x`",
            f"- Candidate-score speedup: `{speedup['score_stage_x']:.2f}x`",
            f"- Native candidate/fold score rows per run: `{payload['workload']['native_score_rows']}`",
            f"- Native score batches per run: `{payload['workload']['native_score_batches']}`",
            f"- WFO bars: `{payload['workload']['bars']}`; Optuna trials: `{payload['workload']['trials']}`; repeats: `{payload['workload']['repeats']}`",
            f"- Full-facade scored candidate-bar visits/s: `{payload['throughput_candidate_bar_visits_per_second']:.1f}`",
            f"- Process peak RSS: `{payload['rss_mb']['peak']:.3f} MiB`; steady-tail median: `{payload['rss_mb']['tail_median']:.3f} MiB`",
            f"- Native RSS tail spread: `{payload['rss_mb']['tail_spread']:.3f} MiB`",
            f"- Exact selection/final-account parity: `{payload['evidence']['public_parity']}`",
            "",
            "The residual is deliberately not presented as a precise report-only timer: it includes",
            "Optuna control, selection/reducers, final stitched reconstruction, and cold result/report",
            "adaptation. The directly measured Rust time is the prepared execute portion inside score.",
            "",
            "The prepared scorer remains opt-in. It does not alter default WFO behavior, candidate",
            "selection, parameter sampling, strategy lifecycle, signal timing, or final account",
            "reconstruction. See `docs/native_prepared_wfo_public.md` for the compatibility matrix.",
            "",
        )
    )


def run(*, bars: int, trials: int, repeats: int) -> dict[str, Any]:
    if trials <= 0 or repeats <= 1:
        raise ValueError("trials must be > 0 and repeats must be > 1")
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - package-level guard
        raise RuntimeError("Phase 74 benchmark requires the optimization extra") from exc

    data = _market(bars)
    # Warm both code paths outside the recorded post-warmup measurement.
    _run(data, policy="off", trials=trials)
    _run(data, policy="require", trials=trials)

    reference_seconds: list[float] = []
    native_seconds: list[float] = []
    reference_score_seconds: list[float] = []
    native_score_seconds: list[float] = []
    rss_samples: list[float] = []
    parity_rows: list[bool] = []
    native_rows: list[int] = []
    native_batches: list[int] = []
    native_scored_bars: list[int] = []
    reference_breakdowns: list[dict[str, float]] = []
    native_breakdowns: list[dict[str, float]] = []
    for _ in range(repeats):
        gc.collect()
        reference, reference_elapsed = _run(data, policy="off", trials=trials)
        gc.collect()
        native, native_elapsed = _run(data, policy="require", trials=trials)
        native_wf = native.metadata["walk_forward"]
        prepared = native_wf["native_prepared_wfo"]
        reference_seconds.append(reference_elapsed)
        native_seconds.append(native_elapsed)
        reference_score_seconds.append(
            float(reference.metadata["walk_forward"]["performance_profile"]["score_seconds"])
        )
        native_score_seconds.append(float(native_wf["performance_profile"]["score_seconds"]))
        reference_breakdowns.append(_profile_breakdown(reference, reference_elapsed))
        native_breakdowns.append(_profile_breakdown(native, native_elapsed))
        native_rows.append(int(prepared["native_rows"]))
        native_batches.append(int(prepared["native_batches"]))
        native_scored_bars.append(int(prepared["native_scored_bars"]))
        rss_samples.append(_rss_mb())
        parity_rows.append(_parity(reference, native))

    reference_full = _median(reference_seconds)
    native_full = _median(native_seconds)
    reference_score = _median(reference_score_seconds)
    native_score = _median(native_score_seconds)
    tail = rss_samples[len(rss_samples) // 2 :] or rss_samples
    tail_spread = max(tail) - min(tail) if tail else 0.0
    tail_median = _median(tail)
    plateau_limit = max(8.0, 0.05 * (tail[0] if tail else 0.0))
    stable_rows = (
        len(set(native_rows)) == 1
        and len(set(native_batches)) == 1
        and len(set(native_scored_bars)) == 1
    )
    payload: dict[str, Any] = {
        "schema": "quantbt-phase74-public-wfo-v1",
        "scope": (
            "post-warmup public QuantBTEndpoint.walk_forward Mode 1 global W0 callback; "
            "candidate/fold fresh-account scorer comparison only"
        ),
        "workload": {
            "bars": int(bars),
            "trials": int(trials),
            "repeats": int(repeats),
            "symbols": 1,
            "optimization_mode": "mode_1_decay",
            "optimization_schedule": "global",
            "target_mode": "signal_notional",
            "target_runtime": "rust",
            "native_score_rows": int(native_rows[-1]),
            "native_score_batches": int(native_batches[-1]),
            "native_scored_bars": int(native_scored_bars[-1]),
        },
        "timings_seconds": {
            "reference_full_facade_median": reference_full,
            "native_full_facade_median": native_full,
            "reference_score_median": reference_score,
            "native_score_median": native_score,
        },
        "timing_breakdown_seconds": {
            "reference": _median_breakdown(reference_breakdowns),
            "native": _median_breakdown(native_breakdowns),
        },
        "speedup": {
            "full_facade_x": reference_full / native_full if native_full > 0.0 else float("inf"),
            "score_stage_x": reference_score / native_score if native_score > 0.0 else float("inf"),
        },
        "throughput_candidate_bar_visits_per_second": throughput_per_second(
            int(native_scored_bars[-1]), native_full
        ),
        "rss_mb": {
            "samples": rss_samples,
            "peak": float(max(rss_samples)) if rss_samples else 0.0,
            "tail_median": float(tail_median),
            "tail_spread": float(tail_spread),
            "plateau_limit": float(plateau_limit),
        },
        "evidence": {
            "public_parity": bool(all(parity_rows)),
            "native_route_active": bool(all(rows > 0 for rows in native_rows)),
            "stable_native_work_counts": stable_rows,
            "full_facade_non_regression": native_full <= reference_full * 1.05,
            "score_stage_reduced": native_score < reference_score,
            "rss_plateau": tail_spread <= plateau_limit,
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="one unrecorded reference/native full WFO run, then fresh endpoint pairs",
            data_sha256=typed_array_sha256(
                data.index.asi8,
                data["open"].to_numpy(),
                data["high"].to_numpy(),
                data["low"].to_numpy(),
                data["close"].to_numpy(),
                data["volume"].to_numpy(),
            ),
            intent_sha256=typed_array_sha256(
                np.asarray(native_rows),
                np.asarray(native_batches),
                np.asarray(native_scored_bars),
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
    return 0 if all(payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
