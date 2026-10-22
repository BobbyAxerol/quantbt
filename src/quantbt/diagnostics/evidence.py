"""Shared immutable inputs and candidate/environment provenance."""

from dataclasses import asdict, dataclass
import math

import numpy as np

from .access import AccessWitness
from .identity import canonical, digest


class MissingInputs(ValueError):
    def __init__(self, missing):
        self.missing = tuple(missing)
        super().__init__("REPLAY_REQUIRED: missing retained inputs "+str(self.missing))


@dataclass(frozen=True)
class FrozenBuffer:
    name: str
    dtype: str
    shape: tuple[int, ...]
    data: bytes

    def __post_init__(self):
        dtype = np.dtype(self.dtype)
        if (not self.name or dtype.kind not in "biuf" or type(self.shape) is not tuple
                or any(type(n) is not int or n < 0 for n in self.shape)
                or not isinstance(self.data, bytes)
                or len(self.data) != math.prod(self.shape)*dtype.itemsize):
            raise ValueError("immutable typed numeric buffer required")

    @classmethod
    def from_array(cls, name, values):
        array = np.ascontiguousarray(values)
        if (not name or array.dtype.kind not in "biuf" or not np.isfinite(array).all()):
            raise ValueError("finite numeric retained inputs required")
        return cls(name, array.dtype.str, array.shape, array.tobytes())

    def array(self):
        return np.frombuffer(self.data, dtype=self.dtype).reshape(self.shape)


@dataclass(frozen=True)
class ExecutionEvidence:
    execution_id: str
    witness: AccessWitness
    buffers: tuple[FrozenBuffer, ...]
    status: str
    source_ref: str
    backend: str

    def __post_init__(self):
        if (not isinstance(self.witness, AccessWitness)
                or any(not isinstance(v, str) or not v for v in (self.execution_id, self.source_ref, self.backend))
                or self.status not in {"VALID", "VALID_NO_TRADE", "VALID_ADVERSE"}
                or type(self.buffers) is not tuple or not self.buffers
                or len({b.name for b in self.buffers}) != len(self.buffers)):
            raise ValueError("only complete valid economic evidence may be cached")
        for buffer in self.buffers:
            values = buffer.array()
            if not isinstance(buffer.data, bytes) or not np.isfinite(values).all():
                raise ValueError("immutable finite buffer required")

    @classmethod
    def from_arrays(cls, execution_id, witness, arrays, *, status="VALID", source_ref, backend):
        return cls(execution_id, witness, tuple(FrozenBuffer.from_array(k, v) for k, v in sorted(arrays.items())),
                   status, source_ref, backend)

    @property
    def size_bytes(self):
        return sum(len(b.data) for b in self.buffers) + len(canonical(dict(
            execution=self.execution_id, witness=asdict(self.witness), status=self.status,
            source_ref=self.source_ref, backend=self.backend,
            buffers=[(b.name, b.dtype, b.shape) for b in self.buffers])).encode())

    @property
    def content_id(self):
        from hashlib import sha256
        identity = sha256(canonical(dict(execution=self.execution_id, witness=asdict(self.witness),
            status=self.status, source_ref=self.source_ref, backend=self.backend,
            buffers=[(b.name, b.dtype, b.shape) for b in self.buffers])).encode())
        for b in self.buffers:
            identity.update(b.data)
        return identity.hexdigest()

    def arrays(self):
        return {b.name: b.array() for b in self.buffers}

    def require(self, plan):
        arrays = self.arrays()
        missing = sorted(set(plan.required_observation_kinds) - arrays.keys())
        if missing:
            raise MissingInputs(missing)
        if "timestamps" in arrays:
            times = arrays["timestamps"]
            if times.ndim != 1 or times.dtype.kind not in "iu" or not len(times) or np.any(np.diff(times) <= 0):
                raise ValueError("ordered nonempty exact timestamp path required")
            if times[0] < self.witness.start_ns or times[-1] >= self.witness.end_ns:
                raise ValueError("retained path outside manifest interval")
            for name in ("equity", "positions", "fees", "funding", "margin", "turnover"):
                if name in arrays and (arrays[name].ndim < 1 or len(arrays[name]) != len(times)):
                    raise ValueError("account path cardinality mismatch: "+name)
        if "equity" in arrays and arrays["equity"].ndim != 1:
            raise ValueError("equity must be one-dimensional")
        if "score" in arrays and arrays["score"].size != 1:
            raise ValueError("one scalar score required")
        fill_names = ("fill_time", "fill_qty", "fill_price", "fill_fee")
        if all(name in arrays for name in fill_names):
            if len({arrays[name].size for name in fill_names}) != 1:
                raise ValueError("fill column cardinality mismatch")
        return self


@dataclass(frozen=True)
class PanelRow:
    trial_id: str
    raw_params_id: str
    effective_params_id: str
    branch_id: str
    execution_id: str
    scenario_id: str
    environment_id: str
    witness: AccessWitness
    warmup_start_ns: int
    cutoff_ns: int
    metric_version: str
    support: int
    status: str
    value: float | None
    source_ref: str
    backend: str
    reason: str | None = None

    def __post_init__(self):
        if (any(not isinstance(getattr(self, k), str) or not getattr(self, k) for k in
                ("trial_id", "raw_params_id", "effective_params_id", "branch_id", "execution_id",
                 "scenario_id", "environment_id", "metric_version", "source_ref", "backend"))
                or self.status not in {"VALID", "VALID_NO_TRADE", "VALID_ADVERSE", "UNAVAILABLE", "INVALID_RUNTIME"}
                or type(self.support) is not int or self.support < 0
                or self.warmup_start_ns > self.witness.start_ns or self.cutoff_ns < self.witness.ready_ns):
            raise ValueError("invalid typed panel provenance/support")
        if self.status in {"UNAVAILABLE", "INVALID_RUNTIME"}:
            if self.value is not None or not self.reason:
                raise ValueError("invalid/missing evidence requires reason and cannot carry an economic sentinel")
        elif self.value is None or not math.isfinite(self.value):
            raise ValueError("valid measured value required")

    def record(self):
        return asdict(self)
