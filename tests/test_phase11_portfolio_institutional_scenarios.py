from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import AccountConfig, ExecutionConfig, MultiSymbolPortfolio, PortfolioBacktestEngine, PortfolioDomainSpec, QuantBTEndpoint, validate_portfolio_result_contract


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


def test_phase41_portfolio_turnover_uses_traded_delta_for_reversals():
    idx = _daily_idx(4)
    positions = {"BTC": pd.Series([0.0, 1.0, -1.0, 0.0], index=idx)}
    closes = {"BTC": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)}

    result = _run(positions, closes, hedge_type="target_units", fee_rate=0.0)

    np.testing.assert_allclose(result.metadata["turnover_series"].to_numpy(), [0.0, 100.0, 200.0, 100.0])
    assert result.metadata["turnover_total"] == 400.0


def test_phase41_portfolio_slippage_is_charged_for_all_trade_directions():
    idx = _daily_idx(5)
    positions = {"BTC": pd.Series([0.0, 1.0, 0.0, -1.0, 0.0], index=idx)}
    closes = {"BTC": pd.Series(100.0, index=idx)}

    result = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="longshort",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0, maintenance_ratio=0.005),
        execution=ExecutionConfig(slippage_bps=10.0),
        fee_rate=0.0,
        hedge_type="target_units",
        asset_type="crypto",
        use_funding=False,
        contract_size=1.0,
    ).result

    np.testing.assert_allclose(result.metadata["slippage_series"].to_numpy(), [0.0, 0.1, 0.1, 0.1, 0.1])
    np.testing.assert_allclose(result.equity.iloc[-1], 9_999.6)


def test_phase41_portfolio_endpoint_legacy_slippage_parameter_is_converted():
    idx = _daily_idx(3)
    positions = pd.DataFrame({"BTC": [0.0, 1.0, 0.0]}, index=idx)
    data = {"BTC": pd.DataFrame({"close": [100.0, 100.0, 100.0], "high": [100.0, 100.0, 100.0], "low": [100.0, 100.0, 100.0]}, index=idx)}

    result = QuantBTEndpoint.portfolio(
        portfolio_mode="longshort",
        hedge_type="target_units",
        initial_capital=10_000,
        leverage=10,
        fee=0.0,
        slippage=0.001,
        use_funding=False,
    ).backtest(data=data, positions=positions)

    assert result.metadata["slippage_bps"] == 10.0
    np.testing.assert_allclose(result.metadata["slippage_total"], 0.2)


def test_phase41_portfolio_fee_rate_is_canonical_one_way_and_legacy_fee_is_compat_bridge():
    idx = _daily_idx(3)
    positions = pd.DataFrame({"BTC": [0.0, 1.0, 0.0]}, index=idx)
    data = {"BTC": pd.DataFrame({"close": [100.0, 100.0, 100.0], "high": [100.0, 100.0, 100.0], "low": [100.0, 100.0, 100.0]}, index=idx)}

    explicit = QuantBTEndpoint.portfolio(
        portfolio_mode="longshort",
        hedge_type="target_units",
        initial_capital=10_000,
        leverage=10,
        fee_rate=0.0005,
        slippage_bps=0.0,
        use_funding=False,
    ).backtest(data=data, positions=positions)
    legacy = QuantBTEndpoint.portfolio(
        portfolio_mode="longshort",
        hedge_type="target_units",
        initial_capital=10_000,
        leverage=10,
        fee=0.001,
        slippage_bps=0.0,
        use_funding=False,
    ).backtest(data=data, positions=positions)

    np.testing.assert_allclose(explicit.fees.to_numpy(), [0.0, 0.05, 0.05])
    np.testing.assert_allclose(explicit.equity.iloc[-1], 9_999.9)
    np.testing.assert_allclose(legacy.equity.to_numpy(), explicit.equity.to_numpy())
    assert explicit.metadata["canonical_one_way_fee_rate"] == 0.0005
    assert legacy.metadata["canonical_one_way_fee_rate"] == 0.0005
    assert explicit.metadata["run_config"]["fees"]["legacy_fee_converted"] is False
    assert legacy.metadata["run_config"]["fees"]["legacy_fee_converted"] is True
    assert explicit.metadata["run_config"]["fees"]["applied_fee_source"] == "fee_rate"
    assert legacy.metadata["run_config"]["fees"]["applied_fee_source"] == "legacy_fee"


def test_phase41_legacy_multisymbol_fee_rate_is_one_way_with_fee_round_trip_alias():
    idx = _daily_idx(3)
    positions = {"BTC": pd.Series([0.0, 1.0, 0.0], index=idx)}
    closes = {"BTC": pd.Series(100.0, index=idx)}

    explicit = MultiSymbolPortfolio(
        positions=positions,
        closes=closes,
        datetime_index=idx,
        mode="longshort",
        fee_rate=0.0005,
        alloc_per_trade=100.0,
        hedge_type="unit",
        initial_capital=10_000.0,
        leverage=10.0,
        use_funding=False,
    )
    legacy_alias = MultiSymbolPortfolio(
        positions=positions,
        closes=closes,
        datetime_index=idx,
        mode="longshort",
        fee=0.001,
        alloc_per_trade=100.0,
        hedge_type="unit",
        initial_capital=10_000.0,
        leverage=10.0,
        use_funding=False,
    )

    np.testing.assert_allclose(explicit.result.metadata["fee_total"], 0.1)
    np.testing.assert_allclose(legacy_alias.result.equity.to_numpy(), explicit.result.equity.to_numpy())


def test_phase41_portfolio_fixed_and_equity_sizing_accounting_share_same_accepted_delta_contract():
    idx = _daily_idx(3)
    closes = {"BTC": pd.Series(100.0, index=idx)}
    fixed_positions = {"BTC": pd.Series([0.0, 1.0, -1.0], index=idx)}
    equity_positions = {"BTC": pd.Series([0.0, 1.0, -1.0], index=idx)}

    fixed = PortfolioBacktestEngine(
        positions=fixed_positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="longshort",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0, maintenance_ratio=0.005),
        execution=ExecutionConfig(slippage_bps=10.0),
        fee_rate=0.001,
        hedge_type="target_units",
        asset_type="crypto",
        use_funding=False,
        contract_size=1.0,
    ).result
    equity = PortfolioBacktestEngine(
        positions=equity_positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="longshort",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0, maintenance_ratio=0.005),
        execution=ExecutionConfig(slippage_bps=10.0),
        fee_rate=0.001,
        hedge_type="%_equity",
        alloc_per_trade=0.25,
        asset_type="crypto",
        use_funding=False,
        contract_size=1.0,
    ).result

    for result in (fixed, equity):
        accepted = result.metadata["accepted_units_report"]["BTC"].to_numpy()
        delta = np.abs(np.diff(np.r_[0.0, accepted]))
        expected_slip = delta * 100.0 * 0.001
        np.testing.assert_allclose(result.metadata["slippage_series"].to_numpy(), expected_slip, rtol=1e-10, atol=1e-10)
        assert result.fees.sum() > 0.0
        assert result.metadata["turnover_total"] > 0.0
        recon = result.metadata["portfolio_reconciliation_report"]
        np.testing.assert_allclose(recon["fee_diff"], 0.0, atol=1e-10)
        np.testing.assert_allclose(recon["slippage_diff"], 0.0, atol=1e-10)
        np.testing.assert_allclose(recon["equity_symbol_pnl_diff"], 0.0, atol=1e-8)


def test_phase41_portfolio_reversal_gate_includes_post_cost_equity_even_when_gross_unchanged():
    idx = _daily_idx(3)
    positions = {"BTC": pd.Series([0.0, 1.0, -1.0], index=idx)}
    closes = {"BTC": pd.Series(100.0, index=idx)}

    result = _run(
        positions,
        closes,
        hedge_type="target_units",
        initial_capital=109.0,
        leverage=1.0,
        fee_rate=0.08,
    )

    assert result.metadata["accepted_units_report"]["BTC"].iloc[1] == 1.0
    assert result.metadata["accepted_units_report"]["BTC"].iloc[2] == 1.0
    assert result.metadata["rebalance_report"].query("timestamp == @idx[2]")["reason"].iloc[0] == "POST_COST_MARGIN"


def test_phase41_market_neutral_missing_one_side_rejects_directional_exposure():
    idx = _daily_idx(4)
    positions = {"BTC": pd.Series([0.0, 1.0, 1.0, 1.0], index=idx), "ETH": pd.Series(0.0, index=idx)}
    closes = {"BTC": pd.Series(100.0, index=idx), "ETH": pd.Series(50.0, index=idx)}

    result = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="market_neutral",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0, maintenance_ratio=0.005),
        fee_rate=0.0,
        hedge_type="target_units",
        asset_type="crypto",
        use_funding=False,
        contract_size=1.0,
    ).result

    assert result.positions.abs().sum(axis=1).max() == 0.0


def test_phase41_risk_parity_has_causal_warmup_without_backward_fill():
    idx = _daily_idx(6)
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 1.0, 1.0, 1.0], index=idx),
        "ETH": pd.Series([0.0, -1.0, -1.0, -1.0, -1.0, -1.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 101.0, 103.0, 102.0, 104.0, 106.0], index=idx),
        "ETH": pd.Series([50.0, 49.0, 48.5, 49.5, 48.0, 47.5], index=idx),
    }

    result = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="risk_parity",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0, maintenance_ratio=0.005),
        fee_rate=0.0,
        hedge_type="gross_exposure",
        alloc_per_trade=1.0,
        risk_lookback=3,
        asset_type="crypto",
        use_funding=False,
        contract_size=1.0,
    ).result

    accepted = result.metadata["accepted_units_report"]
    assert accepted.iloc[1].abs().sum() == 0.0
    assert accepted.iloc[2].abs().sum() == 0.0
    assert accepted.iloc[3].abs().sum() > 0.0


def test_phase41_leading_missing_price_is_not_tradable_until_valid_observation():
    idx = _daily_idx(4)
    positions = {"NEW": pd.Series([0.0, 1.0, 1.0, 1.0], index=idx)}
    closes = {"NEW": pd.Series([np.nan, np.nan, 100.0, 101.0], index=idx)}

    result = _run(positions, closes, hedge_type="target_units", fee_rate=0.0)

    accepted = result.metadata["accepted_units_report"]["NEW"]
    assert accepted.iloc[1] == 0.0
    assert accepted.iloc[2] == 1.0


def test_phase41_stale_price_and_asynchronous_calendar_rebalance_is_rejected_with_reason():
    idx = _daily_idx(5)
    sparse_idx = pd.DatetimeIndex([idx[0], idx[1], idx[4]])
    positions = {"ALT": pd.Series([0.0, 1.0, 2.0, 2.0, 0.0], index=idx)}
    closes = {"ALT": pd.Series([100.0, 100.0, 110.0], index=sparse_idx)}

    result = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="longshort",
        backend="native_portfolio",
        account=AccountConfig(initial_capital=100_000.0, leverage=5.0, maintenance_ratio=0.005),
        fee_rate=0.0,
        hedge_type="target_units",
        asset_type="crypto",
        use_funding=False,
        contract_size=1.0,
    ).result

    accepted = result.metadata["accepted_units_report"]["ALT"]
    assert accepted.iloc[1] == 1.0
    assert accepted.iloc[2] == 1.0
    stale_reject = result.metadata["rebalance_report"].query("timestamp == @idx[2]")
    assert stale_reject["reason"].iloc[0] == "STALE_PRICE"
    assert accepted.iloc[4] == 0.0


def test_phase41_portfolio_reconciliation_report_balances_costs_positions_and_pnl():
    idx = _daily_idx(4)
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -2.0, -2.0, 0.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 100.0, 110.0, 110.0], index=idx),
        "ETH": pd.Series([50.0, 50.0, 45.0, 45.0], index=idx),
    }

    result = _run(positions, closes, hedge_type="target_units", fee_rate=0.001)
    recon = result.metadata["portfolio_reconciliation_report"]

    np.testing.assert_allclose(recon["fee_diff"], 0.0, atol=1e-10)
    np.testing.assert_allclose(recon["slippage_diff"], 0.0, atol=1e-10)
    np.testing.assert_allclose(recon["max_result_position_diff"], 0.0, atol=1e-12)
    np.testing.assert_allclose(recon["equity_symbol_pnl_diff"], 0.0, atol=1e-8)
