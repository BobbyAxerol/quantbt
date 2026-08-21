"""P2 native-driver differential tests.

These tests deliberately compare the new opt-in Rust IR/planning slices with
the existing Python contracts. They do not promote any legacy endpoint route.
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
    NativeIRFold,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    RustNativeIRRunner,
)
from quantbt.core.package_execution_contracts import (
    PackageLegRequest,
    PackageTransactionPolicy,
    execute_package_transaction_reference,
)
from quantbt.core.portfolio_execution_contracts import (
    PortfolioMarginAllocationPolicy,
    execute_portfolio_target_reference,
)


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(n: int = 12) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    close = np.asarray([100.0, 100.5, 101.0, 100.0, 99.0, 100.0, 102.0, 101.5, 100.5, 99.5, 100.5, 101.0])[:n]
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def _runner(frame: pd.DataFrame):
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    runner = backend.prepare_rust_batched_runner(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        contract_size=1.0,
    )
    return backend, runner


@pytest.mark.parametrize(
    ("kind", "signal", "parameters"),
    [
        (
            NativeStrategyKind.SIGNAL_TARGET,
            np.array([0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
            NativeStrategyParameters(quantity=1.0),
        ),
        (
            NativeStrategyKind.GRID_LEVEL,
            np.array([0.0, 1.0, 2.0, 1.0, 0.0, -1.0, -2.0, -1.0, 0.0, 0.0, 0.0, 0.0]),
            NativeStrategyParameters(quantity=0.5),
        ),
        (
            NativeStrategyKind.DCA_PERIODIC,
            np.array([0.0, 1.0, 1.0, 1.0, 0.0, -1.0, -1.0, -1.0, 0.0, 0.0, 0.0, 0.0]),
            NativeStrategyParameters(quantity=0.5, dca_period=2, max_levels=3),
        ),
        (
            NativeStrategyKind.FIXED_BRACKET,
            np.array([0.0, 1.0, 1.0, 0.0, 0.0, -1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            NativeStrategyParameters(quantity=0.5, take_profit_pct=0.04, stop_loss_pct=0.03),
        ),
    ],
)
def test_native_ir_python_reference_and_rust_audit_are_execution_parity_locked(kind, signal, parameters):
    frame = _frame()
    backend, full_runner = _runner(frame)
    program = NativeStrategyIR(kind, "BTC", parameters=parameters)
    reference = program.reference_tape(frame.index, signal, frame["close"])
    compiled = backend.compile_order_commands(frame.index, reference.commands, symbols=["BTC"])
    python = backend.run_order_commands(
        frame.index,
        reference.commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        contract_size=1.0,
        market_arrays=backend.prepare_market_arrays(
            datetime_index=frame.index,
            closes={"BTC": frame["close"]},
            highs={"BTC": frame["high"]},
            lows={"BTC": frame["low"]},
            symbols=["BTC"],
        ),
        compiled_commands=compiled,
        report_level="minimal",
        _force_python_backend=True,
    )
    rust = RustNativeIRRunner(full_runner, program).run_audit(signal)
    payload = rust.payload

    assert payload["strategy_ir_fingerprint"] == program.fingerprint
    assert tuple(RustNativeIRRunner(full_runner, program).disassemble()) == program.disassemble()
    assert int(payload["strategy_ir_command_count"]) == len(reference.commands)
    np.testing.assert_allclose(payload["equity"], python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        payload["positions"][:, 0],
        python.positions["Position_BTC"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(payload["fees"], python.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        payload["turnover"],
        python.diagnostics["turnover"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    assert int(payload["fill_count"]) == int(python.metadata["lifecycle_counters"]["fill_count"])
    assert int(payload["event_count"]) == int(python.metadata["lifecycle_counters"]["event_count"])
    assert int(payload["rejected_count"]) == int(python.metadata["lifecycle_counters"]["rejected_count"])


def test_native_ir_batch_has_single_run_parity_and_worker_count_determinism():
    frame = _frame()
    _, full_runner = _runner(frame)
    program = NativeStrategyIR(NativeStrategyKind.SIGNAL_TARGET, "BTC", parameters=NativeStrategyParameters(quantity=1.0))
    runner = RustNativeIRRunner(full_runner, program)
    signals = np.asarray(
        [
            [0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, -1.0, -1.0, 0.0, 1.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, -1.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    parameter_matrix = np.asarray(
        [[1.0, 0.0, 0.0, 0.0], [0.5, 0.0, 0.0, 0.0], [1.5, 0.0, 0.0, 0.0], [1.0, 0.5, 0.0, 0.0]],
        dtype=np.float64,
    )
    one = runner.run_batch_score(signals, parameter_matrix=parameter_matrix, workers=1)
    assert one.metadata["shared_market_copies_per_scenario"] == 0
    assert one.metadata["boundary_calls"] == 1
    for workers in (2, 4, 8):
        parallel = runner.run_batch_score(
            signals,
            parameter_matrix=parameter_matrix,
            workers=workers,
            chunk_size=1,
        )
        np.testing.assert_array_equal(one.scenario_id, parallel.scenario_id)
        np.testing.assert_array_equal(one.status, parallel.status)
        np.testing.assert_allclose(one.final_equity, parallel.final_equity, rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(one.total_fee, parallel.total_fee, rtol=0.0, atol=1e-12)
        np.testing.assert_array_equal(one.top_ids(2), parallel.top_ids(2))
    for row in range(len(signals)):
        single = runner.run_score(signals[row], parameters=parameter_matrix[row])
        assert one.final_equity[row] == pytest.approx(single.final_equity, abs=1e-12)
    selected = int(one.top_ids(1)[0])
    audit = runner.run_audit(signals[selected], parameters=parameter_matrix[selected])
    assert float(audit.payload["final_equity"]) == pytest.approx(
        one.final_equity[selected], abs=1e-12
    )


def test_native_ir_fold_batch_executes_only_causal_oos_with_fresh_account_parity():
    frame = _frame()
    _, full_runner = _runner(frame)
    program = NativeStrategyIR(
        NativeStrategyKind.SIGNAL_TARGET,
        "BTC",
        parameters=NativeStrategyParameters(quantity=1.0),
    )
    runner = RustNativeIRRunner(full_runner, program)
    signals = np.asarray(
        [
            [0.0, 1.0, 1.0, 0.0, -1.0, 0.0, 0.0, 1.0, 1.0, 0.0, -1.0, 0.0],
            [0.0, -1.0, -1.0, 0.0, 1.0, 0.0, 0.0, -1.0, -1.0, 0.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    parameter_matrix = np.asarray(
        [[1.0, 0.0, 0.0, 0.0], [0.5, 0.0, 0.0, 0.0]], dtype=np.float64
    )
    fold = NativeIRFold(
        fold_id=7,
        warmup_start=0,
        train_start=0,
        train_end=6,
        test_start=6,
        test_end=len(frame),
    )
    folded = runner.run_fold_batch_score(
        signals,
        fold,
        parameter_matrix=parameter_matrix,
        workers=2,
        chunk_size=1,
    )
    _, oos_full_runner = _runner(frame.iloc[fold.test_start : fold.test_end])
    oos_runner = RustNativeIRRunner(oos_full_runner, program)
    for scenario in range(len(signals)):
        single = oos_runner.run_score(
            signals[scenario, fold.test_start : fold.test_end],
            parameters=parameter_matrix[scenario],
        )
        assert folded.final_equity[scenario] == pytest.approx(single.final_equity, abs=1e-12)
    assert folded.metadata["fold_id"] == fold.fold_id
    assert folded.metadata["execution_bars"] == fold.test_end - fold.test_start
    assert folded.metadata["market_windows_created"] == 0
    assert folded.metadata["fold_market_window_bytes"] == 0
    assert folded.metadata["fold_market_view_bytes"] > 0
    assert folded.metadata["source_market_bytes"] > folded.metadata["fold_market_view_bytes"]
    assert folded.metadata["market_view_shared"] is True
    assert folded.metadata["shared_market_copies_per_scenario"] == 0


def test_native_ir_fold_rejects_noncausal_boundary_before_rust_execution():
    with pytest.raises(ValueError, match="causal"):
        NativeIRFold(
            fold_id=1,
            warmup_start=0,
            train_start=3,
            train_end=3,
            test_start=4,
            test_end=5,
        )


def test_native_ir_fold_rejects_non_integer_and_out_of_range_boundaries():
    with pytest.raises(TypeError, match="integer"):
        NativeIRFold(0, 0.0, 0, 1, 1, 2)
    with pytest.raises(ValueError, match="u32"):
        NativeIRFold(0, 0, 0, 1, 1, 2**32)


@pytest.mark.parametrize(
    "policy",
    [
        PortfolioMarginAllocationPolicy.SEQUENTIAL_LEGACY,
        PortfolioMarginAllocationPolicy.PRO_RATA_TO_AVAILABLE_MARGIN,
        PortfolioMarginAllocationPolicy.ALL_OR_NONE_TARGET,
        PortfolioMarginAllocationPolicy.REDUCE_FIRST_THEN_INCREASE,
    ],
)
def test_native_portfolio_preflight_matches_python_reference(policy):
    import _quantbt_native

    kwargs = dict(
        contract_sizes=np.array([1.0, 1.0, 1.0]),
        leverages=np.array([2.0, 2.0, 2.0]),
        fee_rates=np.array([0.001, 0.001, 0.001]),
        slippage_rates=np.array([0.0005, 0.0005, 0.0005]),
        tradable=np.array([True, True, True]),
        stale=np.array([False, False, True]),
        min_qty=np.array([0.0, 0.0, 0.0]),
        min_notional=np.array([0.0, 0.0, 0.0]),
    )
    previous = np.array([1.0, -1.0, 0.0])
    requested = np.array([4.0, -4.0, 1.0])
    prices = np.array([100.0, 100.0, np.nan])
    reference = execute_portfolio_target_reference(
        previous,
        requested,
        prices,
        equity=500.0,
        policy=policy,
        **kwargs,
    )
    payload = _quantbt_native.native_portfolio_target_preflight(
        previous,
        requested,
        prices,
        500.0,
        kwargs["contract_sizes"],
        kwargs["leverages"],
        kwargs["fee_rates"],
        kwargs["slippage_rates"],
        kwargs["tradable"],
        kwargs["stale"],
        kwargs["min_qty"],
        kwargs["min_notional"],
        0.0,
        list(PortfolioMarginAllocationPolicy).index(policy),
    )
    for key, expected in (
        ("accepted_units", reference.accepted_units),
        ("delta_qty", reference.delta_qty),
        ("traded_notional", reference.traded_notional),
        ("fees", reference.fees),
        ("slippage", reference.slippage),
        ("initial_margin", reference.initial_margin),
    ):
        np.testing.assert_allclose(payload[key], expected, rtol=0.0, atol=1e-12)
    assert tuple(payload["rejection_reason"]) == reference.rejection_reasons
    assert float(payload["available_equity_after"]) == pytest.approx(reference.available_equity_after, abs=1e-12)
    assert payload["invariants_pass"] is True


@pytest.mark.parametrize(
    "policy",
    [
        PackageTransactionPolicy.ATOMIC_ALL_OR_NONE,
        PackageTransactionPolicy.BEST_EFFORT,
        PackageTransactionPolicy.SEQUENTIAL,
        PackageTransactionPolicy.HEDGE_AFTER_PRIMARY,
    ],
)
def test_native_package_preflight_matches_python_reference(policy):
    import _quantbt_native

    legs = (
        PackageLegRequest("primary", "BTC-PERP", 1.0, 100.0, 50.0, fee_rate=0.001),
        PackageLegRequest("hedge", "BTC-QUARTER", -1.0, 102.0, 500.0, fee_rate=0.001),
    )
    reference = execute_package_transaction_reference(
        "basis", legs, available_equity=300.0, policy=policy, max_staleness_ns=0
    )
    policy_code = {
        PackageTransactionPolicy.SEQUENTIAL: 0,
        PackageTransactionPolicy.BEST_EFFORT: 1,
        PackageTransactionPolicy.ATOMIC_ALL_OR_NONE: 2,
        PackageTransactionPolicy.HEDGE_AFTER_PRIMARY: 3,
    }[policy]
    payload = _quantbt_native.native_package_transaction_preflight(
        42,
        np.array([10, 11], dtype=np.int64),
        np.array([0, 1], dtype=np.uint32),
        np.array([leg.signed_qty for leg in legs]),
        np.array([leg.price for leg in legs]),
        np.array([leg.initial_margin for leg in legs]),
        np.array([leg.fee_rate for leg in legs]),
        np.array([leg.source_age_ns for leg in legs], dtype=np.int64),
        np.array([leg.venue_code for leg in legs], dtype=np.uint16),
        np.array([leg.venue_sequence for leg in legs], dtype=np.uint32),
        np.array([leg.min_qty for leg in legs]),
        np.array([leg.min_notional for leg in legs]),
        np.array([leg.contract_size for leg in legs]),
        300.0,
        policy_code,
        0,
    )
    expected_accepted = np.array(
        [leg.leg_id in set(reference.accepted_legs) for leg in legs], dtype=bool
    )
    np.testing.assert_array_equal(payload["accepted"], expected_accepted)
    assert tuple(payload["rejection_reason"]) == reference.rejection_reasons
    assert float(payload["reserved_margin"]) == pytest.approx(reference.reserved_margin, abs=1e-12)
    assert float(payload["released_margin"]) == pytest.approx(reference.released_margin, abs=1e-12)
    assert float(payload["package_fee"]) == pytest.approx(reference.package_fee, abs=1e-12)
    assert float(payload["residual_notional"]) == pytest.approx(reference.residual_notional, abs=1e-12)
    assert payload["invariants_pass"] is True
