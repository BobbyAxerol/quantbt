"""Standalone installed-artifact consumer; run with python -I outside checkout."""

from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import importlib.metadata as metadata
import json
from pathlib import Path
import sys


def consume(*, core_version, native_version=None, optimization=True):
    import numpy as np
    import pandas as pd
    import quantbt
    from quantbt import QuantBTEndpoint

    origin = Path(quantbt.__file__).resolve()
    if "site-packages" not in origin.parts or "src" in origin.parts:
        raise AssertionError(f"not installed QuantBT: {origin}")
    assert metadata.version("quantbt-engine") == quantbt.__version__ == core_version
    index = pd.date_range("2020-01-01", periods=850, freq="1D", tz="UTC")
    t = np.arange(len(index), dtype=np.float64)
    close = 100 + 0.025 * t + 3 * np.sin(t / 13) + np.cos(t / 5)
    data = pd.DataFrame(
        dict(open=close, high=close + 1, low=close - 1, close=close, volume=1000 + t),
        index=index,
    )
    result = QuantBTEndpoint.pct_equity(
        initial_capital=20000, use_funding=False, target_runtime="numba"
    ).backtest(
        data=data, signal=pd.Series(np.sin(t / 13) > 0, index=index).astype(float)
    )
    assert len(result.equity) == len(index) and np.isfinite(result.equity).all()
    proof = {
        "python": sys.version,
        "core_version": core_version,
        "origin": str(origin),
        "fixed_account_rows": len(result.equity),
        "optimization": optimization,
    }
    if not optimization:
        assert "optuna" not in sys.modules
        assert "cmaes" not in sys.modules
        from quantbt.optimization.meta_selection.numerics import NumericRuntime

        auto = NumericRuntime(native_policy="auto")
        assert auto.metadata["requested_backend"] == "auto"
        proof["off_optional_dependencies_loaded"] = False
        return proof

    import optuna
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory
    from quantbt.optimization.meta_selection.numerics import NumericRuntime

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def strategy(data, params, train_index, test_index, fold):
        frame = data.loc[: test_index[-1]]
        return (
            (frame.close > frame.close.rolling(params["window"]).mean())
            .astype(float)
            .reindex(test_index)
            .fillna(0)
        )

    def endpoint(mode="off", prepared="off", policy="auto"):
        return QuantBTEndpoint.walk_forward(
            strategy_class=strategy,
            split_mode="2021-01-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            target_mode="signal_notional",
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_causal",
            optuna_trials=6,
            random_seed=731,
            optuna_early_stopping=None,
            initial_capital=20000,
            alloc_per_trade=1000,
            leverage=3,
            fee_rate=0.0005,
            use_funding=False,
            target_runtime="rust" if prepared != "off" else "numba",
            optimization_config=dict(
                scoring_backend="endpoint",
                use_scalar_trial_scoring=False,
                native_prepared_wfo=prepared,
                native_prepared_wfo_workers=1,
                wfo_execution_reuse="off",
                top_is_fraction=0.5,
                flat_eps=1,
                flat_min_samples=1,
                is_subperiods=3,
                scoring_trading_days=365,
                min_trades_per_year=100,
                trade_penalty_factor=0.5,
                meta_selection=dict(
                    mode=mode,
                    min_matured_origins=1,
                    label_observer=True,
                    native_batch_policy=policy,
                ),
            ),
        )

    off = endpoint().backtest(data=data, param_ranges={"window": (3, 31, 2)})

    def ctx():
        return MetaHistoryContext(
            MetaHistory(), "installed-sma", "SYNTHETICUSD", "1D", "qms08"
        )

    shadow = endpoint("shadow").backtest(
        data=data, param_ranges={"window": (3, 31, 2)}, meta_history=ctx()
    )
    np.testing.assert_array_equal(off.equity, shadow.equity)
    assert (
        off.metadata["walk_forward"]["params_by_fold"]
        == shadow.metadata["walk_forward"]["params_by_fold"]
    )
    auto = NumericRuntime(native_policy="auto")
    if native_version is None:
        assert auto.metadata["selected_backend_by_block"]["gram_solve"] == "numpy"
        try:
            NumericRuntime(native_policy="require")
        except ValueError:
            proof["missing_native_require_fails"] = True
        else:
            raise AssertionError("require silently fell back without native")
        proof["off_shadow_parity"] = True
        proof["auto_fallback"] = auto.metadata
        return proof

    import _quantbt_native as native
    from quantbt.core.product_contracts import (
        require_native_package_pair,
        validate_native_runtime_product_descriptor,
    )

    pair = require_native_package_pair(core_version, native.version())
    validate_native_runtime_product_descriptor(native.product_descriptor(), pair=pair)
    assert native.version() == metadata.version("quantbt-native") == native_version
    assert native.qms_numeric_descriptor_v1()["abi"] == "qms-numeric-v1"
    assert hasattr(native, "QMS_PREPARED_METRIC_SUPPORT_V1")
    assert "site-packages" in Path(native.__file__).resolve().parts
    x = np.arange(24, dtype=np.float64).reshape(8, 3) / 8
    y, weights = np.sin(np.arange(8)), np.ones(8)
    actual = NumericRuntime(native_policy="require").fit(x, y, weights, 10)
    expected = NumericRuntime(native_policy="reference").fit(x, y, weights, 10)
    for a, b in zip(actual, expected, strict=True):
        np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-10)
    prepared = endpoint("active", "require", "require").backtest(
        data=data, param_ranges={"window": (3, 31, 2)}, meta_history=ctx()
    )
    ref = endpoint("active", "off", "reference").backtest(
        data=data, param_ranges={"window": (3, 31, 2)}, meta_history=ctx()
    )
    wf, rwf = prepared.metadata["walk_forward"], ref.metadata["walk_forward"]
    assert wf["params_by_fold"] == rwf["params_by_fold"]
    np.testing.assert_allclose(prepared.equity, ref.equity, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(
        prepared.positions, ref.positions, rtol=1e-10, atol=1e-10
    )
    records = wf["meta_selection"]["records"]
    assert (
        wf["meta_selection"]["models"] and not wf["meta_selection"]["observer_failures"]
    )
    for row in records:
        assert row["selected_params"] == wf["params_by_fold"][row["fold_id"]]
        assert not row["current_outer_oos_used_for_selection"]
    assert any(
        r["numeric_backend"]["selected_backend_by_block"].get("gram_solve") == "rust"
        for r in records
    )
    studies = []
    for recipe in ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"):
        bt = endpoint()
        bt = QuantBTEndpoint(
            replace(
                bt.config,
                walkforward_config=replace(
                    bt.config.walkforward_config,
                    optuna_trials=4,
                    sampler_config={"name": recipe},
                ),
            )
        )
        sr = bt.backtest(data=data.iloc[:547], param_ranges={"window": (3, 31, 2)})
        assert sr.metadata["walk_forward"]["sampler_studies"]
        studies.append(recipe)
    proof.update(
        native_version=native_version,
        native_origin=native.__file__,
        descriptor=native.product_descriptor(),
        qms=native.qms_numeric_descriptor_v1(),
        prepared_metadata=wf["prepared_scoring_cache"],
        sampler_recipes=studies,
        off_shadow_parity=True,
        active_reference_prepared_parity=True,
        actual_meta_folds=len(records),
        equity_sha256=sha256(prepared.equity.to_numpy().tobytes()).hexdigest(),
        numeric_blocks=records[-1]["numeric_backend"],
        installed_dependencies={
            name: metadata.version(name)
            for name in ("numpy", "pandas", "numba", "optuna", "cmaes")
        },
    )
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-version", required=True)
    parser.add_argument("--native-version")
    parser.add_argument("--without-optimization", action="store_true")
    args = parser.parse_args()
    from quantbt.optimization.meta_selection.common import wire

    print(
        json.dumps(
            wire(
                consume(
                    core_version=args.core_version,
                    native_version=args.native_version,
                    optimization=not args.without_optimization,
                )
            ),
            sort_keys=True,
        )
    )
