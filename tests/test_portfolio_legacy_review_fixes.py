"""Independent arithmetic controls for the 2026-10-21 legacy portfolio repairs."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import BacktestEngine, MultiSymbolPortfolio, PortfolioBacktestEngine
from quantbt.backends.native_vectorized import NativeVectorizedBackend, NativeVectorizedConfig
from quantbt.backends.native_wfo_public import NativePreparedPublicWfoScorerV1
from quantbt.core.schema import (
    AccountConfig,
    ExecutionConfig,
    FillPricePolicy,
    InstrumentSpec,
    MarginMode,
    OmsMode,
    SameBarPolicy,
)
from quantbt.engines import _build_market_rebalance_orders
from quantbt.sizing.fast import scale_signal_notional_matrix
from quantbt.sizing.modes import compute_target_units


def _index(n=4):
    return pd.date_range("2024-01-01 01:00", periods=n, freq="1h", tz="UTC")


def _portfolio(close, signal, **overrides):
    kwargs = dict(
        datetime_index=signal.index,
        positions={"A": signal},
        closes={"A": close},
        initial_capital=1_000.0,
        alloc_per_trade=100.0,
        contract_size=1.0,
        leverage=1.0,
        fee_rate=0.0,
        use_funding=False,
    )
    kwargs.update(overrides)
    return MultiSymbolPortfolio(**kwargs)


def _backtester(close, signal, **overrides):
    kwargs = dict(
        Datetime=signal.index,
        Position={"A": signal, "B": signal * 0.0},
        Close={"A": close, "B": pd.Series(100.0, index=signal.index)},
        initial_capital=1_000.0,
        alloc_per_trade=100.0,
        leverage=1.0,
        fee=0.0,
        slippage=0.0,
        use_funding_rate=False,
    )
    kwargs.update(overrides)
    return BacktestEngine(**kwargs)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("notional", [0.0, 0.2, 1.0 / 6.0, -0.05, 0.0]),
        ("unit", [0.0, 0.2, 0.2, -0.1, 0.0]),
        ("signal_notional", [0.0, 0.2, 0.2, -0.05, 0.0]),
        ("signal", [0.0, 0.2, 0.2, -0.05, 0.0]),
    ],
)
@pytest.mark.parametrize("pyramiding", [True, False])
def test_series_sizing_uses_contract_multiplier(mode, expected, pyramiding):
    idx = _index(5)
    signal = pd.Series([0.0, 2.0, 2.0, -1.0, 0.0], index=idx)
    close = pd.Series([100.0, 100.0, 120.0, 200.0, 250.0], index=idx)
    expected = np.asarray(expected)
    if not pyramiding:
        expected[1:3] /= 2.0
    actual = compute_target_units(mode, signal, close, 100.0, pyramiding, contract_size=10.0)
    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)
    old_default = compute_target_units(mode, signal, close, 100.0, pyramiding)
    np.testing.assert_allclose(old_default, expected * 10.0, rtol=0.0, atol=1e-12)


def test_matrix_sizing_uses_each_symbols_multiplier_and_keeps_old_default():
    signals = np.asarray([[0.0, 0.0], [1.0, -1.0], [1.0, -1.0], [0.0, 0.0]])
    closes = np.asarray([[100.0, 50.0], [100.0, 50.0], [101.0, 49.0], [101.0, 49.0]])
    actual = scale_signal_notional_matrix(
        signals, closes, np.asarray([100.0, 100.0]), contract_sizes=np.asarray([10.0, 2.0])
    )
    np.testing.assert_allclose(actual, [[0, 0], [0.1, -1], [0.1, -1], [0, 0]], atol=1e-12)
    old_default = scale_signal_notional_matrix(signals, closes, np.asarray([100.0, 100.0]))
    np.testing.assert_allclose(old_default, [[0, 0], [1, -2], [1, -2], [0, 0]], atol=1e-12)


@pytest.mark.parametrize("bad", [0.0, -1.0, np.nan, np.inf])
def test_sizing_rejects_invalid_multipliers(bad):
    series = pd.Series([1.0, 1.0], index=_index(2))
    with pytest.raises(ValueError, match="contract_size"):
        compute_target_units("signal_notional", series, series * 100, 100, contract_size=bad)
    with pytest.raises(ValueError, match="contract_sizes"):
        scale_signal_notional_matrix(
            np.ones((2, 1)), np.full((2, 1), 100.0), np.asarray([100.0]),
            contract_sizes=np.asarray([bad]),
        )


@pytest.mark.parametrize("mode", ["notional", "unit", "signal_notional", "signal"])
def test_legacy_notional_sizing_has_one_currency_unit_of_profit(mode):
    idx = _index()
    close = pd.Series([100.0, 100.0, 101.0, 101.0], index=idx)
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    portfolio = _portfolio(close, signal, hedge_type=mode, contract_size=10.0)
    backtest = _backtester(close, signal, hedge_type=mode, contract_size={"A": 10.0, "B": 2.0})
    for result in (portfolio.result, backtest.result):
        assert result.positions["Position_A"].iloc[1] == pytest.approx(0.1)
        np.testing.assert_allclose(result.equity, [1000, 1000, 1001, 1001], atol=1e-10)


@pytest.mark.parametrize("mode", ["signal_notional", "notional", "unit"])
def test_native_vectorized_shared_sizing_callers_pass_multiplier(mode):
    idx = _index()
    close = pd.Series([100.0, 100.0, 101.0, 101.0], index=idx)
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    backend = NativeVectorizedBackend(NativeVectorizedConfig(
        account=AccountConfig(initial_capital=1000), use_funding=False,
    ))
    result = backend.run_signals(
        datetime_index=idx, positions={"A": signal}, closes={"A": close},
        highs={"A": close}, lows={"A": close}, alloc_per_trade=100.0,
        contract_size={"A": 10.0}, hedge_type=mode,
    )
    assert result.positions["Position_A"].iloc[1] == pytest.approx(0.1)
    np.testing.assert_allclose(result.equity, [1000, 1000, 1001, 1001], atol=1e-10)


@pytest.mark.parametrize("mode", ["signal_notional", "notional", "unit"])
def test_event_adapter_and_prepared_scorer_pass_multiplier(mode):
    idx = _index()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    close = pd.Series(100.0, index=idx)
    orders = _build_market_rebalance_orders(
        idx, {"A": signal}, {"A": close}, 100.0, mode, True, ["A"],
        contract_size={"A": 10.0},
    )
    assert [order.qty for order in orders] == pytest.approx([0.1, 0.1])
    scorer = object.__new__(NativePreparedPublicWfoScorerV1)
    scorer.target_mode = mode
    scorer.config = SimpleNamespace(use_pyramiding=True)
    targets = scorer._target_units(
        signal.to_numpy().reshape(-1, 1), close.to_numpy().reshape(-1, 1), idx, 100.0,
        contract_size=10.0,
    )
    np.testing.assert_allclose(targets[:, 0], [0, 0.1, 0.1, 0], atol=1e-12)


def test_missing_mark_carries_last_price_without_phantom_pnl_or_input_mutation():
    idx = _index()
    close = pd.Series([100.0, 100.0, np.nan, 100.0], index=idx)
    original = close.copy(deep=True)
    signal = pd.Series([0.0, 1.0, 1.0, 1.0], index=idx)
    result = _portfolio(close, signal).result
    np.testing.assert_allclose(result.equity, [1000, 1000, 1000, 1000])
    np.testing.assert_allclose(result.positions["Position_A"], [0, 1, 1, 1])
    np.testing.assert_allclose(result.closes["Close_A"], [100, 100, 100, 100])
    pd.testing.assert_series_equal(close, original)


@pytest.mark.parametrize("missing_timestamp", [False, True])
@pytest.mark.parametrize("signal_values,expected", [([0, 0, 1, 1], [0, 0, 0, 1]), ([0, 1, 0, 0], [0, 1, 1, 0])])
def test_stale_mark_cannot_fill_entry_or_exit(missing_timestamp, signal_values, expected):
    idx = _index()
    close = pd.Series([100.0, 100.0, np.nan, 100.0], index=idx)
    if missing_timestamp:
        close = close.drop(idx[2])
    signal = pd.Series(signal_values, index=idx, dtype=float)
    result = _portfolio(close, signal).result
    np.testing.assert_allclose(result.positions["Position_A"], expected)
    np.testing.assert_allclose(result.equity, [1000, 1000, 1000, 1000])


@pytest.mark.parametrize("mode", ["signal_notional", "notional", "unit"])
def test_leading_missing_marks_do_not_backfill_or_block_first_real_anchor(mode):
    idx = _index()
    close = pd.Series([np.nan, np.nan, 100.0, 110.0], index=idx)
    signal = pd.Series(1.0, index=idx)
    result = _portfolio(close, signal, hedge_type=mode).result
    np.testing.assert_allclose(result.equity, [1000, 1000, 1000, 1010])
    np.testing.assert_allclose(result.positions["Position_A"].iloc[:3], [0, 0, 1])
    assert np.isfinite(result.positions.to_numpy()).all()


@pytest.mark.parametrize("size_kwarg", ["qty_step", "lot_size", "slot_size"])
def test_legacy_facade_forwards_quantity_aliases_and_execution(size_kwarg):
    idx = _index()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    result = PortfolioBacktestEngine(
        positions={"A": signal}, closes={"A": pd.Series(100.0, index=idx)}, datetime_index=idx,
        backend="legacy_portfolio", account=AccountConfig(initial_capital=1000),
        execution=ExecutionConfig(slippage_bps=100), fee_rate=0.0, use_funding=False,
        alloc_per_trade=15.0, min_notional=200.0, **{size_kwarg: 0.1},
    ).result
    assert result.positions.to_numpy().sum() == 0.0
    assert result.metadata["quantity_constraints"]["A"]["qty_step"] == 0.1
    np.testing.assert_allclose(result.equity, [1000, 1000, 1000, 1000])


def test_legacy_facade_combines_execution_and_instrument_notional_minima():
    idx = _index()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    for instrument_minimum, expected in [(0.0, 150.0), (200.0, 200.0)]:
        result = PortfolioBacktestEngine(
            positions={"A": signal}, closes={"A": pd.Series(100.0, index=idx)}, datetime_index=idx,
            backend="legacy_portfolio", account=AccountConfig(initial_capital=1000),
            execution=ExecutionConfig(min_order_notional=150.0), fee_rate=0.0, use_funding=False,
            alloc_per_trade=100.0,
            instruments={"A": InstrumentSpec("A", min_notional=instrument_minimum)},
        ).result
        assert result.metadata["quantity_constraints"]["A"]["min_notional"] == expected
        np.testing.assert_allclose(result.positions, 0.0)


def test_legacy_facade_slippage_and_per_leg_fee_attribution_are_exact():
    idx = _index()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    result = PortfolioBacktestEngine(
        positions={"A": signal, "B": -signal},
        closes={s: pd.Series(100.0, index=idx) for s in ("A", "B")}, datetime_index=idx,
        backend="legacy_portfolio", account=AccountConfig(initial_capital=1000),
        execution=ExecutionConfig(slippage_bps=100), fee_rate=0.01, use_funding=False,
        alloc_per_trade=100.0, contract_size={"A": 10.0, "B": 2.0},
    ).result
    np.testing.assert_allclose(result.equity, [1000, 996, 996, 992], atol=1e-10)
    report = result.metadata["symbol_pnl_report"].set_index(["timestamp", "symbol"])
    assert report.loc[(idx[1], "A"), "fee"] == pytest.approx(1.01)
    assert report.loc[(idx[1], "B"), "fee"] == pytest.approx(0.99)
    assert report.loc[(idx[1], "A"), "total_pnl"] == pytest.approx(-2.01)
    assert report.loc[(idx[1], "B"), "total_pnl"] == pytest.approx(-1.99)
    assert result.metadata["slippage_total"] == pytest.approx(4.0)


def test_legacy_portfolio_checks_delta_minimum_but_allows_small_reduction():
    idx = _index(6)
    signal = pd.Series([0, 1, 1.1, 0.9, 0.1, 0], index=idx, dtype=float)
    result = _portfolio(
        pd.Series(100.0, index=idx), signal, min_qty=0.5, min_notional=50.0,
    ).result
    np.testing.assert_allclose(result.positions["Position_A"], [0, 1, 1, 0.9, 0.1, 0], atol=1e-12)


@pytest.mark.parametrize("mode,weight,allocation", [("signal_notional", 1.0, 100.0), ("%_equity", 2.0, 1.0)])
def test_backtester_publishes_accepted_positions_after_rejection(mode, weight, allocation):
    idx = _index()
    signal = pd.Series([0.0, 1.0, 1.0, 1.0], index=idx)
    result = _backtester(
        pd.Series(100.0, index=idx), signal * weight, hedge_type=mode, initial_capital=50.0,
        alloc_per_trade=allocation,
    ).result
    np.testing.assert_allclose(result.equity, [50, 50, 50, 50])
    np.testing.assert_allclose(result.positions, 0.0)
    assert result.metadata["positions_semantics"] == "accepted_contract_units"
    assert result.metadata["legacy_requested_positions_report"]["Position_A"].iloc[1] > 0.0


def test_backtester_equity_sizing_reports_contracts_and_freezes_carried_units():
    idx = _index()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    result = _backtester(
        pd.Series([100.0, 100.0, 110.0, 110.0], index=idx), signal,
        hedge_type="%_equity", alloc_per_trade=0.1, contract_size={"A": 10.0, "B": 1.0},
    ).result
    np.testing.assert_allclose(result.positions["Position_A"], [0, 0.1, 0.1, 0], atol=1e-12)
    np.testing.assert_allclose(result.equity, [1000, 1000, 1010, 1010], atol=1e-10)
    np.testing.assert_allclose(result.metadata["legacy_requested_positions_report"]["Position_A"], [0, 1, 1, 0])


@pytest.mark.parametrize("mode,weight,allocation", [("signal_notional", 1.0, 500.0), ("%_equity", 5.0, 1.0)])
def test_backtester_accepted_positions_are_flat_from_liquidation(mode, weight, allocation):
    idx = _index()
    signal = pd.Series([0.0, 1.0, 1.0, 1.0], index=idx)
    result = _backtester(
        pd.Series([100.0, 100.0, 80.0, 80.0], index=idx), signal * weight,
        hedge_type=mode, initial_capital=100.0, leverage=10.0, alloc_per_trade=allocation,
    ).result
    assert result.liquidation_bar == 2
    np.testing.assert_allclose(result.positions["Position_A"], [0, 5, 0, 0])
    np.testing.assert_allclose(result.equity, [100, 100, 0, 0])


@pytest.mark.parametrize(
    "closes,side,expected_equity,expected_hits",
    [([100, 200, 100], 1.0, 900.0, (0.0, 0.0)),
     ([100, 50, 100], -1.0, 950.0, (0.0, 0.0)),
     ([100, 100, 110], 1.0, 1010.0, (100.0, 0.0)),
     ([100, 100, 90], -1.0, 1010.0, (0.0, 100.0))],
)
def test_hitrate_uses_carried_side_and_includes_exit_bar(closes, side, expected_equity, expected_hits):
    idx = _index(3)
    portfolio = _portfolio(
        pd.Series(closes, index=idx, dtype=float), pd.Series([0, side, 0], index=idx), hedge_type="unit",
    )
    assert portfolio.result.equity.iloc[-1] == pytest.approx(expected_equity)
    assert portfolio.hitrate_per_symbol()["A"] == expected_hits


def test_hitrate_uses_net_symbol_pnl_after_funding_not_price_direction():
    idx = pd.date_range("2024-01-01 06:00", periods=3, freq="1h", tz="UTC")
    portfolio = _portfolio(
        pd.Series([100.0, 100.0, 101.0], index=idx), pd.Series([0, 1, 0], index=idx),
        use_funding=True, funding_rate=0.02,
    )
    assert portfolio.result.equity.iloc[-1] == pytest.approx(998.98)
    assert portfolio.hitrate_per_symbol()["A"] == (0.0, 0.0)


def test_legacy_funding_uses_shared_event_aggregation_once():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    result = _portfolio(
        pd.Series(100.0, index=idx), pd.Series([0, 1, 1], index=idx),
        use_funding=True, funding_rate=0.01,
    ).result
    np.testing.assert_allclose(result.equity, [1000, 1000, 997])
    assert result.metadata["funding_cost_total"] == pytest.approx(3.0)


def test_legacy_liquidation_has_no_phantom_funding_or_exit_costs():
    idx = pd.date_range("2024-01-01 06:00", periods=4, freq="1h", tz="UTC")
    close = pd.Series(100.0, index=idx)
    low = pd.Series([100.0, 100.0, 70.0, 100.0], index=idx)
    portfolio = _portfolio(
        close, pd.Series([0, 1, 1, 1], index=idx), initial_capital=100.0,
        alloc_per_trade=500.0, leverage=10.0, use_funding=True, funding_rate=0.02,
        highs={"A": close}, lows={"A": low},
    )
    result = portfolio.result
    assert result.liquidation_bar == 2
    report = result.metadata["symbol_pnl_report"].set_index("timestamp")
    assert report.loc[idx[2], "funding_cost"] == 0.0
    assert report.loc[idx[2], "fee"] == 0.0
    assert report.loc[idx[2], "liquidation_adjustment"] == pytest.approx(100.0)
    assert report["total_pnl"].sum() == pytest.approx(-100.0)
    assert portfolio.hitrate_per_symbol()["A"] == (0.0, 0.0)


@pytest.mark.parametrize("account_changes", [
    {"margin_mode": MarginMode.CASH}, {"margin_mode": MarginMode.ISOLATED},
    {"margin_mode": MarginMode.PORTFOLIO}, {"oms_mode": OmsMode.HEDGING}, {"margin_buffer": 0.5},
])
def test_legacy_facade_rejects_unsupported_account_models(account_changes):
    idx = _index()
    with pytest.raises(NotImplementedError):
        PortfolioBacktestEngine(
            positions={"A": pd.Series(1.0, index=idx)}, closes={"A": pd.Series(100.0, index=idx)},
            datetime_index=idx, backend="legacy_portfolio", use_funding=False,
            account=replace(AccountConfig(initial_capital=1000), **account_changes),
        )


@pytest.mark.parametrize("execution_changes", [
    {"fill_price_policy": FillPricePolicy.OPEN}, {"fill_price_policy": FillPricePolicy.NEXT_OPEN},
    {"fill_price_policy": FillPricePolicy.TOUCH}, {"allow_partial_fill": True},
    {"same_bar_policy": SameBarPolicy.ENTRY_FIRST}, {"reject_on_insufficient_margin": False},
])
def test_legacy_facade_rejects_unsupported_execution(execution_changes):
    idx = _index()
    with pytest.raises(NotImplementedError):
        PortfolioBacktestEngine(
            positions={"A": pd.Series(1.0, index=idx)}, closes={"A": pd.Series(100.0, index=idx)},
            datetime_index=idx, backend="legacy_portfolio", use_funding=False,
            execution=replace(ExecutionConfig(), **execution_changes),
        )


@pytest.mark.parametrize("factory", [_portfolio, _backtester])
@pytest.mark.parametrize("bad_config", [{"leverage": np.nan}, {"contract_size": np.inf}, {"margin_buffer": 0.01}])
def test_direct_legacy_configuration_fails_closed(factory, bad_config):
    idx = _index()
    with pytest.raises(ValueError):
        factory(pd.Series(100.0, index=idx), pd.Series(1.0, index=idx), **bad_config)
