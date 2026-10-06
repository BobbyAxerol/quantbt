"""Four synthetic execution alphas. No market-edge or live-readiness claim.

Run: python -m examples.wfo_meta_execution --route intrabar --mode shadow
"""

import argparse
from functools import partial

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.core.delivery_lifecycle import DeliveryContract, DeliveryLifecycle
from quantbt.core.intrabar_session import IntrabarSessionTape, SessionExecutionPolicy
from quantbt.core.orders import OrderAction, OrderCommand
from quantbt.core.schema import OrderSide, OrderType
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.wfo_execution import WfoExecutionWindow


PARAM_RANGES = {"window": (3, 9, 2)}
SYMBOLS = ("PERP", "QUARTER-1", "QUARTER-2")


def market(route="intrabar", *, end="2021-08-31"):
    index = pd.date_range("2021-01-01", end, freq="D", tz="UTC")
    t = np.arange(len(index), dtype=float)
    close = 100 + .04*t + 4*np.sin(t/5) + 1.5*np.cos(t/13)
    opening = np.r_[close[0], close[:-1]]
    frame = pd.DataFrame(dict(open=opening, high=np.maximum(opening, close)+.6,
        low=np.minimum(opening, close)-.6, close=close, volume=10000.), index=index)
    if route != "delivery_arbitrage":
        return frame
    return {s: frame.assign(open=frame.open*(1+i*.015), high=frame.high*(1+i*.015),
        low=frame.low*(1+i*.015), close=frame.close*(1+i*.015)) for i, s in enumerate(SYMBOLS)}


def delivery_lifecycle():
    return DeliveryLifecycle((
        DeliveryContract(SYMBOLS[1], pd.Timestamp("2021-06-30", tz="UTC"),
            pd.Timestamp("2021-06-29", tz="UTC"), "synthetic-contract-catalog-v1"),
        DeliveryContract(SYMBOLS[2], pd.Timestamp("2022-12-31", tz="UTC"),
            pd.Timestamp("2022-12-30", tz="UTC"), "synthetic-contract-catalog-v1")))


class MeanReversionCallback:
    def __init__(self, side, symbol="X"):
        self.side, self.symbol = side.copy(), symbol

    def on_bar_close(self, context):
        # Fill/account feedback is the execution owner's actual position.
        desired = float(self.side.get(context.timestamp, 0.)) * .5
        delta = desired - float(context.positions.get(self.symbol, 0.))
        if abs(delta) <= 1e-12:
            return ()
        return (OrderCommand(context.timestamp, symbol=self.symbol,
            side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
            order_type=OrderType.MARKET, qty=abs(delta),
            order_id=f"callback:{context.timestamp.value}"),)


def generate(route, data, params, index):
    frame = data[SYMBOLS[0]] if isinstance(data, dict) else data
    n = int(params["window"])
    side = np.sign(frame.close.rolling(n).mean() - frame.close).reindex(index).fillna(0.)
    if route == "intrabar":
        transition = side.where(side.ne(side.shift(1, fill_value=0.)), 0.)*.5
        intent = pd.DataFrame(dict(entry_signal=transition, stop_value=.03,
            take_profit_value=.06, trailing_value=.015, exit_long=False, exit_short=False), index=index)
        session = IntrabarSessionTape(session_id=index.asi8 // (7*86400*10**9),
            entry_allowed_at_open=np.ones(len(index), bool), force_flat_at_open=np.zeros(len(index), bool))
        return WfoExecutionWindow(route, index, intent=intent, session=session)
    if route == "event_driven":
        return WfoExecutionWindow(route, index, strategy_factory=partial(MeanReversionCallback, side))
    commands = []
    for i in range(0, len(index)-3, n):
        entry, exit_at = index[i+1], index[i+3]
        symbol = "X" if route == "order_commands" else (
            SYMBOLS[1] if entry < pd.Timestamp("2021-06-27", tz="UTC") else SYMBOLS[2])
        if route == "delivery_arbitrage":
            # Frozen equal-unit basis: the paired perp remains non-expiring.
            legs = ((symbol, OrderSide.BUY), (SYMBOLS[0], OrderSide.SELL))
        else:
            legs = ((symbol, OrderSide.BUY),)
        for leg, entry_side in legs:
            ident = f"entry:{leg}:{entry.value}"
            commands.append(OrderCommand(entry, symbol=leg, side=entry_side,
                order_type=OrderType.LIMIT, qty=.5,
                price=float((data[leg] if isinstance(data, dict) else data).close.loc[index[i]])*(1-.002),
                order_id=ident))
            commands.append(OrderCommand(exit_at, OrderAction.CANCEL, target_order_id=ident))
            commands.append(OrderCommand(exit_at, symbol=leg,
                side=OrderSide.SELL if entry_side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.MARKET, qty=.5, reduce_only=True,
                order_id=f"exit:{leg}:{exit_at.value}"))
    return WfoExecutionWindow(route, index, commands=tuple(commands))


def strategy(route, data, params, train_index, test_index, fold):
    return generate(route, data, params, test_index)


def make_endpoint(route, mode="shadow", *, support=12, backend="python", witness=True, trials=8, policy="auto"):
    common = dict(initial_capital=20000., leverage=3., fee_rate=.0005,
        slippage_bps=2., use_funding=False, symbols=list(SYMBOLS) if route == "delivery_arbitrage" else ["X"])
    if route == "intrabar":
        ctor = QuantBTEndpoint.intrabar_bracket_rust if backend == "rust" else QuantBTEndpoint.intrabar_bracket
        financial = ctor(**common, close_on_last_bar=False, report_level="audit",
            session_policy=SessionExecutionPolicy(max_long_entries_per_session=2,
                max_short_entries_per_session=2))
    else:
        metadata = {"delivery_lifecycle": delivery_lifecycle()} if route == "delivery_arbitrage" else {}
        financial = QuantBTEndpoint.event_driven(input_mode="strategy" if route == "event_driven" else "orders",
            backend=backend, profile="audit", metadata=metadata, **common)
    return QuantBTEndpoint.walk_forward(partial(strategy, route), execution_endpoint=financial,
        target_mode=route, split_mode="2021-03-01", split_frequency="monthly",
        window_mode="rolling", train_window="59D", optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", optuna_trials=trials, random_seed=731,
        optimization_config=dict(candidate_selection_metric="is_only_robust", is_subperiods=1,
            scoring_backend="endpoint", use_scalar_trial_scoring=False, top_is_fraction=.5,
            use_prepared_meta_witness=witness,
            metadata={"use_prepared_meta_witness": witness},
            meta_selection=dict(mode=mode, label_observer=True, min_matured_origins=support,
                native_batch_policy=policy)))


def execute(route, mode="shadow", *, data=None, support=12, backend="python", trials=8, witness=True):
    endpoint = make_endpoint(route, mode, support=support, backend=backend, trials=trials, witness=witness)
    context = MetaHistoryContext(MetaHistory(), "synthetic-execution-demo", "SYNTHETIC-"+route,
        "1D", "execution-demo", clock=lambda fold, stage, elapsed: fold.train_index[-1] + pd.Timedelta(
            seconds={"search": 10, "fit": 20, "seal": 30}[stage]))
    result = endpoint.backtest(data=market(route) if data is None else data, param_ranges=PARAM_RANGES,
        **({"meta_history": context} if mode != "off" else {}))
    return endpoint, result, context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=("intrabar", "event_driven", "order_commands", "delivery_arbitrage"), default="intrabar")
    parser.add_argument("--mode", choices=("off", "shadow", "active"), default="shadow")
    endpoint, result, _ = execute(**vars(parser.parse_args()))
    endpoint.show_metrics()
    print(result.metadata["walk_forward"].get("meta_selection", {}).get("domain_adapter"))
