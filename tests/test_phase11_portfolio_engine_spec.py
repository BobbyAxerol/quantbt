from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    LEGACY_PORTFOLIO_MODES,
    LEGACY_PORTFOLIO_SIZING_MODES,
    NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES,
    PortfolioBacktestEngine,
    PortfolioDomainSpec,
    portfolio_capability_matrix,
    validate_portfolio_result_contract,
)


def _idx():
    return pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")


def _portfolio_inputs(mode: str):
    idx = _idx()
    if mode == "directional":
        positions = {
            "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx),
            "ETH": pd.Series([0.0, -2.0, -2.0, 0.0, 0.0], index=idx),
        }
        closes = {
            "BTC": pd.Series([100.0, 100.0, 100.0, 100.0, 100.0], index=idx),
            "ETH": pd.Series([10.0, 10.0, 10.0, 10.0, 10.0], index=idx),
        }
        alloc = 1_000.0
    else:
        positions = {
            "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx),
            "ETH": pd.Series([0.0, -1.0, -1.0, 0.0, 0.0], index=idx),
        }
        closes = {
            "BTC": pd.Series([100.0, 100.0, 110.0, 120.0, 120.0], index=idx),
            "ETH": pd.Series([50.0, 50.0, 45.0, 40.0, 40.0], index=idx),
        }
        alloc = {"BTC": 1_000.0, "ETH": 2_000.0} if mode == "market_neutral" else 1_000.0
    return idx, positions, closes, alloc


def _run(mode: str, hedge_type: str = "signal_notional"):
    idx, positions, closes, alloc = _portfolio_inputs(mode)
    engine = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode=mode,
        account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
        fee_rate=0.0,
        alloc_per_trade=alloc,
        hedge_type=hedge_type,
        asset_type="crypto",
        use_funding=False,
    )
    return engine.result


def test_phase11_portfolio_capability_matrix_declares_legacy_and_roadmap_modes():
    matrix = portfolio_capability_matrix()

    assert set(matrix["mode"]) == LEGACY_PORTFOLIO_MODES
    assert set(matrix["sizing_mode"]) == NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES
    legacy = matrix[matrix["legacy_supported"]]
    assert set(legacy["sizing_mode"]) == LEGACY_PORTFOLIO_SIZING_MODES
    assert "target_weight" in NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES
    assert "target_units" in NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES
    assert "%_equity" in NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES


def test_phase11_portfolio_domain_spec_normalizes_aliases_and_rejects_unknowns():
    spec = PortfolioDomainSpec(mode="dollar_neutral", sizing_mode="pct_equity", rebalance_policy="signal_change")

    assert spec.mode == "market_neutral"
    assert spec.sizing_mode == "%_equity"
    assert spec.rebalance_policy == "on_signal_change"
    assert spec.native_planned is True
    assert spec.legacy_compatible is False

    with pytest.raises(ValueError):
        PortfolioDomainSpec(mode="unknown")
    with pytest.raises(ValueError):
        PortfolioDomainSpec(sizing_mode="mystery")


@pytest.mark.parametrize("mode", ["longshort", "market_neutral", "directional", "equal_weight"])
def test_phase11_legacy_portfolio_modes_satisfy_domain_contract(mode):
    result = _run(mode)
    spec = PortfolioDomainSpec(mode=mode, sizing_mode="signal_notional")

    report = validate_portfolio_result_contract(result, spec, tolerance=1e-8, raise_on_fail=True)

    assert report["status"] == "pass"
    assert report["checks"]["base_accounting_audit"] is True
    assert report["checks"]["has_margin_columns"] is True


def test_phase11_signal_notional_contract_freezes_units_until_signal_transition():
    result = _run("longshort", hedge_type="signal_notional")
    accepted = result.metadata["accepted_units_report"]

    np.testing.assert_allclose(accepted["BTC"].iloc[1], 10.0)
    np.testing.assert_allclose(accepted["BTC"].iloc[2], 10.0)


def test_phase11_notional_contract_rebalances_units_with_price_drift():
    result = _run("longshort", hedge_type="notional")
    accepted = result.metadata["accepted_units_report"]

    np.testing.assert_allclose(accepted["BTC"].iloc[1], 10.0)
    np.testing.assert_allclose(accepted["BTC"].iloc[2], 1_000.0 / 110.0)


def test_phase11_unit_contract_anchors_units_to_first_price():
    result = _run("longshort", hedge_type="unit")
    accepted = result.metadata["accepted_units_report"]

    np.testing.assert_allclose(accepted["BTC"].iloc[1], 10.0)
    np.testing.assert_allclose(accepted["BTC"].iloc[2], 10.0)
    np.testing.assert_allclose(accepted["ETH"].iloc[1], -20.0)
    np.testing.assert_allclose(accepted["ETH"].iloc[2], -20.0)


def test_phase11_contract_catches_mode_mismatch():
    result = _run("longshort")
    spec = PortfolioDomainSpec(mode="market_neutral", sizing_mode="signal_notional")

    report = validate_portfolio_result_contract(result, spec, tolerance=1e-8)

    assert report["status"] == "fail"
    assert report["checks"]["mode_matches_spec"] is False
