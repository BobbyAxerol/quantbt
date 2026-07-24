from __future__ import annotations

import pytest

from quantbt import (
    OptionKind,
    OptionSelectionFilters,
    available_option_rows,
    prepare_option_tape,
    select_atm_option,
    select_target_delta_option,
    select_target_dte_option,
    select_target_moneyness_option,
)


def test_phase3_select_atm_uses_observable_snapshot(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    decision_ts = int(tape.timestamp_ns[1]) + 10

    selected = select_atm_option(
        tape,
        decision_ts,
        filters=OptionSelectionFilters(option_kind=OptionKind.CALL, min_open_interest=10.0),
    )

    assert selected.snapshot_index == 1
    assert selected.snapshot_timestamp_ns == int(tape.timestamp_ns[1])
    assert selected.decision_timestamp_ns == decision_ts
    assert selected.instrument_id == "BTC-01FEB26-100000-C.DERIBIT"
    assert selected.option_kind is OptionKind.CALL
    assert selected.moneyness == pytest.approx(100_000.0 / 102_000.0)


def test_phase3_select_target_delta_requires_observable_delta(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    decision_ts = int(tape.timestamp_ns[0])

    selected = select_target_delta_option(
        tape,
        decision_ts,
        target_delta=0.55,
        filters=OptionSelectionFilters(option_kind="call", min_bid_size=1.0, min_ask_size=1.0, max_dte_days=40.0),
    )

    assert selected.instrument_id == "BTC-01FEB26-100000-C.DERIBIT"
    assert selected.delta == pytest.approx(0.50)

    chain = option_phase3_chain.copy()
    chain.loc[chain["instrument_id"] == "BTC-01FEB26-100000-C.DERIBIT", "delta"] = float("nan")
    tape_without_delta = prepare_option_tape(chain, option_phase3_registry)
    fallback = select_target_delta_option(
        tape_without_delta,
        decision_ts,
        target_delta=0.55,
        filters=OptionSelectionFilters(option_kind="call", max_dte_days=40.0),
    )
    assert fallback.instrument_id != "BTC-01FEB26-100000-C.DERIBIT"


def test_phase3_select_dte_and_moneyness_filters(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    decision_ts = int(tape.timestamp_ns[0])

    dte = select_target_dte_option(
        tape,
        decision_ts,
        target_dte_days=60.0,
        filters=OptionSelectionFilters(option_kind="call"),
    )
    assert dte.instrument_id == "BTC-01MAR26-100000-C.DERIBIT"

    money = select_target_moneyness_option(
        tape,
        decision_ts,
        target_moneyness=0.90,
        filters=OptionSelectionFilters(option_kind="call", min_dte_days=1.0, max_dte_days=70.0),
    )
    assert money.instrument_id == "BTC-01FEB26-90000-C.DERIBIT"


def test_phase3_liquidity_filters_return_available_rows(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    decision_ts = int(tape.timestamp_ns[0])

    rows = available_option_rows(
        tape,
        decision_ts,
        filters=OptionSelectionFilters(option_kind="call", min_open_interest=50.0, min_volume=20.0, max_spread_bps=1_000),
    )

    assert len(rows) == 3
    assert set(tape.instrument_id[int(row)] for row in rows) == {
        "BTC-01FEB26-90000-C.DERIBIT",
        "BTC-01FEB26-100000-C.DERIBIT",
        "BTC-01MAR26-100000-C.DERIBIT",
    }

    with pytest.raises(ValueError, match="no option candidates"):
        select_atm_option(
            tape,
            decision_ts,
            filters=OptionSelectionFilters(option_kind="call", min_open_interest=1_000_000.0),
        )
