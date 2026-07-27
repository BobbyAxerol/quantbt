from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionContract,
    ExecutionConfig,
    FillPhase,
    FillReplayTape,
    IntrabarEventFlag,
    IntrabarFillReason,
    IntrabarIntentTape,
    IntrabarSizingMode,
    QuantBTEndpoint,
    IntrabarSameBarPolicy,
    TakeProfitGapPolicy,
    prepare_market_tape,
    run_fill_replay_kernel,
    run_intrabar_kernel,
    run_intrabar_reference,
)


def _frame(rows, *, tz="UTC"):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz=tz)
    return pd.DataFrame(rows, index=idx)


def test_phase31e_intrabar_uses_slippage_bps_as_source_of_truth():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "entry": 1.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "entry": 0.0},
        ]
    )
    bt = QuantBTEndpoint.intrabar_bracket(
        initial_capital=10_000.0,
        execution=ExecutionConfig(slippage_bps=10.0),
        fee_rate=0.0,
        use_funding=False,
        close_on_last_bar=False,
        report_level="audit",
    )

    bt.backtest(data=df, signal_col="entry", symbols=["BTC"])

    assert bt.fills_report.iloc[0]["price"] == pytest.approx(100.1)
    assert bt.result.metadata["run_config"]["execution"]["slippage_bps"] == 10.0


def test_phase31e_legacy_slippage_conflict_raises():
    with pytest.raises(ValueError, match="either slippage_bps or legacy slippage"):
        QuantBTEndpoint.intrabar_bracket(slippage=0.0001, slippage_bps=1.0)


def test_phase31e_scalar_funding_rejected_unless_zero_policy_or_disabled():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        ]
    )
    with pytest.raises(ValueError, match="strict funding"):
        prepare_market_tape(data=df, symbols=["BTC"], funding_rate=0.0001, use_funding=True)

    tape = prepare_market_tape(data=df, symbols=["BTC"], funding_rate=0.0, use_funding=True, missing_funding_policy="zero")
    assert not tape.funding_event_mask.any()


def test_phase31g_funding_event_requires_exact_bar_boundary_and_applies_there():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        ]
    )
    with pytest.raises(ValueError, match="align exactly"):
        prepare_market_tape(
            data=df,
            symbols=["BTC"],
            use_funding=True,
            funding_event_timestamps=[pd.Timestamp("2024-01-01 00:30", tz="UTC")],
            funding_event_rates=[0.001],
        )

    tape = prepare_market_tape(
        data=df,
        symbols=["BTC"],
        use_funding=True,
        funding_event_timestamps=[pd.Timestamp("2024-01-01 01:00", tz="UTC")],
        funding_event_rates=[0.001],
    )

    assert tape.funding_event_mask.tolist() == [False, True, False]
    assert tape.funding_rates[1, 0] == pytest.approx(0.001)


def test_phase31h_funding_timestamp_semantics_open_vs_close_and_kernel_parity():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 120.0, "low": 100.0, "close": 120.0},
            {"open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0},
        ]
    )
    funding_ts = [df.index[2]]
    funding_rate = [0.01]
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        exit_long=[False, True, False],
    )
    account = AccountConfig(initial_capital=10_000.0)
    contract = ExecutionContract.intrabar_bracket(close_on_last_bar=False)

    tape_open = prepare_market_tape(
        data=df,
        symbols=["BTC"],
        use_funding=True,
        funding_event_timestamps=funding_ts,
        funding_event_rates=funding_rate,
        bar_timestamp_semantics="open",
    )
    tape_close = prepare_market_tape(
        data=df,
        symbols=["BTC"],
        use_funding=True,
        funding_event_timestamps=funding_ts,
        funding_event_rates=funding_rate,
        bar_timestamp_semantics="close",
    )

    open_oracle = run_intrabar_reference(tape=tape_open, intent=intent, account=account, contract=contract)
    close_oracle = run_intrabar_reference(tape=tape_close, intent=intent, account=account, contract=contract)
    open_kernel = run_intrabar_kernel(tape=tape_open, intent=intent, account=account, contract=contract, report_level="audit")
    close_kernel = run_intrabar_kernel(tape=tape_close, intent=intent, account=account, contract=contract, report_level="audit")

    assert open_oracle.funding.iloc[2] == pytest.approx(2.0)
    assert close_oracle.funding.iloc[2] == pytest.approx(0.0)
    assert open_oracle.equity.iloc[-1] == pytest.approx(10_098.0)
    assert close_oracle.equity.iloc[-1] == pytest.approx(10_100.0)
    np.testing.assert_allclose(open_kernel.equity.to_numpy(), open_oracle.equity.to_numpy(), atol=1e-9, rtol=0.0)
    np.testing.assert_allclose(close_kernel.equity.to_numpy(), close_oracle.equity.to_numpy(), atol=1e-9, rtol=0.0)
    assert open_kernel.metadata["bar_timestamp_semantics"] == "open"
    assert close_kernel.metadata["funding_event_price_reference"] == "close"


def test_phase31h_endpoint_propagates_bar_timestamp_semantics_to_intrabar_tape():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "entry": 1.0, "exit": False},
            {"open": 100.0, "high": 120.0, "low": 100.0, "close": 120.0, "entry": 0.0, "exit": True},
            {"open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "entry": 0.0, "exit": True},
        ]
    )
    bt = QuantBTEndpoint.intrabar_bracket(
        initial_capital=10_000.0,
        fee_rate=0.0,
        use_funding=True,
        bar_timestamp_semantics="open",
        close_on_last_bar=False,
        report_level="audit",
    )

    result = bt.backtest(
        data=df,
        signal_col="entry",
        symbols=["BTC"],
        intent_cols={"exit_long": "exit"},
        funding_event_timestamps=[df.index[2]],
        funding_event_rates=[0.01],
    )

    assert result.metadata["validation_certificate"]["bar_timestamp_semantics"] == "open"
    assert result.metadata["bar_timestamp_semantics"] == "open"
    assert result.funding.iloc[2] == pytest.approx(2.0)


def test_phase31e_dynamic_trailing_uses_value_at_t_not_t_minus_1():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0},
            {"open": 110.0, "high": 111.0, "low": 100.0, "close": 108.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        trailing_value=[0.20, 0.05, 0.05],
    )

    result = run_intrabar_reference(tape=tape, intent=intent, account=AccountConfig(initial_capital=10_000.0))
    kernel = run_intrabar_kernel(tape=tape, intent=intent, account=AccountConfig(initial_capital=10_000.0), report_level="audit")

    assert result.fills[1].reason is IntrabarFillReason.STOP_LOSS
    assert result.fills[1].price == pytest.approx(104.5)
    np.testing.assert_allclose(kernel.equity.to_numpy(), result.equity.to_numpy(), atol=1e-9, rtol=0.0)


def test_phase31e_fixed_notional_pct_equity_risk_sizing_and_qty_filters():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 0], entry_size=[1.0, 0.0], stop_value=[0.05, np.nan])
    account = AccountConfig(initial_capital=10_000.0, leverage=10.0)

    fixed = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        sizing_mode=IntrabarSizingMode.FIXED_NOTIONAL,
        fixed_notional=1_000.0,
        qty_step=0.25,
        report_level="audit",
    )
    assert fixed.fills[0].qty == pytest.approx(10.0)

    pct = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        sizing_mode=IntrabarSizingMode.PCT_EQUITY,
        equity_fraction=0.10,
        qty_step=0.25,
        report_level="audit",
    )
    assert pct.fills[0].qty == pytest.approx(10.0)

    risk = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        sizing_mode=IntrabarSizingMode.RISK_PER_TRADE,
        risk_fraction=0.01,
        qty_step=0.5,
        report_level="audit",
    )
    assert risk.fills[0].qty == pytest.approx(20.0)

    rejected = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        sizing_mode=IntrabarSizingMode.FIXED_NOTIONAL,
        fixed_notional=1.0,
        min_notional=5.0,
        report_level="audit",
    )
    assert rejected.rejected_count == 1
    assert rejected.fill_count == 0


def test_phase31e_exit_long_short_are_side_specific_and_same_side_entry_is_exit_only():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 1, 0],
        entry_size=[1.0, 1.0, 0.0],
        exit_long=[False, True, False],
        exit_short=[True, False, False],
    )

    result = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=AccountConfig(initial_capital=10_000.0),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        report_level="audit",
    )

    assert [fill.reason for fill in result.fills] == [IntrabarFillReason.ENTRY, IntrabarFillReason.TECHNICAL_EXIT]
    assert result.position.iloc[-1] == 0.0
    assert result.rejected_count == 0
    assert int(result.event_flags.iloc[2]) & int(IntrabarEventFlag.ENTRY_SUPPRESSED)


def test_phase31e_strict_timezone_rejects_naive_and_localizes_source_timezone():
    naive = pd.DataFrame(
        [{"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}],
        index=pd.date_range("2024-01-01", periods=1, freq="1h"),
    )
    with pytest.raises(ValueError, match="timezone-naive"):
        prepare_market_tape(data=naive, symbols=["BTC"], use_funding=False)

    tape = prepare_market_tape(data=naive, symbols=["BTC"], use_funding=False, source_timezone="Asia/Ho_Chi_Minh")
    ts = pd.Timestamp(tape.timestamps_ns[0], tz="UTC")
    assert ts == pd.Timestamp("2023-12-31 17:00", tz="UTC")


def test_phase31e_unsupported_contract_field_raises():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(entry_side=[1, 0], entry_size=[1.0, 0.0])
    bad = replace(ExecutionContract.intrabar_bracket(), entry_fill_phase=FillPhase.SAME_CLOSE)

    with pytest.raises(NotImplementedError, match="entry_fill_phase"):
        run_intrabar_kernel(tape=tape, intent=intent, account=AccountConfig(initial_capital=10_000.0), contract=bad)


def test_phase31g_endpoint_preserves_full_execution_contract_policies():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "entry": 1.0, "tp": 0.05},
            {"open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0, "entry": 0.0, "tp": np.nan},
        ]
    )
    contract = ExecutionContract.intrabar_bracket(
        same_bar_policy=IntrabarSameBarPolicy.TP_FIRST,
        take_profit_gap_policy=TakeProfitGapPolicy.OPEN_PRICE_IMPROVEMENT,
        close_on_last_bar=False,
    )
    bt = QuantBTEndpoint.intrabar_bracket(
        execution_contract=contract,
        initial_capital=10_000.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        use_funding=False,
        report_level="audit",
    )

    result = bt.backtest(data=df, signal_col="entry", symbols=["BTC"], intent_cols={"take_profit_value": "tp"})
    restored = ExecutionContract.from_metadata(result.metadata["execution_contract"])

    assert restored.same_bar_policy is IntrabarSameBarPolicy.TP_FIRST
    assert restored.take_profit_gap_policy is TakeProfitGapPolicy.OPEN_PRICE_IMPROVEMENT
    assert restored.close_on_last_bar is False


def test_phase31e_fill_replay_certification_is_granular():
    df = _frame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    fills = FillReplayTape.from_frame(pd.DataFrame([{"bar_index": 1, "side": 1, "qty": 1.0, "price": 100.0, "fee": 0.0}]))

    result = run_fill_replay_kernel(tape=tape, fill_tape=fills, account=AccountConfig(initial_capital=10_000.0))

    assert result.metadata["price_accounting_certified"] is True
    assert result.metadata["fee_accounting_certified"] is True
    assert result.metadata["funding_certified"] is False
    assert result.metadata["margin_certified"] is False
    assert result.metadata["execution_generation_certified"] is False


def test_phase31f_prepared_intrabar_runner_matches_normal_endpoint_and_freezes_profile():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "entry": 1.0, "sl": 0.05},
            {"open": 100.0, "high": 101.0, "low": 94.0, "close": 98.0, "entry": 0.0, "sl": np.nan},
            {"open": 98.0, "high": 99.0, "low": 97.0, "close": 98.0, "entry": 0.0, "sl": np.nan},
        ]
    )
    bt = QuantBTEndpoint.intrabar_bracket(initial_capital=10_000.0, fee_rate=0.0, use_funding=False, report_level="audit")
    normal = bt.backtest(data=df, signal_col="entry", symbols=["BTC"], intent_cols={"stop_value": "sl"})
    runner = bt.prepare_intrabar(data=df, symbols=["BTC"])
    intent = IntrabarIntentTape.from_arrays(entry_side=df["entry"].to_numpy(), entry_size=np.abs(df["entry"].to_numpy()), stop_value=df["sl"].to_numpy())
    prepared = runner.run(intent, report_level="audit")

    np.testing.assert_allclose(prepared.equity.to_numpy(), normal.equity.to_numpy(), atol=1e-9, rtol=0.0)
    assert prepared.metadata["prepared_runner"] is True
    assert prepared.metadata["profile_metadata"]["data_signature"] == normal.metadata["data_signature"]
    assert "prepared_signature" in prepared.metadata["profile_metadata"]


def test_phase31g_data_signature_changes_with_volume_and_funding():
    base = _frame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
        ]
    )
    changed_volume = base.copy()
    changed_volume.iloc[1, changed_volume.columns.get_loc("volume")] = 2.0
    funding = pd.Series([0.0, 0.001], index=base.index)
    no_funding = pd.Series([0.0, 0.0], index=base.index)

    sig_base = prepare_market_tape(data=base, symbols=["BTC"], use_funding=False).signature
    sig_volume = prepare_market_tape(data=changed_volume, symbols=["BTC"], use_funding=False).signature
    sig_funding = prepare_market_tape(data=base, symbols=["BTC"], use_funding=True, funding_rate=funding).signature
    sig_no_funding = prepare_market_tape(data=base, symbols=["BTC"], use_funding=True, funding_rate=no_funding).signature
    sig_open_semantics = prepare_market_tape(data=base, symbols=["BTC"], use_funding=False, bar_timestamp_semantics="open").signature

    assert sig_base != sig_volume
    assert sig_funding != sig_no_funding
    assert sig_base != sig_open_semantics


def test_phase31g_tick_size_quantizes_entry_stop_tp_and_trailing():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "entry": 1.0, "sl": 0.051, "trail": 0.033},
            {"open": 100.03, "high": 102.0, "low": 96.0, "close": 101.07, "entry": 0.0, "sl": np.nan, "trail": 0.033},
            {"open": 101.0, "high": 102.0, "low": 97.0, "close": 100.0, "entry": 0.0, "sl": np.nan, "trail": 0.033},
        ]
    )
    bt = QuantBTEndpoint.intrabar_bracket(
        initial_capital=10_000.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        use_funding=False,
        tick_size=0.05,
        report_level="audit",
    )
    bt.backtest(data=df, signal_col="entry", symbols=["BTC"], intent_cols={"stop_value": "sl", "trailing_value": "trail"})

    assert bt.fills_report.iloc[0]["price"] == pytest.approx(100.05)
    ticks = bt.fills_report["price"].to_numpy(dtype=float) / 0.05
    np.testing.assert_allclose(ticks, np.round(ticks), atol=1e-9, rtol=0.0)
