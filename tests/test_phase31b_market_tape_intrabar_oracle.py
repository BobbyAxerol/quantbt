from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionContract,
    IntrabarFillReason,
    IntrabarIntentTape,
    IntrabarLevelMode,
    get_execution_contract,
    prepare_market_tape,
    run_intrabar_reference,
    QuantBTEndpoint,
)


def _frame(rows) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def test_phase31b_execution_contract_registry_exposes_core_contracts():
    contract = get_execution_contract("intrabar_bracket_v1")

    assert contract.engine_id == "intrabar_bracket_v1"
    assert contract.signal_phase.value == "bar_close"
    assert contract.entry_fill_phase.value == "next_open"
    assert ExecutionContract.close_target().to_metadata()["engine_id"] == "close_target_v2"


def test_phase31b_prepare_market_tape_strict_certificate_and_immutable_arrays():
    df = _frame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0},
            {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 11.0},
        ]
    )

    tape = prepare_market_tape(data=df, symbols=["BTC"], funding_rate=0.0)

    assert tape.symbols == ("BTC",)
    assert tape.validation_certificate.row_count == 2
    assert tape.validation_certificate.ohlc_ok is True
    assert tape.opens.flags.writeable is False
    with pytest.raises(ValueError):
        tape.opens[0, 0] = 1.0


def test_phase31b_prepare_market_tape_rejects_duplicate_unsorted_missing_and_invalid_ohlc():
    duplicate_idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-01-01 00:00", tz="UTC"),
            pd.Timestamp("2024-01-01 00:00", tz="UTC"),
        ]
    )
    duplicate = pd.DataFrame(
        {"open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0], "close": [1.0, 1.0]},
        index=duplicate_idx,
    )
    with pytest.raises(ValueError, match="duplicate"):
        prepare_market_tape(data=duplicate)

    missing = _frame([{"open": 1.0, "high": 1.0, "close": 1.0}])
    with pytest.raises(ValueError, match="missing"):
        prepare_market_tape(data=missing)

    invalid = _frame([{"open": 100.0, "high": 99.0, "low": 98.0, "close": 100.0}])
    with pytest.raises(ValueError, match="invalid OHLCV"):
        prepare_market_tape(data=invalid)


def test_phase31b_prepare_market_tape_funding_dict_requires_symbols():
    df = _frame(
        [
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        ]
    )
    with pytest.raises(KeyError, match="ETH"):
        prepare_market_tape(data={"BTC": df, "ETH": df}, funding_rate={"BTC": 0.0})


def test_phase31b_intrabar_oracle_conservative_same_bar_stop_tp_conflict():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 110.0, "low": 94.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        stop_value=[0.05, np.nan, np.nan],
        take_profit_value=[0.08, np.nan, np.nan],
        level_mode=IntrabarLevelMode.PERCENT_DISTANCE,
    )

    result = run_intrabar_reference(tape=tape, intent=intent, account=AccountConfig(initial_capital=10_000.0))

    assert [fill.reason for fill in result.fills] == [IntrabarFillReason.ENTRY, IntrabarFillReason.STOP_LOSS]
    assert result.fills[1].price == 95.0
    assert result.ambiguity_count == 1
    assert result.position.iloc[-1] == 0.0
    assert result.equity.iloc[-1] == 9_995.0


def test_phase31b_intrabar_oracle_trailing_update_is_next_bar_not_same_bar():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0},
            {"open": 110.0, "high": 111.0, "low": 104.0, "close": 108.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, 0, 0],
        entry_size=[1.0, 0.0, 0.0],
        stop_value=[0.10, np.nan, np.nan],
        trailing_value=[0.05, 0.05, 0.05],
    )

    result = run_intrabar_reference(tape=tape, intent=intent, account=AccountConfig(initial_capital=10_000.0))

    assert len(result.fills) == 2
    assert result.fills[1].bar_index == 2
    assert result.fills[1].price == 104.5
    assert result.equity.iloc[-1] == 10_004.5


def test_phase31b_intrabar_oracle_reversal_is_two_legs_with_two_fees():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 102.0, "high": 103.0, "low": 101.0, "close": 102.0},
        ]
    )
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    intent = IntrabarIntentTape.from_arrays(
        entry_side=[1, -1, 0],
        entry_size=[1.0, 2.0, 0.0],
    )

    result = run_intrabar_reference(
        tape=tape,
        intent=intent,
        account=AccountConfig(initial_capital=10_000.0),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        fee_rate=0.001,
    )

    assert [fill.reason for fill in result.fills[:3]] == [
        IntrabarFillReason.ENTRY,
        IntrabarFillReason.REVERSAL_EXIT,
        IntrabarFillReason.REVERSAL_ENTRY,
    ]
    assert result.fees.iloc[1] == pytest.approx(0.1)
    assert result.fees.iloc[2] == pytest.approx(0.102 + 0.204)
    assert result.position.iloc[-1] == -2.0


def test_phase31b_endpoint_runs_intrabar_reference_with_compact_intent_cols():
    df = _frame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "entry": 1.0, "sl_pct": 0.05, "tp_pct": 0.08},
            {"open": 100.0, "high": 110.0, "low": 94.0, "close": 100.0, "entry": 0.0, "sl_pct": np.nan, "tp_pct": np.nan},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "entry": 0.0, "sl_pct": np.nan, "tp_pct": np.nan},
        ]
    )
    bt = QuantBTEndpoint.intrabar_bracket_reference(
        initial_capital=10_000.0,
        fee_rate=0.0,
        slippage=0.0,
        use_funding=False,
    )

    result = bt.backtest(
        data=df,
        signal_col="entry",
        symbols=["BTC"],
        intent_cols={"stop_value": "sl_pct", "take_profit_value": "tp_pct"},
    )

    assert result.metadata["engine_id"] == "intrabar_reference_v1"
    assert result.metadata["validation_certificate"]["ohlc_ok"] is True
    assert bt.fills_report["reason"].tolist() == ["entry", "stop_loss"]
    assert bt.show_metrics()["final_equity"] == pytest.approx(9_995.0)
