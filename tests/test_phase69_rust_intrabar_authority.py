"""Phase 69 Rust authority tests for the bounded intrabar contract.

The Python reference remains the readable semantic oracle and the Numba route
remains the pinned reproducibility comparator.  Rust is exercised only through
its explicit one-full-tape request, with no Python per-bar execution replay.
"""

from __future__ import annotations

import importlib
import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionContract,
    IntrabarIntentTape,
    IntrabarSameBarPolicy,
    IntrabarSessionTape,
    ProtectiveExitReentryPolicy,
    QuantBTEndpoint,
    SessionExecutionPolicy,
    TakeProfitGapPolicy,
    prepare_market_tape,
    run_intrabar_kernel,
    run_intrabar_reference,
    run_intrabar_session_kernel,
)
from quantbt.backends.native_intrabar_rust import run_rust_intrabar_kernel


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(rows: list[dict[str, float]]) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=len(rows), freq="1h", tz="UTC")
    normalized = []
    for row in rows:
        payload = {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}
        payload.update(row)
        normalized.append(payload)
    return pd.DataFrame(normalized, index=index)


def _fill_tuple(fill) -> tuple[object, ...]:
    return (
        fill.bar_index,
        fill.sequence,
        fill.side,
        fill.qty,
        fill.price,
        fill.fee,
        fill.reason.value,
    )


def _assert_full_parity(reference, numba, rust) -> None:
    for field in (
        "equity",
        "position",
        "average_entry",
        "active_stop",
        "active_take_profit",
        "fees",
        "funding",
    ):
        expected = getattr(reference, field).to_numpy(dtype=float)
        np.testing.assert_allclose(getattr(numba, field).to_numpy(dtype=float), expected, rtol=0.0, atol=1e-9)
        np.testing.assert_allclose(getattr(rust, field).to_numpy(dtype=float), expected, rtol=0.0, atol=1e-9)
    for field in ("initial_margin", "maintenance_margin"):
        np.testing.assert_allclose(
            getattr(rust, field).to_numpy(dtype=float),
            getattr(numba, field).to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-9,
        )
    np.testing.assert_array_equal(numba.event_flags.to_numpy(), reference.event_flags.to_numpy())
    np.testing.assert_array_equal(rust.event_flags.to_numpy(), reference.event_flags.to_numpy())
    expected_fills = [_fill_tuple(fill) for fill in reference.fills]
    assert [_fill_tuple(fill) for fill in numba.fills] == expected_fills
    assert [_fill_tuple(fill) for fill in rust.fills] == expected_fills
    assert rust.fill_count == numba.fill_count == len(reference.fills)
    for field in ("ambiguity_count", "rejected_count", "liquidated", "liquidation_bar"):
        assert getattr(rust, field) == getattr(numba, field) == getattr(reference, field)


def _triple(
    frame: pd.DataFrame,
    intent: IntrabarIntentTape,
    *,
    contract: ExecutionContract | None = None,
    account: AccountConfig | None = None,
    fee_rate: float = 0.00045,
    slippage_rate: float = 0.0002,
    use_funding: bool = False,
    bar_timestamp_semantics: str = "close",
    session_policy: SessionExecutionPolicy | None = None,
    session_tape: IntrabarSessionTape | None = None,
    **execution_kwargs,
):
    contract = contract or ExecutionContract.intrabar_bracket(close_on_last_bar=True)
    account = account or AccountConfig(initial_capital=10_000.0, leverage=3.0, maintenance_ratio=0.005)
    funding = frame["funding_rate"] if "funding_rate" in frame else 0.0
    tape = prepare_market_tape(
        data=frame,
        symbols=["BTC"],
        funding_rate=funding,
        use_funding=use_funding,
        bar_timestamp_semantics=bar_timestamp_semantics,
    )
    reference = run_intrabar_reference(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        session_policy=session_policy,
        session_tape=session_tape,
        **execution_kwargs,
    )
    numba_kwargs = {
        "tape": tape,
        "intent": intent,
        "account": account,
        "contract": contract,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "report_level": "audit",
        **execution_kwargs,
    }
    numba = (
        run_intrabar_session_kernel(
            **numba_kwargs,
            session_policy=session_policy,
            session_tape=session_tape,
        )
        if session_policy is not None
        else run_intrabar_kernel(**numba_kwargs)
    )
    rust = run_rust_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        session_policy=session_policy,
        session_tape=session_tape,
        report_level="audit",
        **execution_kwargs,
    )
    _assert_full_parity(reference, numba, rust)
    assert rust.metadata["rust_intrabar_authority"] is True
    assert rust.metadata["boundary_calls"] == 1
    assert rust.metadata["python_callbacks"] == 0
    assert rust.metadata["audit_detail_truncated"] is False
    return reference, numba, rust


@pytest.mark.parametrize(
    ("same_bar_policy", "expected_reason"),
    [
        (IntrabarSameBarPolicy.CONSERVATIVE, "stop_loss"),
        (IntrabarSameBarPolicy.TP_FIRST, "take_profit"),
        (IntrabarSameBarPolicy.OHLC_PATH, "take_profit"),
        (IntrabarSameBarPolicy.OLHC_PATH, "stop_loss"),
    ],
)
def test_phase69_same_bar_paths_and_exact_audit_trace(same_bar_policy, expected_reason) -> None:
    frame = _frame(
        [
            {},
            {"open": 100.0, "high": 111.0, "low": 94.0, "close": 100.0},
            {},
        ]
    )
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan],
        take_profit_value=[0.08, np.nan, np.nan],
    )
    contract = ExecutionContract.intrabar_bracket(
        same_bar_policy=same_bar_policy,
        close_on_last_bar=False,
    )
    reference, _numba, rust = _triple(frame, intent, contract=contract, fee_rate=0.0, slippage_rate=0.0)
    assert reference.ambiguity_count == rust.ambiguity_count == 1
    assert rust.fills[-1].reason.value == expected_reason
    assert rust.metadata["ambiguity_bar"].tolist() == [1]
    assert rust.metadata["ambiguity_policy"].tolist() == [
        {"conservative": 1, "tp_first": 3, "ohlc_path": 4, "olhc_path": 5}[same_bar_policy.value]
    ]
    audit = rust.fills_report.iloc[-1]
    assert bool(audit["ambiguity_flag"]) is True
    assert int(audit["same_bar_policy_id"]) == int(
        np.asarray(rust.metadata["ambiguity_policy"], dtype=np.uint8)[-1]
    )


@pytest.mark.parametrize(
    ("gap_policy", "expected_exit"),
    [
        (TakeProfitGapPolicy.LIMIT_PRICE_CONSERVATIVE, 108.0),
        (TakeProfitGapPolicy.OPEN_PRICE_IMPROVEMENT, 112.0),
    ],
)
def test_phase69_stop_target_gap_and_trailing_are_oracle_exact(gap_policy, expected_exit) -> None:
    frame = _frame(
        [
            {},
            {"open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0},
            {"open": 112.0, "high": 113.0, "low": 109.0, "close": 110.0},
            {"open": 110.0, "high": 111.0, "low": 101.0, "close": 103.0},
        ]
    )
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0, 0],
        entry_size=[1.0, 0.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan, np.nan],
        take_profit_value=[0.08, np.nan, np.nan, np.nan],
        trailing_value=[0.04, np.nan, np.nan, np.nan],
    )
    contract = ExecutionContract.intrabar_bracket(
        take_profit_gap_policy=gap_policy,
        close_on_last_bar=False,
    )
    _reference, _numba, rust = _triple(frame, intent, contract=contract, fee_rate=0.0, slippage_rate=0.0)
    assert rust.fills[-1].reason.value == "take_profit"
    assert rust.fills[-1].price == pytest.approx(expected_exit)


def test_phase69_technical_reversal_funding_liquidation_and_tick_constraints() -> None:
    frame = _frame(
        [
            {"funding_rate": 0.0},
            {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "funding_rate": 0.0001},
            {"open": 101.0, "high": 102.0, "low": 99.0, "close": 100.0, "funding_rate": 0.0},
            {"open": 100.0, "high": 180.0, "low": 20.0, "close": 50.0, "funding_rate": 0.0},
        ]
    )
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, -1, 0, 0],
        entry_size=[1.19, 1.19, 0.0, 0.0],
        trailing_value=[0.03, 0.03, np.nan, np.nan],
        exit_long=[False, False, False, False],
        exit_short=[False, False, False, False],
    )
    _reference, _numba, rust = _triple(
        frame,
        intent,
        account=AccountConfig(initial_capital=1_000.0, leverage=2.0, maintenance_ratio=1.5),
        use_funding=True,
        fee_rate=0.0005,
        slippage_rate=0.0001,
        bar_timestamp_semantics="open",
        qty_step=0.1,
        tick_size=0.1,
    )
    # This case may liquidate before reversal depending on the marked equity,
    # but it must preserve price quantization and funding timing parity.
    assert all(abs(fill.qty * 10 - round(fill.qty * 10)) < 1e-9 for fill in rust.fills)
    assert rust.metadata["funding_timing_certified"] is True


def test_phase69_session_stale_reentry_eod_and_prepared_runner_parity() -> None:
    frame = _frame(
        [
            {},
            {"low": 94.0},
            {},
            {},
        ]
    )
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 1, 0, 0],
        entry_size=[1.0, 1.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan, np.nan],
    )
    session_tape = IntrabarSessionTape(
        session_id=np.array([0, 0, 1, 1], dtype=np.int64),
        entry_allowed_at_open=np.array([True, True, True, True]),
        force_flat_at_open=np.array([False, False, False, True]),
    )
    policy = SessionExecutionPolicy(
        max_long_entries_per_session=1,
        protective_exit_reentry_policy=ProtectiveExitReentryPolicy.SUPPRESS_SIGNAL_BAR,
    )
    _reference, _numba, direct = _triple(
        frame,
        intent,
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=True),
        fee_rate=0.0,
        slippage_rate=0.0,
        session_policy=policy,
        session_tape=session_tape,
    )

    endpoint = QuantBTEndpoint.intrabar_bracket_rust(
        initial_capital=10_000.0,
        leverage=3.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        use_funding=False,
        close_on_last_bar=True,
        session_policy=policy,
        report_level="audit",
    )
    regular = endpoint.backtest(data=frame, intent=intent, symbols=["BTC"], session_tape=session_tape)
    prepared = endpoint.prepare_intrabar(data=frame, symbols=["BTC"], session_tape=session_tape).run(intent)
    np.testing.assert_allclose(regular.equity.to_numpy(), direct.equity.to_numpy(), rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(prepared.equity.to_numpy(), direct.equity.to_numpy(), rtol=0.0, atol=1e-9)
    assert regular.metadata["native_execution_request_fingerprint"] == prepared.metadata["native_execution_request_fingerprint"]
    assert regular.metadata["session_execution_enabled"] is True
    assert prepared.metadata["prepared_runner"] is True


def test_phase69_public_endpoint_preserves_contract_and_rejects_report_score() -> None:
    frame = _frame([{}, {"high": 111.0, "low": 94.0}, {}])
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan],
        take_profit_value=[0.08, np.nan, np.nan],
    )
    contract = ExecutionContract.intrabar_bracket(
        same_bar_policy=IntrabarSameBarPolicy.TP_FIRST,
        close_on_last_bar=False,
    )
    tape = prepare_market_tape(data=frame, symbols=["BTC"], use_funding=False)
    direct = run_rust_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=AccountConfig(initial_capital=10_000.0, leverage=3.0),
        contract=contract,
        fee_rate=0.0,
        slippage_rate=0.0,
        report_level="audit",
    )
    endpoint = QuantBTEndpoint.intrabar_bracket_rust(
        initial_capital=10_000.0,
        leverage=3.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        use_funding=False,
        execution_contract=contract,
        report_level="audit",
    )
    public = endpoint.backtest(data=frame, intent=intent, symbols=["BTC"])
    np.testing.assert_allclose(public.equity.to_numpy(), direct.equity.to_numpy(), rtol=0.0, atol=1e-9)
    assert public.metadata["execution_contract"] == contract.to_metadata()
    assert int(public.metadata["ambiguity_policy_id"]) == 3
    assert int(public.metadata["fills_report"].iloc[-1]["same_bar_policy_id"]) == 3
    with pytest.raises(ValueError, match="score is reserved"):
        QuantBTEndpoint.intrabar_bracket_rust(report_level="score")


def test_phase69_reject_ambiguous_fails_closed_and_bounded_audit_is_explicit() -> None:
    frame = _frame([{}, {"high": 110.0, "low": 94.0}, {}])
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan],
        take_profit_value=[0.08, np.nan, np.nan],
    )
    tape = prepare_market_tape(data=frame, symbols=["BTC"], use_funding=False)
    reject = ExecutionContract.intrabar_bracket(
        same_bar_policy=IntrabarSameBarPolicy.REJECT_AMBIGUOUS,
        close_on_last_bar=False,
    )
    with pytest.raises(NotImplementedError, match="reject_ambiguous"):
        run_rust_intrabar_kernel(
            tape=tape,
            intent=intent,
            account=AccountConfig(initial_capital=10_000.0),
            contract=reject,
            report_level="audit",
        )

    bounded = run_rust_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=AccountConfig(initial_capital=10_000.0),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        report_level="audit",
        audit_detail_limit=1,
    )
    assert bounded.metadata["audit_detail_truncated"] is True
    assert bounded.metadata["audit_detail_retained_rows"] == 1
    assert bounded.metadata["audit_detail_dropped_rows"] >= 1


def test_phase69_installed_extension_declares_intrabar_capabilities() -> None:
    native = importlib.import_module("_quantbt_native")
    capabilities = dict(native.capabilities())
    assert capabilities["rust_intrabar_bracket_v1"] is True
    assert capabilities["rust_intrabar_session_bracket_v1"] is True
