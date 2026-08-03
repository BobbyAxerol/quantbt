from __future__ import annotations

import pytest

from quantbt import (
    OrderAction,
    OrderActivationPolicy,
    OrderCommand,
    OrderSide,
    OrderType,
    TimeInForce,
)

from .conftest import ScheduledCommandStrategy, assert_native_event_full_parity, bars, run_reactive


def _c(timestamp, **kwargs) -> OrderCommand:
    return OrderCommand(timestamp=timestamp, **kwargs)


def _assert_strategy_parity(strategy, df=None, **kwargs):
    df = bars(8) if df is None else df
    oracle = run_reactive("replay_certified", strategy, data=df, **kwargs)
    candidate = run_reactive("single_pass", strategy, data=df, **kwargs)
    assert_native_event_full_parity(candidate, oracle)
    return candidate, oracle


def test_native_event_cancel_replace_amend_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.LIMIT, qty=1.0, price=50.0, order_id="amend-me"),
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.LIMIT, qty=1.0, price=50.0, order_id="cancel-me"),
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.LIMIT, qty=1.0, price=50.0, order_id="replace-me"),
            ],
            1: [
                _c(t0, action=OrderAction.AMEND, target_order_id="amend-me", price=99.0),
                _c(t0, action=OrderAction.CANCEL, target_order_id="cancel-me"),
                _c(
                    t0,
                    action=OrderAction.REPLACE,
                    target_order_id="replace-me",
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=99.0,
                    order_id="replace-new",
                ),
            ],
            2: [_c(t0, action=OrderAction.CANCEL_ALL, symbol="BTC")],
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df)
    report = candidate.metadata["command_report"].sort_values("original_index")
    assert "amend-me" in set(report["order_id"])
    assert "replace-new" in set(report["order_id"])
    assert "cancel-me" in set(report["order_id"])


def test_native_event_parent_activation_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="parent",
                ),
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    qty=0.5,
                    price=102.0,
                    tif=TimeInForce.GTC,
                    reduce_only=True,
                    parent_order_id="parent",
                    activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                    order_id="child-first-fill",
                ),
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    qty=0.5,
                    price=102.5,
                    tif=TimeInForce.GTC,
                    reduce_only=True,
                    parent_order_id="parent",
                    activation_policy=OrderActivationPolicy.ON_PARENT_FULL_FILL,
                    order_id="child-full-fill",
                ),
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df)
    assert "activate" in set(candidate.metadata["order_events"]["event_name"])


def test_native_event_oco_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC, order_id="entry"),
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=102.0,
                    reduce_only=True,
                    parent_order_id="entry",
                    activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                    oco_group_id="bracket",
                    order_id="take-profit",
                ),
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.STOP_MARKET,
                    qty=1.0,
                    trigger_price=95.0,
                    reduce_only=True,
                    parent_order_id="entry",
                    activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                    oco_group_id="bracket",
                    order_id="stop-loss",
                ),
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df)
    assert [fill.order_id for fill in candidate.fills][:2] == ["entry", "take-profit"]
    assert "cancel" in set(candidate.metadata["order_events"]["event_name"])


def test_native_event_gtd_expiry_bar_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=50.0,
                    tif=TimeInForce.GTD,
                    expires_at=df.index[3],
                    order_id="gtd-bid",
                )
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df)
    assert "expire" in set(candidate.metadata["order_events"]["event_name"])


def test_native_event_ioc_fok_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.LIMIT, qty=1.0, price=50.0, tif=TimeInForce.IOC, order_id="ioc-bid"),
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.LIMIT, qty=1.0, price=50.0, tif=TimeInForce.FOK, order_id="fok-bid"),
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=0.25, tif=TimeInForce.IOC, order_id="ioc-market"),
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df)
    assert [fill.order_id for fill in candidate.fills] == ["ioc-market"]


def test_native_event_reduce_only_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [_c(t0, symbol="BTC", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=1.0, reduce_only=True, order_id="bad-reduce")],
            1: [
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC, order_id="entry"),
                _c(t0, symbol="BTC", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=3.0, reduce_only=True, tif=TimeInForce.IOC, order_id="clip-exit"),
            ],
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df)
    assert [fill.qty for fill in candidate.fills] == [1.0, 1.0]


def test_native_event_quantity_constraint_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.07, tif=TimeInForce.IOC, order_id="rounded"),
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=0.01, tif=TimeInForce.IOC, order_id="min-drop"),
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df, qty_step={"BTC": 0.1}, min_qty={"BTC": 0.1})
    assert [fill.qty for fill in candidate.fills] == [1.0]
    assert candidate.metadata["quantity_preflight"]["changed_count"] == 1
    assert candidate.metadata["quantity_preflight"]["dropped_count"] == 1


@pytest.mark.parametrize(
    ("quantity_kwargs", "qty", "expected_qty", "changed", "dropped"),
    [
        ({"lot_size": {"BTC": 0.25}}, 1.13, [1.0], 1, 0),
        ({"min_qty": {"BTC": 0.2}}, 0.19, [], 0, 1),
        ({"min_notional": {"BTC": 150.0}}, 1.0, [], 0, 1),
        ({"qty_step": {"BTC": 0.1}}, 0.30000000000000004, [0.3], 0, 0),
    ],
)
def test_native_event_quantity_constraint_edge_case_parity(
    quantity_kwargs,
    qty,
    expected_qty,
    changed,
    dropped,
):
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=qty,
                    tif=TimeInForce.IOC,
                    order_id="quantity-edge",
                )
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df, **quantity_kwargs)
    assert [fill.qty for fill in candidate.fills] == pytest.approx(expected_qty, abs=1e-15)
    assert candidate.metadata["quantity_preflight"]["changed_count"] == changed
    assert candidate.metadata["quantity_preflight"]["dropped_count"] == dropped


def test_native_event_reduce_only_quantity_constraint_clip_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.07,
                    tif=TimeInForce.IOC,
                    order_id="rounded-entry",
                ),
                _c(
                    t0,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=3.07,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id="rounded-reduce",
                ),
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df, qty_step={"BTC": 0.1}, min_qty={"BTC": 0.1})
    assert [fill.qty for fill in candidate.fills] == [1.0, 1.0]
    assert candidate.positions["Position_BTC"].iloc[-1] == 0.0


def test_native_event_stop_order_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.STOP_MARKET, qty=0.5, trigger_price=102.0, order_id="stop-market"),
                _c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT, qty=0.5, trigger_price=102.0, price=101.0, order_id="stop-limit"),
            ]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df)
    assert {fill.order_id for fill in candidate.fills} == {"stop-market", "stop-limit"}
