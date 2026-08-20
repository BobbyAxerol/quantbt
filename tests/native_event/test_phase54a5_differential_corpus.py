"""Phase 54A.5.6 full-session differential corpus and exit locks.

The JSON corpus is deliberately small, deterministic, and lifecycle-heavy.  A
case is run through the Python oracle, the API-0.4 Rust compatibility adapter,
the ABI-0.5 direct typed request, and the ABI-0.5 prepared runner.  The test
does not promote any endpoint; it proves that the four representations retain
one execution/accounting contract.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    OrderAction,
    OrderCommand,
    OrderSide,
    OrderType,
    RustNativeIRRunner,
    TimeInForce,
)
from quantbt.backends._native_event_rust import RustFullRunner
from quantbt.core.execution_trace import compare_canonical_traces
from quantbt.core.native_event_parity import assert_native_event_full_parity
from quantbt.core.package_execution_contracts import (
    PackageLegRequest,
    PackageTransactionPolicy,
    execute_package_transaction_reference,
)
from quantbt.core.portfolio_execution_contracts import (
    PortfolioMarginAllocationPolicy,
    execute_portfolio_target_reference,
)
from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


CORPUS_PATH = Path(__file__).resolve().parents[1] / "corpus/native_event/phase54a5_full_session.json"
NUMERIC_ARRAY_FIELDS = (
    "equity",
    "positions",
    "fees",
    "turnover",
    "funding",
    "initial_margin",
    "maintenance_margin",
    "fill_qty",
    "fill_price",
    "fill_fee",
)
DISCRETE_ARRAY_FIELDS = (
    "fill_bar",
    "fill_order_id",
    "fill_symbol",
    "fill_side",
    "fill_reason",
    "fill_ambiguity",
    "event_bar",
    "event_kind",
    "event_status",
    "event_order_id",
    "event_target_id",
    "event_symbol",
    "event_reject_code",
)
SCALAR_FIELDS = (
    "total_fee",
    "total_turnover",
    "total_funding",
    "fill_count",
    "event_count",
    "rejected_count",
    "canceled_count",
    "max_initial_margin",
    "max_maintenance_margin",
    "liquidated",
    "liquidation_bar",
    "liquidation_reason",
)


def _corpus_cases() -> list[dict]:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "quantbt-native-execution-differential-corpus-v1"
    return list(payload["cases"])


def _market(case: dict):
    market = case["market"]
    index = pd.date_range(
        pd.Timestamp(market["start"]),
        periods=int(market["bars"]),
        freq=str(market["frequency"]),
    )
    closes: dict[str, pd.Series] = {}
    highs: dict[str, pd.Series] = {}
    lows: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    funding: dict[str, pd.Series] = {}
    symbols: list[str] = []
    for spec in market["symbols"]:
        symbol = str(spec["symbol"])
        symbols.append(symbol)
        close = float(spec["base"]) + float(spec["step"]) * np.arange(len(index), dtype=np.float64)
        opens[symbol] = pd.Series(close + float(spec["open_offset"]), index=index)
        closes[symbol] = pd.Series(close, index=index)
        highs[symbol] = pd.Series(np.maximum(close, opens[symbol].to_numpy()) + float(spec["high_spread"]), index=index)
        lows[symbol] = pd.Series(np.minimum(close, opens[symbol].to_numpy()) - float(spec["low_spread"]), index=index)
        values = np.zeros(len(index), dtype=np.float64)
        for event in spec.get("funding", []):
            values[int(event["bar"])] = float(event["rate"])
        funding[symbol] = pd.Series(values, index=index)
    volumes = np.full((len(index), len(symbols)), 1_000.0, dtype=np.float64)
    return index, symbols, opens, highs, lows, closes, funding, volumes


def _commands(case: dict, index: pd.DatetimeIndex) -> tuple[OrderCommand, ...]:
    commands: list[OrderCommand] = []
    for row in case["commands"]:
        action = OrderAction(str(row.get("action", "place")))
        kwargs = {
            "timestamp": index[int(row["bar"])],
            "action": action,
            "symbol": row.get("symbol"),
            "order_id": row.get("order_id"),
            "target_order_id": row.get("target_order_id"),
            "parent_order_id": row.get("parent_order_id"),
            "group_id": row.get("group_id"),
            "oco_group_id": row.get("oco_group_id"),
            "reduce_only": bool(row.get("reduce_only", False)),
            "activation_policy": row.get("activation_policy", "immediate"),
            "tif": TimeInForce(str(row.get("tif", "gtc"))),
        }
        if action in {OrderAction.PLACE, OrderAction.REPLACE}:
            kwargs.update(
                {
                    "side": OrderSide(str(row["side"])),
                    "order_type": OrderType(str(row["order_type"])),
                    "qty": float(row["qty"]),
                    "price": row.get("price"),
                    "trigger_price": row.get("trigger_price"),
                }
            )
        if "expires_bar" in row:
            kwargs["expires_at"] = index[int(row["expires_bar"])]
        commands.append(OrderCommand(**kwargs))
    return tuple(commands)


def _backend(case: dict, native_backend: str) -> NativeEventBackend:
    account = case["account"]
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(
                initial_capital=float(account["initial_capital"]),
                leverage=float(account["leverage"]),
                maintenance_ratio=float(account["maintenance_ratio"]),
            ),
            execution=ExecutionConfig(slippage_bps=float(account["slippage_bps"])),
            fee_rate=float(account["fee_rate"]),
            use_funding=bool(account["use_funding"]),
            report_level="audit",
            native_backend=native_backend,
            execution_contract=str(account["event_contract"]),
        )
    )


def _run_public(case: dict, native_backend: str):
    index, symbols, opens, highs, lows, closes, funding, _ = _market(case)
    backend = _backend(case, native_backend)
    commands = _commands(case, index)
    market = backend.prepare_market_arrays(
        index,
        closes=closes,
        highs=highs,
        lows=lows,
        funding_rate=funding,
        symbols=symbols,
    )
    compiled = backend.compile_order_commands(index, commands, symbols=symbols)
    result = backend.run_order_commands(
        index,
        commands,
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        funding_rate=funding,
        symbols=symbols,
        contract_size={symbol: 1.0 for symbol in symbols},
        market_arrays=market,
        compiled_commands=compiled,
        report_level="audit",
    )
    return result, backend, index, symbols, opens, market, compiled


def _make_full_runner(case: dict, backend, index, symbols, opens, market) -> RustFullRunner:
    account = case["account"]
    open_matrix = np.ascontiguousarray(
        np.column_stack([opens[symbol].to_numpy(dtype=np.float64) for symbol in symbols])
    )
    return RustFullRunner(
        idx=index,
        symbols=symbols,
        market_arrays=market,
        contract_sizes=np.ones(len(symbols), dtype=np.float64),
        leverages=np.full(len(symbols), float(account["leverage"]), dtype=np.float64),
        fee_rates=np.full(len(symbols), float(account["fee_rate"]), dtype=np.float64),
        initial_capital=float(account["initial_capital"]),
        maintenance_ratio=float(account["maintenance_ratio"]),
        slippage=float(backend.config.execution.slippage_rate),
        use_funding=bool(account["use_funding"]),
        event_contract=backend.config.execution_contract,
        opens_arr=open_matrix,
        volumes_arr=np.full(market.closes.shape, 1_000.0, dtype=np.float64),
    )


def _direct_request(case: dict, runner: RustFullRunner, compiled, profile: int):
    import _quantbt_native

    ptr, codes, values, expiry = runner._tape_arrays(compiled)
    account = case["account"]
    n_symbols = len(runner.symbols)
    return _quantbt_native.NativeExecutionRequestCore.from_command_tape(
        runner.prepared_market_core,
        ptr,
        codes,
        values,
        expiry,
        np.ones(n_symbols, dtype=np.float64),
        np.full(n_symbols, float(account["leverage"]), dtype=np.float64),
        np.full(n_symbols, float(account["fee_rate"]), dtype=np.float64),
        float(account["initial_capital"]),
        float(account["maintenance_ratio"]),
        float(runner.slippage),
        bool(account["use_funding"]),
        event_contract_code=int(backend_contract_code(runner)),
        output_profile=int(profile),
    )


def backend_contract_code(runner: RustFullRunner) -> int:
    return int(runner.event_contract.contract_code)


def _prepared_request(case: dict, index, symbols, opens, market, compiled, runner: RustFullRunner, profile: int):
    ptr, codes, values, expiry = runner._tape_arrays(compiled)
    account = case["account"]
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=2 * 1024 * 1024, max_entries=8))
    prepared_market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=np.ascontiguousarray(np.column_stack([opens[symbol].to_numpy(dtype=np.float64) for symbol in symbols])),
        highs=np.ascontiguousarray(market.highs, dtype=np.float64),
        lows=np.ascontiguousarray(market.lows, dtype=np.float64),
        closes=np.ascontiguousarray(market.closes, dtype=np.float64),
        volumes=np.full(market.closes.shape, 1_000.0, dtype=np.float64),
        funding=np.ascontiguousarray(market.funding, dtype=np.float64),
        funding_mask=np.ascontiguousarray(market.is_funding_bar, dtype=np.bool_),
        symbols=symbols,
    )
    template = cache.prepare_template(
        prepared_market,
        contract_sizes=np.ones(len(symbols), dtype=np.float64),
        leverages=np.full(len(symbols), float(account["leverage"]), dtype=np.float64),
        fee_rates=np.full(len(symbols), float(account["fee_rate"]), dtype=np.float64),
        initial_capital=float(account["initial_capital"]),
        maintenance_ratio=float(account["maintenance_ratio"]),
        slippage_rate=float(runner.slippage),
        use_funding=bool(account["use_funding"]),
        event_contract_code=backend_contract_code(runner),
    )
    request = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=int(profile),
    )
    return cache, request


def _assert_output_matches_legacy(output, legacy) -> None:
    for field in NUMERIC_ARRAY_FIELDS:
        actual = np.asarray(getattr(output, field))
        expected = np.asarray(getattr(legacy, field))
        # Typed SoA keeps the position path flat and bar-major at the ABI
        # boundary; the legacy adapter reshapes it for the Python result.
        if field == "positions" and actual.ndim == 1 and expected.ndim == 2:
            actual = actual.reshape(expected.shape)
        np.testing.assert_allclose(
            actual,
            expected,
            rtol=0.0,
            atol=1e-12,
        )
    for field in DISCRETE_ARRAY_FIELDS:
        np.testing.assert_array_equal(
            np.asarray(getattr(output, field)),
            np.asarray(getattr(legacy, field)),
        )
    np.testing.assert_allclose(output.final_positions, legacy.positions[-1], rtol=0.0, atol=1e-12)
    for field in SCALAR_FIELDS:
        expected = getattr(legacy, field)
        actual = getattr(output, field)
        if isinstance(expected, (float, np.floating)):
            assert actual == pytest.approx(float(expected), abs=1e-12)
        else:
            assert actual == expected


def _assert_reports_equal(left, right) -> None:
    for key in (
        "initial_capital",
        "final_equity",
        "total_return_pct",
        "cagr_pct",
        "sharpe",
        "sortino",
        "calmar",
        "omega",
        "max_drawdown_pct",
        "profit_factor",
        "num_trades",
    ):
        np.testing.assert_allclose(left[key], right[key], rtol=0.0, atol=1e-12, equal_nan=True)


@pytest.mark.parametrize("case", _corpus_cases(), ids=lambda item: item["id"])
def test_full_session_differential_corpus_locks_python_adapter_typed_and_prepared(case):
    python, _, _, _, _, _, _ = _run_public(case, "python")
    rust, backend, index, symbols, opens, market, compiled = _run_public(case, "rust")

    certificate = assert_native_event_full_parity(rust, python, command_tape=compiled)
    assert certificate["passed"] is True
    trace = compare_canonical_traces(
        rust.metadata["canonical_trace_v1"],
        python.metadata["canonical_trace_v1"],
    )
    assert trace["passed"] is True
    assert rust.metadata["canonical_trace_fingerprint"] == python.metadata["canonical_trace_fingerprint"]
    _assert_reports_equal(rust.full_report(), python.full_report())

    runner = _make_full_runner(case, backend, index, symbols, opens, market)
    legacy = runner.run_tape_audit(compiled)
    direct_request = _direct_request(case, runner, compiled, profile=2)
    direct = direct_request.execute_typed()
    _assert_output_matches_legacy(direct, legacy)
    repeated = direct_request.execute_typed()
    _assert_output_matches_legacy(repeated, legacy)

    cache, prepared_request = _prepared_request(
        case, index, symbols, opens, market, compiled, runner, profile=2
    )
    prepared_runner = cache.new_runner(prepared_request)
    prepared = prepared_runner.execute_typed()
    _assert_output_matches_legacy(prepared, legacy)
    prepared_repeat = prepared_runner.execute_typed()
    _assert_output_matches_legacy(prepared_repeat, legacy)
    assert prepared.runner_run_count == 1
    assert prepared_repeat.runner_run_count == 2
    assert prepared.as_dict()["boundary_calls"] == 1
    before_clear = prepared.equity.copy()
    cache.clear()
    np.testing.assert_allclose(prepared.equity, before_clear, rtol=0.0, atol=0.0)

    expected = case["expect"]
    counters = rust.metadata["lifecycle_counters"]
    assert counters["fill_count"] >= int(expected["minimum_fills"])
    assert counters["event_count"] >= int(expected["minimum_events"])
    assert counters["canceled_count"] >= int(expected["minimum_canceled"])
    assert counters["rejected_count"] >= int(expected["minimum_rejected"])
    if expected["funding_nonzero"]:
        assert abs(float(rust.funding.sum())) > 0.0
    if bool(expected.get("nonzero_reject_code", False)):
        report = rust.metadata["order_report"]
        assert bool((report["reject_code"].to_numpy(dtype=np.int64) != 0).any())


@pytest.mark.parametrize("case", _corpus_cases(), ids=lambda item: item["id"])
def test_typed_profiles_are_one_pass_and_do_not_force_audit_replay(case):
    _, backend, index, symbols, opens, market, compiled = _run_public(case, "rust")
    runner = _make_full_runner(case, backend, index, symbols, opens, market)
    score = _direct_request(case, runner, compiled, profile=0).execute_typed()
    compact = _direct_request(case, runner, compiled, profile=1).execute_typed()
    audit = _direct_request(case, runner, compiled, profile=2).execute_typed()

    assert not hasattr(score, "equity")
    assert not hasattr(compact, "fill_bar")
    for output in (score, compact, audit):
        payload = output.as_dict()
        assert payload["native_execution_passes"] == 1
        assert payload["boundary_calls"] == 1
        assert payload["python_callbacks"] == 0
    assert score.final_equity == pytest.approx(audit.final_equity, abs=1e-12)
    assert compact.final_equity == pytest.approx(audit.final_equity, abs=1e-12)
    np.testing.assert_allclose(compact.equity, audit.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(compact.positions, audit.positions, rtol=0.0, atol=1e-12)


def test_ir_single_batch_and_native_portfolio_package_preflight_remain_exact():
    index = pd.date_range("2026-03-01", periods=16, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.arange(len(index), dtype=np.float64) * 0.1, index=index)
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    runner = RustNativeIRRunner(
        backend.prepare_rust_batched_runner(
            index,
            closes={"BTC": close},
            highs={"BTC": close + 1.0},
            lows={"BTC": close - 1.0},
            symbols=["BTC"],
        ),
        NativeStrategyIR(
            NativeStrategyKind.GRID_LEVEL,
            "BTC",
            parameters=NativeStrategyParameters(quantity=0.25),
        ),
    )
    signal = np.where((np.arange(len(index)) // 3) % 2 == 0, 1.0, -1.0).astype(np.float64)
    single = runner.run_score(signal)
    batch = runner.run_batch_score(np.vstack([signal, signal]), workers=2, chunk_size=1)
    np.testing.assert_allclose(batch.final_equity, [single.final_equity, single.final_equity], rtol=0.0, atol=1e-12)
    assert batch.metadata["boundary_calls"] == 1
    assert batch.metadata["shared_market_copies_per_scenario"] == 0

    import _quantbt_native

    portfolio_kwargs = dict(
        contract_sizes=np.array([1.0, 1.0]),
        leverages=np.array([2.0, 2.0]),
        fee_rates=np.array([0.001, 0.001]),
        slippage_rates=np.array([0.0005, 0.0005]),
        tradable=np.array([True, True]),
        stale=np.array([False, False]),
        min_qty=np.array([0.0, 0.0]),
        min_notional=np.array([0.0, 0.0]),
    )
    portfolio_reference = execute_portfolio_target_reference(
        [1.0, -1.0], [4.0, -4.0], [100.0, 100.0], equity=500.0,
        policy=PortfolioMarginAllocationPolicy.ALL_OR_NONE_TARGET,
        **portfolio_kwargs,
    )
    portfolio_native = _quantbt_native.native_portfolio_target_preflight(
        np.array([1.0, -1.0]), np.array([4.0, -4.0]), np.array([100.0, 100.0]),
        500.0, portfolio_kwargs["contract_sizes"], portfolio_kwargs["leverages"],
        portfolio_kwargs["fee_rates"], portfolio_kwargs["slippage_rates"],
        portfolio_kwargs["tradable"], portfolio_kwargs["stale"], portfolio_kwargs["min_qty"],
        portfolio_kwargs["min_notional"], 0.0,
        list(PortfolioMarginAllocationPolicy).index(PortfolioMarginAllocationPolicy.ALL_OR_NONE_TARGET),
    )
    np.testing.assert_allclose(portfolio_native["accepted_units"], portfolio_reference.accepted_units, rtol=0.0, atol=1e-12)
    assert tuple(portfolio_native["rejection_reason"]) == portfolio_reference.rejection_reasons

    legs = (
        PackageLegRequest("primary", "BTC-PERP", 1.0, 100.0, 50.0, fee_rate=0.001),
        PackageLegRequest("hedge", "BTC-QUARTER", -1.0, 102.0, 500.0, fee_rate=0.001),
    )
    package_reference = execute_package_transaction_reference(
        "basis", legs, available_equity=300.0, policy=PackageTransactionPolicy.ATOMIC_ALL_OR_NONE
    )
    package_native = _quantbt_native.native_package_transaction_preflight(
        7, np.array([10, 11], dtype=np.int64), np.array([0, 1], dtype=np.uint32),
        np.array([leg.signed_qty for leg in legs]), np.array([leg.price for leg in legs]),
        np.array([leg.initial_margin for leg in legs]), np.array([leg.fee_rate for leg in legs]),
        np.array([leg.source_age_ns for leg in legs], dtype=np.int64),
        np.array([leg.venue_code for leg in legs], dtype=np.uint16),
        np.array([leg.venue_sequence for leg in legs], dtype=np.uint32),
        np.array([leg.min_qty for leg in legs]), np.array([leg.min_notional for leg in legs]),
        np.array([leg.contract_size for leg in legs]), 300.0, 2, 0,
    )
    accepted = np.array([leg.leg_id in set(package_reference.accepted_legs) for leg in legs], dtype=bool)
    np.testing.assert_array_equal(package_native["accepted"], accepted)
    assert tuple(package_native["rejection_reason"]) == package_reference.rejection_reasons
