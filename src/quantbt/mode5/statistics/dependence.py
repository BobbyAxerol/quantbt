"""Versioned population-Sharpe HAC, distinct from classical plug-in PSR."""

from dataclasses import asdict, dataclass
import math
from statistics import NormalDist

import numpy as np

from quantbt.mode5.diagnostics.identity import digest as canonical_digest
from .contracts import MetricValue, vector


@dataclass(frozen=True)
class HACPolicy:
    bandwidth: int = 5
    minimum_samples: int = 32
    confidence: float = .95
    version: str = "sharpe_evidence_hac_v1"
    kernel: str = "bartlett"
    small_sample: str = "none"

    def __post_init__(self):
        if (self.version, self.kernel, self.small_sample) != ("sharpe_evidence_hac_v1", "bartlett", "none"):
            raise NotImplementedError("unsupported HAC estimator convention")
        if type(self.bandwidth) is not int or self.bandwidth < 0:
            raise ValueError("nonnegative fixed bandwidth required")
        if type(self.minimum_samples) is not int or self.minimum_samples < max(3, self.bandwidth + 2):
            raise ValueError("minimum sample must exceed bandwidth")
        if not math.isfinite(self.confidence) or not 0 < self.confidence < 1:
            raise ValueError("confidence must be in (0,1)")

    @property
    def identity(self):
        return canonical_digest(asdict(self))


def sharpe_hac(values, *, policy=HACPolicy(), risk_free_per_period=0., reference_period=0.):
    values = vector(values)
    n = len(values)
    def result(value=None, status="VALID", reason=None, components=()):
        return MetricValue("mode5.sharpe_evidence_hac_v1", "probability", n, value, status, reason,
            (("policy_identity", policy.identity),) + components)
    if not np.isfinite(values).all() or not all(map(math.isfinite, (risk_free_per_period, reference_period))):
        return result(status="INVALID", reason="nonfinite observation/reference; no row dropping")
    if n < policy.minimum_samples:
        return result(status="INSUFFICIENT", reason="below frozen HAC minimum sample")
    with np.errstate(over="ignore", invalid="ignore"):
        x = values - risk_free_per_period
    if not np.isfinite(x).all():
        return result(status="INVALID", reason="excess-return numeric overflow")
    scale = float(np.max(np.abs(x)))
    if scale == 0:
        return result(status="UNDEFINED", reason="positive finite population return variance required")
    x = x / scale
    mean = float(x.mean())
    centered = x - mean
    variance = float(np.mean(centered**2))
    if not math.isfinite(variance) or variance <= 0:
        return result(status="UNDEFINED", reason="positive finite population return variance required")
    sigma = math.sqrt(variance)
    sr = mean / sigma
    psi = centered / sigma - mean / (2 * sigma**3) * (centered**2 - variance)
    psi -= psi.mean()
    gamma0 = float(np.dot(psi, psi) / n)
    tau2 = gamma0
    for lag in range(1, policy.bandwidth + 1):
        weight = 1 - lag / (policy.bandwidth + 1)
        tau2 += 2 * weight * float(np.dot(psi[lag:], psi[:-lag]) / n)
    if not math.isfinite(tau2) or tau2 <= 0 or not math.isfinite(sr):
        return result(status="UNDEFINED", reason="nonpositive or nonfinite HAC long-run variance")
    se = math.sqrt(tau2 / n)
    z = (sr - reference_period) / se
    quantile = (1 + policy.confidence) / 2
    if not math.isfinite(z) or not 0 < quantile < 1:
        return result(status="INVALID", reason="HAC reference/interval numeric overflow")
    critical = NormalDist().inv_cdf(quantile)
    low, high = sr - critical*se, sr + critical*se
    if not math.isfinite(low) or not math.isfinite(high):
        return result(status="INVALID", reason="HAC interval numeric overflow")
    components = (("sr_population_period", sr), ("standard_error", se), ("gamma0", gamma0),
        ("long_run_variance", tau2), ("ci_low", low), ("ci_high", high),
        ("reference_period", reference_period), ("z", z), ("bandwidth", policy.bandwidth),
        ("gamma_divisor", "N"), ("influence_centering", "sample_centered"),
        ("small_sample", policy.small_sample))
    return result(.5*math.erfc(-z / math.sqrt(2)), components=components)
