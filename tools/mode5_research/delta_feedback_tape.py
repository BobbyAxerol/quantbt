"""Opt-in current-bar packing over the authoritative command compiler.

This owner caches numeric input rows, never account/order/strategy state.
Commands must be chronological, frozen ``OrderCommand`` records. Advancing
``local_bar`` seals all earlier source rows; only the uncommitted suffix may
change. Start at bar zero and use a new owner, or explicit ``reset()``, with a
new financial session. Bar zero is validated but emits no rows (P0 policy).

An unchanged tuple is an identity witness. A different tuple/list requires an
exact prefix comparison, not a hash or an unchecked append claim. Compilation
and numeric gathers touch only fresh rows/current-bar rows respectively. The
existing compiler itself still constructs its authoritative calendar pointer
when fresh rows are compiled; this module does not construct a second one.
"""

from bisect import bisect_left, bisect_right
from types import MappingProxyType

import numpy as np

from quantbt.core.orders import OrderCommand
from quantbt.backends._native_event_rust import compile_rust_full_tape
from tools.mode5_research.prepared_feedback import CachedTapeRows


_ID_COLUMNS = (6, 7, 8, 9, 10)


def _detached(array):
    """Return an immutable snapshot with no writable cache alias."""
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


class DeltaTapeRows:
    """Pack exactly the current slice without gathering the retained tape.

    The original quantity preflight and both original command compilers remain
    authoritative. IDs use the same append-only, first-compiled-row namespace
    as ``CachedTapeRows``, including IDs from rolled-back speculative rows.
    Source ordinal column 12 remains global, not current-slice-relative.
    Prepared market, calendar and quantity constraints must remain immutable
    for this owner's lifetime, as for the underlying ``CachedTapeRows``.

    This is deliberately not a replacement for full-tape final audit packing.
    Reordering across timestamps, committed edits/drops and late commands fail
    explicitly. Same-bar suffix rollback/reordering and future amendments are
    supported without changing committed rows. ``command_map`` exposes original
    commands (not quantity-adjusted replacements), matching existing feedback.
    """

    def __init__(self, backend, runner, index, symbol, constraints):
        self.backend, self.runner = backend, runner
        self.index, self.symbol, self.constraints = index, symbol, constraints
        self.reset()

    def reset(self):
        """Clear input caches; the caller must separately reset native state."""
        self._cache = CachedTapeRows(
            self.backend, self.runner, self.index, self.symbol, self.constraints
        )
        self._commands = ()
        self._names, self._bars, self._slots = [], [], []
        self._command_map, self._positions = {}, {}
        self._last_bar = -1
        self._counts = dict(
            pack_calls=0,
            identical_tuple_calls=0,
            source_rows_checked=0,
            sequence_rows_copied=0,
            append_updates=0,
            suffix_updates=0,
            unchanged_updates=0,
            original_compiler_calls=0,
            cache_reused_rows=0,
            current_bar_rows_emitted=0,
            full_tape_gathers=0,
        )

    @property
    def id_namespace(self):
        return self._cache.id_namespace

    @property
    def command_map(self):
        return MappingProxyType(self._command_map)

    @property
    def compiled_rows(self):
        return self._cache.compiled_rows

    @property
    def counters(self):
        return MappingProxyType({**self._counts, "compiled_rows": self.compiled_rows})

    def _shared_prefix(self, commands):
        if commands is self._commands:
            self._counts["identical_tuple_calls"] += 1
            return len(commands)
        shared = 0
        for previous, command in zip(self._commands, commands):
            self._counts["source_rows_checked"] += 1
            if previous is not command and previous != command:
                break
            shared += 1
        return shared

    def _compile(self, fresh):
        if not fresh:
            return {}, {}
        effective, preflight = self.backend._apply_command_quantity_constraints(
            idx=self.index,
            commands=fresh,
            closes=self.runner.market_arrays.closes,
            symbol_list=[self.symbol],
            contract_sizes=self.runner.contract_sizes,
            constraints=self.constraints,
        )
        if preflight["dropped_count"]:
            raise ValueError("dropped quantity needs explicit feedback qualification")
        compiled = self.backend.compile_order_commands(
            self.index, effective, symbols=[self.symbol]
        )
        _, codes, values, expiry = compile_rust_full_tape(compiled)
        self._counts["original_compiler_calls"] += 1
        staged, new_ids = {}, {}
        for row, (source_index, _) in enumerate(compiled.sorted_commands):
            code = codes[row].copy()
            for column in _ID_COLUMNS:
                value = int(code[column])
                if value >= 0:
                    name = compiled.id_values[value]
                    if name not in self._cache.ids and name not in new_ids:
                        new_ids[name] = len(self._cache.ids) + len(new_ids)
                    code[column] = (
                        self._cache.ids[name]
                        if name in self._cache.ids
                        else new_ids[name]
                    )
            command = fresh[source_index]
            staged[command.order_id] = (
                command,
                int(compiled.command_bar[row]),
                code,
                values[row].copy(),
                int(expiry[row]),
            )
        if len(staged) != len(fresh):
            raise ValueError("original compiler did not retain each unique source row")
        return staged, new_ids

    def _update(self, commands, local_bar):
        shared = self._shared_prefix(commands)
        committed = bisect_left(self._bars, local_bar)
        if shared < committed:
            raise ValueError("committed command prefix changed, dropped or reordered")
        if shared == len(commands) == len(self._commands):
            self._counts["unchanged_updates"] += 1
            self._commands = commands
            return

        suffix, fresh, seen = [], [], set()
        for position in range(shared, len(commands)):
            command = commands[position]
            if type(command) is not OrderCommand:
                raise TypeError("delta research tape requires frozen OrderCommand rows")
            name = command.order_id
            if type(name) is not str or not name:
                raise ValueError("delta research tape requires unique explicit string order IDs")
            if name in seen or self._positions.get(name, shared) < shared:
                raise ValueError("delta research tape requires unique explicit order IDs")
            seen.add(name)
            suffix.append(command)
            cached = self._cache.rows.get(name)
            if cached is None or (cached[0] is not command and cached[0] != command):
                fresh.append(command)

        staged, new_ids = self._compile(tuple(fresh))
        suffix_bars, suffix_slots = [], []
        previous_bar = self._bars[shared - 1] if shared else -1
        for command in suffix:
            name = command.order_id
            cached = self._cache.rows.get(name)
            bar = staged[name][1] if name in staged else int(self._cache.bars[cached[1]])
            if bar < local_bar:
                raise ValueError("new or changed command enters a committed bar")
            if bar < previous_bar:
                raise ValueError("delta research tape requires stable chronological commands")
            suffix_bars.append(bar)
            previous_bar = bar

        # Nothing below changes cached rows/IDs until all prefix/order checks
        # have succeeded. Invalid deltas cannot poison a later valid retry.
        self._cache.ids.update(new_ids)
        for name, (command, bar, code, values, expiry) in staged.items():
            old = self._cache.rows.get(name)
            slot = old[1] if old is not None else len(self._cache.rows)
            self._cache._reserve(slot + 1)
            self._cache.rows[name] = (command, slot)
            self._cache.bars[slot] = bar
            self._cache.codes[slot] = code
            self._cache.values[slot] = values
            self._cache.expiry[slot] = expiry
        self._cache.compiled_rows += len(staged)
        if new_ids:
            self._cache.id_namespace = tuple(self._cache.ids)
        for name in self._names[shared:]:
            del self._command_map[name]
            del self._positions[name]
        for position, command in enumerate(suffix, start=shared):
            self._command_map[command.order_id] = command
            self._positions[command.order_id] = position
            suffix_slots.append(self._cache.rows[command.order_id][1])
        self._counts["cache_reused_rows"] += len(suffix) - len(staged)
        key = "append_updates" if shared == len(self._commands) else "suffix_updates"
        self._counts[key] += 1
        del self._names[shared:]
        del self._bars[shared:]
        del self._slots[shared:]
        self._names.extend(command.order_id for command in suffix)
        self._bars.extend(suffix_bars)
        self._slots.extend(suffix_slots)
        self._commands = commands

    def pack_bar(self, commands, local_bar):
        """Return detached ``codes(n,16), values(n,3), expiry(n,)`` arrays.

        Same-bar calls are transactional retries. Moving forward seals earlier
        rows; moving backward requires a reset/new owner, never implicit replay.
        Lists are snapshotted to a tuple; unchanged tuple callers avoid that
        copy. Frozen command numeric fields are part of this input contract.
        """
        if isinstance(local_bar, (bool, np.bool_)) or not isinstance(local_bar, (int, np.integer)):
            raise TypeError("integer local_bar required")
        local_bar = int(local_bar)
        if not 0 <= local_bar < len(self.index):
            raise ValueError("local_bar outside prepared calendar")
        if self._last_bar < 0 and local_bar != 0:
            raise ValueError("delta tape must start at local bar zero")
        if local_bar < self._last_bar:
            raise ValueError("local_bar cannot move backward without reset")
        self._counts["pack_calls"] += 1
        if type(commands) is not tuple:
            commands = tuple(commands)
            self._counts["sequence_rows_copied"] += len(commands)
        self._update(commands, local_bar)
        self._last_bar = local_bar
        start = bisect_left(self._bars, local_bar)
        stop = start if local_bar == 0 else bisect_right(self._bars, local_bar)
        slots = self._slots[start:stop]
        codes = self._cache.codes[slots]
        codes[:, 12] = np.arange(start, stop, dtype=np.int64)
        values, expiry = self._cache.values[slots], self._cache.expiry[slots]
        self._counts["current_bar_rows_emitted"] += stop - start
        return _detached(codes), _detached(values), _detached(expiry)
