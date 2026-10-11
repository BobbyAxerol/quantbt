"""Lazy actual-feedback projection and cached existing-compiler tape rows."""

import numpy as np

from quantbt import Fill, OrderSide
from quantbt.backends._native_event_rust import compile_rust_full_tape
from tools.mode5_research.incremental_feedback import FeedbackEvent


class LazyEngineFeedback:
    def __init__(self, audit, commands, index, start, symbol):
        self.audit, self.path_offset = audit, start
        self.index, self.symbol = index, symbol
        self.paths = {key: getattr(audit, key) for key in
                      ("equity", "positions", "fees", "funding", "turnover",
                       "initial_margin", "maintenance_margin")}
        self.metadata = {c.order_id: c.metadata for c in commands}
        self.ids = np.asarray(audit.id_values, dtype=object)
        self.cache = {}

    def _names(self, codes):
        return tuple(None if int(code) < 0 else self.ids[int(code)] for code in codes)

    def events_at(self, bar):
        if bar in self.cache:
            return self.cache[bar]
        a, local = self.audit, bar-self.path_offset
        rows = np.flatnonzero((a.event_bar == local) & np.isin(a.event_kind, (4, 7)))
        fill_rows = np.flatnonzero(a.fill_bar == local)
        fills = {self.ids[int(a.fill_order_id[row])]: row for row in fill_rows}
        if len(fills) != len(fill_rows):
            raise ValueError("partial fill feedback needs an explicit transport")
        events = []
        for row in rows:
            code = int(a.event_order_id[row])
            name = None if code < 0 else self.ids[code]
            kind = "fill" if int(a.event_kind[row]) == 4 else "reject"
            fill = None
            if kind == "fill":
                slot = fills.pop(name)
                fill = Fill(timestamp=self.index[local], symbol=self.symbol, order_id=name,
                    side=OrderSide.BUY if a.fill_side[slot] > 0 else OrderSide.SELL,
                    qty=float(a.fill_qty[slot]), price=float(a.fill_price[slot]),
                    fee=float(a.fill_fee[slot]), metadata=self.metadata[name])
            record = dict(timestamp=self.index[local], bar=local, event_name=kind,
                order_id=name, status=int(a.event_status[row]), reject_code=int(a.event_reject_code[row]))
            events.append(FeedbackEvent(bar, name, kind, fill, record))
        if fills:
            raise ValueError("unmapped actual fill event")
        self.cache[bar] = tuple(events)
        return self.cache[bar]

    def events_before(self, bar):
        a, local = self.audit, bar-self.path_offset
        events = a.event_bar < local
        fills = a.fill_bar < local
        semantic = tuple(getattr(a, key)[fills].tobytes() for key in ("fill_reason", "fill_ambiguity"))
        liquidity = None if a.fill_order_type is None else a.fill_order_type[fills].tobytes()
        return (tuple(getattr(a, key)[events].tobytes() for key in
                     ("event_bar", "event_kind", "event_status", "event_symbol", "event_reject_code")),
                self._names(a.event_order_id[events]), self._names(a.event_target_id[events]),
                tuple(getattr(a, key)[fills].tobytes() for key in
                     ("fill_bar", "fill_symbol", "fill_side", "fill_qty", "fill_price", "fill_fee")),
                self._names(a.fill_order_id[fills]), semantic, liquidity)


class CachedTapeRows:
    """Memoize immutable numeric rows, not financial state or outputs.

    Each new/changed command passes the original quantity and command compiler.
    Integer IDs are remapped by their exact string identity. Public final audit
    remains the original full compiler's responsibility.
    """

    def __init__(self, backend, runner, index, symbol, constraints):
        self.backend, self.runner = backend, runner
        self.index, self.symbol, self.constraints = index, symbol, constraints
        self.rows, self.ids = {}, {}
        self.compiled_rows = 0
        self.bars = np.empty(0, dtype=np.int64)
        self.codes = np.empty((0, 16), dtype=np.int64)
        self.values = np.empty((0, 3), dtype=np.float64)
        self.expiry = np.empty(0, dtype=np.int64)

    def _reserve(self, count):
        if count <= len(self.bars):
            return
        size = max(count, 64, 2*len(self.bars))
        for field, shape in (("bars", (size,)), ("codes", (size, 16)),
                             ("values", (size, 3)), ("expiry", (size,))):
            previous = getattr(self, field)
            grown = np.empty(shape, dtype=previous.dtype)
            grown[:len(previous)] = previous
            setattr(self, field, grown)

    def pack(self, commands):
        names = [c.order_id for c in commands]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise ValueError("cached research tape requires unique explicit order IDs")
        fresh = tuple(c for c in commands if c.order_id not in self.rows or
                      (self.rows[c.order_id][0] is not c and self.rows[c.order_id][0] != c))
        if fresh:
            effective, preflight = self.backend._apply_command_quantity_constraints(idx=self.index,
                commands=fresh, closes=self.runner.market_arrays.closes, symbol_list=[self.symbol],
                contract_sizes=self.runner.contract_sizes, constraints=self.constraints)
            if preflight["dropped_count"]:
                raise ValueError("dropped quantity needs explicit feedback qualification")
            compiled = self.backend.compile_order_commands(self.index, effective, symbols=[self.symbol])
            _, codes, values, expiry = compile_rust_full_tape(compiled)
            for row, (source_index, command) in enumerate(compiled.sorted_commands):
                code = codes[row].copy()
                for column in (6, 7, 8, 9, 10):
                    value = int(code[column])
                    if value >= 0:
                        name = compiled.id_values[value]
                        if name not in self.ids:
                            self.ids[name] = len(self.ids)
                        code[column] = self.ids[name]
                original = fresh[source_index]
                slot = self.rows[original.order_id][1] if original.order_id in self.rows else len(self.rows)
                self._reserve(slot+1)
                self.rows[original.order_id] = (original, slot)
                self.bars[slot], self.codes[slot], self.values[slot], self.expiry[slot] = (
                    compiled.command_bar[row], code, values[row], expiry[row])
                self.compiled_rows += 1
        selected = np.fromiter((self.rows[c.order_id][1] for c in commands), dtype=np.int64,
                               count=len(commands))
        bars = self.bars[selected]
        if np.any(bars[1:] < bars[:-1]):
            raise ValueError("cached research tape requires stable chronological commands")
        codes = self.codes[selected]
        values = self.values[selected]
        expiry = self.expiry[selected]
        codes[:, 12] = np.arange(len(selected), dtype=np.int64)
        ptr = np.cumsum(np.bincount(bars+1, minlength=len(self.index)+1), dtype=np.int64)
        return ptr, codes, values, expiry, tuple(self.ids)

    def execute(self, commands):
        ptr, codes, values, expiry, ids = self.pack(commands)
        module = self.runner._module
        request = module.NativeExecutionRequestCore.from_template_command_tape(
            self.runner._typed_template, ptr, codes, values, expiry, output_profile=2)
        owner = request.new_runner()
        try:
            return owner.execute_typed(), ids
        finally:
            owner.close()


def assert_native_audit_equivalent(left, right):
    """Compare completed native outputs, including lifecycle and terminal slots."""
    import pandas as pd

    for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_allclose(np.asarray(getattr(left, field)),
                                   np.asarray(getattr(right, field)), rtol=0, atol=1e-8,
                                   err_msg=f"completed typed/native {field}")
    pd.testing.assert_frame_equal(left.diagnostics, right.diagnostics, check_dtype=False,
                                  check_exact=False, rtol=0, atol=1e-8)
    for a, b in zip(left.fills, right.fills, strict=True):
        for field in ("timestamp", "symbol", "side", "qty", "price", "fee", "order_id", "liquidity"):
            if getattr(a, field) != getattr(b, field):
                raise AssertionError(f"completed typed/native fill {field}")
    for key in ("order_report", "order_events", "command_report", "active_orders",
                "command_outcome_report_v1", "lifecycle_event_report_v1"):
        pd.testing.assert_frame_equal(left.metadata[key], right.metadata[key], check_dtype=False,
                                      check_exact=False, rtol=0, atol=1e-8)
    for key in ("native_terminal_state_v1", "lifecycle_counters", "execution_contract_id"):
        if left.metadata[key] != right.metadata[key]:
            raise AssertionError(f"completed typed/native {key}")
    if (left.liquidated, left.liquidation_bar) != (right.liquidated, right.liquidation_bar):
        raise AssertionError("completed typed/native liquidation")


def assert_empty_reference_equivalent(reference, actual, commands):
    """The Python owner omits event columns on an empty tape, not its account."""
    if commands or reference.fills or actual.fills:
        raise AssertionError("empty-reference contract requires no commands/fills")
    if not reference.metadata["order_events"].empty or not actual.metadata["order_events"].empty:
        raise AssertionError("empty-reference contract has lifecycle events")
    for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_allclose(np.asarray(getattr(reference, field)),
                                   np.asarray(getattr(actual, field)), rtol=0, atol=1e-8)
    np.testing.assert_allclose(reference.diagnostics.turnover, actual.diagnostics.turnover, rtol=0, atol=1e-8)
    if (reference.liquidated, reference.liquidation_bar, reference.metadata["execution_contract_id"]) != (
            actual.liquidated, actual.liquidation_bar, actual.metadata["execution_contract_id"]):
        raise AssertionError("empty-reference liquidation/clock differs")
