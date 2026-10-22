"""Public synthetic sizing/timing diagnostic; no private alpha or market claims."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import ExecutionContract, IntrabarIntentTape, QuantBTEndpoint
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import OrderSide, OrderType


NOTIONAL = 2000.
PRICES = {"BTCUSDT": 60000., "ETHUSDT": 2500., "SOLUSDT": 150.}


def market(symbol="BTCUSDT", days=92):
    n = days * 24
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = PRICES[symbol] * (1 + .002 * np.sin(np.arange(n)/48))
    frame = pd.DataFrame(dict(open=close, high=close*1.001,
        low=close*.999, close=close, volume=1000.), index=index)
    side = np.zeros(n, dtype=np.int8)
    for i, start in enumerate(np.linspace(10, n-50, 11).astype(int)):
        side[start:start+30] = 1 if i % 2 == 0 else -1
    return frame, side


def intents(side, weight):
    changed = side != np.r_[0, side[:-1]]
    return IntrabarIntentTape.from_arrays(entry_side=np.where(changed, side, 0),
        entry_size=np.full(len(side), weight), stop_value=np.full(len(side), .013),
        take_profit_value=np.full(len(side), .026), technical_exit=changed & (side == 0))


def bracket(symbol, frame, side, *, backend="numba", weight=1., allocation=NOTIONAL):
    constructor = {"reference": QuantBTEndpoint.intrabar_bracket_reference,
        "numba": QuantBTEndpoint.intrabar_bracket,
        "rust": QuantBTEndpoint.intrabar_bracket_rust}[backend]
    endpoint = constructor(initial_capital=20000., leverage=3., fee_rate=.00045,
        slippage_bps=2., use_funding=False, intrabar_sizing_mode="fixed_notional",
        alloc_per_trade=allocation, report_level="audit",
        execution_contract=ExecutionContract.intrabar_bracket())
    result = endpoint.backtest(data=frame, intent=intents(side, weight), symbols=[symbol])
    return endpoint, result


class TargetCallback:
    def __init__(self, targets, symbol):
        self.targets, self.symbol = targets, symbol

    def on_bar_close(self, context):
        delta = float(self.targets.loc[context.timestamp]) - context.positions.get(self.symbol, 0.)
        if abs(delta) <= 1e-12:
            return ()
        return (OrderCommand(context.timestamp, symbol=self.symbol,
            side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
            order_type=OrderType.MARKET, qty=abs(delta),
            order_id=f"target:{context.timestamp.value}"),)


def event(symbol, frame, side, *, backend="python", callback=True):
    # Freeze units until a side transition, rather than rebalance price drift.
    changed = side != np.r_[0, side[:-1]]
    target = pd.Series(np.where(changed, side*NOTIONAL/frame.close, np.nan),
        index=frame.index).ffill().fillna(0.)
    endpoint = QuantBTEndpoint.event_driven(input_mode="strategy" if callback else "orders",
        backend=backend, profile="audit", initial_capital=20000., leverage=3.,
        fee_rate=.00045, slippage_bps=2., use_funding=False,
        execution_contract="event_lifecycle_v3_next_open")
    if callback:
        result = endpoint.backtest(data=frame, symbols=[symbol], strategy=TargetCallback(target, symbol))
    else:
        commands = []
        for t in np.flatnonzero(changed):
            if t + 1 == len(side):
                continue
            delta = target.iloc[t] - (target.iloc[t-1] if t else 0.)
            if abs(delta) > 1e-12:
                commands.append(OrderCommand(frame.index[t+1], symbol=symbol,
                    side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    order_type=OrderType.MARKET, qty=abs(delta), order_id=f"tape:{t}"))
        result = endpoint.backtest(data=frame, symbols=[symbol], order_commands=commands)
    return endpoint, result


def diagnose(days=92):
    rows = []
    for symbol in PRICES:
        frame, side = market(symbol, days)
        for backend in ("reference", "numba", "rust"):
            for label, weight, allocation in (("reported_input", 2000., 100000.),
                    ("correct_fixed_notional", 1., NOTIONAL),
                    ("currency_weights_base_one", NOTIONAL, 1.)):
                bt, result = bracket(symbol, frame, side, backend=backend,
                    weight=weight, allocation=allocation)
                rows.append(dict(symbol=symbol, backend=backend, case=label,
                    attempted_notional=weight*allocation, fills_count=len(bt.fills_report),
                    rejected_count=result.metadata["rejected_count"],
                    fees=float(result.fees.sum()), final_equity=float(result.equity.iloc[-1]),
                    legacy_position_transition_count=result.full_report(scope="full")["num_trades"]))
        for backend in ("python", "rust"):
            for callback in (False, True):
                bt, result = event(symbol, frame, side, backend=backend, callback=callback)
                rows.append(dict(symbol=symbol, backend=backend,
                    case="callback" if callback else "command_tape",
                    fills_count=len(bt.fills_report), final_equity=float(result.equity.iloc[-1])))
    return dict(schema="bracket-synthetic-diagnostic-v1", days=days, bars=days*24,
        private_strategy=False, rows=rows, publication=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=92)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(diagnose(args.days), indent=2, allow_nan=False)
    if args.output is not None:
        with args.output.open("x") as stream:
            stream.write(payload + "\n")
    print(payload)
