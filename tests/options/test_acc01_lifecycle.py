"""Independent ACC-01 F13/F14 expiry, basis and cash oracles."""

from dataclasses import replace

import pytest

from quantbt import OptionLedger, PremiumConvention, settle_option_expiry
from quantbt.core.orders import Fill
from quantbt.core.schema import OrderSide


def _fill(spec, side, qty=1.0, price=0.02, fee=0.0):
    return Fill(timestamp=1, symbol=spec.symbol, side=side, qty=qty, price=price, fee=fee)


@pytest.mark.parametrize(
    "side,settlement_price,cash,realized,payoff",
    [
        (OrderSide.BUY, 125_000.0, 1.18, 0.18, 0.20),
        (OrderSide.SELL, 125_000.0, 0.82, -0.18, -0.20),
        (OrderSide.BUY, 90_000.0, 0.98, -0.02, 0.0),
        (OrderSide.SELL, 90_000.0, 1.02, 0.02, 0.0),
    ],
)
def test_f13_expiry_retires_basis_without_changing_cash(
    option_phase3_registry, side, settlement_price, cash, realized, payoff
):
    spec = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    ledger.apply_fill(_fill(spec, side), spec)
    result = settle_option_expiry(ledger, spec, timestamp_ns=spec.expiry_ns, settlement_price=settlement_price)

    assert ledger.cash["BTC"] == pytest.approx(cash)
    assert ledger.realized_pnl["BTC"] == pytest.approx(realized)
    assert ledger.positions[spec.symbol].realized_pnl == pytest.approx(realized)
    assert ledger.positions[spec.symbol].avg_entry == 0.0
    assert ledger.positions[spec.symbol].is_flat
    assert ledger.settlement_cashflows["BTC"] == pytest.approx(payoff)
    assert result.realized_pnl_by_currency == pytest.approx({"BTC": realized})
    before = ledger.clone()
    with pytest.raises(ValueError, match="already been settled"):
        settle_option_expiry(ledger, spec, timestamp_ns=spec.expiry_ns, settlement_price=settlement_price)
    assert ledger == before


@pytest.mark.parametrize("side,close_side,realized,cash", [
    (OrderSide.BUY, OrderSide.SELL, 0.75, 1.72),
    (OrderSide.SELL, OrderSide.BUY, -0.75, 0.22),
])
def test_f13_partial_close_then_expiry_preserves_remaining_basis_and_fees(
    option_phase3_registry, side, close_side, realized, cash
):
    original = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    spec = replace(original, multiplier=2.0, contract_size=2.0)
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    # Open 3 * 2 at .02; close 1 * 2 at .035; expire 2 * 2 at .20.
    ledger.apply_fill(_fill(spec, side, qty=3.0, fee=0.01), spec)
    ledger.apply_fill(_fill(spec, close_side, price=0.035, fee=0.02), spec)
    assert ledger.positions[spec.symbol].avg_entry == pytest.approx(0.02)
    result = settle_option_expiry(ledger, spec, timestamp_ns=spec.expiry_ns, settlement_price=125_000.0)

    assert ledger.realized_pnl["BTC"] == pytest.approx(realized)
    assert ledger.cash["BTC"] == pytest.approx(cash)
    assert ledger.fees["BTC"] == pytest.approx(0.03)
    assert result.realized_pnl_by_currency["BTC"] == pytest.approx(0.72 if side is OrderSide.BUY else -0.72)
    assert ledger.events[-1]["entry_cost_basis"] == pytest.approx(0.08 if side is OrderSide.BUY else -0.08)


def test_f13_mixed_currency_basis_and_payoff_remain_separate(option_phase3_registry):
    original = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    spec = replace(original, premium_convention=PremiumConvention.LINEAR_QUOTE,
                   premium_currency="USD", quote_currency="USD", settlement_currency="USDC")
    ledger = OptionLedger.from_cash({"USD": 1_000.0, "USDC": 0.0})
    ledger.apply_fill(_fill(spec, OrderSide.BUY, price=100.0, fee=2.0), spec)
    result = settle_option_expiry(ledger, spec, timestamp_ns=spec.expiry_ns, settlement_price=105_000.0)

    assert ledger.cash == pytest.approx({"USD": 898.0, "USDC": 5_000.0})
    assert ledger.realized_pnl == pytest.approx({"USD": -100.0, "USDC": 5_000.0})
    assert result.realized_pnl_by_currency == pytest.approx({"USD": -100.0, "USDC": 5_000.0})
    assert ledger.positions[spec.symbol].realized_pnl == -100.0
    assert ledger.events[-1]["realized_pnl"] is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["settlement_price", "payoff_per_unit"])
def test_f14_invalid_settlement_does_not_mutate_even_flat_account(option_phase3_registry, bad, field):
    spec = option_phase3_registry.instruments[0]
    ledger = OptionLedger.from_cash({"BTC": -0.1, "USD": 20_000.0})
    before = ledger.clone()
    kwargs = {"timestamp_ns": spec.expiry_ns, "settlement_price": 100_000.0,
              "payoff_per_unit": 0.1, "representation": "economic_cash", field: bad}
    with pytest.raises(ValueError, match="finite"):
        ledger.apply_settlement(spec, **kwargs)
    assert ledger == before


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["qty", "price", "fee"])
def test_f14_invalid_fill_rejects_before_cash_position_or_event_mutation(option_phase3_registry, bad, field):
    spec = option_phase3_registry.instruments[0]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    before = ledger.clone()
    with pytest.raises(ValueError):
        fill = replace(_fill(spec, OrderSide.BUY), **{field: bad})
        ledger.apply_fill(fill, spec)
    assert ledger == before


def test_f14_overflowing_settlement_does_not_mutate_open_position(option_phase3_registry):
    spec = option_phase3_registry.instruments[0]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    ledger.apply_fill(_fill(spec, OrderSide.BUY, qty=10.0), spec)
    before = ledger.clone()
    with pytest.raises(ValueError, match="finite"):
        ledger.apply_settlement(spec, timestamp_ns=spec.expiry_ns, settlement_price=100_000.0,
                                payoff_per_unit=1e308, representation="economic_cash")
    assert ledger == before


def test_f15_ledger_cannot_backdate_an_effective_fill(option_phase3_registry):
    spec = option_phase3_registry.instruments[0]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    fill = replace(_fill(spec, OrderSide.BUY), timestamp=2)
    before = ledger.clone()
    with pytest.raises(ValueError, match="effective fill timestamp"):
        ledger.apply_fill(fill, spec, timestamp_ns=1)
    assert ledger == before
