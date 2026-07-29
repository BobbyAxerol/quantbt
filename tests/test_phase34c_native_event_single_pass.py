from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import OrderCommand, QuantBTEndpoint
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def _bars(n: int = 18) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.arange(n) / 3.0) * 3.0 + np.arange(n) * 0.15, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 2.5,
            "low": close - 2.5,
            "close": close,
            "volume": 1_000.0 + np.arange(n),
        },
        index=idx,
    )


class EnterExitStrategy:
    def __init__(self, entry_bar: int = 0, exit_bar: int = 6, qty: float = 1.0):
        self.entry_bar = int(entry_bar)
        self.exit_bar = int(exit_bar)
        self.qty = float(qty)

    def on_bar_close(self, context):
        if context.bar_index == self.entry_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=context.symbols[0],
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=self.qty,
                    tif=TimeInForce.IOC,
                    order_id=f"entry-{self.entry_bar}",
                )
            ]
        if context.bar_index == self.exit_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=context.symbols[0],
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=self.qty,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id=f"exit-{self.exit_bar}",
                )
            ]
        return []


def _assert_accounting_equal(left, right) -> None:
    pd.testing.assert_series_equal(left.equity, right.equity)
    pd.testing.assert_series_equal(left.returns, right.returns)
    pd.testing.assert_frame_equal(left.positions, right.positions)
    pd.testing.assert_series_equal(left.fees, right.fees)
    pd.testing.assert_series_equal(left.funding, right.funding)
    pd.testing.assert_frame_equal(left.margin, right.margin)
    assert left.liquidated == right.liquidated
    assert left.liquidation_bar == right.liquidation_bar


def test_single_pass_minimal_skips_static_replay_but_matches_replay_certified_accounting():
    df = _bars()
    kwargs = dict(initial_capital=10_000, leverage=10, use_funding=False, fee_rate=0.0002, report_level="minimal")

    replay = QuantBTEndpoint.native_event_strategy(
        **kwargs,
        reactive_kernel_mode="replay_certified",
    ).simulate(data=df, strategy=EnterExitStrategy(entry_bar=0, exit_bar=6), symbols=["BTC"])
    single = QuantBTEndpoint.native_event_strategy(
        **kwargs,
        reactive_kernel_mode="single_pass",
    ).simulate(data=df, strategy=EnterExitStrategy(entry_bar=0, exit_bar=6), symbols=["BTC"])

    _assert_accounting_equal(single, replay)
    assert single.metadata["engine"] == "event_v2_reactive_single_pass"
    assert single.metadata["reactive_kernel_mode"] == "single_pass"
    assert single.metadata["static_replay_available"] is False
    assert single.metadata["reactive_static_replay_count"] == 0
    assert single.metadata["reactive_incremental_compile_replays"] == 0
    assert single.metadata["emitted_command_tape"] == ()


def test_single_pass_audit_uses_replay_oracle_and_keeps_fill_bar_ledger():
    df = _bars()
    result = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
        reactive_execution_mode="audit",
        reactive_kernel_mode="single_pass",
    ).simulate(data=df, strategy=EnterExitStrategy(entry_bar=0, exit_bar=6), symbols=["BTC"])

    ledger = result.metadata["compact_fill_ledger"]
    assert result.metadata["single_pass_replay_certified"] is True
    assert result.metadata["static_replay_available"] is True
    assert result.metadata["reactive_static_replay_count"] == 1
    assert result.metadata["command_report"].shape[0] == 2
    assert tuple(ledger.bar.tolist()) == (1, 7)
    assert result.metadata["reactive_audit"]["final_equity_diff"] == 0.0
    assert result.metadata["reactive_audit"]["final_position_diff"]["BTC"] == 0.0


def test_prepared_native_event_score_uses_single_pass_and_keeps_public_run_parity():
    df = _bars(24)
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
    )
    prepared = endpoint.prepare_native_event_strategy(data=df, symbols=["BTC"])

    score = prepared.score(EnterExitStrategy(entry_bar=2, exit_bar=9), trading_days=365)
    audit = prepared.run(EnterExitStrategy(entry_bar=2, exit_bar=9), report_level="audit")

    np.testing.assert_allclose(score.equity, audit.equity.to_numpy(dtype=np.float64), rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(score.returns, audit.returns.to_numpy(dtype=np.float64), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(score.positions, audit.positions[["Position_BTC"]].to_numpy(dtype=np.float64), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(score.fees, audit.fees.to_numpy(dtype=np.float64), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(score.initial_margin, audit.margin["initial_margin"].to_numpy(dtype=np.float64), rtol=0.0, atol=1e-12)
    assert score.metadata["reactive_kernel_mode"] == "single_pass"
    assert score.metadata["static_replay_available"] is False
    assert prepared.metadata["scores"] == 1
    assert prepared.metadata["runs"] == 1
