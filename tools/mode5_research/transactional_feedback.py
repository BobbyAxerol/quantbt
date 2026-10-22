"""Current-bar transactions over the existing Rust financial session.

The Python owner compiles commands and projects actual engine outputs only.
It never computes a fill, mark, fee, funding, margin or liquidation value.
"""

from types import MappingProxyType, SimpleNamespace
from bisect import bisect_left

import numpy as np

from quantbt import Fill, OrderSide
from tools.mode5_research.incremental_feedback import FeedbackEvent
from tools.mode5_research.feedback_prefix import CommittedFeedbackPrefix


PATHS = (
    "equity",
    "positions",
    "fees",
    "funding",
    "turnover",
    "initial_margin",
    "maintenance_margin",
)
EVENTS = (
    "event_kind",
    "event_status",
    "event_order_id",
    "event_target_id",
    "event_symbol",
    "event_reject_code",
)
FILLS = (
    "fill_order_id",
    "fill_symbol",
    "fill_side",
    "fill_qty",
    "fill_price",
    "fill_fee",
    "fill_reason",
    "fill_ambiguity",
    "fill_order_type",
)


class _FeedbackView:
    def __init__(self, owner, step, commands):
        self.owner, self.step = owner, step
        self.path_offset = owner.start
        self.bar = owner.bar
        self.id_values = owner.packed.id_namespace
        self.commands = owner.command_map
        self.prefix_before = owner.committed_prefix
        self.account_bytes = np.asarray(
            [
                step.equity,
                *step.positions,
                step.fee,
                step.funding,
                step.turnover,
                step.initial_margin,
                step.maintenance_margin,
            ],
            dtype=np.float64,
        ).tobytes()
        self.record = {key: tuple(getattr(step, key)) for key in EVENTS + FILLS}
        encoded = tuple(
            np.asarray(
                self.record[key],
                dtype=np.float64
                if key in {"fill_qty", "fill_price", "fill_fee"}
                else np.int64,
            ).tobytes()
            for key in EVENTS + FILLS
        )
        codes = {
            code
            for key in ("event_order_id", "event_target_id", "fill_order_id")
            for code in self.record[key]
            if code >= 0
        }
        names = tuple((code, self.id_values[code]) for code in sorted(codes))
        self.prefix_after = CommittedFeedbackPrefix(
            owner.committed_prefix.stop + 1,
            (owner.committed_prefix.payload, self.account_bytes, encoded, names),
        )
        self.events = self._events()

    @property
    def paths(self):
        return self.owner.paths

    def prefix_certificate(self, bar):
        if bar == self.bar:
            return self.prefix_before
        if bar == self.bar + 1:
            return self.prefix_after
        return None

    def _events(self):
        step, owner = self.step, self.owner
        ids, local = self.id_values, self.bar - owner.start
        fills = {}
        for slot, code in enumerate(step.fill_order_id):
            if code in fills:
                raise ValueError("partial fill feedback needs an explicit transport")
            fills[code] = slot
        result = []
        for slot, kind in enumerate(step.event_kind):
            if kind not in (4, 7):
                continue
            code = step.event_order_id[slot]
            name = None if code < 0 else ids[code]
            fill = None
            if kind == 4:
                row = fills.pop(code)
                fill = Fill(
                    timestamp=owner.index[local],
                    symbol=owner.symbol,
                    order_id=name,
                    side=OrderSide.BUY if step.fill_side[row] > 0 else OrderSide.SELL,
                    qty=step.fill_qty[row],
                    price=step.fill_price[row],
                    fee=step.fill_fee[row],
                    metadata=self.commands[name].metadata,
                )
            label = "fill" if kind == 4 else "reject"
            record = dict(
                timestamp=owner.index[local],
                bar=local,
                event_name=label,
                order_id=name,
                status=step.event_status[slot],
                reject_code=step.event_reject_code[slot],
            )
            result.append(FeedbackEvent(self.bar, name, label, fill, record))
        if fills:
            raise ValueError("unmapped actual fill event")
        return tuple(result)

    def events_at(self, bar):
        if bar == self.bar:
            return self.events
        return self.owner.feedback_by_bar.get(bar, ())

    def events_before(self, bar):
        return self.owner.events_before(bar)


class TransactionalTapeFeedback:
    """One prepared market/session, with bounded same-bar rollback only.

    The compiler's committed prefix is append-only. No financial output is
    written to its retained buffers until the current native transaction commits.
    Current-bar views therefore cannot rewrite a previously committed path or
    event row. Final exports are detached read-only arrays.
    """

    feedback_protocol = "current-bar-transaction-v1"

    def __init__(self, packed, *, index, start, symbol):
        module = packed.runner._module
        factory = getattr(module, "NativeFeedbackSessionCore", None)
        if factory is None:
            raise NotImplementedError(
                "transactional_feedback_v1 requires a qualified native extension"
            )
        self.session = factory.from_template(packed.runner._typed_template)
        self.packed, self.index, self.start, self.symbol = (
            packed,
            index,
            int(start),
            symbol,
        )
        self._account_rows = []
        self._path_cache = None
        self.committed_prefix = CommittedFeedbackPrefix(0, ())
        self.records = []
        self._prefix_rows, self._prefix_bars = [], []
        self.feedback_by_bar = {}
        self.bar = None
        self.current = None
        self.commands = ()
        self.command_map = {}
        self.tape = packed.pack(())
        self.step_tape = None
        self.native_step_calls = self.transactions = self.same_bar_steps = 0
        self.full_tape_executions = 0
        self.closed = False

    @property
    def paths(self):
        if self._path_cache is None:
            data = b"".join(self._account_rows) + bytes(
                (len(self.index) - len(self._account_rows)) * len(PATHS) * 8
            )
            matrix = np.frombuffer(data, dtype=np.float64).reshape(
                len(self.index), len(PATHS)
            )
            self._path_cache = MappingProxyType(
                {
                    key: matrix[:, slot : slot + 1]
                    if key == "positions"
                    else matrix[:, slot]
                    for slot, key in enumerate(PATHS)
                }
            )
        return self._path_cache

    def _pack(self, commands):
        if commands == self.commands:
            return
        previous = self.tape
        self.tape = self.packed.pack(commands)
        if self.tape[-1][: len(previous[-1])] != previous[-1]:
            raise AssertionError("committed ID namespace changed")
        if self.bar is not None:
            local = self.bar - self.start
            old_stop, new_stop = int(previous[0][local]), int(self.tape[0][local])
            if old_stop != new_stop or any(
                a[:old_stop].tobytes() != b[:new_stop].tobytes()
                for a, b in zip(previous[1:4], self.tape[1:4])
            ):
                raise AssertionError("committed command prefix changed")
        self.commands = commands
        self.command_map = {command.order_id: command for command in commands}

    def _bar_tape(self):
        local = self.bar - self.start
        ptr, codes, values, expiry, _ = self.tape
        a, b = (
            (int(ptr[1]), int(ptr[1]))
            if local == 0
            else (int(ptr[local]), int(ptr[local + 1]))
        )
        return codes[a:b], values[a:b], expiry[a:b]

    def begin_bar(self, bar, commands):
        if self.closed or self.bar is not None or bar != self.start + len(self.records):
            raise ValueError("consecutive feedback transaction required")
        self.bar = bar
        self._pack(tuple(commands))
        self.session.begin(bar - self.start)
        self.transactions += 1
        self.step_tape = None
        return self(tuple(commands))

    def __call__(self, commands):
        if self.bar is None or self.closed:
            raise ValueError("active feedback transaction required")
        self._pack(tuple(commands))
        arrays = self._bar_tape()
        encoded = tuple(array.tobytes() for array in arrays)
        if self.step_tape != encoded:
            self.same_bar_steps += int(self.step_tape is not None)
            step = self.session.step(*arrays)
            self.native_step_calls += 1
            self.step_tape = encoded
        else:
            step = self.current.step
        self.current = _FeedbackView(self, step, self.commands)
        return self.current

    def commit_bar(self, bar):
        if bar != self.bar or self.current is None:
            raise ValueError("current feedback transaction required")
        step, local = self.current.step, bar - self.start
        self.session.commit()
        if self.current.prefix_before is not self.committed_prefix:
            raise AssertionError("committed financial prefix changed")
        self._account_rows.append(self.current.account_bytes)
        self._path_cache = None
        self.committed_prefix = self.current.prefix_after
        record = None
        if step.event_kind or step.fill_order_id:
            record = self.current.record
            prefix = tuple(
                np.asarray(
                    record[key],
                    dtype=np.float64
                    if key in {"fill_qty", "fill_price", "fill_fee"}
                    else np.int64,
                ).tobytes()
                for key in EVENTS + FILLS
            )
            self._prefix_bars.append(local)
            self._prefix_rows.append((local, prefix))
        self.records.append(record)
        if self.current.events:
            self.feedback_by_bar[bar] = self.current.events
        self.bar = None

    def events_before(self, bar):
        stop = bisect_left(self._prefix_bars, bar - self.start)
        return tuple(self._prefix_rows[:stop])

    def audit(self):
        if self.bar is not None or len(self.records) != len(self.index):
            raise ValueError("complete committed feedback account required")
        arrays = {
            key: np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)
            for key, value in self.paths.items()
        }
        for fields, prefix in ((EVENTS, "event"), (FILLS, "fill")):
            bars = [
                bar
                for bar, row in enumerate(self.records)
                if row is not None
                for _ in row[fields[0]]
            ]
            arrays[prefix + "_bar"] = np.asarray(bars, dtype=np.int64)
            for key in fields:
                dtype = (
                    np.float64
                    if key in {"fill_qty", "fill_price", "fill_fee"}
                    else np.int64
                )
                arrays[key] = np.asarray(
                    [
                        value
                        for row in self.records
                        if row is not None
                        for value in row[key]
                    ],
                    dtype=dtype,
                )
        arrays = {
            key: np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)
            for key, value in arrays.items()
        }
        step = self.current.step
        return SimpleNamespace(
            **arrays,
            id_values=self.packed.id_namespace,
            liquidated=step.liquidated,
            liquidation_bar=step.liquidation_bar,
            liquidation_reason=step.liquidation_reason,
        )

    def close(self):
        if not self.closed:
            self.session.close()
            self.closed = True
