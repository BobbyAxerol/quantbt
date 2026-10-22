"""Explicit-lifetime reporting cache; no market, account, trial or RNG ownership."""

from collections import OrderedDict
import json

from .account import reduce_account
from .execution import reduce_execution
from .ledger import reduce_ledger
from .snapshots import SnapshotValue


class ReportingCache:
    def __init__(self, *, max_entries=8, max_bytes=4 * 1024 ** 2):
        if any(type(value) is not int or value <= 0 for value in (max_entries, max_bytes)):
            raise ValueError("positive integer entry/byte bounds required")
        self._max_entries, self._max_bytes = max_entries, max_bytes
        self._entries = OrderedDict()
        self.retained_bytes = 0
        self.hits = self.misses = 0
        self.closed = False

    @property
    def max_entries(self):
        return self._max_entries

    @property
    def max_bytes(self):
        return self._max_bytes

    @property
    def entry_count(self):
        return len(self._entries)

    def reduce(self, kind, observations, contract, **options):
        if self.closed:
            raise RuntimeError("reporting cache is closed")
        reducers = {"account": reduce_account, "ledger": reduce_ledger, "execution": reduce_execution}
        if kind not in reducers:
            raise ValueError("unknown reporting reducer")
        if isinstance(observations, SnapshotValue):
            observations.validate_snapshot()
        option_key = json.dumps(options, sort_keys=True, allow_nan=False)
        key = (kind, observations.identity, contract.identity, option_key)
        if key in self._entries:
            self._entries[key][0].validate_snapshot()
            self.hits += 1
            self._entries.move_to_end(key)
            return self._entries[key][0]
        self.misses += 1
        result = reducers[kind](observations, contract, **options)
        weight = result.retained_bytes + sum(len(part.encode("utf-8")) for part in key) + 1024
        if weight <= self.max_bytes:
            while self._entries and (len(self._entries) >= self.max_entries or self.retained_bytes + weight > self.max_bytes):
                _, (_, removed) = self._entries.popitem(last=False)
                self.retained_bytes -= removed
            self._entries[key] = (result, weight)
            self.retained_bytes += weight
        return result

    def release(self, input_identity):
        for key in tuple(self._entries):
            if key[1] == input_identity:
                _, weight = self._entries.pop(key)
                self.retained_bytes -= weight

    def clear(self):
        self._entries.clear()
        self.retained_bytes = 0

    def close(self):
        self.clear()
        self.closed = True

    def __enter__(self):
        if self.closed:
            raise RuntimeError("reporting cache is closed")
        return self

    def __exit__(self, *args):
        self.close()
