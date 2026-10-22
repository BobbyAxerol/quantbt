"""Independent arithmetic regressions for the approved account review repair."""

import numpy as np
import pandas as pd
import pytest

from quantbt import AccountConfig, ExecutionConfig
from quantbt.backends.native_event import NativeEventConfig
from quantbt.backends.native_portfolio import NativePortfolioConfig
from quantbt.backends.native_vectorized import NativeVectorizedConfig
from quantbt.core.preprocessor import make_funding_mask, prepare_funding
from quantbt.core.schema import FillPricePolicy, MarginMode, OmsMode
from quantbt.reporting.portfolio_audit import build_portfolio_domain_audit
from tools.portfolio_account_review import run


@pytest.mark.parametrize("backend", [NativePortfolioConfig, NativeVectorizedConfig, NativeEventConfig])
@pytest.mark.parametrize("field,value", [
    ("margin_mode", MarginMode.ISOLATED), ("margin_mode", MarginMode.CASH),
    ("margin_mode", MarginMode.PORTFOLIO), ("oms_mode", OmsMode.HEDGING),
    ("margin_buffer", .1),
])
def test_account_capabilities_fail_closed(backend, field, value):
    with pytest.raises(NotImplementedError):
        backend(account=AccountConfig(initial_capital=1000, **{field: value}))


@pytest.mark.parametrize("execution", [
    ExecutionConfig(fill_price_policy=FillPricePolicy.NEXT_OPEN),
    ExecutionConfig(fill_price_policy=FillPricePolicy.OPEN),
    ExecutionConfig(allow_partial_fill=True),
    ExecutionConfig(reject_on_insufficient_margin=False),
])
def test_close_portfolio_rejects_ignored_execution_options(execution):
    with pytest.raises(NotImplementedError):
        NativePortfolioConfig(AccountConfig(initial_capital=1000), execution=execution)


@pytest.mark.parametrize("field", ["initial_capital", "leverage", "maintenance_ratio", "margin_buffer"])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_account_values_rejected(field, value):
    values = dict(initial_capital=1000)
    values[field] = value
    with pytest.raises(ValueError):
        AccountConfig(**values)


def test_nonfinite_per_symbol_leverage_cannot_bypass_margin():
    with pytest.raises(ValueError):
        run([100] * 3, [0, 100, 100], leverage={"S0": np.nan})


def test_funding_daily_counts_all_carried_events():
    index = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    assert make_funding_mask(index).tolist() == [False, True, True, True]
    result = run([100] * 4, [0, 1, 1, 1], index=index, use_funding=True, funding_rate=.01)
    np.testing.assert_allclose(result.equity, [1000, 1000, 997, 994])
    np.testing.assert_allclose(result.funding, [0, 0, 3, 3])
    assert result.metadata["portfolio_contract_report"]["passed"]


def test_gapped_funding_uses_each_event_rate_and_preserves_input():
    idx = pd.to_datetime(["2024-01-01 01:00Z", "2024-01-02 01:00Z"])
    rates = pd.Series([.01, .02, .03, .99], index=pd.to_datetime([
        "2024-01-01 08:00Z", "2024-01-01 16:00Z", "2024-01-02 00:00Z", "2024-01-02 01:00Z"]))
    before = rates.copy()
    prepared = prepare_funding(rates, ["A"], idx)
    assert prepared["A"].iloc[1] == pytest.approx(.06)
    pd.testing.assert_series_equal(rates, before)
    assert make_funding_mask(idx).tolist() == [False, True]


@pytest.mark.parametrize("level", ["full", "standard", "minimal"])
def test_raw_funding_not_reconstructed_after_liquidation(level):
    result = run([100] * 4, [0, 10, 10, 0], low_values=[100, 100, 10, 100],
                 account=AccountConfig(initial_capital=100, leverage=20),
                 use_funding=True, funding_rate=.01, report_level=level)
    np.testing.assert_allclose(result.equity, [100, 100, 0, 0])
    np.testing.assert_array_equal(result.funding, 0)
    if level != "minimal":
        assert result.metadata["portfolio_contract_report"]["passed"]
        report = result.metadata["symbol_pnl_report"]
        assert report.total_pnl.sum() == pytest.approx(-100)
        assert report.liquidation_adjustment.sum() == pytest.approx(100)
        assert report.fee.sum() == 0
        bad = report.copy()
        bad.loc[bad.timestamp == result.equity.index[2], "total_pnl"] += 1
        result.metadata["symbol_pnl_report"] = bad
        assert not build_portfolio_domain_audit(result)["passed"]


def test_opposite_side_execution_fees_match_actual_leg_prices():
    result = run([[100, 100]] * 3, [[0, 0], [1, -1], [0, 0]],
                 fee_rate=.01, execution=ExecutionConfig(slippage_bps=100))
    report = result.metadata["symbol_pnl_report"]
    entry = report[report.timestamp == result.equity.index[1]].set_index("symbol")
    assert entry.loc["S0", "fee"] == pytest.approx(1.01)
    assert entry.loc["S1", "fee"] == pytest.approx(.99)
    assert result.metadata["portfolio_contract_report"]["passed"]


def test_partial_reduction_below_im_is_accepted_above_maintenance():
    result = run([100, 100, 110], [0, -19, -18],
                 account=AccountConfig(initial_capital=2000, leverage=1), fee_rate=.0004)
    assert result.positions.iloc[-1, 0] == -18
    assert result.equity.iloc[-1] == pytest.approx(1809.196)
    assert not result.liquidated


def test_increase_still_requires_initial_margin_after_costs():
    result = run([100, 100, 110], [0, -19, -20],
                 account=AccountConfig(initial_capital=2000, leverage=1), fee_rate=.0004)
    assert result.positions.iloc[-1, 0] == -19


def test_order_minima_apply_to_increasing_delta_and_allow_reduction():
    result = run([100] * 5, [0, 1, 1.1, .9, 0], min_qty=.5, min_notional=50)
    np.testing.assert_allclose(result.positions.iloc[:, 0], [0, 1, 1, .9, 0])
    no_entry = run([100] * 3, [0, 1, 1], execution=ExecutionConfig(min_order_notional=200))
    np.testing.assert_array_equal(no_entry.positions, 0)


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("minimum,accepted,equity", [(50, 1.5, 998.5), (50.25, 1, 999)])
def test_notional_minimum_uses_close_mark_before_slippage(sign, minimum, accepted, equity):
    result = run([100] * 3, [0, sign, sign * 1.5], min_notional=minimum,
                 execution=ExecutionConfig(slippage_bps=100))
    assert result.positions.iloc[-1, 0] == pytest.approx(sign * accepted)
    assert result.equity.iloc[-1] == pytest.approx(equity)


def test_heterogeneous_leverage_exposes_margin_not_fictional_scalar_capacity():
    result = run([[100, 100]] * 3, [[0, 0], [1, -1], [1, -1]], leverage={"S0": 1, "S1": 10})
    report = result.metadata["exposure_report"]
    assert report.initial_margin.iloc[-1] == 110
    assert report.available_margin.iloc[-1] == 890
    assert np.isnan(report.buying_power).all()
    assert result.metadata["initial_buying_power"] is None


def test_shared_dca_sizing_applies_multiplier_to_base_and_safety_orders():
    from quantbt import BacktestEngine

    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    prices = pd.Series([100., 100., 99., 99.], index=index)
    result = BacktestEngine(
        Datetime=index, Position=pd.Series([0., 1., 2., 0.], index=index), Close=prices,
        High=prices, Low=prices, hedge_type="dca_ladder", initial_capital=1000,
        leverage=1, contract_size=10, fee=0, slippage=0, use_funding_rate=False,
        dca_base_notional=100, dca_safety_notional=100, dca_step_pct=.01,
        dca_max_safety_orders=1, dca_take_profit_pct=0,
    ).result
    assert result.positions.iloc[1, 0] == pytest.approx(.1)
    assert result.positions.iloc[2, 0] == pytest.approx(.1 + 100 / (99 * 10))
    assert result.equity.iloc[-1] == pytest.approx(999)


def test_event_order_clock_uses_same_default_funding_interval_aggregation():
    from quantbt import NativeEventBackend
    from quantbt.core.orders import OrderIntent
    from quantbt.core.schema import OrderSide, OrderType

    index = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    prices = {"A": pd.Series(100., index=index)}
    backend = NativeEventBackend(NativeEventConfig(
        account=AccountConfig(initial_capital=1000), native_backend="python", use_funding=True))
    result = backend.run_orders(
        datetime_index=index, closes=prices, highs=prices, lows=prices, funding_rate=.01,
        orders=[OrderIntent(timestamp=index[1], symbol="A", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1)],
    )
    np.testing.assert_allclose(result.equity, [1000, 1000, 997, 994])
    np.testing.assert_allclose(result.funding, [0, 0, 3, 3])
