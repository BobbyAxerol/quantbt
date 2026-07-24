from __future__ import annotations

import pandas as pd
import pytest

from quantbt import CANONICAL_OPTION_CHAIN_COLUMNS, validate_option_chain_frame


def _chain() -> pd.DataFrame:
    timestamp_ns = int(pd.Timestamp("2026-01-01 00:00:00", tz="UTC").value)
    expiry_ns = int(pd.Timestamp("2026-02-01 08:00:00", tz="UTC").value)
    return pd.DataFrame(
        {
            "timestamp_ns": [timestamp_ns, timestamp_ns],
            "instrument_id": ["BTC-01FEB26-100000-C.DERIBIT", "BTC-01FEB26-90000-P.DERIBIT"],
            "venue": ["DERIBIT", "DERIBIT"],
            "underlying_id": ["BTC-PERPETUAL.DERIBIT", "BTC-PERPETUAL.DERIBIT"],
            "expiry_ns": [expiry_ns, expiry_ns],
            "strike": [100_000.0, 90_000.0],
            "option_kind": ["CALL", "PUT"],
            "bid_price": [0.010, 0.020],
            "bid_size": [10.0, 20.0],
            "ask_price": [0.011, 0.022],
            "ask_size": [11.0, 21.0],
            "mark_price": [0.0105, 0.021],
            "last_price": [0.0105, 0.021],
            "index_price": [95_000.0, 95_000.0],
            "forward_price": [95_500.0, 95_500.0],
            "mark_iv": [0.6, 0.7],
            "bid_iv": [0.58, 0.68],
            "ask_iv": [0.62, 0.72],
            "delta": [0.45, -0.35],
            "gamma": [0.0001, 0.0002],
            "vega": [100.0, 120.0],
            "theta": [-10.0, -12.0],
            "open_interest": [100.0, 200.0],
            "volume": [5.0, 10.0],
            "quote_currency": ["USD", "USD"],
            "settlement_currency": ["BTC", "BTC"],
            "sequence_id": [2, 1],
            "source_latency_ns": [1_000, 1_000],
        }
    )


def test_phase1_canonical_option_chain_columns_are_public():
    assert "timestamp_ns" in CANONICAL_OPTION_CHAIN_COLUMNS
    assert "instrument_id" in CANONICAL_OPTION_CHAIN_COLUMNS
    assert "bid_price" in CANONICAL_OPTION_CHAIN_COLUMNS
    assert "settlement_currency" in CANONICAL_OPTION_CHAIN_COLUMNS


def test_phase1_validate_option_chain_frame_sorts_and_normalizes_without_dense_matrix():
    out = validate_option_chain_frame(_chain(), max_spread_bps=2_000)

    assert out["venue"].tolist() == ["deribit", "deribit"]
    assert out["option_kind"].tolist() == ["put", "call"]
    assert out["quote_currency"].tolist() == ["USD", "USD"]
    assert out["settlement_currency"].tolist() == ["BTC", "BTC"]
    assert out["sequence_id"].tolist() == [1, 2]
    assert out["instrument_id"].tolist() == ["BTC-01FEB26-90000-P.DERIBIT", "BTC-01FEB26-100000-C.DERIBIT"]


def test_phase1_validate_option_chain_rejects_missing_required_columns():
    frame = _chain().drop(columns=["forward_price"])
    with pytest.raises(ValueError, match="missing required columns"):
        validate_option_chain_frame(frame)


def test_phase1_validate_option_chain_rejects_crossed_wide_and_expired_quotes():
    crossed = _chain()
    crossed.loc[0, "bid_price"] = 0.02
    crossed.loc[0, "ask_price"] = 0.01
    with pytest.raises(ValueError, match="crossed"):
        validate_option_chain_frame(crossed)

    wide = _chain()
    wide.loc[0, "ask_price"] = 1.0
    with pytest.raises(ValueError, match="max_spread_bps"):
        validate_option_chain_frame(wide, max_spread_bps=10)

    expired = _chain()
    expired["expiry_ns"] = expired["timestamp_ns"]
    with pytest.raises(ValueError, match="expired"):
        validate_option_chain_frame(expired)


def test_phase1_validate_option_chain_rejects_duplicate_snapshot_rows():
    frame = pd.concat([_chain(), _chain().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        validate_option_chain_frame(frame)
