from __future__ import annotations

import pytest

from quantbt import OptionFeeResult, OptionLedger
from quantbt.core.orders import Fill
from quantbt.core.schema import LiquiditySide, OrderSide


def _spec(registry, symbol: str):
    return registry.by_symbol[symbol]


def test_phase5_ledger_records_long_premium_fee_and_position(option_phase3_registry):
    spec = _spec(option_phase3_registry, "BTC-01FEB26-100000-C.DERIBIT")
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    fill = Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=2.0, price=0.02, liquidity=LiquiditySide.TAKER)
    fee = OptionFeeResult(fee=0.001, currency="BTC", raw_fee=0.001, cap=1.0, capped=False, schedule_id="test")

    ledger.apply_fill(fill, spec, fee=fee, timestamp_ns=1)

    assert ledger.cash["BTC"] == pytest.approx(1.0 - 0.04 - 0.001)
    assert ledger.fees["BTC"] == pytest.approx(0.001)
    assert ledger.positions[spec.symbol].qty == pytest.approx(2.0)
    assert ledger.positions[spec.symbol].avg_entry == pytest.approx(0.02)
    assert ledger.event_report().iloc[0]["event_type"] == "fill"


def test_phase5_round_trip_no_price_move_equals_spread_plus_fees(option_phase3_registry):
    spec = _spec(option_phase3_registry, "BTC-01FEB26-100000-C.DERIBIT")
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    buy = Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=1.0, price=0.021, liquidity=LiquiditySide.TAKER)
    sell = Fill(timestamp=2, symbol=spec.symbol, side=OrderSide.SELL, qty=1.0, price=0.020, liquidity=LiquiditySide.TAKER)
    fee_buy = OptionFeeResult(fee=0.0001, currency="BTC", raw_fee=0.0001, cap=1.0, capped=False, schedule_id="test")
    fee_sell = OptionFeeResult(fee=0.0001, currency="BTC", raw_fee=0.0001, cap=1.0, capped=False, schedule_id="test")

    ledger.apply_fill(buy, spec, fee=fee_buy, timestamp_ns=1)
    ledger.apply_fill(sell, spec, fee=fee_sell, timestamp_ns=2)

    assert ledger.positions[spec.symbol].is_flat
    assert ledger.cash["BTC"] == pytest.approx(1.0 - 0.001 - 0.0002)
    assert ledger.realized_pnl["BTC"] == pytest.approx(-0.001)
    assert ledger.fees["BTC"] == pytest.approx(0.0002)
    identity = ledger.equity_identity_report(conversion_rates={"BTC": 100_000.0}, reporting_currency="USD")
    assert identity["equity"] == pytest.approx((1.0 - 0.001 - 0.0002) * 100_000.0)
    assert identity["reconciled"] is True


def test_phase5_inverse_btc_premium_and_usd_reporting_equity_reconcile(option_phase3_registry):
    spec = _spec(option_phase3_registry, "BTC-01FEB26-100000-C.DERIBIT")
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    fill = Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=1.0, price=0.01, liquidity=LiquiditySide.TAKER)

    ledger.apply_fill(fill, spec, timestamp_ns=1)
    equity = ledger.equity(
        conversion_rates={"BTC": 100_000.0},
        marks={spec.symbol: 0.01},
        instruments={spec.symbol: spec},
        reporting_currency="USD",
    )

    assert ledger.cash["BTC"] == pytest.approx(0.99)
    assert equity == pytest.approx(100_000.0)
