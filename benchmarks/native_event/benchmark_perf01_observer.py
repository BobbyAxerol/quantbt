#!/usr/bin/env python3
"""Paired PERF-01 observer-overhead baseline for the public WFO facade.

This benchmark deliberately measures one deterministic Mode 1 public endpoint
workload with identical economic inputs while alternating observer-off and
observer-on runs. It is a source/profiler baseline, not a route-promotion or
generic WFO throughput certificate.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Mapping

import numpy as np
import optuna
import pandas as pd

from quantbt import QuantBTEndpoint


ROOT = Path(__file__).resolve().parents[2]
MEASUREMENT_TOOL_PATH = ROOT / "tools" / "measurement_contract.py"
SCHEMA = "quantbt-perf-01-observer-baseline-v1"


def _load_measurement_tool():
    specification = importlib.util.spec_from_file_location("perf01_measurement_contract", MEASUREMENT_TOOL_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load measurement-contract helpers")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _bars(rows: int) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=rows, freq="1D", tz="UTC")
    ordinal = np.arange(rows, dtype=np.float64)
    close = 100.0 + 0.025 * ordinal + 1.25 * np.sin(ordinal / 13.0)
    return pd.DataFrame(
        {
            "open": close - 0.10,
            "high": close + 0.80,
            "low": close - 0.80,
            "close": close,
            "volume": 1_000.0 + ordinal,
        },
        index=index,
    )


def _strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    direction = float(params["direction"])
    ordinal = np.arange(len(test_index), dtype=np.int64)
    return pd.Series(direction * np.where((ordinal // 9) % 2 == 0, 1.0, -1.0), index=test_index)


def _make_endpoint(*, perf_01_profile: bool, trials: int) -> QuantBTEndpoint:
    return QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_schedule="global",
        optimization_config={
            "perf_01_profile": bool(perf_01_profile),
            "scoring_backend": "endpoint",
            "top_is_fraction": 1.0,
            "candidate_selection_metric": "robust_decay",
            "scoring_trading_days": 365,
            "min_trades_per_year": None,
            "trade_penalty_factor": None,
        },
        optuna_trials=int(trials),
        random_seed=41,
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=False,
    )


def _economic_signature(result) -> str:
    """Hash selection and public-account results, excluding profile timings."""

    walk_forward = result.metadata["walk_forward"]
    digest = sha256()
    for series in (result.equity, result.returns, result.positions.iloc[:, 0]):
        digest.update(pd.DatetimeIndex(series.index).asi8.tobytes())
        digest.update(np.asarray(series, dtype=np.float64).tobytes())
    trial_columns = [
        column
        for column in ("trial_id", "objective", "mean_is_sharpe", "mean_oos_sharpe", "mean_decay", "std_decay")
        if column in walk_forward["trial_table"].columns
    ]
    digest.update(
        walk_forward["trial_table"][trial_columns]
        .to_json(orient="split", date_format="iso", double_precision=15)
        .encode("utf-8")
    )
    digest.update(json.dumps(walk_forward["params"], sort_keys=True, default=str).encode("utf-8"))
    digest.update(json.dumps(walk_forward["best_trial"], sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


def _run_once(*, frame: pd.DataFrame, perf_01_profile: bool, trials: int) -> dict[str, Any]:
    endpoint = _make_endpoint(perf_01_profile=perf_01_profile, trials=trials)
    started = perf_counter_ns()
    result = endpoint.backtest(
        data=frame,
        symbols=["BTC"],
        param_ranges={"direction": [-1.0, 1.0]},
    )
    elapsed_ns = perf_counter_ns() - started
    walk_forward = result.metadata["walk_forward"]
    return {
        "elapsed_ns": int(elapsed_ns),
        "economic_signature": _economic_signature(result),
        "selected_params": dict(walk_forward["params"]),
        "final_equity": float(result.equity.iloc[-1]),
        "perf_01_profile": walk_forward["perf_01_profile"],
        "work_shape": {
            "folds": int(walk_forward["n_folds"]),
            "optuna_trial_rows": int(walk_forward["n_optuna_trial_rows"]),
            "bars": int(len(frame)),
        },
    }


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = np.asarray([sample["elapsed_ns"] for sample in samples], dtype=np.float64)
    return {
        "samples": int(len(samples)),
        "median_ns": int(np.median(elapsed)),
        "p95_ns": int(np.quantile(elapsed, 0.95, method="linear")),
        "min_ns": int(np.min(elapsed)),
        "max_ns": int(np.max(elapsed)),
    }


def _percent_summary(samples: list[float]) -> dict[str, float | int]:
    values = np.asarray(samples, dtype=np.float64)
    return {
        "samples": int(len(values)),
        "median_pct": float(np.median(values)),
        "p95_pct": float(np.quantile(values, 0.95, method="linear")),
        "min_pct": float(np.min(values)),
        "max_pct": float(np.max(values)),
    }


def _median_profile(samples: list[dict[str, Any]]) -> dict[str, int | None]:
    stage_names = samples[0]["perf_01_profile"]["exclusive_stage_elapsed_ns"].keys()
    return {
        name: int(
            np.median(
                [sample["perf_01_profile"]["exclusive_stage_elapsed_ns"][name] for sample in samples]
            )
        )
        for name in stage_names
    }


def run_benchmark(*, bars: int, trials: int, warmup: int, repeats: int) -> dict[str, Any]:
    if bars < 400:
        raise ValueError("bars must leave enough history for the declared WFO folds")
    if trials < 1 or warmup < 0 or repeats < 2:
        raise ValueError("trials must be >= 1, warmup >= 0, and repeats >= 2")
    frame = _bars(int(bars))
    for profile in (False, True):
        for _ in range(int(warmup)):
            _run_once(frame=frame, perf_01_profile=profile, trials=trials)

    samples = {False: [], True: []}
    pairs: list[dict[bool, dict[str, Any]]] = []
    previous_verbosity = optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        for ordinal in range(int(repeats)):
            order = (False, True) if ordinal % 2 == 0 else (True, False)
            pair: dict[bool, dict[str, Any]] = {}
            for profile in order:
                sample = _run_once(frame=frame, perf_01_profile=profile, trials=trials)
                samples[profile].append(sample)
                pair[profile] = sample
            pairs.append(pair)
    finally:
        optuna.logging.set_verbosity(previous_verbosity)

    signatures = {sample["economic_signature"] for group in samples.values() for sample in group}
    if len(signatures) != 1:
        raise AssertionError("PERF-01 observer changed public WFO economics or selection")
    off_summary = _summary(samples[False])
    on_summary = _summary(samples[True])
    paired_overhead_pct = [
        100.0 * (pair[True]["elapsed_ns"] - pair[False]["elapsed_ns"]) / pair[False]["elapsed_ns"]
        for pair in pairs
    ]
    paired_overhead_summary = _percent_summary(paired_overhead_pct)
    proposed_budget = {"p50_pct": 3.0, "p95_pct": 5.0}
    within_proposed_budget = bool(
        paired_overhead_summary["median_pct"] <= proposed_budget["p50_pct"]
        and paired_overhead_summary["p95_pct"] <= proposed_budget["p95_pct"]
    )
    measurement = _load_measurement_tool()
    data_sha256 = measurement.typed_array_sha256(
        frame.index.asi8,
        frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=np.float64),
    )
    intent_sha256 = measurement.canonical_json_sha256(
        {"param_ranges": {"direction": [-1.0, 1.0]}, "mode": "mode_1_decay", "trials": int(trials)}
    )
    return {
        "schema": SCHEMA,
        "status": "development_baseline_not_promotion_evidence",
        "workload": {
            "route": "QuantBTEndpoint.walk_forward",
            "mode": "mode_1_decay",
            "schedule": "global",
            "target_mode": "signal_notional",
            "bars": int(bars),
            "trials": int(trials),
            "warmup_runs_per_profile": int(warmup),
            "paired_repeats": int(repeats),
            "pairing": "alternating observer-off/observer-on order",
        },
        "candidate_identity": measurement.capture_measurement_identity(
            root=ROOT,
            warmup_procedure=f"{warmup} unrecorded public WFO runs per profile before alternating pairs",
            data_sha256=data_sha256,
            intent_sha256=intent_sha256,
        ),
        "observer_off": off_summary,
        "observer_on": on_summary,
        "observer_overhead_median_pct": float(paired_overhead_summary["median_pct"]),
        "observer_overhead_pairs_pct": paired_overhead_summary,
        "observer_overhead_proposed_budget": {
            **proposed_budget,
            "within_proposed_budget": within_proposed_budget,
            "binding_release_gate": False,
        },
        "observer_on_exclusive_stage_median_ns": _median_profile(samples[True]),
        "economic_parity": {
            "passed": True,
            "public_result_signature": next(iter(signatures)),
            "selected_params": samples[False][0]["selected_params"],
            "final_equity": samples[False][0]["final_equity"],
            "work_shape": samples[False][0]["work_shape"],
        },
        "interpretation": (
            "This paired source/profiler baseline does not promote a backend, claim generic WFO throughput, "
            "or qualify a candidate wheel. It only establishes observer on/off economics and a public Mode 1 timing shape."
        ),
    }


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=540)
    parser.add_argument("--trials", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    _write(
        args.output,
        run_benchmark(bars=args.bars, trials=args.trials, warmup=args.warmup, repeats=args.repeats),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
