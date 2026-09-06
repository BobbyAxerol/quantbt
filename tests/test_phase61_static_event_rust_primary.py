"""Phase 61 static-event Rust-primary public-route certification.

The static command route is deliberately tested at its public backend boundary.
ABI 0.5 is the normal Rust path; API 0.4 is retained only as an explicit
rollback comparator.  These tests lock accounting parity, direct NativeResult
V2 provenance, and prepared request reuse without pretending that reactive
strategies are part of this phase.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
)
from quantbt.backends._native_event_rust import RustFullRunner
from quantbt.core.native_event_parity import assert_native_event_full_parity


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(*, bars: int = 96) -> pd.DataFrame:
    index = pd.date_range("2026-02-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.08 * phase + 1.75 * np.sin(phase / 6.0)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]] + 0.03,
            "high": close + 1.2,
            "low": close - 1.2,
            "close": close,
            "volume": 1_000.0,
            "funding_rate": np.where(phase % 8 == 0, 0.0001, 0.0),
        },
        index=index,
    )


def _commands(index: pd.DatetimeIndex) -> tuple[OrderCommand, ...]:
    return (
        OrderCommand(
            timestamp=index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.25,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=index[16],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=0.5,
            price=101.5,
            order_id="reduce",
        ),
        OrderCommand(
            timestamp=index[44],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=0.75,
            reduce_only=True,
            order_id="close",
        ),
    )


def _backend(*, native_backend: str, contract: str, abi: str = "0.5") -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=4.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0004,
            use_funding=True,
            native_backend=native_backend,
            execution_contract=contract,
            native_static_abi=abi,
            report_level="audit",
        )
    )


def _run(*, native_backend: str, contract: str, abi: str = "0.5"):
    frame = _frame()
    backend = _backend(native_backend=native_backend, contract=contract, abi=abi)
    return backend.run_order_commands(
        datetime_index=frame.index,
        commands=_commands(frame.index),
        closes={"BTC": frame["close"]},
        opens={"BTC": frame["open"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
        contract_size=1.0,
        report_level="audit",
    )


def _assert_accounting_parity(left, right) -> None:
    for field in ("equity", "positions", "fees", "funding", "margin"):
        np.testing.assert_allclose(
            getattr(left, field).to_numpy(),
            getattr(right, field).to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
    assert left.liquidated == right.liquidated
    assert left.liquidation_bar == right.liquidation_bar
    assert_native_event_full_parity(left, right)


@pytest.mark.parametrize(
    "contract",
    ("event_lifecycle_v2_next_bar_close", "event_lifecycle_v3_next_open"),
)
def test_default_static_abi05_is_typed_no_legacy_session_and_matches_oracles(monkeypatch, contract):
    """The default public route cannot silently reach API 0.4."""

    def legacy_session_was_used(*args, **kwargs):
        raise AssertionError("ABI 0.5 static route must not create FullReactiveSessionCore")

    monkeypatch.setattr(RustFullRunner, "_new_session", legacy_session_was_used)
    rust = _run(native_backend="rust", contract=contract)
    python = _run(native_backend="python", contract=contract)

    _assert_accounting_parity(rust, python)
    metadata = rust.metadata
    assert metadata["native_static_abi_requested"] == "0.5"
    assert metadata["native_static_abi_resolved"] == "0.5"
    assert metadata["native_static_compatibility"] is False
    assert metadata["native_static_execution_boundary_calls"] == 1
    assert metadata["rust_audit_replay"] is False
    assert metadata["native_result_v2"]["result_version"] == 2
    assert metadata["native_result_v2"]["workload_kind"] == "command_tape_v5"
    assert metadata["native_result_v2"]["runtime_class"] == "whole_run_native"
    assert metadata["native_metric_v2"]["contract_version"] == 2


def test_explicit_api04_compat_is_a_rollback_comparator_not_a_default():
    typed = _run(native_backend="rust", contract="event_lifecycle_v3_next_open", abi="0.5")
    compat = _run(native_backend="rust", contract="event_lifecycle_v3_next_open", abi="0.4_compat")

    _assert_accounting_parity(typed, compat)
    assert compat.metadata["native_static_abi_requested"] == "0.4_compat"
    assert compat.metadata["native_static_abi_resolved"] == "0.4_compat"
    assert compat.metadata["native_static_compatibility"] is True
    assert "native_result_v2" not in compat.metadata


def test_typed_prepared_request_reuses_one_rust_owned_tape_and_live_counters():
    frame = _frame()
    backend = _backend(
        native_backend="rust",
        contract="event_lifecycle_v3_next_open",
        abi="0.5",
    )
    market = backend.prepare_market_arrays(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
    )
    compiled = backend.compile_order_commands(frame.index, _commands(frame.index), symbols=["BTC"])
    runner = RustFullRunner(
        idx=frame.index,
        symbols=["BTC"],
        market_arrays=market,
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([4.0], dtype=np.float64),
        fee_rates=np.array([0.0004], dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage=0.0002,
        use_funding=True,
        event_contract="event_lifecycle_v3_next_open",
        opens_arr=frame[["open"]].to_numpy(dtype=np.float64),
        native_static_abi="0.5",
    )
    request_first, native_runner_first = runner._typed_request(compiled, "audit")
    first = runner.run_tape_typed(compiled, profile="audit")
    request_second, native_runner_second = runner._typed_request(compiled, "audit")
    second = runner.run_tape_typed(compiled, profile="audit")

    assert request_first is request_second
    assert native_runner_first is native_runner_second
    np.testing.assert_allclose(first.equity, second.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(first.positions, second.positions, rtol=0.0, atol=1e-12)
    counters = runner.cache_info()
    assert counters["native_static_abi"] == "0.5"
    assert counters["typed_request_entries"] == 1
    assert counters["typed_runner_entries"] == 1
    assert counters["boundary_calls"] == 2
    assert counters["run_count"] == 2
    assert counters["typed_boundary_calls_total"] == 2
    assert counters["typed_run_count_total"] == 2
    assert counters["order_arena_capacity"] >= counters["order_arena_slots"] >= 0
    assert counters["margin_recompute_count"] > 0
    runner.clear_caches()
    assert runner.cache_info()["typed_request_entries"] == 0


def test_prepared_v3_score_requires_real_opens_and_matches_public_static_accounting():
    frame = _frame()
    backend = _backend(
        native_backend="rust",
        contract="event_lifecycle_v3_next_open",
        abi="0.5",
    )
    market = backend.prepare_market_arrays(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
    )
    compiled = backend.compile_order_commands(frame.index, _commands(frame.index), symbols=["BTC"])

    with pytest.raises(ValueError, match="requires explicit opens"):
        backend.run_compiled_tape_score(frame.index, compiled, market_arrays=market)

    score = backend.run_compiled_tape_score(
        frame.index,
        compiled,
        market_arrays=market,
        opens={"BTC": frame["open"]},
    )
    audit = backend.run_order_commands(
        datetime_index=frame.index,
        commands=_commands(frame.index),
        closes={"BTC": frame["close"]},
        opens={"BTC": frame["open"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
        contract_size=1.0,
        market_arrays=market,
        compiled_commands=compiled,
        report_level="audit",
    )
    assert score.metadata["native_static_abi"] == "0.5"
    assert score.metadata["native_metric_v2"]["contract_version"] == 2
    assert score.final_equity == pytest.approx(float(audit.equity.iloc[-1]), abs=1e-12)
    np.testing.assert_allclose(score.final_positions[0], audit.positions["Position_BTC"].iloc[-1], atol=1e-12)
    assert score.total_fee == pytest.approx(float(audit.fees.sum()), abs=1e-12)

    compat_backend = _backend(
        native_backend="rust",
        contract="event_lifecycle_v3_next_open",
        abi="0.4_compat",
    )
    compat_runner = compat_backend.prepare_rust_batched_runner(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
    )
    assert compat_runner.native_static_abi == "0.4_compat"
    compat_runner.clear_caches()


def test_event_driven_endpoint_defaults_to_typed_static_abi_and_preserves_public_result():
    frame = _frame()
    endpoint = QuantBTEndpoint.event_driven(
        input_mode="orders",
        backend="rust",
        profile="audit",
        execution_contract="event_lifecycle_v3_next_open",
        initial_capital=20_000.0,
        leverage=4.0,
        fee_rate=0.0004,
        use_funding=True,
    )
    result = endpoint.simulate(
        data=frame,
        order_commands=_commands(frame.index),
        symbols=["BTC"],
    )

    assert result.metadata["native_static_abi_resolved"] == "0.5"
    assert result.metadata["native_result_v2"]["output_profile"] == "audit"
    assert len(result.equity) == len(frame)
    assert len(result.fills) > 0
