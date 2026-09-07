#!/usr/bin/env python3
"""PERF-08 public WFO preparation benchmark with exact paired parity.

The benchmark deliberately compares the same public endpoint, strategy,
calendar, Optuna seed, trial budget, account contract, and retention policy.
The only lane difference is run-local WFO preparation.  It measures the
ordinary public facade, not a private scorer microbenchmark.

Examples:

    PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_perf08_public_wfo.py \
        --profile smoke
    PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_perf08_public_wfo.py \
        --profile standard --mode mode_4_is_only_robust
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gc
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
for _path in (SOURCE_ROOT, ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from quantbt import QuantBTEndpoint  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, typed_array_sha256  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/perf_08_public_wfo.json"
SCHEMA = "quantbt-perf-08-public-wfo-v1"


@dataclass(frozen=True, slots=True)
class _ModeSpec:
    mode: str
    schedule: str
    selector: str
    scoring_backend: str


MODE_SPECS: tuple[_ModeSpec, ...] = (
    _ModeSpec("mode_1_decay", "global", "robust_decay", "endpoint"),
    _ModeSpec("mode_2_sbb", "global", "robust_decay", "proxy"),
    _ModeSpec("mode_3_flat_minima", "global", "is_plateau_robust", "endpoint"),
    _ModeSpec("mode_4_is_only_robust", "per_fold_causal", "is_only_robust", "endpoint"),
)


PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "smoke": {
        "bars": 2_000,
        "frequency": "1D",
        "split_bar": 720,
        "train_window": "365D",
        "trials": 4,
        "repeats": 3,
        "sbb_samples": 32,
        "is_subperiods": 4,
        "description": "All four modes, paired public-facade smoke measurement.",
        "split_frequency": "quarterly",
        "window_mode": "rolling",
    },
    "standard": {
        "bars": 10_000,
        "frequency": "1h",
        "split_bar": 4_320,
        "train_window": "180D",
        "trials": 48,
        "repeats": 5,
        "sbb_samples": 256,
        "is_subperiods": 8,
        "description": "Headline 10k-hourly public workload; use --mode mode_4_is_only_robust for the primary causal gate.",
        "split_frequency": "quarterly",
        "window_mode": "rolling",
    },
    "broad": {
        "bars": 50_000,
        "frequency": "1h",
        # Leaves six complete-ish semiannual outer test folds after a long,
        # expanding initial history without making a private-alpha claim.
        "split_bar": 23_000,
        "train_window": None,
        "split_frequency": "semi_yearly",
        "window_mode": "expanding",
        "trials": 100,
        "repeats": 1,
        "sbb_samples": 256,
        "is_subperiods": 8,
        "description": "Exploratory 50k-hourly expanding/semiannual Mode 4 causal workload; one paired sample, not a p95 claim.",
    },
}


def _rss_pss_mb() -> dict[str, float]:
    """Read process snapshots without treating shared memory as private RSS."""

    values = {"rss_mb": 0.0, "pss_mb": 0.0}
    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                values["rss_mb"] = float(line.split()[1]) / 1024.0
                break
    rollup = Path("/proc/self/smaps_rollup")
    if rollup.is_file():
        for line in rollup.read_text(encoding="utf-8").splitlines():
            if line.startswith("Pss:"):
                values["pss_mb"] = float(line.split()[1]) / 1024.0
                break
    return values


def _market(bars: int, *, frequency: str) -> pd.DataFrame:
    if bars < 2_000:
        raise ValueError("PERF-08 requires at least 2,000 bars")
    index = pd.date_range("2020-01-01", periods=int(bars), freq=frequency, tz="UTC")
    phase = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 0.012 * phase + 2.7 * np.sin(phase / 31.0) + 0.8 * np.cos(phase / 7.0)
    open_ = np.r_[close[0], close[:-1]] + 0.08 * np.cos(phase / 5.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.55,
            "low": np.minimum(open_, close) - 0.55,
            "close": close,
            "volume": 1_000.0 + phase,
            "funding_rate": np.where((phase.astype(np.int64) % 8) == 0, 0.0001, -0.00005),
        },
        index=index,
    )


def _strategy(data, params, train_index, test_index, fold):
    """Deterministic W0 callback; both paired lanes execute this unchanged."""

    del data, train_index, fold
    amplitude = float(params["amplitude"])
    period = int(params["period"])
    epoch = pd.Timestamp("2020-01-01", tz="UTC")
    bars = ((pd.DatetimeIndex(test_index).asi8 - epoch.value) // pd.Timedelta("1h").value).astype(np.int64)
    signal = amplitude * np.where((bars // period) % 2 == 0, 1.0, -1.0)
    return pd.Series(signal, index=test_index, dtype=float)


def _optimization_config(spec: _ModeSpec, *, prepared: bool, profile: Mapping[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {
        "candidate_selection_metric": spec.selector,
        "scoring_backend": spec.scoring_backend,
        "top_is_fraction": 0.50,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "plateau_quantile": 0.25,
        "plateau_median_weight": 0.25,
        "plateau_std_penalty": 0.50,
        "plateau_size_bonus": 0.01,
        "is_subperiods": int(profile["is_subperiods"]),
        "scoring_trading_days": 365,
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
        "use_numba": True,
        "use_prepared_wfo_context": bool(prepared),
        "use_prepared_scoring_cache": True,
        "use_scalar_trial_scoring": True,
        "compact_trial_ledger": True,
        "wfo_execution_reuse": "off",
        "native_prepared_wfo": "off",
        "profile_walkforward": True,
    }
    if spec.mode == "mode_2_sbb":
        config.update(
            {
                "sbb_samples": int(profile["sbb_samples"]),
                "sbb_block_length": 12,
                "sbb_simulation": "stationary",
                "sbb_decay_lambda": 0.5,
                "sbb_std_penalty": 0.1,
            }
        )
    return config


def _run(data: pd.DataFrame, *, spec: _ModeSpec, prepared: bool, profile: Mapping[str, Any]):
    split_bar = int(profile["split_bar"])
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode=str(data.index[split_bar].date()),
        split_frequency=str(profile["split_frequency"]),
        window_mode=str(profile["window_mode"]),
        train_window=None if profile["train_window"] is None else str(profile["train_window"]),
        target_mode="signal_notional",
        optimization_mode=spec.mode,
        optimization_schedule=spec.schedule,
        optimization_config=_optimization_config(spec, prepared=prepared, profile=profile),
        optuna_trials=int(profile["trials"]),
        optuna_early_stopping=None,
        random_seed=731,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=True,
        funding_rate=data["funding_rate"],
        target_runtime="rust",
    )
    started = perf_counter()
    result = endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"amplitude": (0.2, 1.0, 0.2), "period": (5, 30, 5)},
    )
    return result, float(perf_counter() - started)


def _assert_public_parity(reference, candidate) -> None:
    """Reject timing data unless selection and final continuous account match."""

    left = reference.metadata["walk_forward"]
    right = candidate.metadata["walk_forward"]
    pd.testing.assert_series_equal(reference.equity, candidate.equity, check_exact=False, atol=1.0e-10)
    pd.testing.assert_series_equal(reference.returns, candidate.returns, check_exact=False, atol=1.0e-12)
    pd.testing.assert_frame_equal(reference.positions, candidate.positions, check_exact=False, atol=1.0e-12)
    pd.testing.assert_frame_equal(left["trial_table"], right["trial_table"], check_exact=True)
    pd.testing.assert_frame_equal(left["candidate_table"], right["candidate_table"], check_exact=True)
    assert left["params"] == right["params"]
    assert left["best_trial"] == right["best_trial"]
    assert left["params_by_fold"] == right["params_by_fold"]


def _profile_breakdown(result) -> dict[str, float]:
    profile = dict(result.metadata["walk_forward"].get("performance_profile", {}) or {})
    return {
        "data_alignment_fold_prepare": float(profile.get("data_alignment_fold_prepare_seconds", 0.0)),
        "strategy": float(profile.get("strategy_seconds", 0.0)),
        "score": float(profile.get("score_seconds", 0.0)),
    }


def _measure_mode(data: pd.DataFrame, *, spec: _ModeSpec, profile: Mapping[str, Any]) -> dict[str, Any]:
    # Compile/allocate both exact public routes outside the recorded sample.
    reference_warm, _ = _run(data, spec=spec, prepared=False, profile=profile)
    candidate_warm, _ = _run(data, spec=spec, prepared=True, profile=profile)
    _assert_public_parity(reference_warm, candidate_warm)

    reference_seconds: list[float] = []
    candidate_seconds: list[float] = []
    reference_profile: list[dict[str, float]] = []
    candidate_profile: list[dict[str, float]] = []
    memory_samples: list[dict[str, Any]] = []
    reference_result = reference_warm
    candidate_result = candidate_warm
    for repeat in range(int(profile["repeats"])):
        gc.collect()
        before_memory = _rss_pss_mb()
        if repeat % 2 == 0:
            reference_result, reference_elapsed = _run(data, spec=spec, prepared=False, profile=profile)
            reference_memory = _rss_pss_mb()
            candidate_result, candidate_elapsed = _run(data, spec=spec, prepared=True, profile=profile)
            candidate_memory = _rss_pss_mb()
            order = "reference_then_prepared"
        else:
            candidate_result, candidate_elapsed = _run(data, spec=spec, prepared=True, profile=profile)
            candidate_memory = _rss_pss_mb()
            reference_result, reference_elapsed = _run(data, spec=spec, prepared=False, profile=profile)
            reference_memory = _rss_pss_mb()
            order = "prepared_then_reference"
        _assert_public_parity(reference_result, candidate_result)
        reference_seconds.append(float(reference_elapsed))
        candidate_seconds.append(float(candidate_elapsed))
        reference_profile.append(_profile_breakdown(reference_result))
        candidate_profile.append(_profile_breakdown(candidate_result))
        memory_samples.append(
            {
                "order": order,
                "before_mb": before_memory,
                "reference_after_mb": reference_memory,
                "prepared_after_mb": candidate_memory,
                "reference_delta_mb": {
                    name: float(reference_memory[name] - before_memory[name]) for name in before_memory
                },
                "prepared_delta_mb": {
                    name: float(candidate_memory[name] - before_memory[name]) for name in before_memory
                },
            }
        )

    reference_median = float(median(reference_seconds))
    candidate_median = float(median(candidate_seconds))
    candidate_wf = candidate_result.metadata["walk_forward"]
    prep = dict(candidate_wf.get("prepared_wfo_context", {}) or {})
    windows = dict(prep.get("window_preparation", {}) or {})
    bars = int(candidate_wf.get("n_optuna_trial_rows", 0))
    return {
        "mode": spec.mode,
        "optimization_schedule": spec.schedule,
        "scoring_backend": spec.scoring_backend,
        "reference_seconds": {"samples": reference_seconds, "median": reference_median},
        "prepared_seconds": {"samples": candidate_seconds, "median": candidate_median},
        "speedup_x": reference_median / candidate_median if candidate_median > 0.0 else float("inf"),
        "reference_profile_seconds": {
            name: float(median([row[name] for row in reference_profile])) for name in reference_profile[0]
        },
        "prepared_profile_seconds": {
            name: float(median([row[name] for row in candidate_profile])) for name in candidate_profile[0]
        },
        "work": {
            "folds": int(len(candidate_wf["fold_table"])),
            "studies": int(candidate_wf["n_studies"]),
            "optuna_trial_rows": bars,
        },
        "prepared_windows": windows,
        "memory_samples": memory_samples,
        "parity": True,
    }


def run(*, profile: str, modes: Iterable[str] | None = None) -> dict[str, Any]:
    if profile not in PROFILE_SPECS:
        raise ValueError(f"profile must be one of: {', '.join(sorted(PROFILE_SPECS))}")
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - public dependency guard
        raise RuntimeError("PERF-08 benchmark requires the optimization extra") from exc
    requested = None if modes is None else frozenset(str(item) for item in modes)
    if profile == "broad" and requested != frozenset({"mode_4_is_only_robust"}):
        raise ValueError("the broad PERF-08 profile is intentionally limited to --mode mode_4_is_only_robust")
    specs = tuple(spec for spec in MODE_SPECS if requested is None or spec.mode in requested)
    if not specs:
        raise ValueError("no known PERF-08 WFO modes were selected")
    spec = PROFILE_SPECS[profile]
    data = _market(int(spec["bars"]), frequency=str(spec["frequency"]))
    rows = [_measure_mode(data, spec=item, profile=spec) for item in specs]
    return {
        "schema": SCHEMA,
        "status": "paired_public_wfo_preparation_parity_passed",
        "scope": (
            "same public endpoint/strategy/Optuna/account/final-account retention; "
            "run-local WFO preparation false versus true"
        ),
        "profile": {"id": profile, **spec},
        "rows": rows,
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="one untimed reference/prepared pair per mode, then alternating paired public runs",
            data_sha256=typed_array_sha256(
                data.index.asi8,
                data[["open", "high", "low", "close", "volume", "funding_rate"]].to_numpy(dtype=np.float64),
            ),
            intent_sha256=typed_array_sha256(
                np.frombuffer(
                    "|".join(f"{row['mode']}:{row['optimization_schedule']}" for row in rows).encode("utf-8"),
                    dtype=np.uint8,
                ),
            ),
        ),
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    rows = list(payload["rows"])
    table = "\n".join(
        "| `{mode}` | `{optimization_schedule}` | {reference:.4f} s | {prepared:.4f} s | {speedup:.3f}x | {folds} | {trials} |".format(
            mode=row["mode"],
            optimization_schedule=row["optimization_schedule"],
            reference=float(row["reference_seconds"]["median"]),
            prepared=float(row["prepared_seconds"]["median"]),
            speedup=float(row["speedup_x"]),
            folds=int(row["work"]["folds"]),
            trials=int(row["work"]["optuna_trial_rows"]),
        )
        for row in rows
    )
    mode_notes = (
        (
            "The Mode 2 row preserves its existing NumPy stationary-bootstrap RNG and proxy scorer. It does not claim",
            "a new bootstrap algorithm. Mode 4 causal keeps one study per outer fold and never uses outer OOS for selection.",
        )
        if any(row["mode"] == "mode_2_sbb" for row in rows)
        else (
            "Mode 4 causal keeps one study per outer fold and never uses outer OOS for selection.",
        )
    )
    return "\n".join(
        (
            "# PERF-08 Public WFO Preparation Evidence",
            "",
            "This is an alternating paired public-facade measurement. Every pair retains the same strategy callback,",
            "calendar, parameter space, Optuna seed/trial sequence, account configuration, and final stitched account.",
            "Only `use_prepared_wfo_context` changes. Results are recorded only after full selection and account parity.",
            "",
            "| Mode | Schedule | Reference median | Prepared median | Speedup | Folds | Trial rows |",
            "|---|---|---:|---:|---:|---:|---:|",
            table,
            "",
            *mode_notes,
            "",
            "Prepared-window counters identify only immutable calendar/shard/trade-requirement reuse. They are not a",
            "cross-run result cache, do not reuse Optuna observations, and do not suppress strategy invocations.",
            "",
            "`memory_samples` records alternating same-process RSS/PSS observations before and after each lane. It is",
            "a retention/plateau diagnostic, not a claim of isolated per-lane private memory; shared allocator state is",
            "intentionally not summed as a speedup or a private-memory reduction.",
            "",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILE_SPECS), default="smoke")
    parser.add_argument("--mode", action="append", choices=[item.mode for item in MODE_SPECS])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = run(profile=args.profile, modes=args.mode)
    default = DEFAULT_OUTPUT if args.profile == "smoke" else DEFAULT_OUTPUT.with_name(
        "perf_08_public_wfo_standard.json"
    )
    output = default if args.output is None else args.output
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
