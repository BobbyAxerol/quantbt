#!/usr/bin/env python3
"""Fresh public WFO evidence for NEXT-02.

This benchmark deliberately keeps candidate space, fold schedule, Optuna seed,
account contract, final stitched account, and retention unchanged across lanes.
It reports three distinct public routes rather than averaging them together:

* W0 compatibility strategy with the historical endpoint scorer;
* the same W0 strategy with the opt-in Rust prepared scorer; and
* an opt-in W1 prepared strategy with the same Rust scorer.

Mode 2 remains proxy/path authoritative.  It is measured with W0/W1 but never
relabeled as a scalar Rust score route.  The default smoke profile is evidence
for parity and bottleneck diagnosis; use at least 30 alternating pairs before
calling a timing target statistically qualified.
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
from quantbt.strategies import STRICT_CAUSAL_CACHE_CONTRACT_V1  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, typed_array_sha256  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/next02_fresh_wfo.json"
SCHEMA = "quantbt-next02-fresh-wfo-v1"


@dataclass(frozen=True, slots=True)
class _ModeSpec:
    mode: str
    schedule: str
    selector: str
    scoring_backend: str
    native_scalar_score: bool


MODE_SPECS: tuple[_ModeSpec, ...] = (
    _ModeSpec("mode_1_decay", "global", "robust_decay", "endpoint", True),
    _ModeSpec("mode_1_decay", "per_fold_decay", "robust_decay", "endpoint", True),
    _ModeSpec("mode_1_decay", "per_fold_causal", "robust_decay", "endpoint", True),
    _ModeSpec("mode_2_sbb", "global", "robust_decay", "proxy", False),
    _ModeSpec("mode_3_flat_minima", "global", "is_plateau_robust", "endpoint", True),
    _ModeSpec("mode_4_is_only_robust", "per_fold_causal", "is_only_robust", "endpoint", True),
    _ModeSpec("mode_5_full_robust", "global", "full_robust", "endpoint", True),
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
        "split_frequency": "quarterly",
        "window_mode": "rolling",
    },
    "standard": {
        "bars": 10_000,
        "frequency": "1h",
        "split_bar": 4_320,
        "train_window": "180D",
        "trials": 48,
        "repeats": 7,
        "sbb_samples": 256,
        "is_subperiods": 8,
        "split_frequency": "quarterly",
        "window_mode": "rolling",
    },
}


def _rss_pss_mb() -> dict[str, float]:
    """Read same-process diagnostics without calling shared pages private."""

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


def _signal(index: pd.DatetimeIndex, params: Mapping[str, Any]) -> np.ndarray:
    """Absolute-clock signal shared by W0 and W1, without future market reads."""

    amplitude = float(params["amplitude"])
    period = int(params["period"])
    epoch = pd.Timestamp("2020-01-01", tz="UTC")
    unit = pd.Timedelta("1h").value if len(index) > 1 and (index[1] - index[0]) < pd.Timedelta("1D") else pd.Timedelta("1D").value
    bars = ((pd.DatetimeIndex(index).asi8 - epoch.value) // unit).astype(np.int64)
    return np.asarray(amplitude * np.where((bars // period) % 2 == 0, 1.0, -1.0), dtype=np.float64)


class _PreparedSignals:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def __init__(self, index: pd.DatetimeIndex) -> None:
        self.index = pd.DatetimeIndex(index)

    def generate(self, *, params, fold_id):
        del fold_id
        return {"signal": _signal(self.index, params)}


class _SharedStrategy:
    """One strategy whose W0 and W1 surfaces intentionally agree bit-for-bit."""

    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def __call__(self, *, data, params, train_index, test_index, fold):
        del data, train_index, fold
        return pd.Series(_signal(test_index, params), index=test_index, dtype=float)

    def prepare_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-prepared-wfo-strategy-v1"
        assert len(data) == len(static_config["datetime_index"])
        assert len(folds) > 0
        return _PreparedSignals(data.index)


def _optimization_config(
    spec: _ModeSpec,
    *,
    profile: Mapping[str, Any],
    native_policy: str,
    prepared_strategy: bool,
) -> dict[str, Any]:
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
        "use_prepared_wfo_context": True,
        "use_prepared_scoring_cache": True,
        "use_scalar_trial_scoring": True,
        "compact_trial_ledger": True,
        # Fresh-study gate: prepared market ownership inside this run is
        # allowed, but no completed-score/prefix result is reused.
        "wfo_execution_reuse": "off",
        "native_prepared_wfo": native_policy,
        "native_prepared_wfo_workers": 1,
        "prepared_wfo_strategy": "require" if prepared_strategy else "off",
        "prepared_wfo_strategy_adapter": "w1",
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
    if spec.schedule == "per_fold_causal" and spec.mode == "mode_1_decay":
        config.update(
            {
                "inner_split_frequency": "monthly",
                "inner_window_mode": "rolling",
                "inner_train_window": "60D",
                "inner_min_folds": 2,
            }
        )
    return config


def _run_lane(
    data: pd.DataFrame,
    *,
    spec: _ModeSpec,
    profile: Mapping[str, Any],
    native_policy: str,
    prepared_strategy: bool,
) -> tuple[Any, float]:
    split_bar = int(profile["split_bar"])
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_SharedStrategy(),
        split_mode=str(data.index[split_bar].date()),
        split_frequency=str(profile["split_frequency"]),
        window_mode=str(profile["window_mode"]),
        train_window=str(profile["train_window"]),
        target_mode="signal_notional",
        optimization_mode=spec.mode,
        optimization_schedule=spec.schedule,
        optimization_config=_optimization_config(
            spec,
            profile=profile,
            native_policy=native_policy,
            prepared_strategy=prepared_strategy,
        ),
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


def _native_metadata(wf: Mapping[str, Any]) -> Mapping[str, Any]:
    direct = wf.get("native_prepared_wfo")
    if isinstance(direct, Mapping):
        return direct
    cache = wf.get("prepared_scoring_cache")
    if isinstance(cache, Mapping) and isinstance(cache.get("native_prepared_wfo"), Mapping):
        return cache["native_prepared_wfo"]
    return {}


def _assert_public_parity(reference, observed) -> None:
    """Reject a timing row unless selection and final accounting still agree."""

    left = reference.metadata["walk_forward"]
    right = observed.metadata["walk_forward"]
    pd.testing.assert_series_equal(reference.equity, observed.equity, check_exact=False, atol=1.0e-10)
    pd.testing.assert_series_equal(reference.returns, observed.returns, check_exact=False, atol=1.0e-12)
    pd.testing.assert_frame_equal(reference.positions, observed.positions, check_exact=False, atol=1.0e-12)
    assert left["params"] == right["params"]
    assert left["params_by_fold"] == right["params_by_fold"]
    assert left["best_trial"]["params"] == right["best_trial"]["params"]
    numeric_columns = [
        name
        for name in ("objective", "mean_is_sharpe", "mean_oos_sharpe", "mean_decay", "std_decay")
        if name in left["trial_table"].columns
    ]
    np.testing.assert_allclose(
        left["trial_table"][numeric_columns].to_numpy(dtype=float),
        right["trial_table"][numeric_columns].to_numpy(dtype=float),
        rtol=0.0,
        atol=1.0e-10,
        equal_nan=True,
    )
    pd.testing.assert_series_equal(
        reference.metadata["walk_forward_result"].oos_output,
        observed.metadata["walk_forward_result"].oos_output,
        check_exact=False,
        atol=1.0e-12,
    )


def _lane_snapshot(result, elapsed: float) -> dict[str, Any]:
    wf = result.metadata["walk_forward"]
    profile = dict(wf.get("performance_profile", {}) or {})
    native = dict(_native_metadata(wf))
    reuse = dict(wf.get("wfo_evaluation_runtime", {}) or {})
    strategy = dict(wf.get("prepared_wfo_strategy", {}) or {})
    return {
        "seconds": float(elapsed),
        "profile_seconds": {
            "prepare": float(profile.get("data_alignment_fold_prepare_seconds", 0.0)),
            "strategy": float(profile.get("strategy_seconds", 0.0)),
            "score": float(profile.get("score_seconds", 0.0)),
        },
        "native": {
            "resolved_policy": native.get("resolved_policy"),
            "native_batches": int(native.get("native_batches", 0)),
            "native_rows": int(native.get("native_rows", 0)),
            "native_scored_bars": int(native.get("native_scored_bars", 0)),
            "native_score_seconds": float(native.get("native_score_seconds", 0.0)),
        },
        "prepared_strategy": {
            "resolved_adapter": strategy.get("resolved_adapter"),
            "projection_requests": int(strategy.get("projection_requests", 0)),
            "projection_span_hits": int(strategy.get("projection_span_hits", 0)),
            "projection_gather_fallbacks": int(strategy.get("projection_gather_fallbacks", 0)),
            "projection_full_series_materializations": int(
                strategy.get("projection_full_series_materializations", 0)
            ),
        },
        "fresh_gate": {
            "cache_hits": int(reuse.get("cache_hits", 0)),
            "terminal_score_bars_reused": int(reuse.get("terminal_score_bars_reused", 0)),
        },
    }


def _median_snapshot(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    return {
        "median_seconds": float(median(float(row["seconds"]) for row in rows)),
        "median_profile_seconds": {
            key: float(median(float(row["profile_seconds"][key]) for row in rows))
            for key in first["profile_seconds"]
        },
        "native": dict(rows[-1]["native"]),
        "prepared_strategy": dict(rows[-1]["prepared_strategy"]),
        "fresh_gate": {
            "all_cache_hits_zero": all(int(row["fresh_gate"]["cache_hits"]) == 0 for row in rows),
            "all_reused_prefix_bars_zero": all(
                int(row["fresh_gate"]["terminal_score_bars_reused"]) == 0 for row in rows
            ),
        },
    }


def _paired_ratio_summary(
    baseline: Sequence[Mapping[str, Any]],
    observed: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> dict[str, Any]:
    """Summarize paired ratios without claiming unsupported tail evidence."""

    if len(baseline) != len(observed) or not baseline:
        raise ValueError("paired timing rows must be non-empty and have equal length")
    values = np.asarray(
        [float(right["seconds"]) / float(left["seconds"]) for left, right in zip(baseline, observed)],
        dtype=np.float64,
    )
    if not np.isfinite(values).all() or np.any(values <= 0.0):
        raise ValueError("paired timing ratios must be finite and positive")
    # This is a deterministic non-parametric bootstrap for the median only.
    # A p95 claim remains unavailable until the guide's 100-pair requirement.
    generator = np.random.default_rng(int(seed))
    draws = generator.integers(0, len(values), size=(4_000, len(values)))
    medians = np.median(values[draws], axis=1)
    return {
        "paired_samples": int(len(values)),
        "ratio_p50": float(np.median(values)),
        "ratio_ci95": [float(np.quantile(medians, 0.025)), float(np.quantile(medians, 0.975))],
        "p95_status": "not_claimed_requires_100_paired_samples",
        "qualification": (
            "paired_p50_qualified" if len(values) >= 30 else "diagnostic_only_requires_30_paired_samples"
        ),
    }


def _measure_mode(data: pd.DataFrame, *, spec: _ModeSpec, profile: Mapping[str, Any]) -> dict[str, Any]:
    lanes: dict[str, tuple[str, bool]] = {
        "w0_endpoint": ("off", False),
        "w1_prepared_strategy": ("off", True),
    }
    if spec.native_scalar_score:
        lanes["w0_native_prepared_score"] = ("require", False)
        lanes["w1_native_prepared_score"] = ("require", True)

    warm: dict[str, Any] = {}
    for name, (policy, w1) in lanes.items():
        result, _ = _run_lane(
            data,
            spec=spec,
            profile=profile,
            native_policy=policy,
            prepared_strategy=w1,
        )
        warm[name] = result
        _assert_public_parity(warm["w0_endpoint"], result)

    samples: dict[str, list[dict[str, Any]]] = {name: [] for name in lanes}
    memory: list[dict[str, Any]] = []
    ordered_names = tuple(lanes)
    for repeat in range(int(profile["repeats"])):
        gc.collect()
        before = _rss_pss_mb()
        order = ordered_names[repeat % len(ordered_names) :] + ordered_names[: repeat % len(ordered_names)]
        after: dict[str, dict[str, float]] = {}
        for name in order:
            policy, w1 = lanes[name]
            result, elapsed = _run_lane(
                data,
                spec=spec,
                profile=profile,
                native_policy=policy,
                prepared_strategy=w1,
            )
            _assert_public_parity(warm["w0_endpoint"], result)
            samples[name].append(_lane_snapshot(result, elapsed))
            after[name] = _rss_pss_mb()
        memory.append({"order": order, "before_mb": before, "after_mb": after})

    rows = {name: _median_snapshot(values) for name, values in samples.items()}
    baseline = float(rows["w0_endpoint"]["median_seconds"])
    for name, row in rows.items():
        row["ratio_to_w0_endpoint"] = float(row["median_seconds"]) / baseline
        row["speedup_vs_w0_endpoint_x"] = baseline / float(row["median_seconds"])
    native_ratio = rows.get("w0_native_prepared_score", {}).get("ratio_to_w0_endpoint")
    native_timing = (
        _paired_ratio_summary(
            samples["w0_endpoint"],
            samples["w0_native_prepared_score"],
            seed=731 + len(spec.mode) + len(spec.schedule),
        )
        if "w0_native_prepared_score" in samples
        else None
    )
    return {
        "mode": spec.mode,
        "optimization_schedule": spec.schedule,
        "scoring_backend": spec.scoring_backend,
        "native_scalar_score": bool(spec.native_scalar_score),
        "mode_2_contract": "proxy_path_preserved" if spec.mode == "mode_2_sbb" else None,
        "rows": rows,
        "native_w0_ratio": native_ratio,
        "native_w0_timing": native_timing,
        "fresh_gate": all(
            row["fresh_gate"]["all_cache_hits_zero"]
            and row["fresh_gate"]["all_reused_prefix_bars_zero"]
            for row in rows.values()
        ),
        "parity": True,
        "memory_samples": memory,
    }


def run(
    *,
    profile: str,
    modes: Iterable[str] | None = None,
    schedules: Iterable[str] | None = None,
    repeats: int | None = None,
) -> dict[str, Any]:
    if profile not in PROFILE_SPECS:
        raise ValueError(f"profile must be one of: {', '.join(sorted(PROFILE_SPECS))}")
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - public dependency guard
        raise RuntimeError("NEXT-02 benchmark requires the optimization extra") from exc
    settings = {**PROFILE_SPECS[profile]}
    if repeats is not None:
        if int(repeats) <= 0:
            raise ValueError("repeats must be positive")
        settings["repeats"] = int(repeats)
    wanted = None if modes is None else frozenset(str(item) for item in modes)
    wanted_schedules = None if schedules is None else frozenset(str(item) for item in schedules)
    specs = tuple(
        spec
        for spec in MODE_SPECS
        if (wanted is None or spec.mode in wanted)
        and (wanted_schedules is None or spec.schedule in wanted_schedules)
    )
    if not specs:
        raise ValueError("no known NEXT-02 WFO modes were selected")
    data = _market(int(settings["bars"]), frequency=str(settings["frequency"]))
    rows = [_measure_mode(data, spec=spec, profile=settings) for spec in specs]
    native_rows = [row for row in rows if row["native_scalar_score"]]
    return {
        "schema": SCHEMA,
        "scope": (
            "fresh cache-cold public QuantBTEndpoint.walk_forward comparisons; "
            "same candidate space, seed, account, final stitched account, and retention"
        ),
        "profile": {"id": profile, **settings},
        "rows": rows,
        "outcomes": {
            "o_w1_native_prepared_w0": [row["native_w0_timing"] for row in native_rows],
            "o_w1_target_ratio": 0.70,
            "sample_count": int(settings["repeats"]),
            "statistical_qualification": (
                "paired_p50_qualified_no_p95"
                if int(settings["repeats"]) >= 30
                else "diagnostic_only_requires_30_paired_samples"
            ),
            "mode_2_scalar_rust": "not_applicable_proxy_path_preserved",
            "all_fresh_gates_passed": all(bool(row["fresh_gate"]) for row in rows),
            "all_public_parity_passed": all(bool(row["parity"]) for row in rows),
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="one untimed public run per lane, then alternating fresh cache-cold lanes",
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
    lines = [
        "# NEXT-02 Fresh Public WFO Evidence",
        "",
        "All rows use the same public endpoint, candidate space, seed, calendar, account, retention and final stitched account.",
        "`w0_native_prepared_score` changes only the compatible fresh-account scorer; `w1_*` is a separate opt-in",
        "strategy-preparation protocol. Mode 2 retains its path/bootstrap proxy and has no scalar Rust row.",
        "",
        "| Mode | Schedule | W0 endpoint | W0 native score | Native/W0 p50 [CI95] | W1 native score |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in payload["rows"]:
        lanes = row["rows"]
        baseline = float(lanes["w0_endpoint"]["median_seconds"])
        native = lanes.get("w0_native_prepared_score")
        w1_native = lanes.get("w1_native_prepared_score")
        timing = row.get("native_w0_timing")
        ratio = "N/A"
        if isinstance(timing, Mapping):
            ci = timing["ratio_ci95"]
            ratio = f"{float(timing['ratio_p50']):.3f} [{float(ci[0]):.3f}, {float(ci[1]):.3f}]"
        lines.append(
            "| `{mode}` | `{schedule}` | {base:.4f} s | {native_seconds} | {ratio} | {w1_seconds} |".format(
                mode=row["mode"],
                schedule=row["optimization_schedule"],
                base=baseline,
                native_seconds=(f"{float(native['median_seconds']):.4f} s" if native else "N/A (proxy)"),
                ratio=ratio,
                w1_seconds=(f"{float(w1_native['median_seconds']):.4f} s" if w1_native else "N/A (proxy)"),
            )
        )
    outcome = payload["outcomes"]
    lines.extend(
        (
            "",
            f"- Fresh cache/reused-prefix gates: `{outcome['all_fresh_gates_passed']}`.",
            f"- Selection and final-account parity: `{outcome['all_public_parity_passed']}`.",
            f"- Samples per paired lane: `{outcome['sample_count']}` (`{outcome['statistical_qualification']}`).",
            "- This artifact reports Rust prepared scoring and W1 projection separately from arbitrary Python alpha computation.",
            "  It does not claim a native speedup for user feature generation or Mode 2 bootstrap logic.",
            "",
        )
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILE_SPECS), default="smoke")
    parser.add_argument("--mode", action="append", choices=sorted({spec.mode for spec in MODE_SPECS}))
    parser.add_argument("--schedule", action="append", choices=sorted({spec.schedule for spec in MODE_SPECS}))
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = run(profile=args.profile, modes=args.mode, schedules=args.schedule, repeats=args.repeats)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["outcomes"]["all_fresh_gates_passed"] and payload["outcomes"]["all_public_parity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
