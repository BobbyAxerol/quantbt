"""Bounded, run-owned reuse of exact original-result witness material."""

from collections import OrderedDict
import hashlib

import numpy as np
import pandas as pd

from .common import MetaRecordError, digest, utc


class PreparedMetricWitness:
    """Cache immutable headers, never financial outputs or mutable accounts."""

    def __init__(self, frame, *, config, max_entries=256, max_bytes=8_000_000):
        self.frame, self.config = frame, config
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.rows = pd.util.hash_pandas_object(frame, index=True).to_numpy(copy=True)
        self.rows.flags.writeable = False
        self.schema = digest({"columns": list(frame.columns),
                              "dtypes": [str(d) for d in frame.dtypes]}).encode()
        self.funding = (config.funding_rate.copy(deep=True)
                        if isinstance(config.funding_rate, pd.Series) else None)
        self.cache = OrderedDict()
        self.bytes = 0
        self.stats = dict(header_hits=0, header_misses=0, market_hits=0,
                          market_misses=0, reference_fallbacks=0, evictions=0)
        self.closed = False

    def _get(self, key, create, size=256):
        if self.closed:
            raise MetaRecordError("META_WITNESS_CLOSED")
        if key in self.cache:
            value, _size = self.cache[key]
            self.cache.move_to_end(key)
            return value, True
        value = create()
        if size <= self.max_bytes:
            while self.cache and (len(self.cache) >= self.max_entries
                                  or self.bytes + size > self.max_bytes):
                _, (_, removed) = self.cache.popitem(last=False)
                self.bytes -= removed
                self.stats["evictions"] += 1
            if self.max_entries:
                self.cache[key] = value, size
                self.bytes += size
        return value, False

    @staticmethod
    def calendar_key(index):
        index = pd.DatetimeIndex(index)
        # Same UTC instants yield the same original ISO calendar representation.
        values = index.as_unit("ns").asi8
        return len(index), hashlib.sha256(values.tobytes()).hexdigest()

    def _owned_prefix(self, frame):
        if not isinstance(frame, pd.DataFrame) or len(frame) > len(self.frame):
            return False
        if not frame.columns.equals(self.frame.columns) or not frame.dtypes.equals(self.frame.dtypes):
            return False
        if not frame.index.equals(self.frame.index[:len(frame)]):
            return False
        return all(np.shares_memory(frame[c].to_numpy(), self.frame[c].to_numpy())
                   for c in frame.columns)

    def market_signature(self, frame, index):
        from .observer import market_signature

        if not self._owned_prefix(frame):
            self.stats["reference_fallbacks"] += 1
            return market_signature(frame, index, config=self.config)
        stop = int(frame.index.searchsorted(index[-1], side="right"))
        key = ("market", stop, self.calendar_key(index) if self.funding is not None else None)

        def create():
            sha = hashlib.sha256(self.schema)
            sha.update(self.rows[:stop].tobytes())
            if self.funding is not None:
                rates = self.funding.reindex(index)
                sha.update(pd.util.hash_pandas_object(rates, index=True).to_numpy().tobytes())
            return sha.hexdigest()

        value, hit = self._get(key, create)
        self.stats["market_hits" if hit else "market_misses"] += 1
        return value

    def header(self, index, *, initial_capital, economics_id, metric_id, input_signature):
        key = ("header", self.calendar_key(index), float(initial_capital),
               economics_id, metric_id, input_signature)
        value, hit = self._get(key, lambda: hashlib.sha256(digest({
            "index": [utc(t).isoformat() for t in index],
            "initial_capital": initial_capital, "economics": economics_id,
            "metric": metric_id, "input": input_signature,
        }).encode()))
        self.stats["header_hits" if hit else "header_misses"] += 1
        return value.copy()

    def validate_source(self):
        if self.closed:
            return
        rows = pd.util.hash_pandas_object(self.frame, index=True).to_numpy()
        schema = digest({"columns": list(self.frame.columns),
                         "dtypes": [str(d) for d in self.frame.dtypes]}).encode()
        if schema != self.schema or not np.array_equal(rows, self.rows):
            raise MetaRecordError("META_WITNESS_SOURCE_MUTATED")
        current = self.config.funding_rate
        if self.funding is not None and (not isinstance(current, pd.Series)
                                        or not current.equals(self.funding)):
            raise MetaRecordError("META_WITNESS_FUNDING_MUTATED")

    @property
    def metadata(self):
        return dict(schema="qms-prepared-witness-v1", **self.stats,
                    entries=len(self.cache), retained_bytes=self.bytes,
                    owned_row_hash_bytes=self.rows.nbytes,
                    max_entries=self.max_entries, max_bytes=self.max_bytes,
                    closed=self.closed)

    def close(self):
        self.cache.clear()
        self.bytes = 0
        self.rows = np.empty(0, dtype=np.uint64)
        self.frame = self.config = self.funding = None
        self.closed = True
