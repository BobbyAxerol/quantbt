from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    EntryPositionPolicy,
    ExecutionContract,
    IntrabarEventFlag,
    IntrabarFillReason,
    IntrabarIntentTape,
    IntrabarSessionTape,
    ProtectiveExitReentryPolicy,
    QuantBTEndpoint,
    SessionExecutionPolicy,
    prepare_market_tape,
    run_intrabar_kernel,
    run_intrabar_reference,
    run_intrabar_session_kernel,
)


def _frame(rows) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01 00:00", periods=len(rows), freq="1h", tz="UTC")
    normalized = []
    for row in rows:
        payload = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}
        payload.update(row)
        normalized.append(payload)
    return pd.DataFrame(normalized, index=idx)


def _session(n, *, session_id=None, entry_allowed=None, force_flat=None) -> IntrabarSessionTape:
    return IntrabarSessionTape(
        session_id=np.asarray(session_id if session_id is not None else np.zeros(n), dtype=np.int64),
        entry_allowed_at_open=np.asarray(entry_allowed if entry_allowed is not None else np.ones(n), dtype=bool),
        force_flat_at_open=np.asarray(force_flat if force_flat is not None else np.zeros(n), dtype=bool),
    )


def _run(df, intent, policy, session_tape, *, account=None):
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    return run_intrabar_reference(
        tape=tape,
        intent=intent,
        account=account or AccountConfig(initial_capital=10_000.0, leverage=10.0),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        session_policy=policy,
        session_tape=session_tape,
    )


def _assert_session_kernel_matches_reference(df, intent, policy, session_tape, *, account=None):
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    account = account or AccountConfig(initial_capital=10_000.0, leverage=10.0)
    contract = ExecutionContract.intrabar_bracket(close_on_last_bar=False)
    reference = run_intrabar_reference(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        session_policy=policy,
        session_tape=session_tape,
    )
    kernel = run_intrabar_session_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        session_policy=policy,
        session_tape=session_tape,
        report_level="audit",
    )
    np.testing.assert_allclose(kernel.equity.to_numpy(), reference.equity.to_numpy(), atol=1e-9, rtol=0.0)
    np.testing.assert_allclose(kernel.position.to_numpy(), reference.position.to_numpy(), atol=1e-9, rtol=0.0)
    np.testing.assert_array_equal(kernel.event_flags.to_numpy(), reference.event_flags.to_numpy())
    assert [fill.reason for fill in kernel.fills] == [fill.reason for fill in reference.fills]
    assert kernel.fill_count == len(reference.fills)
    for key in (
        "session_reset_count",
        "session_forced_exit_count",
        "entry_window_blocked_count",
        "long_quota_blocked_count",
        "short_quota_blocked_count",
        "flat_only_blocked_count",
        "stale_session_signal_count",
        "reentry_suppressed_count",
    ):
        assert kernel.metadata[key] == reference.metadata[key]
    return reference, kernel


def test_phase31h_no_session_path_matches_existing_fast_kernel():
    df = _frame(
        [
            {},
            {"high": 110.0, "low": 94.0},
            {},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan],
    )
    contract = ExecutionContract.intrabar_bracket(close_on_last_bar=False)

    reference = run_intrabar_reference(tape=tape, intent=intent, account=AccountConfig(initial_capital=10_000.0), contract=contract)
    kernel = run_intrabar_kernel(tape=tape, intent=intent, account=AccountConfig(initial_capital=10_000.0), contract=contract, report_level="audit")

    np.testing.assert_allclose(reference.equity.to_numpy(), kernel.equity.to_numpy(), atol=1e-9, rtol=0.0)
    np.testing.assert_array_equal(reference.event_flags.to_numpy(), kernel.event_flags.to_numpy())
    assert reference.metadata["session_execution_enabled"] is False


def test_phase31h_session_boundary_resets_entry_quota():
    df = _frame([{}, {}, {}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0, 1, 0],
        entry_size=[1, 0, 0, 1, 0],
        technical_exit=[False, True, False, False, False],
    )
    session_tape = _session(5, session_id=[0, 0, 0, 1, 1])
    policy = SessionExecutionPolicy(max_long_entries_per_session=1)

    result = _run(df, intent, policy, session_tape)

    assert result.metadata["session_reset_count"] == 1
    assert result.metadata["long_quota_blocked_count"] == 0
    assert [fill.reason for fill in result.fills] == [
        IntrabarFillReason.ENTRY,
        IntrabarFillReason.TECHNICAL_EXIT,
        IntrabarFillReason.ENTRY,
    ]


def test_phase31h_stale_signal_does_not_fill_in_new_session():
    df = _frame([{}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(entry_side=[0, 1, 0], entry_size=[0, 1, 0])
    session_tape = _session(3, session_id=[0, 0, 1])
    policy = SessionExecutionPolicy()

    result = _run(df, intent, policy, session_tape)

    assert result.fills == ()
    assert result.metadata["stale_session_signal_count"] == 1
    assert int(result.event_flags.iloc[2]) & int(IntrabarEventFlag.STALE_SESSION_SIGNAL)


def test_phase31h_flat_only_blocks_reversal_without_implicit_exit():
    df = _frame([{}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, -1, 0], entry_size=[1, 1, 0])
    policy = SessionExecutionPolicy(entry_position_policy=EntryPositionPolicy.FLAT_ONLY)

    result = _run(df, intent, policy, _session(3))

    assert [fill.reason for fill in result.fills] == [IntrabarFillReason.ENTRY]
    assert result.position.iloc[-1] == 1.0
    assert result.metadata["flat_only_blocked_count"] == 1
    assert int(result.event_flags.iloc[2]) & int(IntrabarEventFlag.FLAT_ONLY_BLOCKED)


def test_phase31h_long_entry_quota_blocks_fourth_style_entry_without_reject():
    df = _frame([{}, {}, {}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 1, 0, 0],
        entry_size=[1, 0, 1, 0, 0],
        technical_exit=[False, True, False, False, False],
    )
    policy = SessionExecutionPolicy(max_long_entries_per_session=1)

    result = _run(df, intent, policy, _session(5))

    assert [fill.reason for fill in result.fills] == [IntrabarFillReason.ENTRY, IntrabarFillReason.TECHNICAL_EXIT]
    assert result.metadata["long_quota_blocked_count"] == 1
    assert result.rejected_count == 0
    assert int(result.event_flags.iloc[3]) & int(IntrabarEventFlag.ENTRY_QUOTA_BLOCKED)


def test_phase31h_margin_reject_does_not_increment_quota():
    df = _frame([{}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 1, 0], entry_size=[1_000_000, 1, 0])
    policy = SessionExecutionPolicy(max_long_entries_per_session=1)

    result = _run(df, intent, policy, _session(3), account=AccountConfig(initial_capital=1_000.0, leverage=1.0))

    assert result.rejected_count == 1
    assert result.metadata["long_quota_blocked_count"] == 0
    assert [fill.reason for fill in result.fills] == [IntrabarFillReason.ENTRY]


def test_phase31h_entry_then_same_bar_stop_counts_for_quota():
    df = _frame([{}, {"low": 94.0}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 1, 0, 0],
        entry_size=[1, 1, 0, 0],
        stop_value=[0.05, np.nan, np.nan, np.nan],
    )
    policy = SessionExecutionPolicy(max_long_entries_per_session=1)

    result = _run(df, intent, policy, _session(4))

    assert [fill.reason for fill in result.fills] == [IntrabarFillReason.ENTRY, IntrabarFillReason.STOP_LOSS]
    assert result.metadata["long_quota_blocked_count"] == 1
    assert int(result.event_flags.iloc[2]) & int(IntrabarEventFlag.ENTRY_QUOTA_BLOCKED)


def test_phase31h_force_flat_bar_closes_and_suppresses_entry():
    df = _frame([{}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 1, 0], entry_size=[1, 1, 0])
    session_tape = _session(3, force_flat=[False, False, True])
    policy = SessionExecutionPolicy()

    result = _run(df, intent, policy, session_tape)

    assert [fill.reason for fill in result.fills] == [
        IntrabarFillReason.ENTRY,
        IntrabarFillReason.SESSION_FORCED_EXIT,
    ]
    assert result.position.iloc[-1] == 0.0
    assert result.metadata["session_forced_exit_count"] == 1
    assert int(result.event_flags.iloc[2]) & int(IntrabarEventFlag.SESSION_FORCED_EXIT)


def test_phase31h_protective_exit_suppresses_next_signal_when_enabled():
    df = _frame([{}, {"low": 94.0}, {}])
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 1, 0],
        entry_size=[1, 1, 0],
        stop_value=[0.05, np.nan, np.nan],
    )
    policy = SessionExecutionPolicy(
        protective_exit_reentry_policy=ProtectiveExitReentryPolicy.SUPPRESS_SIGNAL_BAR,
    )

    result = _run(df, intent, policy, _session(3))

    assert [fill.reason for fill in result.fills] == [IntrabarFillReason.ENTRY, IntrabarFillReason.STOP_LOSS]
    assert result.metadata["reentry_suppressed_count"] == 1
    assert int(result.event_flags.iloc[2]) & int(IntrabarEventFlag.PROTECTIVE_REENTRY_BLOCKED)


def test_phase31h_endpoint_accepts_session_policy_and_tape_on_reference_route():
    df = _frame([{}, {}, {}])
    policy = SessionExecutionPolicy(max_long_entries_per_session=1)
    session_tape = _session(3)
    bt = QuantBTEndpoint.intrabar_bracket_reference(
        initial_capital=10_000.0,
        fee_rate=0.0,
        use_funding=False,
        session_policy=policy,
    )

    result = bt.backtest(data=df, signal=pd.Series([1, 0, 0], index=df.index), session_tape=session_tape, symbols=["BTC"])

    assert result.metadata["session_execution_enabled"] is True
    assert result.metadata["session_policy"]["max_long_entries_per_session"] == 1


def test_phase31i_session_kernel_matches_reference_for_quota_force_flat_and_reentry():
    df = _frame([{}, {"low": 94.0}, {}, {}, {}])
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 1, 0, 1, 0],
        entry_size=[1, 1, 0, 1, 0],
        stop_value=[0.05, np.nan, np.nan, np.nan, np.nan],
    )
    policy = SessionExecutionPolicy(
        max_long_entries_per_session=2,
        protective_exit_reentry_policy=ProtectiveExitReentryPolicy.SUPPRESS_SIGNAL_BAR,
    )
    session_tape = _session(5, force_flat=[False, False, False, False, True])

    reference, kernel = _assert_session_kernel_matches_reference(df, intent, policy, session_tape)

    assert kernel.metadata["engine_id"] == "intrabar_session_bracket_v1"
    assert reference.metadata["reentry_suppressed_count"] == 1


def test_phase31i_fast_route_accepts_session_policy_and_matches_reference_route():
    df = _frame([{}, {"low": 94.0}, {}])
    signal = pd.Series([1, 1, 0], index=df.index)
    policy = SessionExecutionPolicy(
        protective_exit_reentry_policy=ProtectiveExitReentryPolicy.SUPPRESS_SIGNAL_BAR,
    )
    session_tape = _session(3)
    ref_bt = QuantBTEndpoint.intrabar_bracket_reference(
        initial_capital=10_000.0,
        fee_rate=0.0,
        use_funding=False,
        close_on_last_bar=False,
        session_policy=policy,
    )
    fast_bt = QuantBTEndpoint.intrabar_bracket(
        initial_capital=10_000.0,
        fee_rate=0.0,
        use_funding=False,
        close_on_last_bar=False,
        report_level="audit",
        session_policy=policy,
    )

    df_with_stop = df.assign(sl=[0.05, np.nan, np.nan])
    ref_result = ref_bt.backtest(data=df_with_stop, signal=signal, session_tape=session_tape, symbols=["BTC"], intent_cols={"stop_value": "sl"})
    fast_result = fast_bt.backtest(data=df_with_stop, signal=signal, session_tape=session_tape, symbols=["BTC"], intent_cols={"stop_value": "sl"})

    np.testing.assert_allclose(fast_result.equity.to_numpy(), ref_result.equity.to_numpy(), atol=1e-9, rtol=0.0)
    assert fast_result.metadata["engine_id"] == "intrabar_session_bracket_v1"


def test_phase31i_prepared_session_runner_matches_normal_fast_endpoint():
    bt = QuantBTEndpoint.intrabar_bracket(
        initial_capital=10_000.0,
        fee_rate=0.0,
        use_funding=False,
        close_on_last_bar=False,
        report_level="audit",
        session_policy=SessionExecutionPolicy(),
    )
    df = _frame([{}, {}, {}])
    signal = pd.Series([1, 0, 0], index=df.index)
    session_tape = _session(3)

    normal = bt.backtest(data=df, signal=signal, session_tape=session_tape, symbols=["BTC"])
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 0, 0], entry_size=[1, 0, 0])
    runner = bt.prepare_intrabar(data=df, symbols=["BTC"], session_tape=session_tape)
    prepared = runner.run(intent, report_level="audit")

    np.testing.assert_allclose(prepared.equity.to_numpy(), normal.equity.to_numpy(), atol=1e-9, rtol=0.0)
    assert prepared.metadata["profile_metadata"]["session_tape_signature"] == session_tape.signature


def test_phase31h_session_tape_from_index_builds_local_date_windows():
    idx = pd.date_range("2024-01-01 08:00", periods=4, freq="1h", tz="Asia/Ho_Chi_Minh")

    tape = IntrabarSessionTape.from_index(
        idx,
        timezone="Asia/Ho_Chi_Minh",
        entry_windows=(("09:00", "10:00"),),
        force_flat_time="11:00",
    )

    assert tape.session_id.tolist() == [0, 0, 0, 0]
    assert tape.entry_allowed_at_open.tolist() == [False, True, True, False]
    assert tape.force_flat_at_open.tolist() == [False, False, False, True]
    assert tape.signature
