"""Same-series central moments and original-frequency classical PSR."""

from dataclasses import asdict, dataclass
from functools import lru_cache
import math

import numpy as np

from .contracts import MetricValue, StatisticsPolicy, vector


def _moment_scan(values):
    count, mean, m2, m3, m4 = 0, 0., 0., 0., 0.
    # One-pass central-moment recurrence avoids raw-power cancellation.
    for value in values:
        previous = count
        count += 1
        delta = value - mean
        step = delta / count
        step2 = step * step
        term = delta * step * previous
        m4 += term * step2 * (count * count - 3 * count + 3) + 6 * step2 * m2 - 4 * step * m3
        m3 += term * step * (count - 2) - 3 * step * m2
        m2 += term
        mean += step
    return mean, m2, m3, m4


@lru_cache(maxsize=1)
def compiled_moments():
    from numba import njit
    return njit(cache=False, fastmath=False)(_moment_scan)


@dataclass(frozen=True)
class MomentEstimate:
    n: int
    mean: float | None = None
    variance: float | None = None
    sharpe_period: float | None = None
    skew: float | None = None
    kurtosis_ordinary: float | None = None
    status: str = "VALID"
    reason: str | None = None
    sr_frequency: str = "period"
    population: str = "daily_account_returns"
    variance_ddof: int = 1
    estimator: str = "central_population_v1"

    def to_metadata(self):
        return asdict(self)


def moments(values, *, policy=StatisticsPolicy(), backend="numba", population="daily_account_returns"):
    values = vector(values)
    n = len(values)
    extra = dict(population=population, variance_ddof=policy.variance_ddof)
    if backend not in {"python", "numba"}:
        raise NotImplementedError("only explicit Python/Numba research moments supported")
    if not np.isfinite(values).all():
        return MomentEstimate(n, status="INVALID", reason="nonfinite observation; no row dropping", **extra)
    if n < 3:
        return MomentEstimate(n, status="INSUFFICIENT", reason="at least three same-series observations required", **extra)
    with np.errstate(over="ignore", invalid="ignore"):
        excess = values - policy.risk_free_per_period
    if not np.isfinite(excess).all():
        return MomentEstimate(n, status="INVALID", reason="excess-return numeric overflow", **extra)
    scale = float(np.max(np.abs(excess)))
    if scale == 0:
        return MomentEstimate(n, status="UNDEFINED", reason="zero return variance", **extra)
    kernel = _moment_scan if backend == "python" else compiled_moments()
    with np.errstate(over="ignore", invalid="ignore"):
        mean, m2, m3, m4 = kernel(excess / scale)
    if not all(math.isfinite(x) for x in (mean, m2, m3, m4)):
        return MomentEstimate(n, status="INVALID", reason="central-moment numeric overflow", **extra)
    if m2 <= 0:
        return MomentEstimate(n, status="UNDEFINED", reason="zero return variance", **extra)
    variance_scaled = m2 / (n - policy.variance_ddof)
    variance = (variance_scaled * scale) * scale
    pop_variance = m2 / n
    skew = (m3 / n) / pop_variance**1.5
    kurtosis = (m4 / n) / pop_variance**2
    sr = mean / math.sqrt(variance_scaled)
    mean *= scale
    if variance <= 0 or not all(math.isfinite(x) for x in (mean, variance, skew, kurtosis, sr)):
        return MomentEstimate(n, status="INVALID", reason="standardized-moment numeric overflow", **extra)
    return MomentEstimate(n, mean, variance, sr, skew, kurtosis, **extra)


def sharpe_to_period(value, *, source_frequency, annual_periods):
    if source_frequency not in {"period", "annual"} or not math.isfinite(value):
        raise ValueError("finite SR with explicit source frequency required")
    if not math.isfinite(annual_periods) or annual_periods <= 0:
        raise ValueError("positive annual frequency required")
    return value / math.sqrt(annual_periods) if source_frequency == "annual" else value


def ordinary_kurtosis(value, *, convention):
    if convention not in {"ordinary", "excess"} or not math.isfinite(value):
        raise ValueError("explicit finite kurtosis convention required")
    return value + 3 if convention == "excess" else value


def classical_psr(estimate, *, reference_period=0.0):
    if not isinstance(estimate, MomentEstimate):
        raise TypeError("PSR requires same-series typed moments, not a bare reported Sharpe")
    n = estimate.n if type(estimate.n) is int and estimate.n >= 0 else 0
    def result(value=None, status="VALID", reason=None, components=()):
        return MetricValue("mode5.classical_psr_plugin_v1", "probability", n, value, status, reason, components)
    if type(estimate.n) is not int or estimate.n < 3:
        return result(status="INSUFFICIENT", reason="same return-series N must be an integer >=3")
    if estimate.status != "VALID":
        return result(status=estimate.status, reason=estimate.reason)
    if (estimate.sr_frequency != "period" or estimate.estimator != "central_population_v1"
            or estimate.population not in {"daily_account_returns", "explicit_return_series"}):
        return result(status="INVALID", reason="PSR requires original-frequency return moments, not annual SR or campaign PnL")
    values = (estimate.sharpe_period, estimate.skew, estimate.kurtosis_ordinary,
              estimate.variance, reference_period)
    if any(value is None or not math.isfinite(value) for value in values):
        return result(status="INVALID", reason="finite same-series moments/reference required")
    if estimate.variance <= 0:
        return result(status="UNDEFINED", reason="positive return variance required")
    sr, skew, kurt = values[:3]
    if kurt < 1 or kurt + 1e-12 < 1 + skew*skew:
        return result(status="INVALID", reason="ordinary central moments violate Pearson inequality")
    den2 = 1 - skew * sr + (kurt - 1) * sr * sr / 4
    if not math.isfinite(den2) or den2 <= 0:
        return result(status="UNDEFINED", reason="nonpositive or nonfinite PSR variance approximation")
    z = (sr - reference_period) * math.sqrt(n - 1) / math.sqrt(den2)
    if not math.isfinite(z):
        return result(status="INVALID", reason="PSR z overflow")
    probability = .5 * math.erfc(-z / math.sqrt(2))
    return result(probability, components=(("z", z), ("denominator_squared", den2),
        ("sr_period", sr), ("reference_period", reference_period),
        ("moment_estimator", estimate.estimator)))
