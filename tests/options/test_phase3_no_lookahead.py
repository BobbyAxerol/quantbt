from __future__ import annotations

import pandas as pd
import pytest

from quantbt import OptionSelectionFilters, prepare_option_tape, select_atm_option, select_target_delta_option


def test_phase3_selector_never_uses_future_snapshot(option_phase3_chain, option_phase3_registry):
    chain = option_phase3_chain.copy()
    ts0, ts1 = sorted(chain["timestamp_ns"].unique())
    chain.loc[(chain["timestamp_ns"] == ts1) & (chain["instrument_id"] == "BTC-01FEB26-100000-C.DERIBIT"), "delta"] = 0.90
    tape = prepare_option_tape(chain, option_phase3_registry)
    decision_between_snapshots = int(ts0 + (ts1 - ts0) // 2)

    selected = select_target_delta_option(
        tape,
        decision_between_snapshots,
        target_delta=0.90,
        filters=OptionSelectionFilters(option_kind="call"),
    )

    assert selected.snapshot_timestamp_ns == int(ts0)
    assert selected.delta != pytest.approx(0.90)


def test_phase3_selector_rejects_before_first_snapshot_and_stale_snapshot(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)

    with pytest.raises(ValueError, match="no option snapshot"):
        select_atm_option(tape, int(tape.timestamp_ns[0]) - 1)

    with pytest.raises(ValueError, match="stale"):
        select_atm_option(tape, int(tape.timestamp_ns[-1]) + 10_000_000_000, max_quote_age_ns=1_000_000)


def test_phase3_selector_filters_expired_contracts_at_decision_time(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    decision_after_feb_expiry = int(pd.Timestamp("2026-02-15 00:00:00", tz="UTC").value)

    selected = select_atm_option(
        tape,
        decision_after_feb_expiry,
        filters=OptionSelectionFilters(option_kind="call"),
    )

    assert selected.instrument_id == "BTC-01MAR26-100000-C.DERIBIT"
    assert selected.expiry_ns > decision_after_feb_expiry
