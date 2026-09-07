"""Bounded column storage for the unchanged canonical execution trace schema."""

from __future__ import annotations

from hashlib import sha256

import numpy as np
import pandas as pd


class TraceColumns:
    """Store audit values once, without retaining a dictionary for every row."""

    def __init__(self, capacity, defaults, float_fields, int_fields):
        self.columns = {
            field: np.full(
                capacity, value,
                dtype=np.float64 if field in float_fields else np.int64 if field in int_fields else object,
            )
            for field, value in defaults.items()
        }
        self.int_fields = int_fields
        self.float_fields = frozenset(float_fields)
        self.size = 0
        self.cursor = 0
        self.event_counts = {}

    def append(self, values):
        position = self.cursor
        for field, value in values.items():
            self.columns[field][position] = value
        self.cursor += 1
        kind = values["event_kind"]
        self.event_counts[kind] = self.event_counts.get(kind, 0) + 1

    def fingerprint(self, schema_version, normalize):
        digest = sha256(schema_version.encode("ascii"))
        constant_encoded = {}
        for field, column in self.columns.items():
            if field in self.int_fields or not self.size:
                continue
            values = column[: self.size]
            first = values[0]
            if field in self.float_fields and bool(np.isnan(values).all()):
                constant_encoded[field] = normalize(field, first)
                continue
            try:
                if bool(np.all(values == first)):
                    constant_encoded[field] = normalize(field, first)
            except (TypeError, ValueError):
                # Preserve the established general-purpose serialization path
                # for unusual object payloads.
                pass
        # Encode bounded blocks, sharing identical canonical values within a
        # column. Python's round/NaN/text rules remain the serialization oracle.
        for start in range(0, self.size, 4096):
            encoded_columns = []
            for field, column in self.columns.items():
                values = column[start:min(start + 4096, self.size)]
                if field in self.int_fields:
                    encoded = values.astype("<i8", copy=False).view("V8")
                elif field in constant_encoded:
                    encoded = (constant_encoded[field],) * len(values)
                else:
                    unique, inverse = np.unique(values, return_inverse=True)
                    encoded_unique = np.empty(len(unique), dtype=object)
                    encoded_unique[:] = [normalize(field, value) for value in unique]
                    encoded = encoded_unique[inverse]
                encoded_columns.append(encoded)
            for row in zip(*encoded_columns):
                digest.update(b"".join(row))
        return digest.hexdigest()

    def frame(self):
        if not self.size:
            return pd.DataFrame(columns=self.columns)
        return pd.DataFrame({field: values[:self.size] for field, values in self.columns.items()}, copy=False)


class AccountSnapshotProjection:
    """Align dense account snapshots once; preserve chronological row ordering."""

    def __init__(self, source, index, timestamp_to_bar):
        self.source = source
        if source.empty:
            self.bars = np.empty(0, dtype=np.int64)
            self.order = np.empty(0, dtype=np.int64)
        else:
            timestamps = pd.DatetimeIndex(source["timestamp"]).as_unit("ns").asi8
            bars = np.fromiter((timestamp_to_bar[int(value)] for value in timestamps), dtype=np.int64)
            self.order = np.argsort(bars, kind="stable")
            self.bars = bars[self.order]
        self.counts = np.bincount(self.bars, minlength=len(index))

    def write(self, trace, offsets, sparse_counts, index, accounting, result, symbol_codes, run_id):
        if not len(self.bars):
            return
        source = self.source
        bars = self.bars
        order = self.order
        group_starts = np.cumsum(self.counts) - self.counts
        rows = offsets[bars] + sparse_counts[bars] + np.arange(len(bars)) - group_starts[bars]
        symbols = source["symbol"].astype(str).to_numpy()[order]
        codes = np.fromiter((symbol_codes[symbol] for symbol in symbols), dtype=np.int64)
        after = source["position_qty"].to_numpy(dtype=np.float64)[order]
        before = np.zeros(len(after), dtype=np.float64)
        for symbol in dict.fromkeys(symbols):
            selected = np.flatnonzero(symbols == symbol)
            before[selected[1:]] = after[selected[:-1]]

        locations = accounting.index.get_indexer(index) if not accounting.empty else np.full(len(index), -1)
        present = locations >= 0
        latest = np.maximum.accumulate(np.where(present, np.arange(len(index)), -1))
        previous = np.concatenate(([-1], latest[:-1]))
        previous_equity = np.full(len(index), float(result.initial_capital))
        account_values = {}
        for field in ("equity_actual", "initial_margin", "maintenance_margin", "fee", "funding"):
            values = np.full(len(index), np.nan)
            if present.any():
                values[present] = accounting[field].to_numpy(dtype=np.float64)[locations[present]]
            account_values[field] = values
        seen = previous >= 0
        previous_equity[seen] = account_values["equity_actual"][previous[seen]]
        equity = np.where(present, account_values["equity_actual"], result.equity.to_numpy())
        charge = present[bars] & (codes == 0)
        values = {
            "run_id": run_id, "bar": bars, "timestamp_ns": index.as_unit("ns").asi8[bars],
            "phase": "SNAPSHOT", "sequence": rows, "event_kind": "ACCOUNT_SNAPSHOT",
            "symbol_code": codes, "venue_code": 0, "qty_before": before,
            "qty_delta": after - before, "qty_after": after,
            "price": source["mark_price"].to_numpy(dtype=np.float64)[order],
            "position_before": before, "position_after": after,
            "equity_before": previous_equity[bars], "equity_after": equity[bars],
            "initial_margin_after": account_values["initial_margin"][bars],
            "maintenance_margin_after": account_values["maintenance_margin"][bars],
            "fee": np.where(charge, account_values["fee"][bars], 0.0),
            "funding": np.where(charge, account_values["funding"][bars], 0.0), "reason_code": "OK",
        }
        for field, value in values.items():
            trace.columns[field][rows] = value
        trace.event_counts["ACCOUNT_SNAPSHOT"] = len(rows)
