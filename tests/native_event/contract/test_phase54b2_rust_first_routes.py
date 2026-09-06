"""Phase 54B.2 public Stage-B promotion and differential coverage."""

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
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
)
from quantbt.core.execution_trace import compare_canonical_traces
from quantbt.core.native_event_parity import assert_native_event_full_parity
from quantbt.core.native_event_promotion import NativePromotionContext, resolve_native_event_promotion


_STATIC_CAPABILITIES = (
    "native_event_v2_full_contract",
    "native_event_v2_multisymbol",
    "native_event_v2_funding",
    "native_event_v2_liquidation",
    "native_event_v2_cancel_all_oco",
    "native_event_v2_tif_expiry",
    "native_event_v2_relationships",
    "native_event_v2_quantity_preflight",
)
_IR_CAPABILITIES = _STATIC_CAPABILITIES + (
    "native_strategy_ir_v1",
    "native_strategy_ir_signal_target",
    "native_strategy_ir_grid_level",
    "native_strategy_ir_dca_periodic",
    "native_strategy_ir_fixed_bracket",
    "native_strategy_ir_batch_v1",
)


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    path = 100.0 + 0.015 * np.arange(bars, dtype=np.float64) + 1.5 * np.sin(np.arange(bars) / 37.0)
    return pd.DataFrame(
        {
            "open": np.r_[path[0], path[:-1]],
            "high": path + 1.25,
            "low": path - 1.25,
            "close": path,
            "volume": 1_000.0,
        },
        index=index,
    )


def _assert_accounting_equal(left, right) -> None:
    np.testing.assert_allclose(left.equity.to_numpy(), right.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.positions.to_numpy(), right.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.fees.to_numpy(), right.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.funding.to_numpy(), right.funding.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(left.margin.to_numpy(), right.margin.to_numpy(), rtol=0.0, atol=1e-12)
    assert left.liquidated == right.liquidated
    assert left.liquidation_bar == right.liquidation_bar
    assert left.metadata["lifecycle_counters"] == right.metadata["lifecycle_counters"]
    certificate = assert_native_event_full_parity(left, right)
    assert certificate["passed"] is True
    assert left.metadata["canonical_trace_fingerprint"] == right.metadata["canonical_trace_fingerprint"]
    assert compare_canonical_traces(
        left.metadata["canonical_trace_v1"], right.metadata["canonical_trace_v1"]
    )["passed"] is True


def _static_context(*, bars: int, workload_id: str = "event_static_tape_v2_v3") -> NativePromotionContext:
    capabilities = _STATIC_CAPABILITIES if workload_id.startswith("event_static") else _IR_CAPABILITIES
    return NativePromotionContext(
        requested_backend="auto",
        backend_policy="certified_only",
        workload_id=workload_id,
        execution_contract_id="event_lifecycle_v2_next_bar_close",
        strategy_mode="static_commands" if workload_id.startswith("event_static") else "ir_v1",
        profile="audit",
        account_model="linear_quote_settled_gross_cross",
        bars=bars,
        symbol_count=1,
        native_available=True,
        native_compatible=True,
        native_executable=True,
        native_capabilities=capabilities,
        platform_tags=("cpython-3.11+", "linux-x86_64-local"),
    )


def test_phase72_auto_routes_hold_until_current_candidate_evidence_exists():
    static_small = resolve_native_event_promotion(_static_context(bars=9_999), environment={})
    static_promoted = resolve_native_event_promotion(_static_context(bars=10_000), environment={})
    ir_small = resolve_native_event_promotion(
        _static_context(bars=1_999, workload_id="native_strategy_ir_v1"), environment={}
    )
    ir_promoted = resolve_native_event_promotion(
        _static_context(bars=2_000, workload_id="native_strategy_ir_v1"), environment={}
    )

    for decision in (static_small, static_promoted, ir_small, ir_promoted):
        assert (decision.resolved_backend, decision.reason, decision.minimum_bars) == (
            "python",
            "measurement_evidence_not_current",
            0,
        )


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
def test_phase72_public_static_auto_holds_to_python_while_explicit_rust_matches_oracle():
    # Phase 72 withdraws the stale auto-promotion evidence. This regression
    # proves policy and audit parity, so it deliberately uses a compact tape
    # rather than turning a routing test into three 10k-bar audit runs.
    frame = _frame(512)
    commands = [
        OrderCommand(
            timestamp=frame.index[1], symbol="BTC", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="entry",
        ),
        OrderCommand(
            timestamp=frame.index[256], symbol="BTC", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=1.0, reduce_only=True, order_id="exit",
        ),
    ]

    def run(backend: str):
        endpoint = QuantBTEndpoint.event_driven(
            input_mode="orders",
            profile="audit",
            backend=backend,
            initial_capital=10_000.0,
            leverage=5.0,
            fee_rate=0.0002,
            use_funding=False,
        )
        return endpoint.simulate(data=frame, order_commands=commands, symbols=["BTC"])

    auto = run("auto")
    rust = run("rust")
    python = run("python")
    _assert_accounting_equal(auto, rust)
    _assert_accounting_equal(auto, python)
    assert auto.metadata["execution_plan_v1"]["backend"] == "python"
    assert auto.metadata["native_event_promotion_v1"]["reason"] == "measurement_evidence_not_current"
    assert auto.metadata["native_event_promotion_v1"]["minimum_bars"] == 0


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
def test_phase72_static_v3_explicit_rust_uses_one_rust_pass_without_audit_replay():
    frame = _frame(10_000)
    command = OrderCommand(
        timestamp=frame.index[1], symbol="BTC", side=OrderSide.BUY,
        order_type=OrderType.MARKET, qty=1.0, order_id="entry",
    )
    endpoint = QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile="optimize",
        backend="rust",
        execution_contract="event_lifecycle_v3_next_open",
        initial_capital=10_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        use_funding=False,
    )
    result = endpoint.simulate(data=frame, order_commands=[command], symbols=["BTC"])

    assert result.metadata["execution_plan_v1"]["backend"] == "rust"
    assert result.metadata["rust_output_profile"] == "compact"
    assert result.metadata["rust_audit_replay"] is False
    assert result.metadata["lifecycle_counters"]["fill_count"] == 1
    assert len(result.fills) == 0


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
def test_phase72_v3_multisymbol_explicit_rust_and_auto_python_match_oracle():
    """Keep explicit Rust parity while the current auto route is held safely."""

    index = pd.date_range("2024-01-01 07:00", periods=10_000, freq="1h", tz="UTC")
    phase = np.arange(len(index), dtype=np.float64)
    a_close = pd.Series(100.0 + 0.01 * phase, index=index)
    b_close = pd.Series(200.0 - 0.005 * phase, index=index)
    closes = {"A": a_close, "B": b_close}
    opens = {
        "A": pd.Series(a_close.to_numpy() - 0.07, index=index),
        "B": pd.Series(b_close.to_numpy() + 0.09, index=index),
    }
    highs = {symbol: values + 1.0 for symbol, values in closes.items()}
    lows = {symbol: values - 1.0 for symbol, values in closes.items()}
    funding = {symbol: pd.Series(0.0, index=index) for symbol in closes}
    funding["A"].iloc[9] = 0.001
    funding["B"].iloc[17] = -0.0005
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="A", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.13, order_id="long-a",
        ),
        OrderCommand(
            timestamp=index[2], symbol="B", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=0.77, order_id="short-b",
        ),
        OrderCommand(
            timestamp=index[4_000], symbol="A", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=1.13, reduce_only=True, order_id="close-a",
        ),
        OrderCommand(
            timestamp=index[7_000], symbol="B", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=0.77, reduce_only=True, order_id="close-b",
        ),
    )

    def backend(native_backend: str) -> NativeEventBackend:
        return NativeEventBackend(
            NativeEventConfig(
                account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
                execution=ExecutionConfig(slippage_bps=2.0),
                fee_rate=0.0002,
                use_funding=True,
                native_backend=native_backend,
                execution_contract="event_lifecycle_v3_next_open",
                report_level="audit",
            )
        )

    kwargs = dict(
        datetime_index=index,
        commands=commands,
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        funding_rate=funding,
        symbols=["A", "B"],
        contract_size={"A": 1.0, "B": 1.0},
        qty_step={"A": 0.25, "B": 0.10},
        min_qty={"A": 0.25, "B": 0.10},
        report_level="audit",
    )
    rust_raw = backend("rust").run_order_commands(**kwargs)
    rust_prepared_backend = backend("rust")
    prepared_market = rust_prepared_backend.prepare_market_arrays(
        index, closes=closes, highs=highs, lows=lows, funding_rate=funding, symbols=["A", "B"]
    )
    compiled = rust_prepared_backend.compile_order_commands(index, commands, symbols=["A", "B"])
    rust_prepared = rust_prepared_backend.run_order_commands(
        **kwargs,
        market_arrays=prepared_market,
        compiled_commands=compiled,
    )
    auto = backend("auto").run_order_commands(**kwargs)
    python = backend("python").run_order_commands(**kwargs)

    _assert_accounting_equal(rust_raw, rust_prepared)
    _assert_accounting_equal(rust_raw, python)
    _assert_accounting_equal(auto, python)
    assert auto.metadata["native_event_backend_resolved"] == "python"
    assert auto.metadata["native_event_promotion_v1"]["reason"] == "measurement_evidence_not_current"
    assert rust_raw.metadata["native_event_backend_resolved"] == "rust"
    assert rust_raw.metadata["execution_contract_id"] == "event_lifecycle_v3_next_open"
    assert float(rust_raw.funding.sum()) != 0.0
    assert rust_raw.metadata["quantity_preflight"]["changed_count"] >= 2


def _ir_backend(
    native_backend: str,
    *,
    execution_contract: str = "event_lifecycle_v2_next_bar_close",
) -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend=native_backend,
            execution_contract=execution_contract,
        )
    )


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
@pytest.mark.parametrize(
    ("kind", "parameters", "signal"),
    [
        (
            NativeStrategyKind.GRID_LEVEL,
            NativeStrategyParameters(quantity=0.5),
            lambda n: np.where(np.arange(n) % 120 < 40, 1.0, np.where(np.arange(n) % 120 < 80, 2.0, 0.0)),
        ),
        (
            NativeStrategyKind.DCA_PERIODIC,
            NativeStrategyParameters(quantity=0.25, dca_period=20, max_levels=3),
            lambda n: np.where(np.arange(n) % 180 < 90, 1.0, 0.0),
        ),
        (
            NativeStrategyKind.FIXED_BRACKET,
            NativeStrategyParameters(quantity=0.25, take_profit_pct=0.04, stop_loss_pct=0.03),
            lambda n: np.where(np.arange(n) % 160 < 70, 1.0, 0.0),
        ),
    ],
)
def test_phase72_native_ir_auto_holds_while_explicit_rust_matches_python(kind, parameters, signal):
    frame = _frame(2_000)
    values = signal(len(frame)).astype(np.float64)
    program = NativeStrategyIR(kind, "BTC", parameters=parameters)

    def run(native_backend: str):
        runner = _ir_backend(native_backend).prepare_native_strategy_ir(
            frame.index,
            closes={"BTC": frame["close"]},
            highs={"BTC": frame["high"]},
            lows={"BTC": frame["low"]},
            opens={"BTC": frame["open"]},
            program=program,
            symbols=["BTC"],
        )
        return runner.backtest(values, report_level="audit")

    auto = run("auto")
    rust = run("rust")
    python = run("python")
    _assert_accounting_equal(auto, rust)
    _assert_accounting_equal(auto, python)
    assert auto.metadata["execution_plan_v1"]["backend"] == "python"
    assert auto.metadata["native_event_promotion_v1"]["reason"] == "measurement_evidence_not_current"
    assert rust.metadata["native_strategy_ir_execution_v1"]["python_callbacks"] == 0
    assert rust.metadata["native_strategy_ir_execution_v1"]["rust_audit_replay"] is False


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
def test_stage_b_native_ir_v3_profiles_and_cold_public_adaptation_are_parity_locked():
    frame = _frame(2_000)
    program = NativeStrategyIR(
        NativeStrategyKind.GRID_LEVEL,
        "BTC",
        parameters=NativeStrategyParameters(quantity=0.5),
    )
    signal = np.where(np.arange(len(frame)) % 110 < 50, 2.0, 0.0).astype(np.float64)

    def runner(native_backend: str):
        return _ir_backend(
            native_backend,
            execution_contract="event_lifecycle_v3_next_open",
        ).prepare_native_strategy_ir(
            frame.index,
            closes={"BTC": frame["close"]},
            highs={"BTC": frame["high"]},
            lows={"BTC": frame["low"]},
            opens={"BTC": frame["open"]},
            program=program,
            symbols=["BTC"],
        )

    rust_runner = runner("rust")
    score = rust_runner.run_score(signal)
    compact = rust_runner.run_compact(signal)
    audit = rust_runner.run_audit(signal)
    public_score = rust_runner.backtest(signal, report_level="score")
    public_audit = rust_runner.backtest(signal, report_level="audit")
    python_audit = runner("python").backtest(signal, report_level="audit")

    assert score.profile == "score"
    assert compact.profile == "compact"
    assert audit.profile == "audit"
    assert score.final_equity == pytest.approx(float(audit.payload["final_equity"]), abs=1e-12)
    np.testing.assert_allclose(compact.payload["equity"], audit.payload["equity"], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(public_score.equity.to_numpy(), audit.payload["equity"], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(public_audit.equity.to_numpy(), audit.payload["equity"], rtol=0.0, atol=1e-12)
    _assert_accounting_equal(public_audit, python_audit)
    assert public_score.metadata["execution_plan_v1"]["backend"] == "rust"
    assert public_score.metadata["native_strategy_ir_execution_v1"]["output_profile"] == "compact"
    assert public_score.metadata["native_strategy_ir_execution_v1"]["rust_audit_replay"] is False
    assert public_audit.metadata["execution_contract_id"] == "event_lifecycle_v3_next_open"


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
def test_stage_b_native_ir_batch_and_causal_fold_keep_one_boundary_and_fresh_state():
    frame = _frame(2_000)
    program = NativeStrategyIR(NativeStrategyKind.GRID_LEVEL, "BTC", parameters=NativeStrategyParameters(quantity=0.5))
    runner = _ir_backend("rust").prepare_native_strategy_ir(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        program=program,
        symbols=["BTC"],
    )
    base = np.where(np.arange(len(frame)) % 90 < 40, 1.0, 0.0)
    signals = np.vstack((base, -base, 2.0 * base, np.roll(base, 7))).astype(np.float64)
    parameters = np.asarray([[0.5, 0.0, 0.0, 0.0]] * len(signals), dtype=np.float64)
    one = runner.run_batch_score(signals, parameter_matrix=parameters, workers=1)
    parallel = runner.run_batch_score(signals, parameter_matrix=parameters, workers=2, chunk_size=1)
    np.testing.assert_allclose(one.final_equity, parallel.final_equity, rtol=0.0, atol=1e-12)
    assert one.metadata["boundary_calls"] == 1
    assert one.metadata["shared_market_copies_per_scenario"] == 0
    assert one.metadata["execution_plan_v1"]["backend"] == "rust"

    python_runner = _ir_backend("python").prepare_native_strategy_ir(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        program=program,
        symbols=["BTC"],
    )
    python_batch = python_runner.run_batch_score(signals, parameter_matrix=parameters, workers=1)
    np.testing.assert_allclose(one.final_equity, python_batch.final_equity, rtol=0.0, atol=1e-12)
    selected = int(one.top_ids(1)[0])
    selected_audit = runner.run_audit(signals[selected], parameters=parameters[selected])
    assert selected_audit.final_equity == pytest.approx(float(one.final_equity[selected]), abs=1e-12)

    fold = NativeIRFold(
        fold_id=3,
        warmup_start=0,
        train_start=0,
        train_end=1_200,
        test_start=1_200,
        test_end=2_000,
    )
    oos = runner.run_fold_batch_score(signals, fold, parameter_matrix=parameters, workers=2)
    assert oos.metadata["boundary_calls"] == 1
    assert oos.metadata["fold_id"] == 3
    assert oos.metadata["execution_bars"] == 800
    assert oos.metadata["shared_market_copies_per_scenario"] == 0
    python_oos = python_runner.run_fold_batch_score(signals, fold, parameter_matrix=parameters, workers=1)
    np.testing.assert_allclose(oos.final_equity, python_oos.final_equity, rtol=0.0, atol=1e-12)


def test_stage_b_native_ir_small_auto_request_falls_back_to_python_with_reason():
    frame = _frame(256)
    runner = _ir_backend("auto").prepare_native_strategy_ir(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        program=NativeStrategyIR(NativeStrategyKind.SIGNAL_TARGET, "BTC", parameters=NativeStrategyParameters(quantity=1.0)),
        symbols=["BTC"],
    )
    result = runner.backtest(np.where(np.arange(len(frame)) % 20 < 10, 1.0, 0.0), report_level="audit")
    assert result.metadata["execution_plan_v1"]["backend"] == "python"
    assert result.metadata["native_event_promotion_v1"]["reason"] == "measurement_evidence_not_current"
