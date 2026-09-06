#!/usr/bin/env python3
"""Phase 77.1 public WFO baseline and legacy percent-equity contract evidence.

This module deliberately measures the public facade before Phase 77.2 changes
any hot path.  It is a *baseline*, not a promotion artifact: the working tree
may be dirty during development, every requested/resolved backend is recorded,
and unsupported paths are rows with an explicit reason rather than omitted
speed claims.

The matrix separates three contracts which must not be conflated:

* W0 public callback WFO candidate scoring;
* the legacy ``pct_equity`` transition-sizing engine; and
* W3 reactive WFO, which remains a distinct prepared-reactive facade.

Run a small complete routing matrix during development:

    PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase77_1_public_matrix.py \
        --profile smoke

Run the five-repeat 10,000-bar headline comparator deliberately:

    PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase77_1_public_matrix.py \
        --profile standard

The 100,000-bar stress profile is opt-in because it is a resource test, not a
release-smoke command.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gc
from hashlib import sha256
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
from tools.measurement_contract import (  # noqa: E402
    build_work_counters,
    capture_measurement_identity,
    typed_array_sha256,
)


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase77_1_public_matrix.json"
MANIFEST_PATH = ROOT / "benchmarks/native_event/manifests/phase77_1_public_matrix_v1.json"
SCHEMA = "quantbt-phase77-1-public-workload-baseline-v1"
EPS = 1.0e-10


@dataclass(frozen=True)
class WorkloadRow:
    """One public route whose observed behavior must stay visible."""

    identifier: str
    mode: str
    schedule: str
    route: str
    target_mode: str
    scoring_backend: str
    native_policy: str
    expected_resolution: str
    selection_contract: str


PUBLIC_ROWS: tuple[WorkloadRow, ...] = (
    WorkloadRow(
        "mode1_global_w0_native_eligible",
        "mode_1_decay",
        "global",
        "walk_forward",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "one retrospective study; declared fold OOS participates in decay selection",
    ),
    WorkloadRow(
        "mode1_per_fold_decay_w0_native_eligible",
        "mode_1_decay",
        "per_fold_decay",
        "walk_forward",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "one independent study per outer fold; same-fold OOS selects among top-IS candidates",
    ),
    WorkloadRow(
        "mode1_per_fold_causal_w0_native_eligible",
        "mode_1_decay",
        "per_fold_causal",
        "walk_forward",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "one study per outer fold; nested inner IS/OOS only, outer OOS remains untouched",
    ),
    WorkloadRow(
        "mode1_train_test_w0_native_eligible",
        "mode_1_decay",
        "global",
        "train_test_split",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "single declared train/test fold; OOS contributes to Mode 1 decay selection",
    ),
    WorkloadRow(
        "mode2_global_proxy_preserved",
        "mode_2_sbb",
        "global",
        "walk_forward",
        "signal_notional",
        "proxy",
        "auto",
        "proxy_preserved",
        "bounded path-resampling proxy; stationary-bootstrap path construction remains authoritative",
    ),
    WorkloadRow(
        "mode2_train_test_proxy_preserved",
        "mode_2_sbb",
        "global",
        "train_test_split",
        "signal_notional",
        "proxy",
        "auto",
        "proxy_preserved",
        "single declared train/test with the same bounded path-resampling proxy",
    ),
    WorkloadRow(
        "mode3_global_w0_native_eligible",
        "mode_3_flat_minima",
        "global",
        "walk_forward",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "one retrospective study; cluster/plateau selection after endpoint scoring",
    ),
    WorkloadRow(
        "mode3_train_test_w0_native_eligible",
        "mode_3_flat_minima",
        "global",
        "train_test_split",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "single declared train/test with flat-minima selection",
    ),
    WorkloadRow(
        "mode4_global_w0_native_eligible",
        "mode_4_is_only_robust",
        "global",
        "walk_forward",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "one retrospective study; IS-only temporal and plateau robustness",
    ),
    WorkloadRow(
        "mode4_per_fold_causal_w0_native_eligible",
        "mode_4_is_only_robust",
        "per_fold_causal",
        "walk_forward",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "one IS-only study per outer fold; strict outer OOS after frozen selection",
    ),
    WorkloadRow(
        "mode4_train_test_w0_native_eligible",
        "mode_4_is_only_robust",
        "global",
        "train_test_split",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "single declared train/test; IS-only robust selection",
    ),
    WorkloadRow(
        "mode5_full_sample_w0_native_eligible",
        "mode_5_full_robust",
        "global",
        "walk_forward",
        "signal_notional",
        "endpoint",
        "require",
        "native_prepared",
        "full declared sample calibration; no fabricated OOS validation claim",
    ),
    WorkloadRow(
        "pct_equity_auto_fallback",
        "mode_4_is_only_robust",
        "global",
        "walk_forward",
        "pct_equity",
        "endpoint",
        "auto",
        "fallback",
        "legacy transition-sized percent-equity scorer remains authoritative",
    ),
)


# These are deliberately not folded into the W0 callback comparator. Each has
# a distinct strategy/account/tape contract and therefore owns its own timing
# denominator and parity evidence. Keeping the boundary in the artifact avoids
# presenting an eligible W0 score speedup as a generic Rust claim.
SEPARATE_SCOPE_EVIDENCE: tuple[dict[str, str], ...] = (
    {
        "route": "reactive_w3",
        "evidence": "benchmarks/native_event/results/phase76_reactive_wfo.json",
        "contract": "prepared reactive callback; reset-flat segmented accounts",
        "coverage": "Mode 1 global timing; Modes 1/3/4/5 fixed-candidate selector parity in tests/test_phase76_reactive_wfo.py",
        "boundary": "No W0 comparator or generic walk_forward speedup claim.",
    },
    {
        "route": "direct_target_vectorized",
        "evidence": "benchmarks/native_event/results/phase66_rust_target_vectorized.json",
        "contract": "typed direct target tape",
        "coverage": "separate target/vectorized authority benchmark",
        "boundary": "Not generic callback WFO or legacy pct_equity.",
    },
    {
        "route": "shared_account_portfolio",
        "evidence": "benchmarks/native_event/results/phase67_shared_portfolio.json",
        "contract": "bounded shared-account portfolio",
        "coverage": "separate portfolio parity and throughput benchmark",
        "boundary": "Not a single-symbol public WFO score route.",
    },
    {
        "route": "bounded_package",
        "evidence": "benchmarks/native_event/results/phase68_bounded_package.json",
        "contract": "same-account bounded package",
        "coverage": "separate package reconciliation benchmark",
        "boundary": "Not a generic package/arbitrage WFO promotion claim.",
    },
)


PROFILE_SPECS: dict[str, dict[str, int | str]] = {
    "smoke": {
        "bars": 720,
        "frequency": "1D",
        "split_mode": "2020-07-01",
        "split_frequency": "quarterly",
        "train_window": "180D",
        "trials": 4,
        "repeats": 1,
        "description": "Complete public routing and selection-contract matrix; not a headline speed claim.",
    },
    "standard": {
        "bars": 10_000,
        # Ten thousand daily bars would create more than one hundred quarterly
        # folds. The declared standard comparator is instead a real 10,000-bar
        # hourly tape with three calendar folds, so its candidate/fold budget
        # matches the public measurement contract.
        "frequency": "1h",
        "split_mode": "2020-07-01",
        "split_frequency": "quarterly",
        "train_window": "180D",
        "trials": 64,
        "repeats": 5,
        "description": "Five-repeat paired headline W0 Mode 1 global comparator on the declared standard profile.",
    },
    "long": {
        "bars": 100_000,
        "frequency": "1h",
        "split_mode": "2020-02-01",
        "split_frequency": "yearly",
        "train_window": "30D",
        "trials": 256,
        "repeats": 1,
        "description": "Opt-in stress probe; records timeout/memory outcome and is never a default release command.",
    },
}


def _memory_snapshot_mb() -> dict[str, float]:
    """Return Linux RSS/PSS snapshots without claiming process ownership splits."""

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
    if bars < 540:
        raise ValueError("public WFO baseline needs at least 540 bars")
    index = pd.date_range("2020-01-01", periods=int(bars), freq=frequency, tz="UTC")
    phase = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 0.025 * phase + 2.2 * np.sin(phase / 13.0) + 0.7 * np.cos(phase / 31.0)
    open_ = np.r_[close[0], close[:-1]] + 0.08 * np.cos(phase / 5.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.75,
            "low": np.minimum(open_, close) - 0.75,
            "close": close,
            "volume": 1_000.0 + phase,
            "funding_rate": np.where((phase.astype(np.int64) % 7) == 0, 0.00015, -0.00005),
        },
        index=index,
    )


def _transition_strategy(data, params, train_index, test_index, fold):
    """A deterministic W0 callback whose output only depends on `test_index`."""

    del data, train_index, fold
    amplitude = float(params["amplitude"])
    period = int(params["period"])
    epoch = pd.Timestamp("2020-01-01", tz="UTC")
    bars = ((pd.DatetimeIndex(test_index).asi8 - epoch.value) // pd.Timedelta("1D").value).astype(np.int64)
    signal = amplitude * np.where((bars // period) % 2 == 0, 1.0, -1.0)
    return pd.Series(signal, index=test_index, dtype=float)


def _selection_config(row: WorkloadRow, *, native_policy: str, profile: bool) -> dict[str, Any]:
    config: dict[str, Any] = {
        "candidate_selection_metric": "robust_decay",
        "top_is_fraction": 0.50,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "plateau_quantile": 0.25,
        "plateau_median_weight": 0.25,
        "plateau_std_penalty": 0.50,
        "plateau_size_bonus": 0.01,
        "scoring_backend": row.scoring_backend,
        "scoring_trading_days": 365,
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
        "native_prepared_wfo": native_policy,
        "native_prepared_wfo_workers": 1,
        "profile_walkforward": bool(profile),
        "metadata": {"lifecycle_ledger_max_rows": 64},
    }
    if row.mode == "mode_2_sbb":
        config.update(
            {
                "sbb_samples": 8,
                "sbb_block_length": 3,
                "sbb_simulation": "stationary",
                "sbb_decay_lambda": 0.5,
                "sbb_std_penalty": 0.1,
            }
        )
    elif row.mode == "mode_3_flat_minima":
        config["candidate_selection_metric"] = "is_plateau_robust"
    elif row.mode == "mode_4_is_only_robust":
        config.update({"candidate_selection_metric": "is_only_robust", "is_subperiods": 2})
    elif row.mode == "mode_5_full_robust":
        config.update({"candidate_selection_metric": "full_robust", "is_subperiods": 1})
    if row.schedule == "per_fold_causal" and row.mode == "mode_1_decay":
        config.update(
            {
                "inner_split_frequency": "monthly",
                "inner_window_mode": "rolling",
                "inner_train_window": "60D",
                "inner_min_folds": 2,
            }
        )
    return config


def _endpoint_for(
    row: WorkloadRow,
    data: pd.DataFrame,
    *,
    native_policy: str,
    trials: int,
    profile: bool,
) -> QuantBTEndpoint:
    """Build one public endpoint with no hidden internal-route mutation."""

    common = {
        "strategy_class": _transition_strategy,
        "target_mode": row.target_mode,
        "optimization_mode": row.mode,
        "optimization_schedule": row.schedule,
        "optimization_config": _selection_config(row, native_policy=native_policy, profile=profile),
        "optuna_trials": int(trials),
        "optuna_early_stopping": None,
        "random_seed": 731,
        "initial_capital": 20_000.0,
        "leverage": 3.0,
        "maintenance_ratio": 0.005,
        "alloc_per_trade": 0.5 if row.target_mode == "pct_equity" else 1_000.0,
        # The legacy BacktestEngine still consumes its historical round-trip
        # `fee` argument. Keep it numerically equivalent to the explicit
        # one-way fee_rate for this baseline instead of allowing the legacy
        # default to silently alter the fallback row.
        "fee": 0.0004,
        "fee_rate": 0.0002,
        "slippage": 0.0001,
        "use_funding": True,
        "funding_rate": data["funding_rate"],
        "use_pyramiding": True,
        "target_runtime": "rust",
    }
    if row.route == "train_test_split":
        return QuantBTEndpoint.train_test_split(
            test_start=str(data.index[int(len(data) * 0.65)].date()),
            window_mode="rolling",
            train_window="365D",
            **common,
        )
    return QuantBTEndpoint.walk_forward(
        split_mode=str(data.attrs["phase77_1_split_mode"]),
        split_frequency=str(data.attrs["phase77_1_split_frequency"]),
        window_mode="rolling",
        train_window=str(data.attrs["phase77_1_train_window"]),
        **common,
    )


def _run_endpoint(
    row: WorkloadRow,
    data: pd.DataFrame,
    *,
    native_policy: str,
    trials: int,
    profile: bool,
    params: Mapping[str, Any] | None = None,
) -> tuple[Any, float]:
    endpoint = _endpoint_for(row, data, native_policy=native_policy, trials=trials, profile=profile)
    started = perf_counter()
    result = endpoint.backtest(
        data=data,
        symbols=["BTC"],
        params=None if params is None else dict(params),
        param_ranges=None if params is not None else {"amplitude": [0.4, 0.8], "period": [7, 13]},
    )
    return result, float(perf_counter() - started)


def _json_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, pd.Series):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, pd.DataFrame):
        return [_json_value(row) for row in value.to_dict(orient="records")]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return str(value)
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _tolerant_value(value: Any, *, decimals: int = 9) -> Any:
    """Canonicalize only comparison evidence, never the recorded raw result."""

    if isinstance(value, (float, np.floating)):
        if not np.isfinite(float(value)):
            return str(value)
        return round(float(value), decimals)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, Mapping):
        return {str(key): _tolerant_value(item, decimals=decimals) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_tolerant_value(item, decimals=decimals) for item in value]
    return _json_value(value)


def _tolerant_array_hash(values: Any, *, decimals: int = 9) -> str:
    array = np.asarray(values, dtype=np.float64)
    return typed_array_sha256(np.round(array, decimals=decimals))


def _selection_table_fingerprint(table: Any) -> str:
    if not isinstance(table, pd.DataFrame) or table.empty:
        return _stable_hash([])
    columns = [
        column
        for column in (
            "trial_id",
            "params",
            "objective",
            "mean_is_sharpe",
            "mean_oos_sharpe",
            "mean_decay",
            "std_decay",
            "pruned",
            "schedule_fold_id",
            "study_id",
            "fold_seed",
        )
        if column in table.columns
    ]
    return _stable_hash(_tolerant_value(table.loc[:, columns].to_dict(orient="records")))


def _resolved_native_metadata(result: Any) -> dict[str, Any]:
    wf = dict(result.metadata["walk_forward"])
    cache = dict(wf.get("prepared_scoring_cache", {}) or {})
    prepared = dict(cache.get("native_prepared_wfo", wf.get("native_prepared_wfo", {})) or {})
    return prepared


def _result_fingerprint(result: Any) -> dict[str, Any]:
    wf = dict(result.metadata["walk_forward"])
    trial_table = wf.get("trial_table", pd.DataFrame())
    candidate_table = wf.get("candidate_table", pd.DataFrame())
    result_wf = result.metadata.get("walk_forward_result")
    oos_output = getattr(result_wf, "oos_output", None)
    best_trial = dict(wf.get("best_trial", {}) or {})
    best_fields = {
        key: best_trial.get(key)
        for key in (
            "trial_id",
            "params",
            "objective",
            "mean_is_sharpe",
            "mean_oos_sharpe",
            "mean_decay",
            "std_decay",
            "schedule_fold_id",
            "study_id",
            "fold_seed",
        )
        if key in best_trial
    }
    return {
        "params": _json_value(wf.get("params", {})),
        "params_by_fold": _json_value(wf.get("params_by_fold", {})),
        "best_trial": _tolerant_value(best_fields),
        "trial_table_sha256": _selection_table_fingerprint(trial_table),
        "candidate_table_sha256": _selection_table_fingerprint(candidate_table),
        "equity_sha256": _tolerant_array_hash(result.equity.to_numpy(dtype=np.float64)),
        "positions_sha256": _tolerant_array_hash(result.positions.to_numpy(dtype=np.float64)),
        "oos_output_sha256": (
            None
            if oos_output is None
            else _tolerant_array_hash(np.asarray(oos_output, dtype=np.float64))
        ),
    }


def _assert_public_parity(reference: Any, native: Any) -> None:
    """Fail closed before timing a route as a native/reference comparator."""

    for field, atol in (("equity", EPS), ("returns", 1.0e-12), ("fees", 1.0e-12), ("funding", 1.0e-12)):
        left = getattr(reference, field)
        right = getattr(native, field)
        if isinstance(left, pd.Series):
            pd.testing.assert_series_equal(left, right, check_exact=False, atol=atol)
        else:
            pd.testing.assert_frame_equal(left, right, check_exact=False, atol=atol)
    pd.testing.assert_frame_equal(reference.positions, native.positions, check_exact=False, atol=1.0e-12)
    assert _result_fingerprint(reference) == _result_fingerprint(native)


def _fold_counters(result: Any, *, candidate_count: int) -> dict[str, Any]:
    wf_result = result.metadata["walk_forward_result"]
    folds = tuple(
        {
            "fold_id": int(fold.fold_id),
            "test_start": 0,
            "test_end": int(len(fold.test_index)),
        }
        for fold in wf_result.folds
    )
    counters = build_work_counters(
        supplied_market_bars=int(len(result.equity.index)),
        candidate_count=int(candidate_count),
        scenario_count=1,
        symbol_count=1,
        folds=folds,
    )
    counters["scope"] = "outer_fold_test_windows_only_not_all_internal_IS_or_SBB_paths"
    return counters


def _summary(
    row: WorkloadRow,
    result: Any,
    *,
    elapsed: float,
    lane: str,
    samples: Sequence[float],
) -> dict[str, Any]:
    wf = dict(result.metadata["walk_forward"])
    prepared = _resolved_native_metadata(result)
    profile = dict(wf.get("performance_profile", {}) or {})
    trial_table = wf.get("trial_table", pd.DataFrame())
    candidate_count = int(len(trial_table))
    rows = {
        "id": row.identifier,
        "lane": lane,
        "mode": row.mode,
        "optimization_schedule": row.schedule,
        "public_route": row.route,
        "target_mode": row.target_mode,
        "scoring_backend": row.scoring_backend,
        "selection_contract": row.selection_contract,
        "requested_native_prepared_policy": prepared.get("requested_policy"),
        "resolved_native_prepared_policy": prepared.get("resolved_policy"),
        "native_prepared_reason": prepared.get("reason"),
        "native_score_rows": int(prepared.get("native_rows", 0) or 0),
        "native_score_batches": int(prepared.get("native_batches", 0) or 0),
        "native_scored_bars": int(prepared.get("native_scored_bars", 0) or 0),
        "requested_target_runtime": "rust",
        "resolved_final_backend": result.metadata.get("backend"),
        "validation_claim": wf.get("validation_claim"),
        "causality_claim": wf.get("causality_claim"),
        "chronological_validation_claim": wf.get("chronological_validation_claim"),
        "oos_used_for_selection": bool(wf.get("oos_used_for_selection", False)),
        "fold_count": int(wf.get("n_folds", 0)),
        "candidate_count": candidate_count,
        "timing_seconds": {
            "samples": [float(value) for value in samples],
            "median": float(median(samples)),
            "p95": float(np.quantile(np.asarray(samples, dtype=np.float64), 0.95)),
            "last": float(elapsed),
            "prepare_fold_plan": float(profile.get("data_alignment_fold_prepare_seconds", 0.0)),
            "strategy_generation": float(profile.get("strategy_seconds", 0.0)),
            "candidate_score": float(profile.get("score_seconds", 0.0)),
            "native_execute_within_score": float(prepared.get("native_score_seconds", 0.0) or 0.0),
        },
        "work_counters": _fold_counters(result, candidate_count=candidate_count),
        "fingerprint": _result_fingerprint(result),
    }
    return rows


def _run_pair(row: WorkloadRow, data: pd.DataFrame, *, trials: int, repeats: int) -> dict[str, Any]:
    """Warm and alternately measure a public reference/native pair."""

    # A first pair is intentionally outside timings: it compiles/imports and
    # checks result identity before any performance evidence is produced.
    reference_warm, _ = _run_endpoint(row, data, native_policy="off", trials=trials, profile=True)
    native_warm, _ = _run_endpoint(row, data, native_policy="require", trials=trials, profile=True)
    _assert_public_parity(reference_warm, native_warm)
    prepared_warm = _resolved_native_metadata(native_warm)
    if prepared_warm.get("resolved_policy") != "native_prepared":
        raise AssertionError(f"{row.identifier} did not enter the declared native prepared route: {prepared_warm}")

    reference_times: list[float] = []
    native_times: list[float] = []
    reference_result = reference_warm
    native_result = native_warm
    rss_samples: list[dict[str, float]] = []
    for repeat in range(int(repeats)):
        gc.collect()
        if repeat % 2 == 0:
            reference_result, reference_elapsed = _run_endpoint(
                row, data, native_policy="off", trials=trials, profile=True
            )
            native_result, native_elapsed = _run_endpoint(
                row, data, native_policy="require", trials=trials, profile=True
            )
        else:
            native_result, native_elapsed = _run_endpoint(
                row, data, native_policy="require", trials=trials, profile=True
            )
            reference_result, reference_elapsed = _run_endpoint(
                row, data, native_policy="off", trials=trials, profile=True
            )
        _assert_public_parity(reference_result, native_result)
        reference_times.append(float(reference_elapsed))
        native_times.append(float(native_elapsed))
        rss_samples.append(_memory_snapshot_mb())

    reference_row = _summary(
        row, reference_result, elapsed=reference_times[-1], lane="reference_endpoint", samples=reference_times
    )
    native_row = _summary(
        row, native_result, elapsed=native_times[-1], lane="prepared_native", samples=native_times
    )
    native_row["paired_speedup_vs_reference"] = float(median(reference_times) / median(native_times))
    return {
        "status": "measured_pair_parity_passed",
        "reference": reference_row,
        "native": native_row,
        "rss_pss_samples_mb": rss_samples,
        "rss_pss_tail_spread_mb": {
            key: float(max(sample[key] for sample in rss_samples) - min(sample[key] for sample in rss_samples))
            for key in ("rss_mb", "pss_mb")
        },
    }


def _run_unpaired(row: WorkloadRow, data: pd.DataFrame, *, trials: int) -> dict[str, Any]:
    """Record an intentionally unsupported/fallback route without a fake pair."""

    result, elapsed = _run_endpoint(row, data, native_policy=row.native_policy, trials=trials, profile=True)
    prepared = _resolved_native_metadata(result)
    if prepared.get("resolved_policy") != row.expected_resolution:
        raise AssertionError(
            f"{row.identifier} expected {row.expected_resolution!r}, got {prepared.get('resolved_policy')!r}: {prepared}"
        )
    return {
        "status": "measured_unpaired_contract_route",
        "observed": _summary(row, result, elapsed=elapsed, lane="authoritative_contract_route", samples=[elapsed]),
    }


def pct_equity_transition_probe() -> dict[str, Any]:
    """Hand-computable financial fixtures for the legacy transition contract."""

    index = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 120.0, 120.0, 132.0],
            "high": [100.0, 100.0, 120.0, 120.0, 132.0],
            "low": [100.0, 100.0, 120.0, 120.0, 132.0],
            "close": [100.0, 100.0, 120.0, 120.0, 132.0],
        },
        index=index,
    )
    transition_signal = pd.Series([0.0, 1.0, 1.0, -1.0, -1.0], index=index)
    transition = QuantBTEndpoint.pct_equity(
        initial_capital=10_000.0,
        leverage=3.0,
        alloc_per_trade=0.5,
        fee=0.0,
        fee_rate=0.0,
        slippage=0.0,
        use_funding=False,
        use_pyramiding=True,
    ).backtest(data=frame, signal=transition_signal, symbols=["BTC"])
    expected_transition_equity = np.asarray([10_000.0, 10_000.0, 11_000.0, 11_000.0, 10_450.0])
    np.testing.assert_allclose(transition.equity.to_numpy(dtype=np.float64), expected_transition_equity, rtol=0.0, atol=EPS)

    first_bar = QuantBTEndpoint.pct_equity(
        initial_capital=10_000.0,
        leverage=3.0,
        alloc_per_trade=0.5,
        fee=0.0,
        fee_rate=0.0,
        use_funding=False,
    ).backtest(data=frame, signal=pd.Series(1.0, index=index), symbols=["BTC"])
    np.testing.assert_allclose(first_bar.equity.to_numpy(dtype=np.float64), 10_000.0, rtol=0.0, atol=EPS)

    # Funding masks are defined on 00:00 / 08:00 / 16:00 UTC window entry.
    # Use 8-hour bars so this fixture proves the carried-position ordering,
    # rather than accidentally relying on a daily bar that has no event mask.
    funding_index = pd.date_range("2024-02-01", periods=3, freq="8h", tz="UTC")
    funding_frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [100.0, 100.0, 100.0],
            "low": [100.0, 100.0, 100.0],
            "close": [100.0, 100.0, 100.0],
            "funding_rate": [0.0, 0.0, 0.01],
        },
        index=funding_index,
    )
    funding = QuantBTEndpoint.pct_equity(
        initial_capital=10_000.0,
        leverage=3.0,
        alloc_per_trade=0.5,
        fee=0.0,
        fee_rate=0.0,
        slippage=0.0,
        use_funding=True,
        funding_rate=funding_frame["funding_rate"],
    ).backtest(
        data=funding_frame,
        signal=pd.Series([0.0, 1.0, 1.0], index=funding_index),
        symbols=["BTC"],
    )
    np.testing.assert_allclose(float(funding.equity.iloc[-1]), 9_950.0, rtol=0.0, atol=EPS)

    rejected = QuantBTEndpoint.pct_equity(
        initial_capital=1_000.0,
        leverage=1.0,
        alloc_per_trade=1.0,
        fee=0.02,
        fee_rate=0.01,
        slippage=0.0,
        use_funding=False,
    ).backtest(
        data=frame.iloc[:4],
        signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=frame.index[:4]),
        symbols=["BTC"],
    )
    np.testing.assert_allclose(rejected.equity.to_numpy(dtype=np.float64), 1_000.0, rtol=0.0, atol=EPS)

    percentage = QuantBTEndpoint.pct_equity(
        initial_capital=10_000.0,
        leverage=3.0,
        alloc_per_trade=50.0,
        fee=0.0,
        fee_rate=0.0,
        slippage=0.0,
        use_funding=False,
    ).backtest(data=frame, signal=transition_signal, symbols=["BTC"])
    pd.testing.assert_series_equal(transition.equity, percentage.equity, check_exact=False, atol=EPS)

    return {
        "contract_id": "legacy_pct_equity_transition_sizing_v1",
        "entry_hold_reversal_equity": transition.equity.to_list(),
        "expected_entry_hold_reversal_equity": expected_transition_equity.tolist(),
        "first_bar_is_snapshot": True,
        "funding_on_carried_position": True,
        "rejected_unchanged_signal_is_not_retried": True,
        "alloc_fraction_and_percent_alias_match": True,
        "reported_positions_are_raw_weights": bool(
            float(rejected.positions.iloc[1, 0]) == 1.0 and float(rejected.equity.iloc[1]) == 1_000.0
        ),
    }


def _fixed_candidate_fingerprint(data: pd.DataFrame) -> dict[str, Any]:
    """Lock one fixed public candidate outside any optimizer study."""

    # A fixed-candidate replay has no Optuna study. Use the ordinary global
    # lifecycle because per-fold schedules intentionally reject `params=...`
    # rather than quietly bypassing their independent-study contract.
    row = next(item for item in PUBLIC_ROWS if item.identifier == "mode4_global_w0_native_eligible")
    first, _ = _run_endpoint(
        row,
        data,
        native_policy="off",
        trials=0,
        profile=True,
        params={"amplitude": 0.8, "period": 7},
    )
    second, _ = _run_endpoint(
        row,
        data,
        native_policy="off",
        trials=0,
        profile=True,
        params={"amplitude": 0.8, "period": 7},
    )
    first_fingerprint = _result_fingerprint(first)
    second_fingerprint = _result_fingerprint(second)
    if first_fingerprint != second_fingerprint:
        raise AssertionError("fixed public WFO candidate was not reproducible")
    return first_fingerprint


def run(
    *,
    profile: str = "smoke",
    include_rows: Iterable[str] | None = None,
    allow_long: bool = False,
) -> dict[str, Any]:
    """Execute a bounded phase baseline and return JSON-safe evidence."""

    if profile not in PROFILE_SPECS:
        raise ValueError(f"profile must be one of {', '.join(sorted(PROFILE_SPECS))}")
    if profile == "long" and not allow_long:
        raise ValueError("long is a deliberate stress run; pass allow_long=True")
    spec = PROFILE_SPECS[profile]
    data = _market(int(spec["bars"]), frequency=str(spec["frequency"]))
    data.attrs.update(
        {
            "phase77_1_frequency": str(spec["frequency"]),
            "phase77_1_split_mode": str(spec["split_mode"]),
            "phase77_1_split_frequency": str(spec["split_frequency"]),
            "phase77_1_train_window": str(spec["train_window"]),
        }
    )
    names = None if include_rows is None else set(include_rows)
    selected = tuple(row for row in PUBLIC_ROWS if names is None or row.identifier in names)
    if not selected:
        raise ValueError("no workload rows selected")
    if profile != "smoke" and names is None:
        selected = (next(row for row in PUBLIC_ROWS if row.identifier == "mode1_global_w0_native_eligible"),)

    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - install-level guard
        raise RuntimeError("Phase 77.1 public WFO benchmark requires Optuna") from exc

    memory_before = _memory_snapshot_mb()
    rows: list[dict[str, Any]] = []
    for row in selected:
        if row.expected_resolution == "native_prepared":
            rows.append(_run_pair(row, data, trials=int(spec["trials"]), repeats=int(spec["repeats"])))
        else:
            rows.append(_run_unpaired(row, data, trials=int(spec["trials"])))
    fixed = _fixed_candidate_fingerprint(data)
    pct_probe = pct_equity_transition_probe()
    gc.collect()
    memory_after = _memory_snapshot_mb()

    data_hash = typed_array_sha256(
        data.index.asi8,
        data[["open", "high", "low", "close", "volume", "funding_rate"]].to_numpy(dtype=np.float64),
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "phase": "77.1",
        "status": "baseline_only_not_promotion_eligible",
        "profile": {"id": profile, **spec},
        "matrix_manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "selected_workload_ids": [row.identifier for row in selected],
        "excluded_workload_ids": [row.identifier for row in PUBLIC_ROWS if row not in selected],
        "separate_scope_evidence": list(SEPARATE_SCOPE_EVIDENCE),
        "rows": rows,
        "fixed_candidate_reproducibility": fixed,
        "pct_equity_transition_contract": pct_probe,
        "memory_mb": {
            "before": memory_before,
            "after": memory_after,
            "delta": {key: float(memory_after[key] - memory_before[key]) for key in memory_before},
            "interpretation": "same-process baseline; no per-backend ownership or cold-process peak claim",
        },
        "findings_to_next_phase": [
            {
                "priority": 1,
                "owner": "77.2",
                "measured_or_inspected": "inspected_and_contract_locked",
                "baseline_loss": "legacy pct_equity executes only on raw-weight transition and reports raw weights, so direct per-bar EquityFraction cannot be substituted.",
                "mechanism": "introduce a typed transition-sizing request with accepted-unit state and a separate public adapter.",
                "domain_risk": "silent drift-rebalance or rejection-retry changes fees, margin and final equity.",
                "comparator": "legacy_pct_equity_transition_sizing_v1 hand fixtures plus public fold parity.",
                "gate": "exact accepted-unit/equity/cost/rejection parity before any Rust eligibility widening.",
            },
            {
                "priority": 2,
                "owner": "77.2",
                "measured_or_inspected": "measured_public_matrix",
                "baseline_loss": "W0 endpoint scoring enters Rust only for certified scalar signal/notional/unit routes; callback generation and selection/report adaptation remain Python-owned.",
                "mechanism": "share prepared market ownership and compact metric columns without changing strategy lifecycle or Optuna order.",
                "domain_risk": "candidate ordering, strict causal boundaries and final stitched account parity.",
                "comparator": "paired reference/native rows in this artifact, fixed candidate fingerprint and same-seed trial-table fingerprint.",
                "gate": "same params, trial ordering, output, fees, funding and final account within declared tolerance.",
            },
            {
                "priority": 3,
                "owner": "77.3",
                "measured_or_inspected": "scope_lock",
                "baseline_loss": "Mode 2 proxy and W3 reactive routes have different execution and sampling contracts; they must not inherit a W0 score speedup claim.",
                "mechanism": "separate sparse/reactive native state and bounded SBB work only after their own comparator is defined.",
                "domain_risk": "changed bootstrap RNG/path semantics, missed reactive wake, or TPE-sequence relabeling.",
                "comparator": "Mode 2 proxy-preserved row and Phase 76 reactive artifacts.",
                "gate": "identical path fingerprints or explicit non-comparability labels; no auto-promotion from this baseline.",
            },
        ],
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure=(
                "per eligible row warm reference/native public WFO once, assert full result fingerprint parity, "
                "then alternate paired order; unpaired fallback rows are recorded without a speed ratio"
            ),
            data_sha256=data_hash,
            intent_sha256=_stable_hash({"rows": [row.identifier for row in selected], "profile": profile}),
        ),
    }
    return _json_value(payload)


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 77.1 Public Workload Baseline",
        "",
        "This is a non-promotional baseline captured before Phase 77.2 changes dispatch or accounting.",
        "Each requested/resolved route is explicit. A fallback is evidence of an authority boundary, not a zero-speed native result.",
        "",
        "## Profile",
        "",
        (
            f"- Profile: `{payload['profile']['id']}`; bars: `{payload['profile']['bars']}` at "
            f"`{payload['profile']['frequency']}`; split: `{payload['profile']['split_frequency']}` after "
            f"`{payload['profile']['train_window']}` training; trials: `{payload['profile']['trials']}`; "
            f"repeats: `{payload['profile']['repeats']}`."
        ),
        f"- Status: `{payload['status']}`.",
        "",
        "## Public Matrix",
        "",
        "| Workload | Lane / resolution | Median | Native score rows | Selection contract |",
        "|---|---|---:|---:|---|",
    ]
    for entry in payload["rows"]:
        if entry["status"] == "measured_pair_parity_passed":
            native = entry["native"]
            reference = entry["reference"]
            lines.append(
                "| `{}` | prepared-native / `{}` | {:.6f} s vs {:.6f} s reference | {} | {} |".format(
                    native["id"],
                    native["resolved_native_prepared_policy"],
                    native["timing_seconds"]["median"],
                    reference["timing_seconds"]["median"],
                    native["native_score_rows"],
                    native["selection_contract"],
                )
            )
        else:
            observed = entry["observed"]
            lines.append(
                "| `{}` | authoritative route / `{}` | {:.6f} s | {} | {} |".format(
                    observed["id"],
                    observed["resolved_native_prepared_policy"],
                    observed["timing_seconds"]["median"],
                    observed["native_score_rows"],
                    observed["selection_contract"],
                )
            )
    pct = payload["pct_equity_transition_contract"]
    lines.extend(
        [
            "",
            "## Legacy `%_equity` Contract",
            "",
            f"- First bar is a snapshot: `{pct['first_bar_is_snapshot']}`.",
            f"- Funding is charged to the carried position: `{pct['funding_on_carried_position']}`.",
            f"- An unchanged signal after margin rejection is not retried: `{pct['rejected_unchanged_signal_is_not_retried']}`.",
            f"- Fraction and percentage allocation aliases agree: `{pct['alloc_fraction_and_percent_alias_match']}`.",
            f"- Public position output remains raw signal weights: `{pct['reported_positions_are_raw_weights']}`.",
            "",
            "See `docs/contracts/pct_equity_transition_v1.md` and `docs/performance/public_wfo_baseline_v1.md` for the executable scope, work-count definitions, and Phase 77.2/77.3 gates.",
            "",
        ]
    )
    lines.extend(
        [
            "## Separate Scope Evidence",
            "",
            "The rows above are W0 public callback evidence only. The following routes retain their own comparator and are not included in a W0 speed ratio:",
            "",
            "| Route | Evidence | Boundary |",
            "|---|---|---|",
            *[
                "| `{route}` | `{evidence}` | {boundary} |".format(**entry)
                for entry in payload["separate_scope_evidence"]
            ],
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILE_SPECS), default="smoke")
    parser.add_argument("--row", action="append", dest="rows", help="Run only one declared workload id; repeatable.")
    parser.add_argument("--allow-long", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output. Defaults are profile-specific so standard evidence never overwrites smoke.",
    )
    args = parser.parse_args(argv)
    payload = run(profile=args.profile, include_rows=args.rows, allow_long=bool(args.allow_long))
    default_output = (
        DEFAULT_OUTPUT
        if args.profile == "smoke"
        else DEFAULT_OUTPUT.with_name(f"phase77_1_public_{args.profile}.json")
    )
    chosen_output = default_output if args.output is None else args.output
    output = chosen_output if chosen_output.is_absolute() else ROOT / chosen_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
