from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionContract,
    FillReplayTape,
    IntrabarFillReason,
    IntrabarIntentTape,
    QuantBTEndpoint,
    prepare_market_tape,
    run_fill_replay_kernel,
    run_intrabar_kernel,
    run_intrabar_reference,
)


def _frame(rows) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def _assert_kernel_matches_reference(df, intent, *, account=None, fee_rate=0.0, slippage_rate=0.0, close_on_last_bar=True):
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    account = account or AccountConfig(initial_capital=10_000.0, leverage=10.0)
    contract = ExecutionContract.intrabar_bracket(close_on_last_bar=close_on_last_bar)
    reference = run_intrabar_reference(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )
    kernel = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        report_level="audit",
    )
    np.testing.assert_allclose(kernel.equity.to_numpy(), reference.equity.to_numpy(), atol=1e-9, rtol=0.0)
    np.testing.assert_allclose(kernel.position.to_numpy(), reference.position.to_numpy(), atol=1e-9, rtol=0.0)
    np.testing.assert_allclose(kernel.fees.to_numpy(), reference.fees.to_numpy(), atol=1e-9, rtol=0.0)
    np.testing.assert_array_equal(kernel.event_flags.to_numpy(), reference.event_flags.to_numpy())
    assert [fill.reason for fill in kernel.fills] == [fill.reason for fill in reference.fills]
    assert kernel.fill_count == len(reference.fills)
    return reference, kernel


def test_phase31c_kernel_matches_oracle_same_bar_ambiguity_and_audit_fills():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 110.0, "low": 94.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        ]
    )
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan],
        take_profit_value=[0.08, np.nan, np.nan],
    )

    reference, kernel = _assert_kernel_matches_reference(df, intent)

    assert kernel.ambiguity_count == reference.ambiguity_count == 1
    assert kernel.fills_report["reason"].tolist() == ["entry", "stop_loss"]
    assert kernel.metadata["two_pass_audit"] is True


def test_phase31c_kernel_slippage_is_marked_from_actual_fill_price():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        ]
    )
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 0], entry_size=[1.0, 0.0])

    reference, kernel = _assert_kernel_matches_reference(
        df,
        intent,
        fee_rate=0.0,
        slippage_rate=0.001,
        close_on_last_bar=False,
    )

    assert reference.fills[0].price == pytest.approx(100.1)
    assert kernel.equity.iloc[-1] == pytest.approx(10_001.9)


def test_phase31c_kernel_trailing_and_reversal_match_oracle():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0},
            {"open": 110.0, "high": 112.0, "low": 104.0, "close": 108.0},
            {"open": 107.0, "high": 108.0, "low": 101.0, "close": 103.0},
        ]
    )
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, -1, 0, 0],
        entry_size=[1.0, 2.0, 0.0, 0.0],
        trailing_value=[0.05, 0.05, 0.05, 0.05],
    )

    _reference, kernel = _assert_kernel_matches_reference(df, intent, fee_rate=0.001)

    reasons = [fill.reason for fill in kernel.fills]
    assert IntrabarFillReason.REVERSAL_EXIT in reasons
    assert IntrabarFillReason.REVERSAL_ENTRY in reasons


def test_phase31c_kernel_rejects_insufficient_initial_margin():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 0], entry_size=[200.0, 0.0])

    result = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=AccountConfig(initial_capital=1_000.0, leverage=1.0),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        report_level="audit",
    )

    assert result.rejected_count == 1
    assert result.fill_count == 0
    assert result.position.iloc[-1] == 0.0


def test_phase31c_kernel_liquidates_unprotected_intrabar_breach():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 40.0, "close": 80.0},
            {"open": 80.0, "high": 81.0, "low": 79.0, "close": 80.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 0, 0], entry_size=[10.0, 0.0, 0.0])

    result = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=AccountConfig(initial_capital=1_000.0, leverage=2.0, maintenance_ratio=1.5),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        report_level="audit",
    )

    assert result.liquidated is True
    assert result.liquidation_bar == 1
    assert result.equity.iloc[-1] == 0.0
    assert result.fills[-1].reason == IntrabarFillReason.LIQUIDATION


def test_phase31c_fill_replay_reconstructs_accounting_from_explicit_fills():
    df = _frame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
            {"open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    fills = FillReplayTape.from_frame(
        pd.DataFrame(
            [
                {"bar_index": 1, "sequence": 0, "side": 1, "qty": 1.0, "price": 100.0, "fee": 0.1, "reason": "entry"},
                {"bar_index": 2, "sequence": 0, "side": -1, "qty": 1.0, "price": 103.0, "fee": 0.103, "reason": "take_profit"},
            ]
        )
    )

    result = run_fill_replay_kernel(
        tape=tape,
        fill_tape=fills,
        account=AccountConfig(initial_capital=10_000.0),
    )

    assert result.equity.iloc[-1] == pytest.approx(10_002.797)
    assert result.position.iloc[-1] == 0.0
    assert result.metadata["accounting_certified"] is True
    assert result.metadata["execution_generation_certified"] is False


def test_phase31c_fast_endpoint_supports_standard_and_audit_report_levels():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "entry": 1.0, "sl": 0.05},
            {"open": 100.0, "high": 101.0, "low": 94.0, "close": 98.0, "entry": 0.0, "sl": np.nan},
            {"open": 98.0, "high": 99.0, "low": 97.0, "close": 98.0, "entry": 0.0, "sl": np.nan},
        ]
    )

    standard = QuantBTEndpoint.intrabar_bracket(initial_capital=10_000.0, fee_rate=0.0, slippage_bps=0.0, use_funding=False, report_level="standard")
    standard_result = standard.backtest(data=df, signal_col="entry", symbols=["BTC"], intent_cols={"stop_value": "sl"})
    assert standard_result.metadata["engine_id"] == "intrabar_bracket_v1"
    assert standard_result.metadata["report_level"] == "standard"
    assert standard.fills_report.empty

    audit = QuantBTEndpoint.intrabar_bracket(initial_capital=10_000.0, fee_rate=0.0, slippage_bps=0.0, use_funding=False, report_level="audit")
    audit_result = audit.backtest(data=df, signal_col="entry", symbols=["BTC"], intent_cols={"stop_value": "sl"})
    assert audit_result.metadata["report_level"] == "audit"
    assert audit.fills_report["reason"].tolist() == ["entry", "stop_loss"]
    assert audit.show_metrics()["final_equity"] == pytest.approx(9_995.0)


def test_phase31c_fill_replay_endpoint_accepts_single_dataframe_argument():
    df = _frame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        ]
    )
    fills = pd.DataFrame([{"bar_index": 1, "sequence": 0, "side": 1, "qty": 1.0, "price": 100.0, "fee": 0.0}])

    bt = QuantBTEndpoint.fill_replay(initial_capital=10_000.0)
    result = bt.backtest(data=df, symbols=["BTC"], fill_replay=fills)

    assert result.metadata["engine_id"] == "fill_replay_v1"
    assert result.equity.iloc[-1] == pytest.approx(10_002.0)


def test_phase31c_warm_kernel_is_materially_faster_than_python_oracle():
    n = 2_000
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    base = 100.0 + np.sin(np.arange(n) / 20.0)
    df = pd.DataFrame(
        {
            "open": base,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base + 0.2,
        },
        index=idx,
    )
    entry_side = np.zeros(n, dtype=np.int8)
    entry_size = np.zeros(n, dtype=np.float64)
    entry_side[::40] = 1
    entry_size[::40] = 1.0
    intent = IntrabarIntentTape.from_arrays(entry_side=entry_side, entry_size=entry_size, stop_value=np.full(n, 0.03))
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    account = AccountConfig(initial_capital=10_000.0, leverage=10.0)
    contract = ExecutionContract.intrabar_bracket(close_on_last_bar=True)

    run_intrabar_kernel(tape=tape, intent=intent, account=account, contract=contract, report_level="minimal")
    start = time.perf_counter()
    fast = run_intrabar_kernel(tape=tape, intent=intent, account=account, contract=contract, report_level="minimal")
    fast_seconds = time.perf_counter() - start

    start = time.perf_counter()
    slow = run_intrabar_reference(tape=tape, intent=intent, account=account, contract=contract)
    slow_seconds = time.perf_counter() - start

    np.testing.assert_allclose(fast.equity.to_numpy(), slow.equity.to_numpy(), atol=1e-9, rtol=0.0)
    assert fast_seconds < slow_seconds
