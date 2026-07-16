from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import AccountConfig, PortfolioBacktestEngine, PortfolioDomainSpec, validate_portfolio_result_contract


def _idx():
    return pd.date_range("2024-01-01", periods=6, freq="1D", tz="UTC")


def _inputs(mode: str):
    idx = _idx()
    if mode == "directional":
        positions = {
            "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, -1.0, -1.0], index=idx),
            "ETH": pd.Series([0.0, -2.0, -2.0, 0.0, 1.0, 1.0], index=idx),
            "SOL": pd.Series([0.0, 0.5, 0.5, 0.0, 0.0, 0.0], index=idx),
        }
        closes = {
            "BTC": pd.Series([100.0, 100.0, 105.0, 102.0, 104.0, 103.0], index=idx),
            "ETH": pd.Series([10.0, 10.0, 9.0, 11.0, 12.0, 13.0], index=idx),
            "SOL": pd.Series([20.0, 20.0, 21.0, 19.0, 18.0, 17.0], index=idx),
        }
    else:
        positions = {
            "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, -0.5, -0.5], index=idx),
            "ETH": pd.Series([0.0, -1.0, -1.0, 0.0, 0.75, 0.75], index=idx),
            "SOL": pd.Series([0.0, 0.5, 0.5, 0.0, 0.0, 0.0], index=idx),
        }
        closes = {
            "BTC": pd.Series([100.0, 100.0, 110.0, 105.0, 108.0, 112.0], index=idx),
            "ETH": pd.Series([50.0, 50.0, 45.0, 48.0, 47.0, 49.0], index=idx),
            "SOL": pd.Series([20.0, 20.0, 22.0, 21.0, 19.0, 18.0], index=idx),
        }
    return idx, positions, closes


def _run(mode: str, backend: str, hedge_type: str, *, initial_capital: float = 100_000.0):
    idx, positions, closes = _inputs(mode)
    return PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode=mode,
        backend=backend,
        account=AccountConfig(initial_capital=initial_capital, leverage=8.0, maintenance_ratio=0.005),
        fee_rate=0.0004,
        alloc_per_trade={"BTC": 1_000.0, "ETH": 1_500.0, "SOL": 500.0},
        contract_size=1.0,
        hedge_type=hedge_type,
        asset_type="crypto",
        use_funding=False,
    ).result


@pytest.mark.parametrize("mode", ["longshort", "market_neutral", "directional", "equal_weight"])
@pytest.mark.parametrize("hedge_type", ["signal_notional", "signal", "notional", "unit"])
def test_phase11b_native_portfolio_matches_legacy_for_supported_modes(mode, hedge_type):
    legacy = _run(mode, "legacy_portfolio", hedge_type)
    native = _run(mode, "native_portfolio", hedge_type)

    np.testing.assert_allclose(native.equity.to_numpy(), legacy.equity.to_numpy(), rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(native.positions.to_numpy(), legacy.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        native.metadata["target_units_report"].to_numpy(),
        legacy.metadata["target_units_report"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        native.metadata["accepted_units_report"].to_numpy(),
        legacy.metadata["accepted_units_report"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        native.metadata["accepted_notional_report"].to_numpy(),
        legacy.metadata["accepted_notional_report"].to_numpy(),
        rtol=0.0,
        atol=1e-9,
    )

    spec = PortfolioDomainSpec(mode=mode, sizing_mode=hedge_type)
    report = validate_portfolio_result_contract(native, spec, tolerance=1e-8, raise_on_fail=True)
    assert report["status"] == "pass"
    assert native.metadata["backend"] == "native_portfolio"
    assert native.metadata["portfolio_contract_report"]["passed"] is True


def test_phase11b_native_portfolio_rejects_unimplemented_roadmap_sizing_modes():
    with pytest.raises(NotImplementedError):
        _run("longshort", "native_portfolio", "dca_ladder")


def test_phase11c_native_portfolio_target_units_are_explicit_contracts():
    result = _run("longshort", "native_portfolio", "target_units")
    target = result.metadata["target_units_report"]

    np.testing.assert_allclose(target["BTC"].iloc[1], 1.0)
    np.testing.assert_allclose(target["ETH"].iloc[1], -1.0)
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_phase11c_native_portfolio_target_notional_respects_contract_size():
    idx = _idx()
    positions = {
        "BTC": pd.Series([0.0, 1_000.0, 1_000.0, 0.0, 0.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -500.0, -500.0, 0.0, 0.0, 0.0], index=idx),
        "SOL": pd.Series(0.0, index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 100.0, 110.0, 100.0, 100.0, 100.0], index=idx),
        "ETH": pd.Series([50.0, 50.0, 50.0, 50.0, 50.0, 50.0], index=idx),
        "SOL": pd.Series([20.0, 20.0, 20.0, 20.0, 20.0, 20.0], index=idx),
    }
    result = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="longshort",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=100_000.0, leverage=10.0),
        fee_rate=0.0,
        alloc_per_trade=1_000.0,
        contract_size={"BTC": 2.0, "ETH": 5.0, "SOL": 1.0},
        hedge_type="target_notional",
        asset_type="crypto",
        use_funding=False,
    ).result
    target = result.metadata["target_units_report"]

    np.testing.assert_allclose(target["BTC"].iloc[1], 1_000.0 / (100.0 * 2.0))
    np.testing.assert_allclose(target["BTC"].iloc[2], 1_000.0 / (110.0 * 2.0))
    np.testing.assert_allclose(target["ETH"].iloc[1], -500.0 / (50.0 * 5.0))
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_phase11c_native_portfolio_fixed_notional_uses_signal_times_alloc():
    result = _run("longshort", "native_portfolio", "fixed_notional")
    target = result.metadata["target_units_report"]

    np.testing.assert_allclose(target["BTC"].iloc[1], 1_000.0 / 100.0)
    np.testing.assert_allclose(target["BTC"].iloc[2], 1_000.0 / 110.0)
    np.testing.assert_allclose(target["ETH"].iloc[1], -1_500.0 / 50.0)
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_phase11b_native_portfolio_preserves_margin_rejection_behavior():
    legacy = _run("longshort", "legacy_portfolio", "signal_notional", initial_capital=100.0)
    native = _run("longshort", "native_portfolio", "signal_notional", initial_capital=100.0)

    np.testing.assert_allclose(native.equity.to_numpy(), legacy.equity.to_numpy(), rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(
        native.metadata["accepted_units_report"].to_numpy(),
        legacy.metadata["accepted_units_report"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    assert len(native.metadata["rebalance_report"]) == len(legacy.metadata["rebalance_report"])
