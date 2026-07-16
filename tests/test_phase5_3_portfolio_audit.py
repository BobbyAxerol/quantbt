from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    MultiSymbolPortfolio,
    PortfolioBacktestEngine,
    build_portfolio_domain_audit,
)


def _idx():
    return pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")


def _base_inputs(idx):
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -1.0, -1.0, 0.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 100.0, 110.0, 120.0], index=idx),
        "ETH": pd.Series([50.0, 50.0, 45.0, 40.0], index=idx),
    }
    return positions, closes


def _run_portfolio(mode: str, *, positions=None, closes=None, alloc_per_trade=1_000.0, initial_capital=50_000.0):
    idx = _idx()
    positions, closes = _base_inputs(idx) if positions is None else (positions, closes)
    return PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode=mode,
        account=AccountConfig(initial_capital=initial_capital, leverage=10.0),
        fee_rate=0.0004,
        alloc_per_trade=alloc_per_trade,
        asset_type="crypto",
        use_funding=False,
    ).result


def test_phase5_3_portfolio_longshort_reports_reconcile_to_equity():
    result = _run_portfolio("longshort")

    audit = build_portfolio_domain_audit(result, tolerance=1e-8, raise_on_fail=True)

    assert audit["status"] == "pass"
    assert audit["mode"] == "longshort"
    assert result.metadata["fee_total"] > 0.0
    np.testing.assert_allclose(
        result.metadata["symbol_pnl_report"].groupby("timestamp")["total_pnl"].sum().to_numpy(),
        result.equity.diff().fillna(0.0).to_numpy(),
        atol=1e-8,
    )


def test_phase5_3_portfolio_market_neutral_balances_long_and_short_notional():
    result = _run_portfolio("market_neutral", alloc_per_trade={"BTC": 1_000.0, "ETH": 2_000.0})
    exposure = result.metadata["exposure_report"]

    audit = build_portfolio_domain_audit(result, tolerance=1e-8, raise_on_fail=True)

    assert audit["status"] == "pass"
    np.testing.assert_allclose(exposure["long_notional"].iloc[1], exposure["short_notional"].iloc[1])
    np.testing.assert_allclose(exposure["gross_notional"].iloc[1], 3_000.0)


def test_phase5_3_portfolio_directional_keeps_only_dominant_notional_leg():
    idx = _idx()
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -2.0, -2.0, 0.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
        "ETH": pd.Series([10.0, 10.0, 10.0, 10.0], index=idx),
    }
    result = _run_portfolio("directional", positions=positions, closes=closes)
    accepted = result.metadata["accepted_units_report"]

    audit = build_portfolio_domain_audit(result, tolerance=1e-8, raise_on_fail=True)

    assert audit["status"] == "pass"
    assert accepted["BTC"].iloc[1] == 0.0
    assert accepted["ETH"].iloc[1] < 0.0


def test_phase5_3_portfolio_equal_weight_equalizes_active_symbol_notionals():
    idx = _idx()
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -2.0, -2.0, 0.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
        "ETH": pd.Series([10.0, 10.0, 10.0, 10.0], index=idx),
    }
    result = _run_portfolio("equal_weight", positions=positions, closes=closes)
    notional = result.metadata["accepted_notional_report"].abs()

    audit = build_portfolio_domain_audit(result, tolerance=1e-8, raise_on_fail=True)

    assert audit["status"] == "pass"
    np.testing.assert_allclose(notional["BTC"].iloc[1], notional["ETH"].iloc[1])


def test_phase5_3_portfolio_margin_gate_rejects_unaffordable_target_and_reports_it():
    idx = _idx()
    pos = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    close = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)

    msp = MultiSymbolPortfolio(
        positions={"BTC": pos},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
        datetime_index=idx,
        mode="longshort",
        fee_rate=0.0,
        alloc_per_trade=5_000.0,
        initial_capital=1_000.0,
        leverage=1.0,
        asset_type="crypto",
        use_funding=False,
    )
    result = msp.result
    audit = build_portfolio_domain_audit(result, tolerance=1e-8, raise_on_fail=True)

    assert audit["status"] == "pass"
    assert audit["rebalance_count"] > 0
    assert result.metadata["target_units_report"]["BTC"].iloc[1] == 50.0
    assert result.metadata["accepted_units_report"]["BTC"].iloc[1] == 0.0


def test_phase5_3_portfolio_audit_fails_on_corrupted_symbol_pnl_report():
    result = _run_portfolio("longshort")
    corrupted = result.metadata["symbol_pnl_report"].copy()
    corrupted.loc[corrupted.index[2], "total_pnl"] += 1.0
    result.metadata["symbol_pnl_report"] = corrupted

    audit = build_portfolio_domain_audit(result, tolerance=1e-8)

    assert audit["status"] == "fail"
    assert audit["checks"]["pnl_reconciles_to_equity"] is False
    with pytest.raises(AssertionError):
        build_portfolio_domain_audit(result, tolerance=1e-8, raise_on_fail=True)
