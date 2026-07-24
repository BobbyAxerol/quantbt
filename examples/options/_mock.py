from __future__ import annotations

import pandas as pd

from quantbt import (
    ExerciseStyle,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    PremiumConvention,
    SettlementStyle,
)


TS0 = int(pd.Timestamp("2026-01-01 00:00:00", tz="UTC").value)
TS1 = int(pd.Timestamp("2026-01-01 01:00:00", tz="UTC").value)
EXPIRY_NEAR = int(pd.Timestamp("2026-02-01 08:00:00", tz="UTC").value)
EXPIRY_FAR = int(pd.Timestamp("2026-03-01 08:00:00", tz="UTC").value)


def linear_registry() -> OptionInstrumentRegistry:
    specs = [
        _linear("BTC-C90", 90_000.0, OptionKind.CALL, EXPIRY_NEAR),
        _linear("BTC-C100", 100_000.0, OptionKind.CALL, EXPIRY_NEAR),
        _linear("BTC-C110", 110_000.0, OptionKind.CALL, EXPIRY_NEAR),
        _linear("BTC-P90", 90_000.0, OptionKind.PUT, EXPIRY_NEAR),
        _linear("BTC-C100-MAR", 100_000.0, OptionKind.CALL, EXPIRY_FAR),
    ]
    return OptionInstrumentRegistry.from_iterable(specs)


def inverse_registry() -> OptionInstrumentRegistry:
    specs = [
        _inverse("BTC-01FEB26-100000-C.DERIBIT", 100_000.0, OptionKind.CALL, EXPIRY_NEAR),
        _inverse("BTC-01FEB26-100000-P.DERIBIT", 100_000.0, OptionKind.PUT, EXPIRY_NEAR),
    ]
    return OptionInstrumentRegistry.from_iterable(specs)


def chain(registry: OptionInstrumentRegistry, *, inverse: bool = False) -> pd.DataFrame:
    rows = []
    for ts, forward, bump in ((TS0, 100_000.0, 0.0), (TS1, 102_000.0, 0.10)):
        for idx, spec in enumerate(registry.instruments):
            base = 0.02 + 0.005 * idx + bump * 0.01 if inverse else 2_000.0 + 250.0 * idx + bump * 100.0
            rows.append(
                {
                    "timestamp_ns": ts,
                    "instrument_id": spec.symbol,
                    "venue": spec.venue.upper(),
                    "underlying_id": spec.underlying_id,
                    "expiry_ns": spec.expiry_ns,
                    "strike": spec.strike,
                    "option_kind": spec.option_kind.value,
                    "bid_price": base * 0.98,
                    "bid_size": 10.0,
                    "ask_price": base * 1.02,
                    "ask_size": 10.0,
                    "mark_price": base,
                    "last_price": base,
                    "index_price": forward,
                    "forward_price": forward,
                    "mark_iv": 0.60,
                    "bid_iv": 0.58,
                    "ask_iv": 0.62,
                    "delta": 0.5 if spec.option_kind is OptionKind.CALL else -0.5,
                    "gamma": 0.0001,
                    "vega": 100.0,
                    "theta": -10.0,
                    "open_interest": 100.0,
                    "volume": 25.0,
                    "quote_currency": spec.quote_currency,
                    "settlement_currency": spec.settlement_currency,
                    "sequence_id": idx,
                    "source_latency_ns": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def _linear(symbol: str, strike: float, kind: OptionKind, expiry_ns: int) -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol=symbol,
        venue="test",
        underlying_id="BTC-PERP.TEST",
        underlying_index_id="BTC-INDEX.TEST",
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
        convention_version="example_linear_v1",
    )


def _inverse(symbol: str, strike: float, kind: OptionKind, expiry_ns: int) -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol=symbol,
        venue="deribit",
        underlying_id="BTC-PERPETUAL.DERIBIT",
        underlying_index_id="BTC-INDEX.DERIBIT",
        option_kind=kind,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.INVERSE_BASE,
        settlement_style=SettlementStyle.CASH,
        strike=strike,
        expiry_ns=expiry_ns,
        settlement_currency="BTC",
        premium_currency="BTC",
        quote_currency="USD",
        multiplier=1.0,
        contract_size=1.0,
        qty_step=0.1,
        convention_version="example_deribit_inverse_v1",
    )
