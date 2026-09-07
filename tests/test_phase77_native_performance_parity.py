"""Phase 77 performance closure locks for Rust boundary optimizations.

These tests deliberately assert accounting and retained-output parity rather
than a wall-clock threshold.  Timing is environment dependent; a fast path is
only valid when it is observationally equivalent to the existing certified
contract.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt.backends.native_intrabar_rust import (
    prepare_rust_intrabar_market,
    prepare_rust_intrabar_request,
    run_rust_intrabar_kernel,
)
from quantbt.backends.native_vectorized import NativeVectorizedBackend, NativeVectorizedConfig
from quantbt.core.constraints import build_quantity_constraints
from quantbt.core.intrabar_reference import IntrabarIntentTape
from quantbt.core.market_tape import prepare_market_tape
from quantbt.core.schema import AccountConfig, ExecutionConfig
from quantbt.preparation.native_execution import NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(bars: int = 18) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=bars, freq="1h", tz="UTC")
    close = 100.0 + np.linspace(0.0, 4.0, bars)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": np.full(bars, 10.0),
        },
        index=index,
    )


def _intent(bars: int) -> IntrabarIntentTape:
    entry_side = np.zeros(bars, dtype=np.int8)
    entry_size = np.zeros(bars, dtype=np.float64)
    entry_side[1] = 1
    entry_size[1] = 1.0
    return IntrabarIntentTape.from_arrays(
        entry_side=entry_side,
        entry_size=entry_size,
        stop_value=np.where(np.arange(bars) == 1, 0.04, np.nan),
        take_profit_value=np.where(np.arange(bars) == 1, 0.08, np.nan),
    )


def _intrabar_kwargs(tape, intent):
    from quantbt import ExecutionContract

    return {
        "tape": tape,
        "intent": intent,
        "account": AccountConfig(initial_capital=10_000.0, leverage=3.0, maintenance_ratio=0.005),
        "contract": ExecutionContract.intrabar_bracket(close_on_last_bar=True),
        "fee_rate": 0.0005,
        "slippage_rate": 0.0002,
        "report_level": "audit",
    }


def _assert_intrabar_parity(left, right) -> None:
    for field in (
        "equity",
        "position",
        "average_entry",
        "active_stop",
        "active_take_profit",
        "fees",
        "funding",
        "event_flags",
        "initial_margin",
        "maintenance_margin",
    ):
        np.testing.assert_allclose(
            getattr(left, field).to_numpy(),
            getattr(right, field).to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
    assert left.fills == right.fills
    assert left.fills_report.equals(right.fills_report)
    for key in (
        "native_execution_terminal_fingerprint",
        "fill_count",
        "ambiguity_count",
        "rejected_count",
        "liquidated",
        "liquidation_bar",
    ):
        assert left.metadata[key] == right.metadata[key]


def test_prepared_intrabar_market_skips_only_duplicate_digest_and_request_cache() -> None:
    frame = _frame()
    tape = prepare_market_tape(data=frame, symbols=["BTC"], use_funding=False)
    intent = _intent(tape.n_bars)
    kwargs = _intrabar_kwargs(tape, intent)
    cache = NativeExecutionPreparationCache()
    prepared_market = prepare_rust_intrabar_market(tape=tape, native_preparation_cache=cache)

    # The compatibility route remains content-addressed. The explicit prepared
    # route validates the same mutable intent but does not retain it in L4.
    cached = run_rust_intrabar_kernel(
        **kwargs,
        native_preparation_cache=cache,
    )
    request_entries = cache.diagnostics["tiers"]["request"]["entry_count"]
    ephemeral = run_rust_intrabar_kernel(
        **kwargs,
        prepared_market=prepared_market,
        reuse_request=False,
    )

    _assert_intrabar_parity(cached, ephemeral)
    assert cache.diagnostics["tiers"]["request"]["entry_count"] == request_entries
    assert ephemeral.metadata["prepared_market_owner"] == "reused"
    assert ephemeral.metadata["request_cache_policy"] == "ephemeral_validated"
    assert ephemeral.metadata["prepared_market_signature"] == prepared_market.market.signature


def test_prepared_intrabar_request_preserves_native_fingerprint_without_python_digest(monkeypatch) -> None:
    frame = _frame()
    tape = prepare_market_tape(data=frame, symbols=["BTC"], use_funding=False)
    intent = _intent(tape.n_bars)
    kwargs = _intrabar_kwargs(tape, intent)
    cache = NativeExecutionPreparationCache()
    prepared_market = prepare_rust_intrabar_market(tape=tape, native_preparation_cache=cache)
    content_addressed = prepare_rust_intrabar_request(
        **kwargs,
        native_preparation_cache=cache,
    )

    import quantbt.preparation.native_execution as execution

    monkeypatch.setattr(execution, "_digest", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("digest")))
    ephemeral = prepare_rust_intrabar_request(
        **kwargs,
        prepared_market=prepared_market,
        reuse_request=False,
    )

    assert ephemeral.request.signature == content_addressed.request.signature
    left = dict(ephemeral.request.core.execute())
    right = dict(content_addressed.request.core.execute())
    assert left.keys() == right.keys()
    for key in left:
        if isinstance(left[key], np.ndarray):
            np.testing.assert_array_equal(left[key], right[key])
        else:
            assert left[key] == right[key]


def test_unconstrained_units_target_fast_path_matches_numba_and_exposes_selection() -> None:
    bars = 24
    index = pd.date_range("2026-02-01", periods=bars, freq="1h", tz="UTC")
    closes = np.ascontiguousarray((100.0 + np.linspace(0.0, 6.0, bars))[:, None])
    targets = np.zeros((bars, 1), dtype=np.float64)
    targets[2:15, 0] = 1.0
    targets[15:20, 0] = -1.0

    common = {
        "datetime_index": index,
        "target_units": {"BTC": pd.Series(targets[:, 0], index=index)},
        "closes": {"BTC": pd.Series(closes[:, 0], index=index)},
        "highs": {"BTC": pd.Series(closes[:, 0] + 1.0, index=index)},
        "lows": {"BTC": pd.Series(closes[:, 0] - 1.0, index=index)},
        "funding_rate": 0.0,
        "symbols": ["BTC"],
    }
    config = dict(
        account=AccountConfig(initial_capital=10_000.0, leverage=3.0, maintenance_ratio=0.005),
        execution=ExecutionConfig(slippage_bps=2.0),
        fee_rate=0.0005,
        use_funding=False,
    )
    rust = NativeVectorizedBackend(NativeVectorizedConfig(target_runtime="rust", **config)).run_target_units(**common)
    numba = NativeVectorizedBackend(NativeVectorizedConfig(target_runtime="numba", **config)).run_target_units(**common)

    for field in ("equity", "fees", "funding"):
        np.testing.assert_allclose(
            getattr(rust, field).to_numpy(),
            getattr(numba, field).to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
    np.testing.assert_allclose(rust.positions.to_numpy(), numba.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.margin.to_numpy(), numba.margin.to_numpy(), rtol=0.0, atol=1e-12)
    assert rust.metadata["native_target_execution"]["native_target_specialization"] == "units_unconstrained_delta_skip_v1"


def test_target_typed_metadata_is_scalar_only_and_preserves_legacy_provenance() -> None:
    frame = _frame(10)
    index = frame.index
    backend = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=3.0),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0,
            use_funding=False,
            target_runtime="rust",
        )
    )
    closes = np.ascontiguousarray(frame["close"].to_numpy(dtype=np.float64)[:, None])
    output, metadata, _diagnostics = backend._rust_target_payload(
        idx=index,
        symbol_list=["BTC"],
        closes_m=closes,
        highs_m=np.ascontiguousarray(closes + 1.0),
        lows_m=np.ascontiguousarray(closes - 1.0),
        target_m=np.zeros_like(closes),
        funding_m=np.zeros_like(closes),
        is_funding=np.zeros(len(index), dtype=np.bool_),
        contract_sizes=np.ones(1, dtype=np.float64),
        leverages=np.full(1, 3.0, dtype=np.float64),
        fee_rates=np.zeros(1, dtype=np.float64),
        constraints=build_quantity_constraints(["BTC"]),
        target_kind="units",
        equity_fraction=np.ones(1, dtype=np.float64),
        output_profile=1,
    )

    assert not isinstance(output, dict)
    assert metadata["native_target_no_order_arena"] is True
    assert metadata["native_execution_buffer_transfer"] == "rust_vec_to_numpy_zero_copy"
    assert metadata["native_execution_terminal_fingerprint"] == output.terminal_fingerprint


def test_prepared_rust_runner_profiles_repeat_and_survive_cache_eviction() -> None:
    """Prepared ownership must not weaken report or lifetime contracts."""

    from quantbt import QuantBTEndpoint

    frame = _frame()
    intent = _intent(len(frame))
    endpoint = QuantBTEndpoint.intrabar_bracket_rust(
        initial_capital=10_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0005,
        slippage_bps=2.0,
        use_funding=False,
        report_level="minimal",
    )
    runner = endpoint.prepare_intrabar(data=frame, symbols=["BTC"])
    minimal = runner.run(intent, report_level="minimal")
    standard = runner.run(intent, report_level="standard")
    audit = runner.run(intent, report_level="audit")

    for result in (standard, audit):
        np.testing.assert_allclose(result.equity.to_numpy(), minimal.equity.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(result.positions.to_numpy(), minimal.positions.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(result.fees.to_numpy(), minimal.fees.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(result.funding.to_numpy(), minimal.funding.to_numpy(), rtol=0.0, atol=1e-12)

    assert minimal.fills == ()
    assert standard.fills == ()
    assert len(audit.fills) == audit.metadata["fill_count"]
    assert minimal.metadata["request_cache_policy"] == "ephemeral_validated"
    assert audit.metadata["prepared_market_owner"] == "reused"

    # The runner owns a detached immutable market core. Clearing the cache must
    # release cache references, not invalidate a live runner or alter its run.
    cache = endpoint._rust_intrabar_preparation
    cache.clear(force=True)
    replay = runner.run(intent, report_level="audit")
    np.testing.assert_allclose(replay.equity.to_numpy(), audit.equity.to_numpy(), rtol=0.0, atol=1e-12)
    assert replay.metadata["native_execution_terminal_fingerprint"] == audit.metadata[
        "native_execution_terminal_fingerprint"
    ]
