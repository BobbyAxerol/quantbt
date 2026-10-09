"""Frozen train-only transforms and decision-vintage labels over provider tapes."""

from dataclasses import asdict, dataclass
import threading

import numpy as np

from tools.mode5_diagnostics import AccessWitness
from tools.mode5_diagnostics.evidence import FrozenBuffer
from tools.mode5_diagnostics.identity import digest
from .manifests import calendar


@dataclass(frozen=True)
class FeatureTape:
    provider_id: str
    times: FrozenBuffer
    values: FrozenBuffer
    available: FrozenBuffer
    quality: FrozenBuffer

    @classmethod
    def from_arrays(cls, provider_id, times_ns, values, available_ns, quality):
        times = calendar(times_ns)
        raw = np.asarray(values, dtype=np.float64)
        available = np.asarray(available_ns)
        flags = np.asarray(quality)
        if (not provider_id or raw.shape != times.shape or available.shape != times.shape
                or available.dtype.kind not in "iu" or flags.shape != times.shape or flags.dtype.kind not in "iu"
                or not np.isin(flags, [0,1,2,3]).all() or np.any((flags == 0) & ~np.isfinite(raw))):
            raise ValueError("qualified feature/availability/quality tape required")
        if np.any(available > np.iinfo(np.int64).max) or np.any(available == np.iinfo(np.int64).min):
            raise ValueError("availability timestamp overflow or NaT sentinel")
        # 0=valid, 1=missing, 2=stale, 3=warmup. Masked values never become a normal state.
        raw = np.where(flags == 0, raw, 0.)
        return cls(provider_id, FrozenBuffer.from_array("times", times), FrozenBuffer.from_array("values", raw),
            FrozenBuffer.from_array("available", available.astype(np.int64)),
            FrozenBuffer.from_array("quality", flags.astype(np.int8)))

    def __post_init__(self):
        times = calendar(self.times.array())
        if (not self.provider_id or any(b.array().shape != times.shape for b in (self.values,self.available,self.quality))
                or self.available.array().dtype.kind not in "iu"
                or self.quality.array().dtype.kind not in "iu" or self.values.array().dtype.kind != "f"
                or not np.isin(self.quality.array(), [0,1,2,3]).all()
                or not np.isfinite(self.values.array()).all()):
            raise ValueError("invalid immutable feature tape")
        if (np.any(self.available.array() > np.iinfo(np.int64).max)
                or np.any(self.available.array() == np.iinfo(np.int64).min)):
            raise ValueError("availability timestamp overflow or NaT sentinel")


@dataclass(frozen=True)
class PartitionSnapshot:
    provider_id: str
    namespace: str
    fit_witness: AccessWitness
    train_content_id: str
    mean: float
    scale: float
    thresholds: tuple[float, ...]
    quantiles: tuple[float, ...]
    count: int
    version: str = "train_zscore_quantile_v1"

    def __post_init__(self):
        if (not self.provider_id or not self.namespace or not self.train_content_id
                or not isinstance(self.fit_witness, AccessWitness) or self.version != "train_zscore_quantile_v1"
                or type(self.count) is not int or self.count < 2 or not np.isfinite([self.mean,self.scale,*self.thresholds]).all()
                or self.scale <= 0 or type(self.thresholds) is not tuple or type(self.quantiles) is not tuple
                or not self.quantiles or len(self.thresholds) != len(self.quantiles)
                or any(not 0 < q < 1 for q in self.quantiles)
                or any(a >= b for a,b in zip(self.quantiles,self.quantiles[1:]))
                or any(a >= b for a,b in zip(self.thresholds,self.thresholds[1:]))):
            raise ValueError("qualified frozen transform required; constant support is not rescued")

    @property
    def identity(self):
        return digest(asdict(self))

    def label(self, tape, *, purpose):
        if tape.provider_id != self.provider_id or purpose not in {"decision_vintage", "asof_calibration_descriptive"}:
            raise ValueError("provider/purpose identity mismatch")
        times, values, avail, quality = (b.array() for b in (tape.times,tape.values,tape.available,tape.quality))
        valid = (quality == 0) & (avail <= times)
        if purpose == "decision_vintage":
            valid &= times >= self.fit_witness.ready_ns
        else:
            # Historical labels can depend on current calibration, never claim pseudo-live rights.
            valid &= times < self.fit_witness.end_ns
        labels = np.full(len(times), -1, dtype=np.int16)
        labels[valid] = np.searchsorted(self.thresholds, (values[valid]-self.mean)/self.scale, side="right")
        return LabelTape(self.identity, self.namespace, purpose, self.fit_witness.ready_ns,
            tape.times, FrozenBuffer.from_array("labels", labels), FrozenBuffer.from_array("valid", valid))


def fit_partition(tape, witness, policy, *, namespace, quantiles=(.25,.75), min_observations=8):
    policy.require(witness)
    if policy.purpose != "diagnostic":
        raise PermissionError("transform fitting requires train diagnostic scope, not validation/selection rights")
    times, values, avail, quality = (b.array() for b in (tape.times,tape.values,tape.available,tape.quality))
    mask = (times >= witness.start_ns) & (times < witness.end_ns)
    valid = mask & (quality == 0) & (avail <= policy.cutoff_ns)
    if (type(quantiles) is not tuple or not quantiles or any(not 0 < q < 1 for q in quantiles)
            or any(a >= b for a,b in zip(quantiles,quantiles[1:])) or type(min_observations) is not int
            or min_observations < 2 or int(valid.sum()) < min_observations):
        raise ValueError("INSUFFICIENT_FEATURE_SUPPORT or invalid preregistered quantiles")
    mean, scale = float(values[valid].mean()), float(values[valid].std(ddof=0))
    if scale <= 0:
        raise ValueError("constant train support; no artificial normal-state thresholds")
    thresholds = tuple(float(v) for v in np.quantile((values[valid]-mean)/scale, quantiles, method="linear"))
    content = digest(dict(times=times[mask].tolist(), values=np.where(valid,values,0.)[mask].tolist(),
        available=np.where(valid,avail,0)[mask].tolist(), quality=quality[mask].tolist(), valid=valid[mask].tolist(),
        cutoff=policy.cutoff_ns, min_observations=min_observations))
    return PartitionSnapshot(tape.provider_id, namespace, witness, content, mean, scale,
                             thresholds, quantiles, int(valid.sum()))


@dataclass(frozen=True)
class LabelTape:
    transform_id: str
    namespace: str
    purpose: str
    vintage_ns: int
    times: FrozenBuffer
    labels: FrozenBuffer
    valid: FrozenBuffer

    def __post_init__(self):
        times = calendar(self.times.array())
        if (not self.transform_id or not self.namespace or self.purpose not in
                {"decision_vintage", "asof_calibration_descriptive"} or type(self.vintage_ns) is not int
                or self.labels.array().shape != times.shape or self.valid.array().shape != times.shape
                or self.labels.array().dtype.kind not in "iu" or self.valid.array().dtype.kind != "b"
                or np.any(self.labels.array() < -1) or np.any(self.valid.array() & (self.labels.array() < 0))
                or np.any(~self.valid.array() & (self.labels.array() != -1))):
            raise ValueError("invalid immutable label vintage")

    def prefix_identity(self, cutoff_ns):
        mask = self.times.array() <= cutoff_ns
        return digest(dict(transform=self.transform_id, namespace=self.namespace, purpose=self.purpose,
            vintage=self.vintage_ns, times=self.times.array()[mask].tolist(),
            labels=self.labels.array()[mask].tolist(), valid=self.valid.array()[mask].tolist()))

    @property
    def identity(self):
        return self.prefix_identity(int(self.times.array()[-1]))

    def decision_labels(self):
        if self.purpose != "decision_vintage":
            raise PermissionError("retrospective descriptive labels do not authorize historical decisions")
        return self.labels.array()


class VintageStore:
    """Namespaces may coexist; historical decisions cannot be overwritten."""

    def __init__(self):
        self._labels = {}
        self._lock = threading.RLock()

    def seal(self, labels):
        if not isinstance(labels, LabelTape):
            raise TypeError("typed label tape required")
        key = (labels.namespace, labels.purpose, labels.vintage_ns)
        with self._lock:
            old = self._labels.get(key)
            if old is not None and old.identity != labels.identity:
                raise ValueError("vintage already sealed; register new namespace/revision")
            self._labels[key] = labels
        return labels.identity

    def records(self):
        with self._lock:
            return tuple(dict(namespace=k[0], purpose=k[1], vintage_ns=k[2], identity=v.identity)
                         for k,v in sorted(self._labels.items()))
