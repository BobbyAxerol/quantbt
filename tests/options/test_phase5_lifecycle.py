from __future__ import annotations

import pytest

from quantbt import (
    ExerciseStyle,
    OptionInstrumentSpec,
    OptionKind,
    OptionLedger,
    OptionSettlementRepresentation,
    PremiumConvention,
    SettlementStyle,
    option_expiry_payoff_per_unit,
    settle_option_expiry,
)
from quantbt.core.orders import Fill
from quantbt.core.schema import LiquiditySide, OrderSide


def _expiry_ns() -> int:
    return 1_800_000_000_000_000_000


def _linear_call() -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol="BTC-USDC-C",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.CALL,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.CASH,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="USDC",
        premium_currency="USDC",
        quote_currency="USDC",
    )


def _linear_future_then_cash_put() -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol="BTC-USDC-P",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.PUT,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.FUTURE_THEN_CASH,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="USDC",
        premium_currency="USDC",
        quote_currency="USDC",
    )


def test_phase5_otm_expiry_closes_position_once_with_zero_cashflow():
    spec = _linear_call()
    ledger = OptionLedger.from_cash({"USDC": 10_000.0})
    ledger.apply_fill(
        Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=1.0, price=100.0, liquidity=LiquiditySide.TAKER),
        spec,
        timestamp_ns=1,
    )

    result = settle_option_expiry(ledger, spec, timestamp_ns=_expiry_ns(), settlement_price=90_000.0)

    assert result.itm is False
    assert result.cashflow == pytest.approx(0.0)
    assert ledger.positions[spec.symbol].is_flat
    assert ledger.cash["USDC"] == pytest.approx(9_900.0)
    with pytest.raises(ValueError, match="already been settled"):
        settle_option_expiry(ledger, spec, timestamp_ns=_expiry_ns() + 1, settlement_price=90_000.0)


def test_phase5_itm_linear_cash_payoff_and_future_then_cash_representation():
    call = _linear_call()
    ledger = OptionLedger.from_cash({"USDC": 10_000.0})
    ledger.apply_fill(
        Fill(timestamp=1, symbol=call.symbol, side=OrderSide.BUY, qty=2.0, price=100.0, liquidity=LiquiditySide.TAKER),
        call,
        timestamp_ns=1,
    )

    result = settle_option_expiry(ledger, call, timestamp_ns=_expiry_ns(), settlement_price=105_000.0)

    assert option_expiry_payoff_per_unit(call, 105_000.0) == pytest.approx(5_000.0)
    assert result.cashflow == pytest.approx(10_000.0)
    assert result.representation is OptionSettlementRepresentation.ECONOMIC_CASH
    assert ledger.cash["USDC"] == pytest.approx(19_800.0)

    put = _linear_future_then_cash_put()
    ledger2 = OptionLedger.from_cash({"USDC": 10_000.0})
    ledger2.apply_fill(
        Fill(timestamp=1, symbol=put.symbol, side=OrderSide.BUY, qty=1.0, price=100.0, liquidity=LiquiditySide.TAKER),
        put,
        timestamp_ns=1,
    )
    result2 = settle_option_expiry(ledger2, put, timestamp_ns=_expiry_ns(), settlement_price=95_000.0)
    assert result2.cashflow == pytest.approx(5_000.0)
    assert result2.representation is OptionSettlementRepresentation.FUTURE_THEN_CASH


def test_phase5_inverse_itm_payoff_settles_in_base_currency(option_phase3_registry):
    spec = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    ledger.apply_fill(
        Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=1.0, price=0.01, liquidity=LiquiditySide.TAKER),
        spec,
        timestamp_ns=1,
    )

    result = settle_option_expiry(ledger, spec, timestamp_ns=spec.expiry_ns, settlement_price=110_000.0)

    assert option_expiry_payoff_per_unit(spec, 110_000.0) == pytest.approx(10_000.0 / 110_000.0)
    assert result.cashflow == pytest.approx(10_000.0 / 110_000.0)
    assert ledger.cash["BTC"] == pytest.approx(1.0 - 0.01 + 10_000.0 / 110_000.0)
    identity = ledger.equity_identity_report(conversion_rates={"BTC": 110_000.0}, reporting_currency="USD")
    assert identity["equity"] == pytest.approx((1.0 - 0.01 + 10_000.0 / 110_000.0) * 110_000.0)
