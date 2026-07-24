from __future__ import annotations

import pytest

from quantbt import (
    ExerciseStyle,
    OptionInstrumentSpec,
    OptionKind,
    PremiumConvention,
    SettlementStyle,
    calculate_option_fee,
    deribit_inverse_fee_schedule,
    deribit_linear_usdc_fee_schedule,
)
from quantbt.core.orders import Fill
from quantbt.core.schema import LiquiditySide, OrderSide


def _expiry_ns() -> int:
    return 1_800_000_000_000_000_000


def _inverse_spec() -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol="BTC-OPT-C",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.CALL,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.INVERSE_BASE,
        settlement_style=SettlementStyle.CASH,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="BTC",
        premium_currency="BTC",
        quote_currency="USD",
    )


def _linear_spec() -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol="BTC-USDC-C",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.CALL,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.FUTURE_THEN_CASH,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="USDC",
        premium_currency="USDC",
        quote_currency="USDC",
    )


def test_phase5_deribit_inverse_fee_is_per_leg_capped_in_base_currency():
    fill = Fill(timestamp=1, symbol="BTC-OPT-C", side=OrderSide.BUY, qty=1.0, price=0.001, liquidity=LiquiditySide.TAKER)
    fee = calculate_option_fee(fill, _inverse_spec(), deribit_inverse_fee_schedule(), reference_price=100_000.0)

    assert fee.currency == "BTC"
    assert fee.raw_fee == pytest.approx(0.0003)
    assert fee.cap == pytest.approx(0.000125)
    assert fee.fee == pytest.approx(0.000125)
    assert fee.capped is True


def test_phase5_deribit_linear_usdc_fee_is_reference_notional_capped_by_premium():
    fill = Fill(timestamp=1, symbol="BTC-USDC-C", side=OrderSide.BUY, qty=1.0, price=100.0, liquidity=LiquiditySide.TAKER)
    fee = calculate_option_fee(fill, _linear_spec(), deribit_linear_usdc_fee_schedule(), reference_price=100_000.0)

    assert fee.currency == "USDC"
    assert fee.raw_fee == pytest.approx(30.0)
    assert fee.cap == pytest.approx(12.5)
    assert fee.fee == pytest.approx(12.5)
    assert fee.capped is True


def test_phase5_option_fee_cap_is_per_leg_not_package_level():
    spec = _linear_spec()
    schedule = deribit_linear_usdc_fee_schedule()
    fills = [
        Fill(timestamp=1, symbol="BTC-USDC-C", side=OrderSide.BUY, qty=1.0, price=100.0, liquidity=LiquiditySide.TAKER),
        Fill(timestamp=1, symbol="BTC-USDC-C", side=OrderSide.SELL, qty=1.0, price=100.0, liquidity=LiquiditySide.TAKER),
    ]

    fees = [calculate_option_fee(fill, spec, schedule, reference_price=100_000.0) for fill in fills]

    assert [fee.fee for fee in fees] == pytest.approx([12.5, 12.5])
    assert sum(fee.fee for fee in fees) == pytest.approx(25.0)
