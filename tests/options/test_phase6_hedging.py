from __future__ import annotations

import pytest

from quantbt import (
    OptionGreeks,
    OptionHedgeConfig,
    OptionHedgePolicyType,
    OptionLedger,
    compute_net_option_delta,
    hedge_decision,
    run_delta_hedge_path,
)
from quantbt.core.orders import Fill
from quantbt.core.schema import LiquiditySide, OrderSide


def test_phase6_compute_net_option_delta_after_fill_and_greek_recompute(option_phase3_registry):
    spec = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    ledger.apply_fill(
        Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=2.0, price=0.02, liquidity=LiquiditySide.TAKER),
        spec,
        timestamp_ns=1,
    )

    delta = compute_net_option_delta(
        ledger,
        {spec.symbol: OptionGreeks(price=0.02, delta=0.45, gamma=0.0, vega=0.0, theta=0.0, currency="BTC", unit="base")},
        {spec.symbol: spec},
    )

    assert delta == pytest.approx(0.90)


def test_phase6_hedge_pnl_uses_previous_hedge_before_rebalance():
    result = run_delta_hedge_path(
        [1, 2, 3],
        [100.0, 110.0, 105.0],
        [1.0, 1.0, 0.4],
        OptionHedgeConfig(policy=OptionHedgePolicyType.FIXED_THRESHOLD, threshold=0.05),
    )

    report = result.hedge_report
    assert report.loc[0, "trade_qty"] == pytest.approx(-1.0)
    assert report.loc[0, "hedge_qty_after"] == pytest.approx(-1.0)
    assert report.loc[1, "prior_hedge_qty"] == pytest.approx(-1.0)
    assert report.loc[1, "hedge_pnl_for_prior_move"] == pytest.approx(-10.0)
    assert report.loc[2, "hedge_pnl_for_prior_move"] == pytest.approx(5.0)
    assert result.hedge_pnl == pytest.approx(-5.0)
    assert report.loc[2, "trade_qty"] == pytest.approx(0.6)
    assert result.final_hedge_qty == pytest.approx(-0.4)


def test_phase6_hedge_policy_variants_are_explicit():
    hysteresis = hedge_decision(
        timestamp_ns=10,
        net_option_delta=0.08,
        current_hedge_qty=0.0,
        config=OptionHedgeConfig(policy="hysteresis_band", enter_band=0.10, exit_band=0.03),
        currently_active=False,
    )
    assert hysteresis.should_rebalance is False

    hysteresis_active = hedge_decision(
        timestamp_ns=10,
        net_option_delta=0.08,
        current_hedge_qty=0.0,
        config=OptionHedgeConfig(policy="hysteresis_band", enter_band=0.10, exit_band=0.03),
        currently_active=True,
    )
    assert hysteresis_active.should_rebalance is True
    assert hysteresis_active.reason == "hysteresis_exit_band"

    time_based = hedge_decision(
        timestamp_ns=20,
        net_option_delta=1.0,
        current_hedge_qty=0.0,
        config=OptionHedgeConfig(policy="time_based", rebalance_interval_ns=100),
        last_rebalance_timestamp_ns=10,
    )
    assert time_based.should_rebalance is False
    assert time_based.reason == "time_based_not_due"

    vol_scaled = hedge_decision(
        timestamp_ns=20,
        net_option_delta=0.5,
        current_hedge_qty=0.0,
        config=OptionHedgeConfig(policy="realized_vol_scaled_band", realized_vol_multiplier=2.0, min_band=0.01),
        underlying_prices=[100.0, 105.0, 95.0, 110.0],
    )
    assert vol_scaled.band >= 0.01
    assert vol_scaled.should_rebalance is True
