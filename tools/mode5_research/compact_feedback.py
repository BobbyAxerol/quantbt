"""Opt-in current-bar transport; all financial state stays in FullSession.

The packed protocol is an experimental companion capability, not a fallback
financial implementation. A fresh owner/session is required for every run.
The ordinary native protocol remains available for isolated delta comparisons.
"""

from types import SimpleNamespace

import numpy as np

from tools.mode5_research.feedback_prefix import CommittedFeedbackPrefix
from tools.mode5_research.incremental_feedback import IncrementalFeedbackCompiler
from tools.mode5_research.transactional_feedback import (
    EVENTS, FILLS, PATHS, TransactionalTapeFeedback, _FeedbackView,
)


_EVENT_COLUMNS = EVENTS
_FILL_INTS = ("fill_order_id", "fill_symbol", "fill_side", "fill_reason",
              "fill_ambiguity", "fill_order_type")
_FILL_FLOATS = ("fill_qty", "fill_price", "fill_fee")
_EMPTY_RECORD = {name: () for name in EVENTS + FILLS}
_EMPTY_ENCODING = (b"",) * len(_EMPTY_RECORD)


def decode_packet(packet):
    """Decode native-endian f64/i64 buffers without converting IDs to floats."""
    if type(packet) is not tuple or len(packet) != 5 or any(type(p) is not bytes for p in packet):
        raise TypeError("versioned immutable five-buffer native feedback packet required")
    account = np.frombuffer(packet[0], dtype=np.float64)
    if len(account) != 7:
        raise ValueError("single-symbol research feedback packet required")
    events = np.frombuffer(packet[1], dtype=np.int64).reshape(-1, 6)
    fill_ints = np.frombuffer(packet[2], dtype=np.int64).reshape(-1, 6)
    fill_values = np.frombuffer(packet[3], dtype=np.float64).reshape(-1, 3)
    terminal = np.frombuffer(packet[4], dtype=np.int64)
    if len(terminal) != 3 or terminal[0] not in (0, 1) or len(fill_ints) != len(fill_values):
        raise ValueError("malformed native feedback packet")
    columns = {name: tuple(matrix[:, column].tolist())
               for names, matrix in ((_EVENT_COLUMNS, events), (_FILL_INTS, fill_ints),
                                     (_FILL_FLOATS, fill_values))
               for column, name in enumerate(names)} if len(events) or len(fill_ints) else _EMPTY_RECORD
    return SimpleNamespace(equity=float(account[0]), positions=account[1:2],
        fee=float(account[2]), funding=float(account[3]), turnover=float(account[4]),
        initial_margin=float(account[5]), maintenance_margin=float(account[6]),
        liquidated=bool(terminal[0]), liquidation_bar=int(terminal[1]),
        liquidation_reason=int(terminal[2]), **columns)


class CompactFeedbackView(_FeedbackView):
    """Preserve original feedback semantics without repeated empty projections."""

    def __init__(self, owner, step, account_bytes=None):
        self.owner, self.step, self.path_offset = owner, step, owner.start
        self.bar, self.id_values, self.commands = owner.bar, owner.packed.id_namespace, owner.command_map
        self.prefix_before = owner.committed_prefix
        self.account_bytes = account_bytes if account_bytes is not None else np.asarray(
            [step.equity, *step.positions, step.fee, step.funding, step.turnover,
             step.initial_margin, step.maintenance_margin], dtype=np.float64).tobytes()
        if step.event_kind or step.fill_order_id:
            self.record = {key: tuple(getattr(step, key)) for key in EVENTS + FILLS}
            encoded = tuple(np.asarray(self.record[key], dtype=np.float64
                if key in _FILL_FLOATS else np.int64).tobytes() for key in EVENTS + FILLS)
            codes = {code for key in ("event_order_id", "event_target_id", "fill_order_id")
                     for code in self.record[key] if code >= 0}
            names = tuple((code, self.id_values[code]) for code in sorted(codes))
            self.events = self._events()
        else:
            self.record, encoded, names, self.events = _EMPTY_RECORD, _EMPTY_ENCODING, (), ()
        self.encoded = encoded
        self.prefix_after = CommittedFeedbackPrefix(owner.committed_prefix.stop + 1,
            (owner.committed_prefix.payload, self.account_bytes, encoded, names))


class CompactFeedbackCompiler(IncrementalFeedbackCompiler):
    @staticmethod
    def _prefix_unchanged(before, after, bar):
        if before is None:
            return
        if type(before) is CompactFeedbackView and type(after) is CompactFeedbackView:
            if before.owner is not after.owner:
                raise AssertionError("committed native feedback owner changed")
            left, right = before.prefix_certificate(bar), after.prefix_certificate(bar)
            if (before.path_offset == after.path_offset and type(left) is CommittedFeedbackPrefix
                    and left is right and left.stop == max(0, bar-before.path_offset)):
                return
        IncrementalFeedbackCompiler._prefix_unchanged(before, after, bar)


class CompactTapeFeedback(TransactionalTapeFeedback):
    """Delta input plus optional advance/packed-step over the same native core.

    Packed mode defers the physical commit until the next advance, or final
    audit. Logical committed buffers remain immutable at the original bar
    boundary. A same-bar retry still restores the native transaction checkpoint.
    No financial calculation is performed here.
    """

    def __init__(self, packed, *, index, start, symbol, fused=False):
        self.packed, self.index, self.start, self.symbol = packed, index, int(start), symbol
        self.session = packed.runner._module.NativeFeedbackSessionCore.from_template(
            packed.runner._typed_template)
        self.fused = bool(fused)
        if self.fused and not all(callable(getattr(self.session, name, None))
                                 for name in ("advance_packed", "step_packed")):
            self.session.close()
            raise NotImplementedError("qualified packed-feedback native capability required")
        self._account_rows, self.records, self._prefix_rows, self._prefix_bars = [], [], [], []
        self._path_cache = None
        self.committed_prefix = CommittedFeedbackPrefix(0, ())
        self.feedback_by_bar = {}
        self.bar = self.current = self.step_tape = None
        self.commands, self.command_map = (), {}
        self.native_step_calls = self.transactions = self.same_bar_steps = 0
        self.native_boundary_calls = self.full_tape_executions = 0
        self.closed = self._pending_native_commit = False

    def begin_bar(self, bar, commands):
        if self.closed or self.bar is not None or bar != self.start + len(self.records):
            raise ValueError("consecutive feedback transaction required")
        self.bar, self.step_tape = bar, None
        if not self.fused:
            self.session.begin(bar-self.start)
            self.native_boundary_calls += 1
        self.transactions += 1
        return self(commands)

    def __call__(self, commands):
        if self.bar is None or self.closed:
            raise ValueError("active feedback transaction required")
        commands = commands if type(commands) is tuple else tuple(commands)
        if self.current is not None and self.step_tape is not None and commands is self.commands:
            return self.current
        arrays = self.packed.pack_bar(commands, self.bar-self.start)
        encoded = tuple(array.tobytes() for array in arrays)
        self.commands, self.command_map = commands, self.packed.command_map
        if encoded != self.step_tape:
            repeated = self.step_tape is not None
            self.same_bar_steps += int(repeated)
            if self.fused:
                packet = (self.session.step_packed(*arrays) if repeated else
                          self.session.advance_packed(self.bar-self.start, *arrays))
                self._pending_native_commit = True
                step, account_bytes = decode_packet(packet), packet[0]
            else:
                step, account_bytes = self.session.step(*arrays), None
            self.native_step_calls += 1
            self.native_boundary_calls += 1
            self.step_tape = encoded
        else:
            step, account_bytes = self.current.step, self.current.account_bytes
        self.current = CompactFeedbackView(self, step, account_bytes)
        return self.current

    def commit_bar(self, bar):
        if bar != self.bar or self.current is None:
            raise ValueError("current feedback transaction required")
        if not self.fused:
            self.session.commit()
            self.native_boundary_calls += 1
        if self.current.prefix_before is not self.committed_prefix:
            raise AssertionError("committed financial prefix changed")
        self._account_rows.append(self.current.account_bytes)
        self._path_cache, self.committed_prefix = None, self.current.prefix_after
        record = None
        if self.current.step.event_kind or self.current.step.fill_order_id:
            record = self.current.record
            self._prefix_bars.append(bar-self.start)
            self._prefix_rows.append((bar-self.start, self.current.encoded))
        self.records.append(record)
        if self.current.events:
            self.feedback_by_bar[bar] = self.current.events
        self.bar = None

    def audit(self):
        if self.bar is not None or len(self.records) != len(self.index):
            raise ValueError("complete committed feedback account required")
        if self.fused and self._pending_native_commit:
            self.session.commit()
            self.native_boundary_calls += 1
            self._pending_native_commit = False
        return super().audit()

    def close(self):
        super().close()
