"""Additional estimator policy, not another QuantBT account/reporting contract."""

from dataclasses import asdict, dataclass
import math

import numpy as np

from quantbt.mode5.diagnostics.identity import digest as canonical_digest


@dataclass(frozen=True)
class MetricValue:
    metric_id: str
    unit: str
    sample_count: int
    value: float | None = None
    status: str = "VALID"
    reason: str | None = None
    components: tuple[tuple[str, float | int | str | None], ...] = ()

    def __post_init__(self):
        if not self.metric_id.startswith("mode5.") or not self.unit:
            raise ValueError("versioned research namespace and unit required")
        if type(self.sample_count) is not int or self.sample_count < 0:
            raise ValueError("observation count must be a nonnegative integer")
        if self.status not in {"VALID", "INSUFFICIENT", "UNDEFINED", "INVALID", "UNAVAILABLE",
                               "REPLAY_REQUIRED", "NO_LOSS", "BANKRUPT"}:
            raise ValueError("unknown metric disposition")
        if self.status == "VALID":
            if self.value is None or not math.isfinite(self.value) or self.reason is not None:
                raise ValueError("valid metrics require a finite value and no null reason")
        elif self.value is not None or not self.reason:
            raise ValueError("nonvalid metrics require null plus reason")
        object.__setattr__(self, "components", tuple(tuple(row) for row in self.components))
        for _, value in self.components:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("nonfinite diagnostic component")

    def to_metadata(self):
        return asdict(self)


@dataclass(frozen=True)
class StatisticsPolicy:
    version: str = "mode5.statistics.v1"
    annual_periods: float = 365.0
    variance_ddof: int = 1
    risk_free_per_period: float = 0.0
    moment_estimator: str = "central_population_v1"

    def __post_init__(self):
        if self.version != "mode5.statistics.v1" or self.moment_estimator != "central_population_v1":
            raise ValueError("unsupported statistics policy")
        if type(self.variance_ddof) is not int or self.variance_ddof not in (0, 1):
            raise ValueError("explicit ddof 0 or 1 required")
        if not math.isfinite(self.annual_periods) or self.annual_periods <= 0:
            raise ValueError("positive annual reporting frequency required")
        if not math.isfinite(self.risk_free_per_period):
            raise ValueError("finite per-period RF required")

    @property
    def identity(self):
        return canonical_digest(asdict(self))


def vector(values):
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError("one-dimensional metric population required")
    return np.ascontiguousarray(array)


def converted_return(value, *, source_unit):
    factors = {"decimal": 1., "percent": .01, "bps": .0001}
    if source_unit not in factors or not math.isfinite(value):
        raise ValueError("finite value and explicit return unit required")
    return value * factors[source_unit]


def annual_rf_to_period(value, annual_periods):
    if not math.isfinite(value) or value <= -1 or not math.isfinite(annual_periods) or annual_periods <= 0:
        raise ValueError("valid geometric annual RF/frequency required")
    return math.expm1(math.log1p(value) / annual_periods)
