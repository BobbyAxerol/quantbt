#!/usr/bin/env python3
"""Certify the strict nested-causal Mode 1 walk-forward contract.

This deterministic release audit has two independent layers:

1. A controlled WalkForwardEngine oracle proves that every inner OOS used by
   Mode 1 decay selection is contained in its outer IS window. It also checks
   completed-prefix invariance after future data is appended.
2. The public QuantBTEndpoint route compares prepared and reference execution
   byte-for-byte for the stitched account result.

It intentionally cannot prove that arbitrary user strategy code has no
look-ahead. A strategy remains responsible for constructing causal indicators.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

import quantbt
from quantbt import QuantBTEndpoint
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine


AUDIT_SCHEMA = "quantbt-phase50-nested-causal-audit-v1"


def _frame(end: str) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", end, freq="1D", tz="UTC")
    phase = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 0.03 * phase + np.sin(phase / 11.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0 + phase,
        },
        index=index,
    )


def _nested_config(**overrides: Any) -> WalkForwardConfig:
    values: dict[str, Any] = {
        "split_mode": "2021-01-01",
        "split_frequency": "quarterly",
        "window_mode": "rolling",
        "train_window": "180D",
        "optimization_mode": "mode_1_decay",
        "optimization_schedule": "per_fold_causal",
        "candidate_selection_metric": "robust_decay",
        "inner_split_frequency": "monthly",
        "inner_window_mode": "rolling",
        "inner_train_window": "60D",
        "inner_min_folds": 2,
        "optuna_trials": 4,
        "random_seed": 71,
        "top_is_fraction": 1.0,
        "scoring_backend": "endpoint",
    }
    values.update(overrides)
    return WalkForwardConfig(**values)


def _oracle_strategy(call_log: list[dict[str, Any]]):
    def build(data, params, train_index, test_index, fold):
        visible_end = pd.Timestamp(data.index[-1])
        requested_end = pd.Timestamp(test_index[-1])
        if visible_end > requested_end:
            raise AssertionError(
                "strategy received market data after its requested scoring horizon"
            )
        call_log.append(
            {
                "fold_id": int(fold.fold_id),
                "visible_end": visible_end,
                "train_end": pd.Timestamp(train_index[-1]),
                "requested_end": requested_end,
            }
        )
        return pd.Series(float(params["side"]), index=test_index)

    return build


def _oracle_scorer(data, output, index, fold, params, context, trading_days):
    del output, fold, trading_days
    if pd.Timestamp(data.index[-1]) > pd.Timestamp(index[-1]):
        raise AssertionError("scorer received future market data")

    side = int(params["side"])
    if context == "out-of-sample scoring":
        sharpe = 2.0 if side == 1 else -1.0
    elif context == "post-selection outer OOS realization":
        sharpe = 1.25 if side == 1 else -1.25
    else:
        sharpe = 1.0 if side == 1 else 0.5
    return {
        "sharpe": sharpe,
        "turnover": 100.0,
        "trade_count": 100.0,
        "mean_return": 0.0,
        "volatility": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": 1.0,
    }


def _run_oracle(end: str):
    calls: list[dict[str, Any]] = []
    result = WalkForwardEngine(
        strategy=_oracle_strategy(calls),
        scorer=_oracle_scorer,
        config=_nested_config(),
    ).run(data=_frame(end), param_ranges={"side": [0, 1]})
    return result, calls


def _endpoint_strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    return pd.Series(float(params["side"]), index=test_index)


def _run_endpoint(*, prepared: bool):
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_endpoint_strategy,
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_schedule="per_fold_causal",
        optimization_config={
            "candidate_selection_metric": "robust_decay",
            "inner_split_frequency": "monthly",
            "inner_window_mode": "rolling",
            "inner_train_window": "60D",
            "inner_min_folds": 2,
            "top_is_fraction": 1.0,
            "scoring_backend": "proxy",
            "use_prepared_scoring_cache": prepared,
            "use_prepared_wfo_context": prepared,
            "use_scalar_trial_scoring": prepared,
            "compact_trial_ledger": prepared,
        },
        optuna_trials=2,
        random_seed=79,
        initial_capital=20_000.0,
        leverage=2.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=False,
    )
    result = endpoint.backtest(
        data=_frame("2021-06-30"),
        symbols=["BTC"],
        param_ranges={"side": [1]},
    )
    return result


def _timestamps(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, str]]:
    records = frame.loc[:, columns].copy()
    for column in columns:
        records[column] = pd.to_datetime(records[column], utc=True).astype(str)
    return records.to_dict(orient="records")


def _assert_fail_closed() -> str:
    try:
        WalkForwardEngine(
            strategy=_oracle_strategy([]),
            scorer=_oracle_scorer,
            config=_nested_config(inner_train_window="360D"),
        ).run(data=_frame("2021-06-30"), param_ranges={"side": [0, 1]})
    except ValueError as exc:
        if "no room for an inner OOS window" not in str(exc):
            raise AssertionError(f"unexpected fail-closed error: {exc}") from exc
        return str(exc)
    raise AssertionError("insufficient inner history did not fail closed")


def _assert_global_metadata() -> dict[str, str]:
    def global_strategy(data, params, train_index, test_index, fold):
        # Global is deliberately retrospective. This compatibility check probes
        # its metadata only and must not impose the causal strategy contract.
        del data, train_index, fold
        return pd.Series(float(params["side"]), index=test_index)

    def global_scorer(data, output, index, fold, params, context, trading_days):
        del data, output, index, fold, params, context, trading_days
        return {
            "sharpe": 1.0,
            "turnover": 0.0,
            "trade_count": 0.0,
            "mean_return": 0.0,
            "volatility": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": 1.0,
        }

    result = WalkForwardEngine(
        strategy=global_strategy,
        scorer=global_scorer,
        config=WalkForwardConfig(
            split_mode="2021-01-01",
            split_frequency="single",
            optimization_mode="mode_4_is_only_robust",
            candidate_selection_metric="is_only_robust",
            scoring_backend="endpoint",
        ),
    ).run(data=_frame("2021-06-30"), params={"side": 1})
    metadata = result.metadata
    if metadata["validation_claim"] != "walk_forward_oos":
        raise AssertionError("legacy global validation claim changed")
    if metadata["chronological_validation_claim"] != "not_causal_multi_fold_global_calibration":
        raise AssertionError("global chronological claim is missing or incorrect")
    return {
        "validation_claim": metadata["validation_claim"],
        "chronological_validation_claim": metadata["chronological_validation_claim"],
    }


def run_audit(*, expect_installed: bool = False) -> dict[str, Any]:
    """Run deterministic causal-boundary and public endpoint parity checks."""
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:  # pragma: no cover - optimization is a declared test extra
        pass
    module_path = Path(quantbt.__file__).resolve()
    if expect_installed and "site-packages" not in module_path.parts:
        raise AssertionError(f"expected an installed package, imported {module_path}")

    short, short_calls = _run_oracle("2021-06-30")
    extended, _ = _run_oracle("2021-09-30")
    short_metadata = short.metadata
    inner = short_metadata["inner_fold_table"]
    selection = short_metadata["fold_selection_table"]

    if short_metadata["validation_claim"] != "strict_nested_fold_local_retraining":
        raise AssertionError("strict nested Mode 1 validation claim is missing")
    if short_metadata["chronological_validation_claim"] != "strict_outer_oos_after_frozen_selection":
        raise AssertionError("strict outer-OOS chronological claim is missing")
    if short_metadata["oos_used_for_selection"]:
        raise AssertionError("outer OOS was marked as selection input")
    if inner.empty or selection.empty:
        raise AssertionError("nested audit tables must not be empty")
    if not bool((inner["inner_test_end"] <= inner["outer_train_end"]).all()):
        raise AssertionError("an inner OOS interval escaped its outer IS window")
    if not bool((inner["outer_test_start"] > inner["inner_test_end"]).all()):
        raise AssertionError("an outer OOS interval overlaps an inner OOS interval")
    if bool(selection["outer_oos_used_for_selection"].any()):
        raise AssertionError("outer OOS entered the fold-level selection ledger")
    if not all(call["visible_end"] <= call["requested_end"] for call in short_calls):
        raise AssertionError("strategy received data beyond a requested evaluation horizon")

    completed_fold_count = len(short.folds)
    short_params = short_metadata["params_by_fold"]
    extended_params = {
        fold_id: params
        for fold_id, params in extended.metadata["params_by_fold"].items()
        if fold_id < completed_fold_count
    }
    if extended_params != short_params:
        raise AssertionError("appending future data changed completed-fold parameters")
    prefix_end = short.folds[-1].test_end
    pd.testing.assert_series_equal(
        short.oos_output.loc[short.folds[0].test_start : prefix_end],
        extended.oos_output.loc[short.folds[0].test_start : prefix_end],
    )

    reference = _run_endpoint(prepared=False)
    prepared = _run_endpoint(prepared=True)
    pd.testing.assert_series_equal(reference.equity, prepared.equity)
    pd.testing.assert_frame_equal(reference.positions, prepared.positions)
    reference_wf = reference.metadata["walk_forward"]
    prepared_wf = prepared.metadata["walk_forward"]
    if reference_wf["params_by_fold"] != prepared_wf["params_by_fold"]:
        raise AssertionError("prepared context changed selected fold parameters")
    if not reference_wf["inner_fold_table"].equals(prepared_wf["inner_fold_table"]):
        raise AssertionError("prepared context changed nested-fold boundaries")

    fail_closed_error = _assert_fail_closed()
    global_claim = _assert_global_metadata()
    return {
        "schema": AUDIT_SCHEMA,
        "passed": True,
        "quantbt_version": quantbt.__version__,
        "quantbt_module": str(module_path),
        "scope": "single-symbol deterministic Mode 1 walk-forward certification",
        "limitations": [
            "The audit proves engine data boundaries and accounting parity, not causal indicator construction inside arbitrary user strategy code."
        ],
        "checks": {
            "strict_nested_claim": short_metadata["validation_claim"],
            "chronological_validation_claim": short_metadata["chronological_validation_claim"],
            "outer_oos_used_for_selection": bool(short_metadata["oos_used_for_selection"]),
            "inner_fold_count": int(len(inner)),
            "outer_fold_count": int(len(short.folds)),
            "inner_boundaries": _timestamps(
                inner,
                ["outer_train_end", "inner_test_end", "outer_test_start"],
            ),
            "prefix_invariance": True,
            "prepared_reference_equity_max_abs_diff": float(
                np.max(np.abs(reference.equity.to_numpy() - prepared.equity.to_numpy()))
            ),
            "prepared_reference_positions_max_abs_diff": float(
                np.max(
                    np.abs(
                        reference.positions.to_numpy(dtype=float)
                        - prepared.positions.to_numpy(dtype=float)
                    )
                )
            ),
            "prepared_reference_params_equal": True,
            "prepared_reference_inner_folds_equal": True,
            "fail_closed_error": fail_closed_error,
            "global_compatibility": global_claim,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/quantbt-phase50-wfo-causal-audit.json"),
        help="JSON audit destination (default: /tmp/quantbt-phase50-wfo-causal-audit.json)",
    )
    parser.add_argument(
        "--expect-installed",
        action="store_true",
        help="fail unless quantbt resolves from a site-packages installation",
    )
    args = parser.parse_args(argv)
    try:
        report = run_audit(expect_installed=bool(args.expect_installed))
    except Exception as exc:
        print(f"Phase 50 causal WFO audit: FAIL: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checks = report["checks"]
    print("Phase 50 causal WFO audit: PASS")
    print(f"  package: {report['quantbt_version']} ({report['quantbt_module']})")
    print(
        "  nested folds: "
        f"{checks['inner_fold_count']} inner across {checks['outer_fold_count']} outer folds"
    )
    print(
        "  prepared/reference max diff: "
        f"equity={checks['prepared_reference_equity_max_abs_diff']:.1f}, "
        f"positions={checks['prepared_reference_positions_max_abs_diff']:.1f}"
    )
    print(f"  audit JSON: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
