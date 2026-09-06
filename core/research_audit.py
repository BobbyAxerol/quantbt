"""Versioned, columnar research-audit artifacts for public WFO runs.

This module is intentionally outside the economic execution hot path.  It
turns already-authoritative trial, fold, selection, and deployment records into
immutable typed chunks after a WFO decision is made.  It never reruns a
strategy, reconstructs a missing audit as if it were original, or changes the
optimizer's interaction order.

The physical representation is a small NumPy structure-of-arrays store with a
versioned value codec.  It avoids one Python dict/JSON object per retained row
while retaining the exact logical values needed for research review and legacy
DataFrame export on the cold path.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import base64
from importlib.metadata import PackageNotFoundError, version as distribution_version
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


RESEARCH_AUDIT_SCHEMA_V1 = "quantbt-research-audit-v1"
RESEARCH_AUDIT_CODEC_V1 = "quantbt-research-columnar-codec-v1"
RESEARCH_AUDIT_DIGEST_V1 = "sha256-canonical-logical-v1"

FINANCIAL_RETENTION_LEVELS_V1 = frozenset({"score", "compact", "audit"})
RESEARCH_RETENTION_LEVELS_V1 = frozenset({"full_trial_ledger", "selected_only", "none"})
FINANCIAL_RETENTION_SCOPES_V1 = frozenset({"selected_final_execution", "segmented_reset_flat_execution"})


class ResearchAuditError(RuntimeError):
    """A requested research-audit contract could not be fulfilled."""


class ResearchAuditBudgetError(ResearchAuditError):
    """The declared bounded-retention budget was exhausted."""


class ResearchAuditWriteError(ResearchAuditError):
    """A requested audit export failed before completion."""


class ResearchAuditSchemaError(ResearchAuditError):
    """A logical record cannot be represented by the versioned codec."""


def _freeze_array(values: np.ndarray) -> np.ndarray:
    array = np.ascontiguousarray(values).copy()
    array.setflags(write=False)
    return array


def _canonical_value(value: Any) -> Any:
    """Encode supported values without using an arbitrary ``repr`` fallback."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Enum):
        return {
            "@quantbt": "enum",
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_value(value.value),
        }
    if isinstance(value, np.generic):
        return _canonical_value(value.item())
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return {"@quantbt": "int", "value": str(int(value))}
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            encoded = "nan"
        elif math.isinf(number):
            encoded = "inf" if number > 0.0 else "-inf"
        else:
            encoded = number.hex()
        return {"@quantbt": "float", "value": encoded}
    if isinstance(value, pd.Timestamp):
        timestamp = pd.Timestamp(value)
        timezone = None if timestamp.tz is None else str(timestamp.tz)
        return {
            "@quantbt": "timestamp",
            "nanoseconds": str(int(timestamp.value)),
            "timezone": timezone,
        }
    if isinstance(value, pd.Timedelta):
        return {"@quantbt": "timedelta", "nanoseconds": str(int(value.value))}
    if isinstance(value, range):
        return {
            "@quantbt": "range",
            "start": int(value.start),
            "stop": int(value.stop),
            "step": int(value.step),
        }
    if isinstance(value, bytes):
        return {"@quantbt": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise ResearchAuditSchemaError("object ndarray values are not supported by the research audit codec")
        return {
            "@quantbt": "ndarray",
            "dtype": str(value.dtype),
            "shape": [int(item) for item in value.shape],
            "base64": base64.b64encode(np.ascontiguousarray(value).tobytes()).decode("ascii"),
        }
    if isinstance(value, tuple):
        return {"@quantbt": "tuple", "items": [_canonical_value(item) for item in value]}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Mapping):
        items: list[list[Any]] = []
        for key in sorted(value):
            item = value[key]
            if not isinstance(key, str):
                raise ResearchAuditSchemaError("research-audit mapping keys must be strings")
            items.append([key, _canonical_value(item)])
        return {"@quantbt": "mapping", "items": items}
    raise ResearchAuditSchemaError(
        f"unsupported research-audit value type {type(value).__module__}.{type(value).__qualname__}; "
        "declare a primitive/category value or an explicit serializable adapter"
    )


def _restore_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_restore_value(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    marker = value.get("@quantbt")
    if marker is None:
        return {str(key): _restore_value(item) for key, item in value.items()}
    if marker == "int":
        return int(str(value["value"]))
    if marker == "enum":
        # A logical audit round-trip preserves the declared enum type and
        # value without importing arbitrary user modules during inspection.
        return {
            "enum_type": str(value["type"]),
            "value": _restore_value(value["value"]),
        }
    if marker == "float":
        raw = str(value["value"])
        if raw == "nan":
            return float("nan")
        if raw == "inf":
            return float("inf")
        if raw == "-inf":
            return float("-inf")
        return float.fromhex(raw)
    if marker == "timestamp":
        result = pd.Timestamp(int(str(value["nanoseconds"])), unit="ns", tz="UTC")
        timezone = value.get("timezone")
        return result if timezone in {None, "UTC"} else result.tz_convert(str(timezone))
    if marker == "timedelta":
        return pd.Timedelta(int(str(value["nanoseconds"])), unit="ns")
    if marker == "range":
        return range(int(value["start"]), int(value["stop"]), int(value["step"]))
    if marker == "bytes":
        return base64.b64decode(str(value["base64"]).encode("ascii"))
    if marker == "ndarray":
        dtype = np.dtype(str(value["dtype"]))
        shape = tuple(int(item) for item in value["shape"])
        payload = base64.b64decode(str(value["base64"]).encode("ascii"))
        return np.frombuffer(payload, dtype=dtype).copy().reshape(shape)
    if marker == "tuple":
        return tuple(_restore_value(item) for item in value["items"])
    if marker == "mapping":
        return {str(key): _restore_value(item) for key, item in value["items"]}
    raise ResearchAuditSchemaError(f"unknown research-audit codec marker: {marker!r}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _logical_digest(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchRetentionPlanV1:
    """Independent financial and research-retention contract for one WFO run."""

    financial_retention: str = "score"
    # ``none`` is intentionally the compatibility default. Existing WFO
    # result tables remain untouched; a columnar sidecar is opt-in so legacy
    # callers do not gain a new retained-memory cost merely by upgrading.
    research_retention: str = "none"
    financial_scope: str = "selected_final_execution"
    chunk_rows: int = 256
    max_retained_chunks: int = 4_096
    max_materialized_frames: int = 3

    def __post_init__(self) -> None:
        financial = str(self.financial_retention).lower().strip()
        research = str(self.research_retention).lower().strip()
        scope = str(self.financial_scope).lower().strip()
        if financial not in FINANCIAL_RETENTION_LEVELS_V1:
            raise ValueError(
                "financial_retention must be one of: " + ", ".join(sorted(FINANCIAL_RETENTION_LEVELS_V1))
            )
        if research not in RESEARCH_RETENTION_LEVELS_V1:
            raise ValueError(
                "research_retention must be one of: " + ", ".join(sorted(RESEARCH_RETENTION_LEVELS_V1))
            )
        if scope not in FINANCIAL_RETENTION_SCOPES_V1:
            raise ValueError(
                "financial_retention_scope must be one of: "
                + ", ".join(sorted(FINANCIAL_RETENTION_SCOPES_V1))
                + "; all-candidate fill retention is not silently approximated"
            )
        if int(self.chunk_rows) <= 0:
            raise ValueError("research_audit_chunk_rows must be > 0")
        if int(self.max_retained_chunks) <= 0:
            raise ValueError("research_audit_max_chunks must be > 0")
        if int(self.max_materialized_frames) <= 0:
            raise ValueError("research_audit_max_materialized_frames must be > 0")
        object.__setattr__(self, "financial_retention", financial)
        object.__setattr__(self, "research_retention", research)
        object.__setattr__(self, "financial_scope", scope)
        object.__setattr__(self, "chunk_rows", int(self.chunk_rows))
        object.__setattr__(self, "max_retained_chunks", int(self.max_retained_chunks))
        object.__setattr__(self, "max_materialized_frames", int(self.max_materialized_frames))

    @classmethod
    def from_config(cls, config: Any) -> "ResearchRetentionPlanV1":
        metadata = dict(getattr(config, "metadata", {}) or {})
        return cls(
            financial_retention=metadata.get("financial_retention", "score"),
            research_retention=metadata.get("research_retention", "none"),
            financial_scope=metadata.get("financial_retention_scope", "selected_final_execution"),
            chunk_rows=metadata.get("research_audit_chunk_rows", 256),
            max_retained_chunks=metadata.get("research_audit_max_chunks", 4_096),
            max_materialized_frames=metadata.get("research_audit_max_materialized_frames", 3),
        )

    def metadata(self) -> dict[str, object]:
        return {
            "schema": RESEARCH_AUDIT_SCHEMA_V1,
            "financial_retention": self.financial_retention,
            "research_retention": self.research_retention,
            "financial_scope": self.financial_scope,
            "chunk_rows": int(self.chunk_rows),
            "max_retained_chunks": int(self.max_retained_chunks),
            "max_materialized_frames": int(self.max_materialized_frames),
        }


@dataclass(frozen=True, slots=True)
class EncodedValueColumnV1:
    """Immutable offset/data byte column for non-primitive logical values."""

    offsets: np.ndarray
    data: np.ndarray

    def __post_init__(self) -> None:
        offsets = np.asarray(self.offsets, dtype=np.uint64)
        data = np.asarray(self.data, dtype=np.uint8)
        if offsets.ndim != 1 or data.ndim != 1 or len(offsets) == 0:
            raise ResearchAuditSchemaError("encoded value columns require non-empty one-dimensional offsets/data")
        if int(offsets[0]) != 0 or int(offsets[-1]) != len(data):
            raise ResearchAuditSchemaError("encoded value column offsets do not span its byte payload")
        if np.any(offsets[1:] < offsets[:-1]):
            raise ResearchAuditSchemaError("encoded value column offsets must be monotonic")
        object.__setattr__(self, "offsets", _freeze_array(offsets))
        object.__setattr__(self, "data", _freeze_array(data))

    @classmethod
    def from_values(cls, values: Sequence[Any]) -> "EncodedValueColumnV1":
        payloads = [_canonical_bytes(value) for value in values]
        offsets = np.zeros(len(payloads) + 1, dtype=np.uint64)
        for index, payload in enumerate(payloads, start=1):
            offsets[index] = offsets[index - 1] + len(payload)
        joined = b"".join(payloads)
        data = np.frombuffer(joined, dtype=np.uint8).copy()
        return cls(offsets=offsets, data=data)

    def __len__(self) -> int:
        return len(self.offsets) - 1

    def value_at(self, index: int) -> Any:
        if not 0 <= int(index) < len(self):
            raise IndexError(index)
        start = int(self.offsets[index])
        stop = int(self.offsets[index + 1])
        try:
            payload = json.loads(bytes(self.data[start:stop]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchAuditSchemaError("encoded research-audit payload is invalid") from exc
        return _restore_value(payload)

    def values(self) -> list[Any]:
        return [self.value_at(index) for index in range(len(self))]

    def metadata(self) -> dict[str, object]:
        return {
            "codec": RESEARCH_AUDIT_CODEC_V1,
            "row_count": len(self),
            "payload_bytes": int(self.data.nbytes),
            "offset_dtype": str(self.offsets.dtype),
        }


@dataclass(frozen=True, slots=True)
class ColumnarResearchTableV1:
    """One immutable typed SoA research chunk with optional dictionary columns."""

    table_name: str
    chunk_id: str
    primitive_columns: Mapping[str, np.ndarray]
    dictionary_columns: Mapping[str, tuple[np.ndarray, tuple[str, ...]]]
    encoded_columns: Mapping[str, EncodedValueColumnV1]
    row_count: int
    logical_digest: str

    def __post_init__(self) -> None:
        if not str(self.table_name).strip() or not str(self.chunk_id).strip():
            raise ResearchAuditSchemaError("research table and chunk identifiers must be non-empty")
        if int(self.row_count) < 0:
            raise ResearchAuditSchemaError("research table row_count must be >= 0")
        primitive: dict[str, np.ndarray] = {}
        for name, values in self.primitive_columns.items():
            array = np.asarray(values)
            if array.ndim != 1 or len(array) != int(self.row_count):
                raise ResearchAuditSchemaError(f"primitive column {name!r} has an invalid shape")
            if array.dtype.hasobject:
                raise ResearchAuditSchemaError(f"primitive column {name!r} must not have object dtype")
            primitive[str(name)] = _freeze_array(array)
        dictionaries: dict[str, tuple[np.ndarray, tuple[str, ...]]] = {}
        for name, value in self.dictionary_columns.items():
            codes, dictionary = value
            code_array = np.asarray(codes, dtype=np.int32)
            labels = tuple(str(item) for item in dictionary)
            if code_array.ndim != 1 or len(code_array) != int(self.row_count):
                raise ResearchAuditSchemaError(f"dictionary column {name!r} has an invalid shape")
            if not labels or len(set(labels)) != len(labels):
                raise ResearchAuditSchemaError(f"dictionary column {name!r} has an invalid dictionary")
            if np.any(code_array < 0) or np.any(code_array >= len(labels)):
                raise ResearchAuditSchemaError(f"dictionary column {name!r} has an out-of-range code")
            dictionaries[str(name)] = (_freeze_array(code_array), labels)
        encoded: dict[str, EncodedValueColumnV1] = {}
        for name, column in self.encoded_columns.items():
            if len(column) != int(self.row_count):
                raise ResearchAuditSchemaError(f"encoded column {name!r} has an invalid row count")
            encoded[str(name)] = column
        names = set(primitive) | set(dictionaries) | set(encoded)
        if len(names) != len(primitive) + len(dictionaries) + len(encoded):
            raise ResearchAuditSchemaError("research table column names must be unique across physical encodings")
        object.__setattr__(self, "primitive_columns", MappingProxyType(primitive))
        object.__setattr__(self, "dictionary_columns", MappingProxyType(dictionaries))
        object.__setattr__(self, "encoded_columns", MappingProxyType(encoded))

    @classmethod
    def from_records(
        cls,
        *,
        table_name: str,
        chunk_id: str,
        records: Sequence[Mapping[str, Any]],
    ) -> "ColumnarResearchTableV1":
        copied = [dict(record) for record in records]
        if not copied:
            return cls(
                table_name=table_name,
                chunk_id=chunk_id,
                primitive_columns={},
                dictionary_columns={},
                encoded_columns={},
                row_count=0,
                logical_digest=_logical_digest({"table_name": table_name, "records": []}),
            )
        names: list[str] = []
        seen: set[str] = set()
        for record in copied:
            for name in record:
                key = str(name)
                if key not in seen:
                    seen.add(key)
                    names.append(key)
        values_by_name = {name: [record.get(name) for record in copied] for name in names}
        primitive: dict[str, np.ndarray] = {}
        dictionaries: dict[str, tuple[np.ndarray, tuple[str, ...]]] = {}
        encoded: dict[str, EncodedValueColumnV1] = {}
        for name, values in values_by_name.items():
            if values and all(isinstance(value, bool) for value in values):
                primitive[name] = np.asarray(values, dtype=np.bool_)
            elif values and all(
                isinstance(value, (int, np.integer)) and not isinstance(value, bool) for value in values
            ):
                primitive[name] = np.asarray(values, dtype=np.int64)
            elif values and all(isinstance(value, (float, np.floating)) for value in values):
                primitive[name] = np.asarray(values, dtype=np.float64)
            elif values and all(isinstance(value, str) for value in values):
                dictionary: list[str] = []
                index_by_value: dict[str, int] = {}
                codes = np.empty(len(values), dtype=np.int32)
                for index, value in enumerate(values):
                    code = index_by_value.get(value)
                    if code is None:
                        code = len(dictionary)
                        dictionary.append(value)
                        index_by_value[value] = code
                    codes[index] = code
                dictionaries[name] = (codes, tuple(dictionary))
            else:
                encoded[name] = EncodedValueColumnV1.from_values(values)
        logical = _logical_digest(
            {"table_name": str(table_name), "records": [{name: record.get(name) for name in names} for record in copied]}
        )
        return cls(
            table_name=table_name,
            chunk_id=chunk_id,
            primitive_columns=primitive,
            dictionary_columns=dictionaries,
            encoded_columns=encoded,
            row_count=len(copied),
            logical_digest=logical,
        )

    @property
    def physical_bytes(self) -> int:
        return int(
            sum(array.nbytes for array in self.primitive_columns.values())
            + sum(codes.nbytes + sum(len(label.encode("utf-8")) for label in labels) for codes, labels in self.dictionary_columns.values())
            + sum(column.offsets.nbytes + column.data.nbytes for column in self.encoded_columns.values())
        )

    def to_records(self) -> list[dict[str, Any]]:
        rows = [dict() for _ in range(int(self.row_count))]
        for name, values in self.primitive_columns.items():
            for index, value in enumerate(values):
                rows[index][name] = value.item() if isinstance(value, np.generic) else value
        for name, (codes, dictionary) in self.dictionary_columns.items():
            for index, code in enumerate(codes):
                rows[index][name] = dictionary[int(code)]
        for name, column in self.encoded_columns.items():
            for index, value in enumerate(column.values()):
                rows[index][name] = value
        return rows

    def to_pandas(self) -> pd.DataFrame:
        return pd.DataFrame(self.to_records())

    def metadata(self) -> dict[str, object]:
        return {
            "schema": RESEARCH_AUDIT_SCHEMA_V1,
            "table_name": self.table_name,
            "chunk_id": self.chunk_id,
            "row_count": int(self.row_count),
            "logical_digest": self.logical_digest,
            "physical_bytes": self.physical_bytes,
            "primitive_columns": {name: str(values.dtype) for name, values in self.primitive_columns.items()},
            "dictionary_columns": {
                name: {"code_dtype": str(codes.dtype), "dictionary": list(labels)}
                for name, (codes, labels) in self.dictionary_columns.items()
            },
            "encoded_columns": {name: column.metadata() for name, column in self.encoded_columns.items()},
        }


AuditExportHookV1 = Callable[[str, str, ColumnarResearchTableV1], None]


class ResearchAuditWriterV1:
    """Bounded, synchronous, idempotent owner for immutable audit chunks.

    The public WFO path currently has no separate writer thread.  A synchronous
    bounded sink is deliberate: it avoids a new worker pool and gives a clear
    budget failure instead of silently dropping trial records.  A caller may
    attach an export hook, but that only promises a process-completion callback;
    it does not claim crash durability or an fsync contract.
    """

    def __init__(
        self,
        *,
        plan: ResearchRetentionPlanV1,
        export_hook: AuditExportHookV1 | None = None,
    ) -> None:
        self.plan = plan
        self._export_hook = export_hook
        self._tables: dict[str, list[ColumnarResearchTableV1]] = {}
        self._committed: dict[str, str] = {}
        self._state = "collecting"
        self._failure: str | None = None
        self._committed_chunks = 0
        self._idempotent_retries = 0
        self._exported_chunks = 0
        self._missing_range: dict[str, object] | None = None
        self._cancel_reason: str | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def tables(self) -> Mapping[str, tuple[ColumnarResearchTableV1, ...]]:
        return MappingProxyType({name: tuple(chunks) for name, chunks in self._tables.items()})

    def append_records(self, table_name: str, records: Sequence[Mapping[str, Any]]) -> None:
        if self._state != "collecting":
            raise ResearchAuditWriteError(f"cannot append research audit after state={self._state!r}")
        rows = list(records)
        if not rows:
            return
        for start in range(0, len(rows), self.plan.chunk_rows):
            chunk_rows = rows[start : start + self.plan.chunk_rows]
            ordinal = len(self._tables.get(table_name, ()))
            chunk = ColumnarResearchTableV1.from_records(
                table_name=table_name,
                chunk_id=f"{table_name}:{ordinal:08d}",
                records=chunk_rows,
            )
            self.append_chunk(chunk)

    def append_chunk(self, chunk: ColumnarResearchTableV1) -> None:
        if self._state != "collecting":
            raise ResearchAuditWriteError(f"cannot append research audit after state={self._state!r}")
        prior = self._committed.get(chunk.chunk_id)
        if prior is not None:
            if prior != chunk.logical_digest:
                self._fail(f"conflicting_duplicate_chunk:{chunk.chunk_id}")
                raise ResearchAuditWriteError(f"conflicting duplicate research-audit chunk {chunk.chunk_id!r}")
            self._idempotent_retries += 1
            return
        if self._committed_chunks >= self.plan.max_retained_chunks:
            self._fail("retained_chunk_budget_exceeded")
            raise ResearchAuditBudgetError(
                f"research audit exceeded max_retained_chunks={self.plan.max_retained_chunks}; "
                "increase the budget or request selected_only/none explicitly"
            )
        if self._export_hook is not None:
            try:
                self._export_hook(chunk.table_name, chunk.chunk_id, chunk)
            except Exception as exc:  # noqa: BLE001 - an audit sink failure is public state.
                self._fail(f"export_hook_failed:{type(exc).__name__}")
                raise ResearchAuditWriteError(
                    f"research audit export failed for chunk {chunk.chunk_id!r}: {exc}"
                ) from exc
            self._exported_chunks += 1
        self._tables.setdefault(chunk.table_name, []).append(chunk)
        self._committed[chunk.chunk_id] = chunk.logical_digest
        self._committed_chunks += 1

    def cancel(self, *, missing_range: Mapping[str, object], reason: str) -> None:
        if self._state != "collecting":
            return
        self._state = "canceled"
        self._missing_range = dict(missing_range)
        self._cancel_reason = str(reason)

    def close(self) -> None:
        if self._state == "collecting":
            self._state = "memory_complete"

    def _fail(self, reason: str) -> None:
        self._state = "failed"
        self._failure = str(reason)

    def metadata(self) -> dict[str, object]:
        table_rows = {name: int(sum(chunk.row_count for chunk in chunks)) for name, chunks in self._tables.items()}
        table_bytes = {name: int(sum(chunk.physical_bytes for chunk in chunks)) for name, chunks in self._tables.items()}
        return {
            "schema": RESEARCH_AUDIT_SCHEMA_V1,
            "writer_state": self._state,
            "failure": self._failure,
            "memory_result_complete": self._state == "memory_complete",
            "process_completion_flush": (
                "not_requested" if self._export_hook is None else self._state == "memory_complete"
            ),
            "crash_durable": "not_provided",
            "bounded_sink": "synchronous_owned_chunks_v1",
            "queue_mode": "synchronous_backpressure_v1",
            "queue_capacity_chunks": 1,
            "queue_high_watermark_chunks": 1 if self._committed_chunks else 0,
            "ownership": "immutable_chunk_transferred_before_source_release",
            "committed_chunks": int(self._committed_chunks),
            "idempotent_chunk_retries": int(self._idempotent_retries),
            "exported_chunks": int(self._exported_chunks),
            "table_rows": table_rows,
            "table_physical_bytes": table_bytes,
            "total_physical_bytes": int(sum(table_bytes.values())),
            "missing_range": None if self._missing_range is None else dict(self._missing_range),
            "cancel_reason": self._cancel_reason,
        }


def _freeze_manifest_value(value: Any) -> Any:
    """Recursively freeze immutable audit manifests after their digest is set."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_manifest_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_manifest_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_manifest_value(item) for item in value)
    if isinstance(value, np.ndarray):
        return _freeze_array(value)
    return value


def _logical_record_mapping(value: Any, *, label: str) -> dict[str, Any]:
    """Extract one original record without falling back to an arbitrary repr."""

    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if is_dataclass(value):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    as_dict = getattr(value, "to_dict", None)
    if callable(as_dict):
        mapped = as_dict()
        if isinstance(mapped, Mapping):
            return {str(key): item for key, item in mapped.items()}
    named_tuple = getattr(value, "_asdict", None)
    if callable(named_tuple):
        mapped = named_tuple()
        if isinstance(mapped, Mapping):
            return {str(key): item for key, item in mapped.items()}
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        return {str(key): item for key, item in attributes.items()}
    raise ResearchAuditSchemaError(
        f"cannot retain original {label} record of type "
        f"{type(value).__module__}.{type(value).__qualname__}; provide a mapping or dataclass adapter"
    )


def _series_value_at(series: Any, timestamp: Any, ordinal: int) -> Any:
    if not isinstance(series, pd.Series):
        return None
    if len(series) == 0:
        return None
    if timestamp in series.index:
        return series.loc[timestamp]
    if 0 <= ordinal < len(series):
        return series.iloc[ordinal]
    return None


def _timestamp_or_none(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value) if isinstance(value, (pd.Timestamp, np.datetime64)) else value


def _sequence_length(value: Any) -> int | None:
    """Return a truthful record count without treating a scalar as a sequence."""

    if value is None:
        return None
    try:
        return int(len(value))
    except TypeError:
        return None


def _has_nonzero_numeric_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (pd.Series, pd.DataFrame)):
        values = value.to_numpy(dtype=np.float64, copy=False)
    else:
        try:
            values = np.asarray(value, dtype=np.float64)
        except (TypeError, ValueError):
            return False
    return bool(values.size and np.any(np.isfinite(values) & (np.abs(values) > 0.0)))


def _original_fill_audit_source(result: Any, metadata: Mapping[str, Any]) -> tuple[Any, bool]:
    """Return original fills and whether an empty sequence is economically valid.

    A generic target/vectorized result can expose an empty ``fills`` attribute
    while still carrying position changes or costs.  That is not a fill audit.
    An empty fill sequence is accepted only for a provably inactive result.
    """

    source = getattr(result, "fills", None)
    if source is None:
        source = metadata.get("fills_report")
    count = _sequence_length(source)
    if count is None:
        return source, False
    if count > 0:
        return source, True
    has_activity = any(
        _has_nonzero_numeric_value(value)
        for value in (
            getattr(result, "fees", None),
            getattr(result, "funding", None),
            getattr(result, "positions", None),
        )
    )
    return source, not has_activity


# Artifact construction is intentionally a cold-path module.  Import it only
# after the codec, immutable value helpers, and bounded writer are defined so
# the public compatibility surface remains `quantbt.core.research_audit`.
from .research_audit_artifact import ResearchAuditArtifactV1, build_walkforward_research_audit


__all__ = [
    "ColumnarResearchTableV1",
    "EncodedValueColumnV1",
    "FINANCIAL_RETENTION_SCOPES_V1",
    "FINANCIAL_RETENTION_LEVELS_V1",
    "RESEARCH_AUDIT_CODEC_V1",
    "RESEARCH_AUDIT_DIGEST_V1",
    "RESEARCH_AUDIT_SCHEMA_V1",
    "RESEARCH_RETENTION_LEVELS_V1",
    "ResearchAuditArtifactV1",
    "ResearchAuditBudgetError",
    "ResearchAuditError",
    "ResearchAuditSchemaError",
    "ResearchAuditWriteError",
    "ResearchAuditWriterV1",
    "ResearchRetentionPlanV1",
    "build_walkforward_research_audit",
]
