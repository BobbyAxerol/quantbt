from __future__ import annotations

import numpy as np
import pytest

from quantbt import InstrumentRegistrySignature, PreparedOptionTape, prepare_option_tape


def test_phase3_prepare_option_tape_builds_csr_ragged_arrays(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry, max_spread_bps=1_000)

    assert isinstance(tape, PreparedOptionTape)
    assert tape.snapshot_count == 2
    assert tape.row_count == 8
    assert tape.row_ptr.tolist() == [0, 4, 8]
    assert tape.timestamp_ns.tolist() == sorted(option_phase3_chain["timestamp_ns"].unique().tolist())
    assert tape.instrument_code.dtype == np.int32
    assert tape.option_kind_code.tolist().count(0) == 6
    assert tape.option_kind_code.tolist().count(1) == 2
    assert tape.signature.row_count == 8
    assert tape.signature.snapshot_count == 2
    assert tape.signature.instrument_registry_signature == option_phase3_registry.signature
    assert tape.signature.convention_signature == option_phase3_registry.signature.signature


def test_phase3_prepare_option_tape_rejects_unknown_instrument(option_phase3_chain, option_phase3_registry):
    chain = option_phase3_chain.copy()
    chain.loc[0, "instrument_id"] = "BTC-UNKNOWN.DERIBIT"

    with pytest.raises(ValueError, match="not in registry"):
        prepare_option_tape(chain, option_phase3_registry)


def test_phase3_prepare_option_tape_rejects_registry_static_mismatch(option_phase3_chain, option_phase3_registry):
    bad_strike = option_phase3_chain.copy()
    bad_strike.loc[0, "strike"] = 91_000.0
    with pytest.raises(ValueError, match="strike"):
        prepare_option_tape(bad_strike, option_phase3_registry)

    bad_kind = option_phase3_chain.copy()
    bad_kind.loc[0, "option_kind"] = "put"
    with pytest.raises(ValueError, match="option_kind"):
        prepare_option_tape(bad_kind, option_phase3_registry)


def test_phase3_prepare_option_tape_rejects_crossed_and_stale_source_latency(option_phase3_chain, option_phase3_registry):
    crossed = option_phase3_chain.copy()
    crossed.loc[0, "bid_price"] = crossed.loc[0, "ask_price"] + 0.01
    with pytest.raises(ValueError, match="crossed"):
        prepare_option_tape(crossed, option_phase3_registry)

    stale = option_phase3_chain.copy()
    stale.loc[0, "source_latency_ns"] = 10_000_000_000
    with pytest.raises(ValueError, match="stale source latency"):
        prepare_option_tape(stale, option_phase3_registry, max_source_latency_ns=1_000_000)


def test_phase3_prepared_tape_compatibility_checks(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry, convention_signature=("custom", "v1"))

    tape.validate_compatible(
        registry_signature=option_phase3_registry.signature,
        convention_signature=("custom", "v1"),
        timestamps_ns=tape.timestamp_ns,
    )
    with pytest.raises(ValueError, match="registry signature"):
        tape.validate_compatible(registry_signature=InstrumentRegistrySignature(0, (), (), ()))
    with pytest.raises(ValueError, match="convention signature"):
        tape.validate_compatible(convention_signature=("custom", "v2"))
    with pytest.raises(ValueError, match="timestamp mismatch"):
        tape.validate_compatible(timestamps_ns=[int(tape.timestamp_ns[0])])
