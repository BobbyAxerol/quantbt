from __future__ import annotations

import math

import pandas as pd
import pytest

from quantbt import (
    ExerciseStyle,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    PremiumConvention,
    SettlementStyle,
    butterfly,
    calendar,
    collar,
    compile_option_package_orders,
    condor,
    covered_call,
    long_call,
    long_put,
    option_expiry_payoff_per_unit,
    risk_reversal,
    short_call,
    short_put,
    straddle,
    strangle,
    vertical,
)


TS = int(pd.Timestamp("2026-01-01", tz="UTC").value)
EXPIRY_NEAR = int(pd.Timestamp("2026-02-01", tz="UTC").value)
EXPIRY_FAR = int(pd.Timestamp("2026-03-01", tz="UTC").value)
S0 = 100.0


@pytest.fixture
def linear_registry() -> OptionInstrumentRegistry:
    specs = []
    for strike in (80.0, 90.0, 100.0, 110.0, 120.0):
        specs.append(_spec(f"C{int(strike)}", strike, OptionKind.CALL, EXPIRY_NEAR))
        specs.append(_spec(f"P{int(strike)}", strike, OptionKind.PUT, EXPIRY_NEAR))
    specs.append(_spec("C100F", 100.0, OptionKind.CALL, EXPIRY_FAR))
    return OptionInstrumentRegistry.from_iterable(specs)


@pytest.mark.parametrize(
    ("name", "builder", "expected"),
    [
        ("long_call", lambda: long_call(TS, "C100"), lambda s: max(s - 100.0, 0.0)),
        ("short_call", lambda: short_call(TS, "C100"), lambda s: -max(s - 100.0, 0.0)),
        ("long_put", lambda: long_put(TS, "P100"), lambda s: max(100.0 - s, 0.0)),
        ("short_put", lambda: short_put(TS, "P100"), lambda s: -max(100.0 - s, 0.0)),
        ("straddle", lambda: straddle(TS, "C100", "P100"), lambda s: max(s - 100.0, 0.0) + max(100.0 - s, 0.0)),
        ("strangle", lambda: strangle(TS, "C110", "P90"), lambda s: max(s - 110.0, 0.0) + max(90.0 - s, 0.0)),
        ("vertical", lambda: vertical(TS, "C100", "C110"), lambda s: max(s - 100.0, 0.0) - max(s - 110.0, 0.0)),
        (
            "butterfly",
            lambda: butterfly(TS, "C90", "C100", "C110"),
            lambda s: max(s - 90.0, 0.0) - 2.0 * max(s - 100.0, 0.0) + max(s - 110.0, 0.0),
        ),
        (
            "condor",
            lambda: condor(TS, "C90", "C100", "C110", "C120"),
            lambda s: max(s - 90.0, 0.0) - max(s - 100.0, 0.0) - max(s - 110.0, 0.0) + max(s - 120.0, 0.0),
        ),
        ("calendar", lambda: calendar(TS, "C100", "C100F"), lambda s: 0.0),
        ("covered_call", lambda: covered_call(TS, "UNDERLYING", "C110"), lambda s: (s - S0) - max(s - 110.0, 0.0)),
        (
            "collar",
            lambda: collar(TS, "UNDERLYING", "P90", "C110"),
            lambda s: (s - S0) + max(90.0 - s, 0.0) - max(s - 110.0, 0.0),
        ),
        ("risk_reversal", lambda: risk_reversal(TS, "P90", "C110"), lambda s: -max(90.0 - s, 0.0) + max(s - 110.0, 0.0)),
    ],
)
def test_v1_strategy_template_golden_payoffs(linear_registry, name, builder, expected):
    package = builder()
    grid = (70.0, 90.0, 100.0, 105.0, 130.0)

    assert package.metadata["template"] in name or name in package.metadata["template"]
    assert compile_option_package_orders(package)
    for settlement_price in grid:
        observed = _terminal_payoff(package, linear_registry, settlement_price)
        assert observed == pytest.approx(expected(settlement_price), abs=1e-12)


def test_short_straddle_and_bearish_risk_reversal(linear_registry):
    short = straddle(TS, "C100", "P100", side="short")
    bearish_rr = risk_reversal(TS, "P90", "C110", direction="bearish")

    for settlement_price in (80.0, 100.0, 125.0):
        assert _terminal_payoff(short, linear_registry, settlement_price) == pytest.approx(
            -(max(settlement_price - 100.0, 0.0) + max(100.0 - settlement_price, 0.0))
        )
        assert _terminal_payoff(bearish_rr, linear_registry, settlement_price) == pytest.approx(
            max(90.0 - settlement_price, 0.0) - max(settlement_price - 110.0, 0.0)
        )


def test_templates_emit_packages_only():
    package = butterfly(TS, "C90", "C100", "C110", quantity=2.0)

    assert not hasattr(package, "payoff")
    assert not hasattr(package, "pnl")
    assert [leg.ratio for leg in package.legs] == [1.0, 2.0, 1.0]
    assert [leg.side.value for leg in package.legs] == ["buy", "sell", "buy"]
    assert len(compile_option_package_orders(package)) == 3


def _terminal_payoff(package, registry: OptionInstrumentRegistry, settlement_price: float) -> float:
    instruments = registry.by_symbol
    total = 0.0
    for leg in package.legs:
        signed_qty = float(package.quantity) * float(leg.ratio) * float(leg.side.sign)
        if leg.instrument_id in instruments:
            payoff = option_expiry_payoff_per_unit(instruments[leg.instrument_id], settlement_price)
            total += signed_qty * payoff * float(instruments[leg.instrument_id].multiplier)
        elif leg.metadata.get("asset_role") == "underlying":
            total += signed_qty * (float(settlement_price) - S0)
        else:
            raise AssertionError(f"unknown leg in golden payoff test: {leg.instrument_id}")
    assert math.isfinite(total)
    return total


def _spec(symbol: str, strike: float, kind: OptionKind, expiry_ns: int) -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol=symbol,
        venue="test",
        underlying_id="UNDERLYING",
        underlying_index_id="UNDERLYING-INDEX",
        option_kind=kind,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.CASH,
        strike=strike,
        expiry_ns=expiry_ns,
        settlement_currency="USD",
        premium_currency="USD",
        quote_currency="USD",
        multiplier=1.0,
        contract_size=1.0,
        qty_step=1.0,
        convention_version="golden_linear_v1",
    )
