from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import AccountConfig, PortfolioBacktestEngine, PortfolioDomainSpec, QuantBTEndpoint, validate_portfolio_result_contract


def _idx():
    return pd.date_range("2024-01-01", periods=8, freq="1D", tz="UTC")


def _market():
    idx = _idx()
    closes = {
        "AAA": pd.Series([100, 102, 104, 103, 105, 107, 106, 108], index=idx, dtype=float),
        "BBB": pd.Series([50, 49, 48, 49, 47, 46, 45, 44], index=idx, dtype=float),
        "CCC": pd.Series([20, 21, 20, 22, 23, 22, 24, 25], index=idx, dtype=float),
    }
    highs = {k: v * 1.01 for k, v in closes.items()}
    lows = {k: v * 0.99 for k, v in closes.items()}
    return idx, closes, highs, lows


def _positions(values=None):
    idx = _idx()
    values = values or {
        "AAA": [0, 1, 1, 1, 1, 1, 1, 1],
        "BBB": [0, -1, -1, -1, -1, -1, -1, -1],
        "CCC": [0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    }
    return {k: pd.Series(v, index=idx, dtype=float) for k, v in values.items()}


def _run(mode="longshort", hedge_type="target_weight", positions=None, **kwargs):
    idx, closes, highs, lows = _market()
    return PortfolioBacktestEngine(
        positions=positions or _positions(),
        closes=closes,
        highs=highs,
        lows=lows,
        datetime_index=idx,
        mode=mode,
        backend="native_portfolio",
        account=AccountConfig(initial_capital=100_000.0, leverage=5.0, maintenance_ratio=0.005),
        fee_rate=0.0,
        alloc_per_trade=kwargs.pop("alloc_per_trade", 0.5),
        contract_size=1.0,
        hedge_type=hedge_type,
        asset_type="crypto",
        use_funding=False,
        **kwargs,
    ).result


def test_native_portfolio_pct_equity_sizes_from_live_equity_on_signal_change():
    result = _run(hedge_type="%_equity", alloc_per_trade=0.5)
    target_notional = result.metadata["target_notional_report"]

    np.testing.assert_allclose(target_notional["AAA"].iloc[1], 50_000.0)
    np.testing.assert_allclose(target_notional["BBB"].iloc[1], -50_000.0)
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_native_portfolio_target_weight_uses_signal_as_equity_weight():
    result = _run(hedge_type="target_weight")
    target_notional = result.metadata["target_notional_report"]

    np.testing.assert_allclose(target_notional["AAA"].iloc[1], 100_000.0)
    np.testing.assert_allclose(target_notional["BBB"].iloc[1], -100_000.0)
    np.testing.assert_allclose(target_notional["CCC"].iloc[1], 50_000.0)
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_native_portfolio_gross_exposure_normalizes_to_requested_gross():
    result = _run(hedge_type="gross_exposure", alloc_per_trade=1.2)
    exposure = result.metadata["exposure_report"]

    active = exposure["gross_notional"] > 0
    np.testing.assert_allclose(exposure.loc[active, "target_gross_notional"].iloc[0], 120_000.0, rtol=0, atol=1e-9)
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_native_portfolio_net_exposure_normalizes_to_requested_net():
    positions = _positions({"AAA": [0, 1, 1, 1, 1, 1, 1, 1], "BBB": [0, 1, 1, 1, 1, 1, 1, 1], "CCC": [0, 0, 0, 0, 0, 0, 0, 0]})
    result = _run(hedge_type="net_exposure", alloc_per_trade=0.8, positions=positions)
    exposure = result.metadata["exposure_report"]

    active = exposure["gross_notional"] > 0
    np.testing.assert_allclose(exposure.loc[active, "net_notional"].iloc[0], 80_000.0, rtol=0, atol=1e-9)
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_native_portfolio_risk_parity_equalizes_vol_scaled_contribution():
    result = _run(mode="risk_parity", hedge_type="gross_exposure", alloc_per_trade=1.0, risk_lookback=2)
    report = validate_portfolio_result_contract(
        result,
        PortfolioDomainSpec(mode="risk_parity", sizing_mode="gross_exposure"),
        tolerance=1e-8,
        raise_on_fail=True,
    )

    assert report["checks"]["risk_parity_balanced"] is True


def test_native_portfolio_beta_neutral_uses_beta_weighted_notional():
    result = _run(
        mode="beta_neutral",
        hedge_type="gross_exposure",
        alloc_per_trade=1.0,
        betas={"AAA": 1.0, "BBB": 1.5, "CCC": 0.5},
    )
    exposure = result.metadata["exposure_report"]
    active = exposure["gross_notional"] > 0

    assert exposure.loc[active, "beta_exposure_notional"].abs().max() <= 1e-8
    assert result.metadata["portfolio_contract_report"]["passed"] is True


def test_endpoint_portfolio_defaults_to_native_portfolio_backend():
    idx, closes, highs, lows = _market()
    data = {s: pd.DataFrame({"close": closes[s], "high": highs[s], "low": lows[s]}, index=idx) for s in closes}
    positions = pd.DataFrame(_positions(), index=idx)

    endpoint = QuantBTEndpoint.portfolio(
        portfolio_mode="longshort",
        hedge_type="target_weight",
        initial_capital=100_000,
        leverage=5,
        fee=0.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=data, positions=positions)

    assert result.metadata["backend"] == "native_portfolio"
    assert result.metadata["hedge_type"] == "target_weight"
