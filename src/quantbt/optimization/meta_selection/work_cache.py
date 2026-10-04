"""Bounded exact numeric reuse; eviction never removes scientific history."""

from hashlib import sha256

from .common import canonical, frozen_array


class ExactWorkCache:
    """One immutable output per block, with context AND complete buffer identity."""

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self.entries = {}
        self.hits = self.misses = self.clears = 0

    @staticmethod
    def key(context, arrays):
        if context is None:
            return None
        identity = sha256(canonical(context).encode())
        for value in arrays:
            identity.update(canonical((value.shape, value.dtype.str)).encode())
            if value.size:
                identity.update(memoryview(value).cast("B"))
        return identity.hexdigest()

    def get(self, block, key):
        entry = self.entries.get(block)
        if key is not None and entry is not None and entry[0] == key:
            self.hits += 1
            return tuple(a.copy() for a in entry[1])
        self.misses += 1
        return None

    def put(self, block, key, arrays):
        self.entries.pop(block, None)
        if key is None:
            return
        required = sum(a.nbytes for a in arrays)
        # This is a workspace eviction/bypass, not a reduction in rows/features.
        if required + self.retained_bytes <= self.max_bytes:
            self.entries[block] = (key, tuple(frozen_array(a) for a in arrays))

    @property
    def retained_bytes(self):
        return sum(a.nbytes for _, arrays in self.entries.values() for a in arrays)

    def clear(self):
        self.entries.clear()
        self.clears += 1

    @property
    def metadata(self):
        return {
            "identity": "context_and_complete_float64_buffers_v1",
            "lifetime": "one_numeric_runtime_no_financial_state",
            "maximum_entries": 2,
            "maximum_bytes": self.max_bytes,
            "retained_bytes": self.retained_bytes,
            "hits": self.hits,
            "misses": self.misses,
            "clears": self.clears,
        }
