"""Typed WFO windows delegate to existing execution, never to signal accounting."""

from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
import pandas as pd

from .core.intrabar_session import IntrabarSessionTape
from .core.orders import OrderCommand


EXECUTION_ROUTES = frozenset({"intrabar", "event_driven", "order_commands", "delivery_arbitrage"})


def validate_execution_route(config, wf):
    endpoint = config.wfo_execution_config
    expected = {"intrabar": {"intrabar_bracket", "intrabar_bracket_reference", "intrabar_bracket_rust"},
        "event_driven": {"native_event_strategy"}, "order_commands": {"orders"}, "delivery_arbitrage": {"orders"}}
    if endpoint is None or endpoint.mode not in expected[wf.target_mode]:
        raise ValueError("execution endpoint and WFO route are incompatible")
    if wf.fold_account_policy != "carry_position" or wf.scoring_backend != "endpoint":
        raise NotImplementedError("execution WFO v1 requires endpoint scoring and continuous carry_position")
    if wf.optimization_mode == "mode_2_sbb":
        raise NotImplementedError("execution WFO has no certified bootstrap execution path")
    if wf.metadata.get("native_prepared_wfo", "off") == "require":
        raise NotImplementedError("native prepared target scorer cannot consume execution windows")
    if wf.target_mode == "delivery_arbitrage":
        from .core.delivery_lifecycle import DeliveryLifecycle
        lifecycle = endpoint.metadata.get("delivery_lifecycle")
        if not isinstance(lifecycle, DeliveryLifecycle):
            raise ValueError("delivery requires an explicit authoritative lifecycle")
        validate_delivery_funding(endpoint, lifecycle)


def validate_delivery_funding(config, lifecycle):
    from .optimization.meta_selection.domains.portfolio_contract import funding_for
    if config.use_funding:
        for contract in lifecycle.contracts:
            rates = np.asarray(funding_for(config, contract.symbol), dtype=float)
            if not np.isfinite(rates).all() or np.any(rates != 0):
                raise ValueError("delivery futures do not accrue perpetual funding; declare zero per delivery leg")


@dataclass(frozen=True, eq=False)
class WfoExecutionWindow:
    route: str
    index: pd.DatetimeIndex
    intent: pd.DataFrame | None = None
    session: IntrabarSessionTape | None = None
    commands: tuple[OrderCommand, ...] = ()
    strategy_factory: Callable | None = field(default=None, repr=False)
    parts: tuple = field(default=(), repr=False)
    schema: str = "wfo-execution-window-v1"

    def __post_init__(self):
        idx = self.index
        if (self.schema != "wfo-execution-window-v1" or self.route not in EXECUTION_ROUTES
                or not isinstance(idx, pd.DatetimeIndex) or len(idx) == 0
                or idx.tz is None or not idx.is_unique or not idx.is_monotonic_increasing):
            raise ValueError("execution window requires an exact aware calendar and registered schema/route")
        object.__setattr__(self, "commands", tuple(self.commands))
        object.__setattr__(self, "parts", tuple(self.parts))
        if self.route == "intrabar":
            if (not isinstance(self.intent, pd.DataFrame) or not self.intent.index.equals(idx)
                    or "entry_signal" not in self.intent):
                raise ValueError("intrabar payload requires exact intent index and entry_signal")
            if self.commands or self.strategy_factory is not None:
                raise ValueError("intrabar payload cannot contain commands/callback")
            if self.session is not None and len(self.session.session_id) != len(idx):
                raise ValueError("session payload must cover exact intent calendar")
        elif self.intent is not None or self.session is not None:
            raise ValueError("event payload cannot contain intrabar intent/session")
        if self.route == "event_driven":
            if (not callable(self.strategy_factory) and not self.parts) or self.commands:
                raise ValueError("callback payload requires a fresh no-argument strategy_factory")
        elif self.strategy_factory is not None:
            raise ValueError("command payload cannot contain a callback factory")
        for c in self.commands:
            if not isinstance(c, OrderCommand):
                raise TypeError("execution window commands must be OrderCommand")
            t = pd.Timestamp(c.timestamp)
            if t.tzinfo is None or t not in idx:
                raise ValueError("command timestamp is outside exact execution window")

    def slice(self, index):
        rows = self.index.get_indexer(index)
        if (rows < 0).any():
            raise ValueError("execution window does not cover exact requested calendar")
        session = None if self.session is None else IntrabarSessionTape(
            session_id=self.session.session_id[rows],
            entry_allowed_at_open=self.session.entry_allowed_at_open[rows],
            force_flat_at_open=self.session.force_flat_at_open[rows])
        return replace(self, index=index,
            intent=None if self.intent is None else self.intent.loc[index].copy(),
            session=session, commands=tuple(c for c in self.commands if pd.Timestamp(c.timestamp) in index))


def stitch_execution_windows(outputs, index):
    parts = tuple(outputs)
    route = parts[0].route
    covered = pd.DatetimeIndex([] , tz="UTC")
    for p in parts:
        if p.route != route or len(covered.intersection(p.index)):
            raise ValueError("execution windows must have one route and disjoint calendars")
        if len(p.index.difference(index)):
            raise ValueError("execution window lies outside final calendar")
        if len(covered) and p.index[0] <= covered[-1]:
            raise ValueError("execution windows must be chronological")
        covered = covered.append(p.index)
    if route != "intrabar":
        return WfoExecutionWindow(route, index,
            commands=tuple(c for p in parts for c in p.commands), parts=parts)
    columns = parts[0].intent.columns
    if any(not p.intent.columns.equals(columns) for p in parts):
        raise ValueError("intrabar intent schema cannot change across folds")
    intent = pd.DataFrame({c: pd.Series(False if parts[0].intent[c].dtype == bool else 0.,
        index=index, dtype=parts[0].intent[c].dtype) for c in columns})
    for p in parts:
        intent.loc[p.index] = p.intent
    session = None
    if any(p.session is not None for p in parts):
        if not all(p.session is not None for p in parts):
            raise ValueError("session policy cannot appear/disappear across folds")
        ids = np.full(len(index), np.iinfo(np.int64).min, dtype=np.int64)
        allowed, flat = np.zeros(len(index), bool), np.zeros(len(index), bool)
        for p in parts:
            rows = index.get_indexer(p.index)
            ids[rows] = p.session.session_id
            allowed[rows], flat[rows] = p.session.entry_allowed_at_open, p.session.force_flat_at_open
        session = IntrabarSessionTape(session_id=ids,
            entry_allowed_at_open=allowed, force_flat_at_open=flat)
    return WfoExecutionWindow(route, index, intent=intent, session=session, parts=parts)


class _FoldCallbacks:
    """Switch alpha instances, not execution/account/order state, at a close."""

    def __init__(self, window):
        self.parts = window.parts or (window,)
        self.current = None
        self.child = None

    def on_bar_close(self, context):
        part = next((p for p in self.parts if p.index[0] <= context.timestamp <= p.index[-1]), None)
        if part is None:
            return ()
        local = replace(context, bar_index=int(part.index.get_loc(context.timestamp)))
        if part is not self.current:
            self.current, self.child = part, part.strategy_factory()
            if not callable(getattr(self.child, "on_bar_close", None)):
                raise TypeError("strategy_factory must return the event_driven callback protocol")
            initial = getattr(self.child, "initialize", lambda c: ())(local)
            return tuple(initial or ()) + tuple(self.child.on_bar_close(local) or ())
        return self.child.on_bar_close(local)

    def finalize(self, context):
        if self.child is None:
            return ()
        local = replace(context, bar_index=int(self.current.index.get_indexer([context.timestamp])[0]))
        return getattr(self.child, "finalize", lambda c: ())(local)


def execute_window(config, data, output, *, symbols=None):
    from .endpoint import QuantBTEndpoint
    if not isinstance(output, WfoExecutionWindow):
        raise TypeError("execution WFO requires WfoExecutionWindow, not position/signal output")
    expected = {"intrabar": {"intrabar_bracket", "intrabar_bracket_reference", "intrabar_bracket_rust"},
                "event_driven": {"native_event_strategy"},
                "order_commands": {"orders"}, "delivery_arbitrage": {"orders"}}
    if config.mode not in expected[output.route]:
        raise ValueError("execution endpoint and WFO route are incompatible")
    endpoint = QuantBTEndpoint(config)
    frame = ({s: f.loc[output.index] for s, f in data.items()}
             if isinstance(data, dict) else data.loc[output.index])
    if output.route == "intrabar":
        # This endpoint requires exact-window rates; retain its strict guard.
        if isinstance(config.funding_rate, pd.Series):
            if not config.funding_rate.index.is_unique:
                raise ValueError("funding series index must be unique")
            endpoint = QuantBTEndpoint(replace(config, funding_rate=config.funding_rate.loc[output.index]))
        frame = frame.copy()
        for c in output.intent:
            frame[c] = output.intent[c]
        result = endpoint.backtest(data=frame, signal_col="entry_signal", symbols=symbols,
            session_tape=output.session, intent_cols={c: c for c in output.intent if c != "entry_signal"})
        from .core.constraints import build_quantity_constraints
        result.metadata["quantity_constraints"] = build_quantity_constraints(
            result.symbols, instruments=config.instruments, qty_step=config.qty_step,
            lot_size=config.lot_size, slot_size=config.slot_size,
            min_qty=config.min_qty, min_notional=config.min_notional).as_dict()
    elif output.route == "event_driven":
        result = endpoint.backtest(data=frame, strategy=_FoldCallbacks(output), symbols=symbols)
    else:
        commands = output.commands
        lifecycle = config.metadata.get("delivery_lifecycle")
        if output.route == "delivery_arbitrage":
            from .core.delivery_lifecycle import DeliveryLifecycle
            if not isinstance(lifecycle, DeliveryLifecycle):
                raise ValueError("delivery_arbitrage requires explicit DeliveryLifecycle")
            validate_delivery_funding(config, lifecycle)
            commands = lifecycle.compile(commands, output.index)
        result = endpoint.backtest(data=frame, order_commands=commands, symbols=symbols,
            datetime_index=output.index)
        if output.route == "delivery_arbitrage":
            lifecycle.reconcile(result)
    result.metadata["wfo_execution_window"] = dict(schema=output.schema, route=output.route,
        diagnostic_account="reset_flat", final_stitch="one_original_continuous_account",
        callback_boundary="bar_close_next_open", financial_replays=0)
    return result
