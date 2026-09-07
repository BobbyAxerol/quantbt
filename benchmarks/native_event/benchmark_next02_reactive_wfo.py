#!/usr/bin/env python3
"""Fresh public reactive-WFO evidence for NEXT-02.

The comparison is deliberately narrow and honest.  Both lanes call the public
``QuantBTEndpoint.prepare_reactive_walk_forward(...)`` facade with the same
market, scalar reactive strategy, Optuna seed, fold construction, reset-flat
account contract, retention and search space.  The only changed control is the
public ``ReactiveWfoRuntimeConfigV1.preparation_policy``:

* ``compatibility`` is B1: validated historical per-task descriptor creation;
* ``prepared`` is B2: run-local exact fold/window/shard preparation.

This is a fresh-study measurement.  A new endpoint and runtime are built for
every timed sample, completed-result reuse is absent, and no cache-hit/resume
result is presented as throughput.  It measures the normal scalar W3 callback
protocol, not the distinct R3B adaptive-batch protocol.  Mode 2 remains
explicitly unsupported by reactive WFO because its return-path bootstrap proxy
is not an order-lifecycle evaluation contract.
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

from quantbt import (  # noqa: E402
    ExecutionConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.backends import ReactiveWfoRuntimeConfigV1  # noqa: E402
from quantbt.strategies import STRICT_CAUSAL_CACHE_CONTRACT_V1  # noqa: E402
from quantbt.walkforward import WalkForwardConfig  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, typed_array_sha256  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/next02_reactive_wfo.json"
SCHEMA = "quantbt-next02-reactive-wfo-v1"


@dataclass(frozen=True, slots=True)
class _ModeSpec:
    mode: str
    schedule: str
    selector: str


MODE_SPECS: tuple[_ModeSpec, ...] = (
    _ModeSpec("mode_1_decay", "global", "robust_decay"),
    _ModeSpec("mode_1_decay", "per_fold_decay", "robust_decay"),
    _ModeSpec("mode_1_decay", "per_fold_causal", "robust_decay"),
    _ModeSpec("mode_3_flat_minima", "global", "is_plateau_robust"),
    _ModeSpec("mode_4_is_only_robust", "per_fold_causal", "is_only_robust"),
    _ModeSpec("mode_5_full_robust", "global", "full_robust"),
)

PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "smoke": {
        "bars": 2_000,
        "frequency": "1D",
        "split_bar": 720,
        "train_window": "365D",
        "trials": 4,
        "repeats": 3,
        "is_subperiods": 4,
        "split_frequency": "quarterly",
        "window_mode": "rolling",
    },
    "standard": {
        "bars": 4_000,
        "frequency": "1D",
        "split_bar": 1_440,
        "train_window": "730D",
        "trials": 12,
        "repeats": 7,
        "is_subperiods": 6,
        "split_frequency": "semi_yearly",
        "window_mode": "rolling",
    },
}


REQUIREMENTS = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="none",
    context_mode="numeric",
)


def _rss_pss_mb() -> dict[str, float]:
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
    close = 100.0 + 0.045 * phase + 3.4 * np.sin(phase / 19.0) + 0.6 * np.cos(phase / 7.0)
    open_ = np.r_[close[0], close[:-1]] + 0.1 * np.cos(phase / 5.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.85,
            "low": np.minimum(open_, close) - 0.85,
            "close": close,
            "volume": 1_000.0 + phase,
            "funding_rate": np.where((phase.astype(np.int64) % 8) == 0, 0.0001, -0.00005),
        },
        index=index,
    )


class _ScalarTaskStrategy:
    """A normal R1 scalar callback with two deterministic market commands."""

    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, *, task, params: Mapping[str, Any]) -> None:
        self.task = task
        self.params = dict(params)
        self.call_count = 0

    def reset(self, *, seed: int, task) -> None:
        assert int(seed) == int(task.seed)
        self.task = task
        self.call_count = 0

    def on_bar_close(self, context, out) -> None:
        self.call_count += 1
        bar = int(context.bar_index)
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
        return (
            str(self.task.candidate_id),
            int(self.task.fold_id),
            int(self.task.start_bar),
            int(self.task.end_bar),
            int(self.call_count),
        )


class _PreparedScalarStrategy:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def build_strategy(self, *, params, task):
        return _ScalarTaskStrategy(task=task, params=params)

    def close(self) -> None:
        return None


class _ScalarFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-reactive-wfo-static-v1"
        assert len(data) > 0
        assert len(folds) > 0
        return _PreparedScalarStrategy()


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


def _walkforward_config(data: pd.DataFrame, *, spec: _ModeSpec, profile: Mapping[str, Any]) -> WalkForwardConfig:
    values: dict[str, Any] = {
        "split_mode": str(data.index[int(profile["split_bar"])].date()),
        "split_frequency": str(profile["split_frequency"]),
        "window_mode": str(profile["window_mode"]),
        "train_window": str(profile["train_window"]),
        "min_train_bars": 180,
        "min_test_bars": 60,
        "target_mode": "signal_notional",
        "optimization_mode": spec.mode,
        "optimization_schedule": spec.schedule,
        "fold_boundary_position_policy": "reset_flat",
        "fold_account_policy": "reset_flat",
        "optuna_trials": int(profile["trials"]),
        "optuna_early_stopping": None,
        "random_seed": 731,
        "candidate_selection_metric": spec.selector,
        "top_is_fraction": 0.50,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "is_subperiods": int(profile["is_subperiods"]),
        "scoring_trading_days": 365,
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
        "metadata": {
            "wfo_execution_reuse": "off",
            "fresh_study_measurement": True,
        },
    }
    if spec.schedule == "per_fold_causal" and spec.mode == "mode_1_decay":
        values.update(
            {
                "inner_split_frequency": "quarterly",
                "inner_window_mode": "rolling",
                # The nested plan inherits min_train_bars=180. Keep the
                # rolling descriptor long enough to satisfy that certified
                # causal contract rather than weakening the fixture gate.
                "inner_train_window": "180D",
                "inner_min_folds": 2,
            }
        )
    return WalkForwardConfig(**values)


def _assert_result_parity(reference, observed) -> None:
    assert reference.params == observed.params
    assert reference.params_by_fold == observed.params_by_fold
    assert reference.best_trial == observed.best_trial
    pd.testing.assert_frame_equal(reference.trial_table, observed.trial_table, check_exact=True)
    pd.testing.assert_frame_equal(reference.candidate_table, observed.candidate_table, check_exact=True)
    pd.testing.assert_frame_equal(reference.fold_table, observed.fold_table, check_exact=True)
    assert len(reference.fold_results) == len(observed.fold_results)
    for left, right in zip(reference.fold_results, observed.fold_results, strict=True):
        assert left.task == right.task
        assert left.strategy_state_fingerprint == right.strategy_state_fingerprint
        for field in ("equity", "fees", "funding", "positions"):
            np.testing.assert_allclose(
                getattr(left.result, field).to_numpy(dtype=np.float64),
                getattr(right.result, field).to_numpy(dtype=np.float64),
                rtol=0.0,
                atol=1.0e-10,
            )


def _run_public(
    data: pd.DataFrame,
    *,
    spec: _ModeSpec,
    profile: Mapping[str, Any],
    preparation_policy: str,
) -> tuple[Any, float]:
    endpoint = _endpoint(data)
    runtime = endpoint.prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_ScalarFactory(),
        walkforward_config=_walkforward_config(data, spec=spec, profile=profile),
        runtime_config=ReactiveWfoRuntimeConfigV1(
            worker_mode="inprocess",
            optimizer_schedule="certified_sequential_v1",
            preparation_policy=preparation_policy,
        ),
        symbols=["BTCUSDT"],
    )
    try:
        started = perf_counter()
        result = runtime.backtest(
            param_ranges={
                "direction": [-1.0, 1.0],
                "quantity": [0.10, 0.18, 0.26, 0.34],
            }
        )
        return result, float(perf_counter() - started)
    finally:
        runtime.close()


def _snapshot(result, *, seconds: float) -> dict[str, Any]:
    metadata = result.metadata
    runtime = dict(metadata["runtime"])
    preparation = dict(metadata["wfo_preparation"])
    scalar = dict(runtime["scalar_sessions"])
    if preparation["policy"] == "prepared":
        if not preparation["enabled"]:
            raise AssertionError("prepared reactive WFO policy did not enable run-local preparation")
    elif preparation["policy"] == "compatibility":
        if preparation["enabled"]:
            raise AssertionError("compatibility reactive WFO policy unexpectedly used prepared descriptors")
    else:  # pragma: no cover - provenance contract assertion
        raise AssertionError(f"unexpected reactive WFO preparation policy: {preparation['policy']!r}")
    return {
        "seconds": float(seconds),
        "score_calls": int(runtime["score_calls"]),
        "score_bars": int(runtime["score_bars"]),
        "score_seconds": float(runtime["score_seconds"]),
        "python_callback_calls": int(scalar.get("python_callback_calls", 0)),
        "native_sessions_created": int(scalar.get("sessions_created", 0)),
        "preparation": preparation,
        "fresh_gate": {
            "fresh_endpoint_per_sample": True,
            "fresh_runtime_per_sample": True,
            "completed_result_reuse": "off_by_contract",
            "reused_prefix_bars": 0,
        },
    }


def _median_snapshot(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    return {
        "median_seconds": float(median(float(row["seconds"]) for row in rows)),
        "median_score_seconds": float(median(float(row["score_seconds"]) for row in rows)),
        "median_score_calls": int(median(int(row["score_calls"]) for row in rows)),
        "median_score_bars": int(median(int(row["score_bars"]) for row in rows)),
        "median_python_callback_calls": int(median(int(row["python_callback_calls"]) for row in rows)),
        "preparation": dict(first["preparation"]),
        "fresh_gate": {
            "all_fresh_endpoints": all(bool(row["fresh_gate"]["fresh_endpoint_per_sample"]) for row in rows),
            "all_fresh_runtimes": all(bool(row["fresh_gate"]["fresh_runtime_per_sample"]) for row in rows),
            "all_reused_prefix_bars_zero": all(int(row["fresh_gate"]["reused_prefix_bars"]) == 0 for row in rows),
        },
    }


def _paired_ratio_summary(
    baseline: Sequence[Mapping[str, Any]],
    observed: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> dict[str, Any]:
    if len(baseline) != len(observed) or not baseline:
        raise ValueError("paired timing rows must be non-empty and have equal length")
    ratios = np.asarray(
        [float(right["seconds"]) / float(left["seconds"]) for left, right in zip(baseline, observed)],
        dtype=np.float64,
    )
    if not np.isfinite(ratios).all() or np.any(ratios <= 0.0):
        raise ValueError("paired timing ratios must be finite and positive")
    generator = np.random.default_rng(int(seed))
    draws = generator.integers(0, len(ratios), size=(4_000, len(ratios)))
    medians = np.median(ratios[draws], axis=1)
    return {
        "paired_samples": int(len(ratios)),
        "ratio_p50": float(np.median(ratios)),
        "ratio_ci95": [float(np.quantile(medians, 0.025)), float(np.quantile(medians, 0.975))],
        "p95_status": "not_claimed_requires_100_paired_samples",
        "qualification": (
            "paired_p50_qualified" if len(ratios) >= 30 else "diagnostic_only_requires_30_paired_samples"
        ),
    }


def _measure_mode(data: pd.DataFrame, *, spec: _ModeSpec, profile: Mapping[str, Any]) -> dict[str, Any]:
    policies = ("compatibility", "prepared")
    warm: dict[str, Any] = {}
    for policy in policies:
        result, _ = _run_public(data, spec=spec, profile=profile, preparation_policy=policy)
        warm[policy] = result
        _assert_result_parity(warm["compatibility"], result)

    samples: dict[str, list[dict[str, Any]]] = {policy: [] for policy in policies}
    memory_samples: list[dict[str, Any]] = []
    for repeat in range(int(profile["repeats"])):
        gc.collect()
        before = _rss_pss_mb()
        order = policies if repeat % 2 == 0 else tuple(reversed(policies))
        after: dict[str, dict[str, float]] = {}
        for policy in order:
            result, seconds = _run_public(data, spec=spec, profile=profile, preparation_policy=policy)
            _assert_result_parity(warm["compatibility"], result)
            samples[policy].append(_snapshot(result, seconds=seconds))
            after[policy] = _rss_pss_mb()
        memory_samples.append({"order": order, "before_mb": before, "after_mb": after})

    return {
        "mode": spec.mode,
        "optimization_schedule": spec.schedule,
        "rows": {policy: _median_snapshot(rows) for policy, rows in samples.items()},
        "timing": _paired_ratio_summary(
            samples["compatibility"],
            samples["prepared"],
            seed=9_103 + len(spec.mode) + len(spec.schedule),
        ),
        "fresh_gate": all(
            bool(row["fresh_gate"]["all_fresh_endpoints"])
            and bool(row["fresh_gate"]["all_fresh_runtimes"])
            and bool(row["fresh_gate"]["all_reused_prefix_bars_zero"])
            for row in (_median_snapshot(samples[policy]) for policy in policies)
        ),
        "parity": True,
        "memory_samples": memory_samples,
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
        raise RuntimeError("NEXT-02 reactive WFO benchmark requires the optimization extra") from exc
    settings = {**PROFILE_SPECS[profile]}
    if repeats is not None:
        if int(repeats) <= 0:
            raise ValueError("repeats must be positive")
        settings["repeats"] = int(repeats)
    wanted_modes = None if modes is None else frozenset(str(value) for value in modes)
    wanted_schedules = None if schedules is None else frozenset(str(value) for value in schedules)
    specs = tuple(
        spec
        for spec in MODE_SPECS
        if (wanted_modes is None or spec.mode in wanted_modes)
        and (wanted_schedules is None or spec.schedule in wanted_schedules)
    )
    if not specs:
        raise ValueError("no known NEXT-02 reactive WFO mode/schedule was selected")
    data = _market(int(settings["bars"]), frequency=str(settings["frequency"]))
    rows = [_measure_mode(data, spec=spec, profile=settings) for spec in specs]
    return {
        "schema": SCHEMA,
        "scope": (
            "fresh public W3 scalar reactive-WFO B1/B2 comparison; same strategy, market, seed, account, "
            "folds, selection, audit and reset-flat contract"
        ),
        "limitations": {
            "fixture": "deterministic economic command fixture; not a B0 product-alpha reproduction",
            "mode_2_sbb": "unsupported_no_return_path_proxy",
            "r3b": "separate_opt_in_sampling_contract_not_compared_here",
            "p95": "not_claimed_requires_100_paired_samples",
        },
        "profile": {"id": profile, **settings},
        "rows": rows,
        "outcomes": {
            "o_w2_target_ratio": 0.70,
            "paired_results": [row["timing"] for row in rows],
            "statistical_qualification": (
                "paired_p50_qualified_no_p95"
                if int(settings["repeats"]) >= 30
                else "diagnostic_only_requires_30_paired_samples"
            ),
            "all_fresh_gates_passed": all(bool(row["fresh_gate"]) for row in rows),
            "all_public_parity_passed": all(bool(row["parity"]) for row in rows),
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure=(
                "one untimed public run per policy, then alternating B1 compatibility/B2 prepared "
                "fresh endpoints and runtimes"
            ),
            data_sha256=typed_array_sha256(
                data.index.asi8,
                data[["open", "high", "low", "close", "volume", "funding_rate"]].to_numpy(dtype=np.float64),
            ),
            intent_sha256=typed_array_sha256(
                np.frombuffer(
                    "|".join(f"{spec.mode}:{spec.schedule}" for spec in specs).encode("utf-8"), dtype=np.uint8
                ),
            ),
        ),
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# NEXT-02 Fresh Public Reactive-WFO Evidence",
        "",
        "Every timing pair uses the same public W3 scalar strategy, market, seed, account, folds, selection and audit.",
        "B1 uses `preparation_policy=\"compatibility\"`; B2 uses `preparation_policy=\"prepared\"`.",
        "",
        "| Mode | Schedule | B1 compatibility | B2 prepared | B2/B1 p50 [CI95] |",
        "|---|---|---:|---:|---:|",
    ]
    for row in payload["rows"]:
        lanes = row["rows"]
        timing = row["timing"]
        ci = timing["ratio_ci95"]
        lines.append(
            "| `{mode}` | `{schedule}` | {baseline:.4f} s | {prepared:.4f} s | {ratio:.3f} [{low:.3f}, {high:.3f}] |".format(
                mode=row["mode"],
                schedule=row["optimization_schedule"],
                baseline=float(lanes["compatibility"]["median_seconds"]),
                prepared=float(lanes["prepared"]["median_seconds"]),
                ratio=float(timing["ratio_p50"]),
                low=float(ci[0]),
                high=float(ci[1]),
            )
        )
    outcomes = payload["outcomes"]
    lines.extend(
        (
            "",
            f"- Fresh gates: `{outcomes['all_fresh_gates_passed']}`.",
            f"- Public result/account parity: `{outcomes['all_public_parity_passed']}`.",
            f"- Samples per pair: `{payload['profile']['repeats']}` (`{outcomes['statistical_qualification']}`).",
            "- Mode 2 remains explicitly unsupported for W3; R3B is a separately versioned batch protocol.",
            "- This B1/B2 engineering comparison does not claim a legacy B0 product-alpha reproduction.",
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
