from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import AccountConfig, PortfolioBacktestEngine, PortfolioDomainSpec, validate_portfolio_result_contract


def _daily_idx(n=5):
    return pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")


def _run(positions, closes, *, highs=None, lows=None, hedge_type="target_units", initial_capital=100_000.0, leverage=5.0, fee_rate=0.0, funding_rate=0.0, use_funding=False):
    idx = next(iter(closes.values())).index
    return PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=highs or closes,
        lows=lows or closes,
        datetime_index=idx,
        mode="longshort",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=initial_capital, leverage=leverage, maintenance_ratio=0.005),
        fee_rate=fee_rate,
        alloc_per_trade=1_000.0,
        contract_size=1.0,
        hedge_type=hedge_type,
        asset_type="crypto",
        use_funding=use_funding,
        funding_rate=funding_rate,
    ).result


def test_phase11c_flat_portfolio_stays_at_initial_equity():
    idx = _daily_idx()
    positions = {"BTC": pd.Series(0.0, index=idx), "ETH": pd.Series(0.0, index=idx)}
    closes = {
        "BTC": pd.Series([100.0, 110.0, 90.0, 120.0, 115.0], index=idx),
        "ETH": pd.Series([50.0, 45.0, 55.0, 60.0, 58.0], index=idx),
    }

    result = _run(positions, closes)

    np.testing.assert_allclose(result.equity.to_numpy(), 100_000.0)
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_phase11c_long_short_and_short_only_pnl_are_directionally_correct():
    idx = _daily_idx(4)
    closes = {
        "BTC": pd.Series([100.0, 100.0, 110.0, 120.0], index=idx),
        "ETH": pd.Series([50.0, 50.0, 45.0, 40.0], index=idx),
    }
    long_only = _run({"BTC": pd.Series([0.0, 1.0, 1.0, 0.0], index=idx), "ETH": pd.Series(0.0, index=idx)}, closes)
    short_only = _run({"BTC": pd.Series(0.0, index=idx), "ETH": pd.Series([0.0, -1.0, -1.0, 0.0], index=idx)}, closes)
    long_short = _run({"BTC": pd.Series([0.0, 1.0, 1.0, 0.0], index=idx), "ETH": pd.Series([0.0, -1.0, -1.0, 0.0], index=idx)}, closes)

    assert long_only.equity.iloc[2] > long_only.initial_capital
    assert short_only.equity.iloc[2] > short_only.initial_capital
    np.testing.assert_allclose(
        long_short.equity.iloc[2] - long_short.initial_capital,
        (long_only.equity.iloc[2] - long_only.initial_capital) + (short_only.equity.iloc[2] - short_only.initial_capital),
    )


def test_phase11c_missing_data_alignment_does_not_create_nan_reports():
    idx = _daily_idx(5)
    positions = {"BTC": pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx)}
    closes = {"BTC": pd.Series([100.0, 100.0, np.nan, 110.0, 105.0], index=idx)}

    result = _run(positions, closes)

    assert np.isfinite(result.equity.to_numpy()).all()
    assert np.isfinite(result.metadata["accepted_notional_report"].to_numpy()).all()


def test_phase11c_fee_and_funding_reconcile_to_contract_report():
    idx = pd.date_range("2024-01-01 06:00", periods=5, freq="1h", tz="UTC")
    positions = {"BTC": pd.Series([0.0, 1.0, 1.0, 1.0, 0.0], index=idx)}
    closes = {"BTC": pd.Series([100.0, 100.0, 100.0, 100.0, 100.0], index=idx)}

    result = _run(
        positions,
        closes,
        initial_capital=10_000.0,
        leverage=10.0,
        fee_rate=0.0004,
        funding_rate=0.001,
        use_funding=True,
    )
    report = validate_portfolio_result_contract(result, PortfolioDomainSpec(mode="longshort", sizing_mode="target_units"), raise_on_fail=True)

    assert report["passed"] is True
    assert result.fees.sum() > 0.0
    assert result.funding.sum() > 0.0


def test_phase11c_leverage_gates_buying_power_without_scaling_target_size():
    idx = _daily_idx(3)
    positions = {"BTC": pd.Series([0.0, 10.0, 10.0], index=idx)}
    closes = {"BTC": pd.Series([100.0, 100.0, 110.0], index=idx)}

    accepted = _run(positions, closes, initial_capital=100.0, leverage=20.0)
    rejected = _run(positions, closes, initial_capital=100.0, leverage=1.0)

    assert accepted.metadata["initial_buying_power"] == 2_000.0
    assert accepted.metadata["accepted_units_report"]["BTC"].iloc[1] == 10.0
    assert rejected.metadata["initial_buying_power"] == 100.0
    assert rejected.metadata["accepted_units_report"]["BTC"].iloc[1] == 0.0


def test_phase11c_liquidation_is_auditable_without_fake_force_flat_fee():
    idx = _daily_idx(4)
    positions = {"BTC": pd.Series([0.0, 10.0, 10.0, 0.0], index=idx)}
    closes = {"BTC": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)}
    highs = {"BTC": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)}
    lows = {"BTC": pd.Series([100.0, 100.0, 10.0, 100.0], index=idx)}

    result = _run(positions, closes, highs=highs, lows=lows, initial_capital=100.0, leverage=20.0)
    report = validate_portfolio_result_contract(result, PortfolioDomainSpec(mode="longshort", sizing_mode="target_units"), raise_on_fail=True)

    assert result.liquidated is True
    assert result.liquidation_bar == 2
    assert report["passed"] is True
    assert result.fees.sum() == 0.0
