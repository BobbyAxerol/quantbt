from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    ExecutionConfig,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    NativePortfolioBackend,
    NativePortfolioConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    PackageExecutionKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
)


def test_native_vectorized_prepared_signal_notional_matches_normal_run_and_rejects_stale_signature():
    idx = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.linspace(0.0, 2.0, len(idx))), index=idx)
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.5, 0.5, 0.0, 0.0], index=idx)
    closes = {"BTC": close}
    highs = {"BTC": close * 1.002}
    lows = {"BTC": close * 0.998}
    positions = {"BTC": signal}
    backend = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=4.0),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )

    normal = backend.run_signals(
        idx,
        positions,
        closes,
        highs=highs,
        lows=lows,
        symbols=["BTC"],
        alloc_per_trade=5_000.0,
        hedge_type="signal_notional",
    )
    market = backend.prepare_market_arrays(idx, closes=closes, highs=highs, lows=lows, symbols=["BTC"])
    prepared = backend.run_signals(
        idx,
        positions,
        closes,
        highs=highs,
        lows=lows,
        symbols=["BTC"],
        alloc_per_trade=5_000.0,
        hedge_type="signal_notional",
        market_arrays=market,
    )

    np.testing.assert_allclose(prepared.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(prepared.positions.to_numpy(), normal.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(prepared.fees.to_numpy(), normal.fees.to_numpy(), rtol=0.0, atol=1e-12)

    with pytest.raises(ValueError, match="prepared market arrays"):
        backend.run_signals(
            idx[:-1],
            {"BTC": signal.iloc[:-1]},
            closes,
            highs=highs,
            lows=lows,
            symbols=["BTC"],
            alloc_per_trade=5_000.0,
            hedge_type="signal_notional",
            market_arrays=market,
        )


def test_native_portfolio_report_levels_preserve_accounting_core_and_keep_full_default_audit():
    idx, positions, closes = _portfolio_fixture()
    backend = NativePortfolioBackend(
        NativePortfolioConfig(
            account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )

    kwargs = dict(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        symbols=list(positions),
        mode="market_neutral",
        hedge_type="notional",
        alloc_per_trade={"BTC": 2_000.0, "ETH": 2_000.0},
        use_pyramiding=True,
        funding_rate=0.0,
    )
    full = backend.run_signals(**kwargs)
    standard = backend.run_signals(**kwargs, report_level="standard")
    minimal = backend.run_signals(**kwargs, report_level="minimal")

    for result in (standard, minimal):
        np.testing.assert_allclose(result.equity.to_numpy(), full.equity.to_numpy(), rtol=0.0, atol=1e-10)
        np.testing.assert_allclose(result.returns.to_numpy(), full.returns.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(result.positions.to_numpy(), full.positions.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(result.fees.to_numpy(), full.fees.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(result.funding.to_numpy(), full.funding.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(result.margin.to_numpy(), full.margin.to_numpy(), rtol=0.0, atol=1e-10)

    assert full.metadata["report_level"] == "full"
    assert full.metadata["portfolio_contract_report"]["passed"] is True
    assert "rebalance_report" in full.metadata
    assert standard.metadata["report_level"] == "standard"
    assert standard.metadata["portfolio_contract_report"]["passed"] is True
    assert "symbol_pnl_report" in standard.metadata
    assert "rebalance_report" not in standard.metadata
    assert minimal.metadata["report_level"] == "minimal"
    assert minimal.metadata["portfolio_contract_report"]["status"] == "skipped"
    assert "symbol_pnl_report" not in minimal.metadata
    assert "accepted_units_report" in minimal.metadata


def test_walkforward_single_symbol_endpoint_scoring_reuses_prepared_vectorized_market_arrays_without_metric_drift():
    idx = pd.date_range("2021-01-01", "2022-03-31", freq="1D", tz="UTC")
    close = 100.0 + np.cumsum(np.sin(np.linspace(0.0, 8.0, len(idx))) * 0.05)
    data = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )

    def strategy(data, params, train_index, test_index, fold):
        threshold = float(params["threshold"])
        ret = data.loc[: test_index[-1], "close"].pct_change().fillna(0.0)
        signal = np.where(ret > threshold / 10_000.0, 1.0, np.where(ret < -threshold / 10_000.0, -1.0, 0.0))
        return pd.Series(signal, index=ret.index).reindex(test_index).fillna(0.0)

    def run(use_cache: bool):
        endpoint = QuantBTEndpoint.train_test_split(
            strategy_class=strategy,
            test_start="2022-01-01",
            target_mode="signal_notional",
            backend="native_vectorized",
            optimization_mode="mode_1_decay",
            optimization_config={
                "scoring_backend": "endpoint",
                "use_prepared_scoring_cache": use_cache,
            },
            optuna_trials=6,
            random_seed=77,
            initial_capital=20_000.0,
            leverage=3.0,
            alloc_per_trade=5_000.0,
            fee_rate=0.0001,
            use_funding=False,
            use_pyramiding=False,
        )
        return endpoint.backtest(data=data, param_ranges={"threshold": (0.2, 1.0, 0.2)})

    cached = run(True)
    uncached = run(False)
    cached_wf = cached.metadata["walk_forward"]
    uncached_wf = uncached.metadata["walk_forward"]
    cache_meta = cached_wf["prepared_scoring_cache"]

    assert cached_wf["params"] == uncached_wf["params"]
    assert cached_wf["best_trial"]["objective"] == pytest.approx(uncached_wf["best_trial"]["objective"])
    assert cached.equity.iloc[-1] == pytest.approx(uncached.equity.iloc[-1])
    assert cache_meta["available"] is True
    assert cache_meta["prepared_runs"] > 0
    assert cache_meta["market_cache_misses"] > 0
    assert uncached_wf["prepared_scoring_cache"]["prepared_runs"] == 0


def test_native_event_basis_arbitrage_accepts_prepared_market_arrays_with_equity_parity():
    idx = pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC")
    perp = pd.Series(100.0 + np.sin(np.linspace(0.0, 3.0, len(idx))), index=idx)
    quarterly = pd.Series(perp.to_numpy() + 1.0 + np.cos(np.linspace(0.0, 2.0, len(idx))) * 0.25, index=idx)
    closes = {"PERP": perp, "QUARTERLY": quarterly}
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0], index=idx)
    spec = BasisArbitrageSpec(
        arb_id="PHASE14C_BASIS",
        legs=(
            ArbitrageLeg("PERP", 1.0, role="perp", contract_type=ContractType.LINEAR, funding_enabled=True),
            ArbitrageLeg("QUARTERLY", -1.0, role="quarterly", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=5_000.0,
            reference_symbol="PERP",
        ),
        execution_policy=ArbExecutionPolicy(PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )
    funding = {"PERP": pd.Series(0.00005, index=idx), "QUARTERLY": 0.0}
    backend = NativeEventBackend(
        NativeEventConfig(account=AccountConfig(initial_capital=50_000.0, leverage=5.0), fee_rate=0.0001, use_funding=True)
    )

    normal = backend.run_basis_arbitrage(idx, spec, signal, closes, funding_rate=funding)
    market = backend.prepare_market_arrays(idx, closes=closes, highs=closes, lows=closes, funding_rate=funding, symbols=list(closes))
    prepared = backend.run_basis_arbitrage(idx, spec, signal, closes, funding_rate=funding, market_arrays=market)

    np.testing.assert_allclose(prepared.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(prepared.positions.to_numpy(), normal.positions.to_numpy(), rtol=0.0, atol=1e-12)
    assert prepared.metadata["package_pnl_report"].equals(normal.metadata["package_pnl_report"])

    with pytest.raises(ValueError, match="prepared market arrays"):
        backend.run_basis_arbitrage(idx[:-1], spec, signal.iloc[:-1], closes, funding_rate=funding, market_arrays=market)


def _portfolio_fixture():
    idx = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -1.0, -1.0, 0.0, 1.0, 1.0, 0.0, 0.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 101.0, 102.0, 101.5, 100.5, 99.0, 100.0, 101.0], index=idx),
        "ETH": pd.Series([50.0, 49.5, 49.0, 50.0, 51.0, 52.0, 51.0, 50.5], index=idx),
    }
    return idx, positions, closes
