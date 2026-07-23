from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    PremiumConvention,
    SettlementStyle,
    ExerciseStyle,
)


def ns(value: str) -> int:
    return int(pd.Timestamp(value, tz="UTC").value)


@pytest.fixture
def option_phase3_registry() -> OptionInstrumentRegistry:
    expiry_1 = ns("2026-02-01 08:00:00")
    expiry_2 = ns("2026-03-01 08:00:00")
    specs = []
    for symbol, strike, kind, expiry in (
        ("BTC-01FEB26-90000-C.DERIBIT", 90_000.0, OptionKind.CALL, expiry_1),
        ("BTC-01FEB26-100000-C.DERIBIT", 100_000.0, OptionKind.CALL, expiry_1),
        ("BTC-01FEB26-110000-P.DERIBIT", 110_000.0, OptionKind.PUT, expiry_1),
        ("BTC-01MAR26-100000-C.DERIBIT", 100_000.0, OptionKind.CALL, expiry_2),
    ):
        specs.append(
            OptionInstrumentSpec(
                symbol=symbol,
                venue="deribit",
                underlying_id="BTC-PERPETUAL.DERIBIT",
                underlying_index_id="BTC-INDEX.DERIBIT",
                option_kind=kind,
                exercise_style=ExerciseStyle.EUROPEAN,
                premium_convention=PremiumConvention.INVERSE_BASE,
                settlement_style=SettlementStyle.CASH,
                strike=strike,
                expiry_ns=expiry,
                settlement_currency="BTC",
                premium_currency="BTC",
                quote_currency="USD",
                qty_step=0.1,
                convention_version="deribit_inverse_v1",
            )
        )
    return OptionInstrumentRegistry.from_iterable(specs)


@pytest.fixture
def option_phase3_chain() -> pd.DataFrame:
    ts0 = ns("2026-01-01 00:00:00")
    ts1 = ns("2026-01-01 01:00:00")
    expiry_1 = ns("2026-02-01 08:00:00")
    expiry_2 = ns("2026-03-01 08:00:00")
    rows = []
    for ts, forward, seq_base in ((ts0, 100_000.0, 1), (ts1, 102_000.0, 10)):
        rows.extend(
            [
                _row(ts, seq_base + 0, "BTC-01FEB26-90000-C.DERIBIT", 90_000.0, "call", expiry_1, forward, 0.012, 0.013, 0.86),
                _row(ts, seq_base + 1, "BTC-01FEB26-100000-C.DERIBIT", 100_000.0, "call", expiry_1, forward, 0.020, 0.021, 0.50),
                _row(ts, seq_base + 2, "BTC-01FEB26-110000-P.DERIBIT", 110_000.0, "put", expiry_1, forward, 0.030, 0.032, -0.64),
                _row(ts, seq_base + 3, "BTC-01MAR26-100000-C.DERIBIT", 100_000.0, "call", expiry_2, forward, 0.050, 0.052, 0.54),
            ]
        )
    return pd.DataFrame(rows)


def _row(
    timestamp_ns: int,
    sequence_id: int,
    instrument_id: str,
    strike: float,
    option_kind: str,
    expiry_ns: int,
    forward_price: float,
    bid_price: float,
    ask_price: float,
    delta: float,
) -> dict:
    return {
        "timestamp_ns": timestamp_ns,
        "instrument_id": instrument_id,
        "venue": "DERIBIT",
        "underlying_id": "BTC-PERPETUAL.DERIBIT",
        "expiry_ns": expiry_ns,
        "strike": strike,
        "option_kind": option_kind,
        "bid_price": bid_price,
        "bid_size": 10.0,
        "ask_price": ask_price,
        "ask_size": 12.0,
        "mark_price": 0.5 * (bid_price + ask_price),
        "last_price": 0.5 * (bid_price + ask_price),
        "index_price": forward_price - 100.0,
        "forward_price": forward_price,
        "mark_iv": 0.60,
        "bid_iv": 0.58,
        "ask_iv": 0.62,
        "delta": delta,
        "gamma": 0.0001,
        "vega": 100.0,
        "theta": -10.0,
        "open_interest": 100.0,
        "volume": 25.0,
        "quote_currency": "USD",
        "settlement_currency": "BTC",
        "sequence_id": sequence_id,
        "source_latency_ns": 1_000_000,
    }
