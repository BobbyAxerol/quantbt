"""Typed WFO windows delegate to existing execution, never to signal accounting."""

from copy import deepcopy
from dataclasses import dataclass, field, fields, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping

import numpy as np
import pandas as pd

from .core.intrabar_session import IntrabarSessionTape
from .core.orders import OrderCommand

if TYPE_CHECKING:
    from .walkforward import WalkForwardFold


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


def _assembly_index(index):
    if (not isinstance(index, pd.DatetimeIndex) or index.tz is None
            or not index.is_unique or not index.is_monotonic_increasing):
        raise ValueError("execution assembly requires an exact aware chronological index")
    values = np.frombuffer(index.asi8.tobytes(), dtype=np.int64)
    array = pd.array(values, dtype=index.dtype, copy=False)
    return pd.DatetimeIndex(array, name=index.name, copy=False)


def _assembly_params(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _assembly_params(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_assembly_params(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_assembly_params(v) for v in value)
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise TypeError("execution assembly params cannot contain object arrays")
        return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)
    return deepcopy(value)


@dataclass(frozen=True, eq=False)
class WfoExecutionAssemblyRequest:
    """Final-only adapter input, after every selection and observer evaluation.

    An execution strategy may opt in with ``assemble_wfo_execution(request)``.
    Applied parameter containers and fold calendars are detached read-only
    snapshots; ``index`` is the entire final account calendar, including
    non-OOS bars. ``windows``
    are generated diagnostic OOS payload snapshots, not an authorized final
    state handoff. ``data`` is an ordinary detached strategy-data copy supplied
    only at final assembly, never a new selection/observer input.

    The caller owns its actual-feedback compiler and boundary semantics. Return
    an ordinary same-route, exact-full-index WfoExecutionWindow, not positions
    or diagnostic callback parts. QuantBT executes that window once through the
    existing final account path. No selection, labels, RNG or diagnostic account
    is replayed here. Additive WalkForwardResult metadata
    ``wfo_execution_assembly`` records this request schema, final-only scope and
    the hook's module/qualified name as ``adapter_identity`` when available;
    it is not a source hash certificate.
    """

    route: str
    index: pd.DatetimeIndex
    folds: tuple["WalkForwardFold", ...]
    params_by_fold: Mapping[int, Mapping[str, Any]]
    windows: tuple[WfoExecutionWindow, ...]
    data: pd.DataFrame | dict[str, pd.DataFrame] = field(repr=False)
    schema: str = "wfo-execution-assembly-request-v1"

    def __post_init__(self):
        from .walkforward import WalkForwardFold

        index = _assembly_index(self.index)
        folds, windows = tuple(self.folds), tuple(self.windows)
        if (self.schema != "wfo-execution-assembly-request-v1"
                or self.route not in EXECUTION_ROUTES or not len(index)
                or not folds or len(folds) != len(windows)
                or any(not isinstance(f, WalkForwardFold) for f in folds)):
            raise ValueError("execution assembly requires a registered route/schema and matching folds/windows")
        fold_ids = [f.fold_id for f in folds]
        if (not isinstance(self.params_by_fold, Mapping) or len(set(fold_ids)) != len(fold_ids)
                or set(self.params_by_fold) != set(fold_ids)
                or any(not isinstance(p, Mapping) for p in self.params_by_fold.values())):
            raise ValueError("execution assembly requires applied params for exactly every fold")
        previous_end = None
        for fold, window in zip(folds, windows):
            if (not isinstance(window, WfoExecutionWindow) or window.route != self.route
                    or not window.index.equals(fold.test_index)
                    or len(window.index.difference(index))
                    or fold.test_start != window.index[0] or fold.test_end != window.index[-1]):
                raise ValueError("execution assembly requires same-route windows on exact fold/final indexes")
            if previous_end is not None and window.index[0] <= previous_end:
                raise ValueError("execution assembly folds/windows must be chronological and disjoint")
            previous_end = window.index[-1]
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "folds", tuple(replace(f, **{
            item.name: _assembly_index(getattr(f, item.name)) for item in fields(f)
            if isinstance(getattr(f, item.name), pd.DatetimeIndex)}) for f in folds))
        object.__setattr__(self, "params_by_fold", _assembly_params(self.params_by_fold))
        object.__setattr__(self, "windows", tuple(replace(w,
            index=_assembly_index(w.index), intent=None if w.intent is None else w.intent.copy(deep=True),
            session=deepcopy(w.session), commands=deepcopy(w.commands)) for w in windows))
        object.__setattr__(self, "data", deepcopy(self.data))


def assemble_final_execution(strategy, **kwargs):
    """Invoke only the opted-in final hook; never substitute diagnostic parts."""
    assembler = strategy.assemble_wfo_execution
    if not callable(assembler):
        raise TypeError("assemble_wfo_execution must be callable")
    request = WfoExecutionAssemblyRequest(**kwargs)
    output = assembler(request)
    if not isinstance(output, WfoExecutionWindow):
        raise TypeError("final execution assembly must return WfoExecutionWindow, not positions/signals")
    output = replace(output)  # Revalidate mutable payloads before final execution.
    if output.route != request.route or not output.index.equals(request.index):
        raise ValueError("final execution assembly must preserve route and exact full final index")
    if output.route == "event_driven" and (output.parts or not callable(output.strategy_factory)):
        raise ValueError("final callback assembly requires a final strategy_factory without diagnostic parts")
    module, name = getattr(assembler, "__module__", None), getattr(assembler, "__qualname__", None)
    return output, {"wfo_execution_assembly": dict(schema=request.schema, scope="final_only",
        adapter_identity=f"{module}.{name}" if module and name else None)}


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


def _callback_timestamp_ns(timestamp):
    if isinstance(timestamp, pd.Timestamp) and timestamp.tzinfo is not None:
        try:
            return timestamp.value
        except OverflowError:
            pass
    return None


class _CallbackCalendarCursor:
    """Exact lookup on validated calendars; None requests the pandas fallback."""

    def __init__(self, index):
        self.index = index
        self.values = None
        if (type(index) is pd.DatetimeIndex and len(index) and index.tz is not None
                and getattr(index.dtype, "unit", "ns") == "ns"
                and index.is_unique and index.is_monotonic_increasing and not index.hasnans):
            self.values = index.asi8
        self.next = 0
        self.previous = -1

    def locate(self, timestamp):
        if self.values is None:
            return None
        value = _callback_timestamp_ns(timestamp)
        if value is None:
            return None
        values, offset = self.values, self.next
        if offset < len(values) and values[offset] == value:
            pass
        elif self.previous >= 0 and values[self.previous] == value:
            return self.previous
        else:
            offset = int(np.searchsorted(values, value))
            if offset == len(values) or values[offset] != value:
                return -1
        self.previous, self.next = offset, offset + 1
        return offset


class _FoldCallbacks:
    """Switch alpha instances, not execution/account/order state, at a close."""

    def __init__(self, window):
        self.parts = window.parts or (window,)
        self.current = None
        self.child = None
        self._calendar = None
        self._part_cursor = 0
        self._starts = self._ends = None
        if all(isinstance(p, WfoExecutionWindow)
               and _CallbackCalendarCursor(p.index).values is not None for p in self.parts):
            starts = np.asarray([p.index.asi8[0] for p in self.parts], dtype=np.int64)
            ends = np.asarray([p.index.asi8[-1] for p in self.parts], dtype=np.int64)
            if np.all(starts[1:] > ends[:-1]):
                self._starts, self._ends = starts, ends

    def _part_at(self, timestamp):
        value = _callback_timestamp_ns(timestamp) if self._starts is not None else None
        if value is None:
            return next((p for p in self.parts if p.index[0] <= timestamp <= p.index[-1]), None)
        slot = self._part_cursor
        if not self._starts[slot] <= value <= self._ends[slot]:
            slot = int(np.searchsorted(self._starts, value, side="right")) - 1
            if slot < 0 or value > self._ends[slot]:
                return None
        self._part_cursor = slot
        return self.parts[slot]

    def on_bar_close(self, context):
        part = self._part_at(context.timestamp)
        if part is None:
            return ()
        calendar = self._calendar if part is self.current else _CallbackCalendarCursor(part.index)
        offset = calendar.locate(context.timestamp)
        if offset is None or offset < 0:
            offset = int(part.index.get_loc(context.timestamp))
        local = replace(context, bar_index=offset)
        if part is not self.current:
            self.current, self.child = part, part.strategy_factory()
            self._calendar = calendar
            if not callable(getattr(self.child, "on_bar_close", None)):
                raise TypeError("strategy_factory must return the event_driven callback protocol")
            initial = getattr(self.child, "initialize", lambda c: ())(local)
            return tuple(initial or ()) + tuple(self.child.on_bar_close(local) or ())
        return self.child.on_bar_close(local)

    def finalize(self, context):
        if self.child is None:
            return ()
        offset = self._calendar.locate(context.timestamp)
        if offset is None:
            offset = int(self.current.index.get_indexer([context.timestamp])[0])
        local = replace(context, bar_index=offset)
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
    clock = result.metadata.get("event_clock_contract", {})
    intrabar = result.metadata.get("execution_contract", {})
    activation = clock.get("command_activation_phase", intrabar.get("entry_fill_phase"))
    boundary = ("bar_close_next_open" if activation in {"next_bar_open", "next_open"}
                else "bar_close_next_bar_close" if activation == "next_bar_close" else "unreported")
    result.metadata["wfo_execution_window"] = dict(schema=output.schema, route=output.route,
        diagnostic_account="reset_flat", final_stitch="one_original_continuous_account",
        callback_boundary=boundary if output.route == "event_driven" else "not_applicable",
        intent_boundary=boundary if output.route == "intrabar" else "not_applicable",
        command_timestamp_semantics="effective_bar" if output.route in {"order_commands", "delivery_arbitrage"} else "signal_bar_close",
        execution_contract_id=result.metadata.get("execution_contract_id", intrabar.get("engine_id")),
        financial_replays=0)
    return result
