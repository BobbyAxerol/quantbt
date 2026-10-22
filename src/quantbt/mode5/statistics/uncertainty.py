"""Bounded fixed-path time-block intervals, not whole-selection uncertainty."""

from dataclasses import asdict, dataclass

import numpy as np

from .contracts import StatisticsPolicy, vector
from .moments import moments


@dataclass(frozen=True)
class BlockPolicy:
    block_length: int = 7
    draws: int = 256
    seed: int = 731
    confidence: float = .95
    chunk_size: int = 16
    version: str = "circular_block_moment_intervals_v1"

    def __post_init__(self):
        if self.version != "circular_block_moment_intervals_v1":
            raise ValueError("unsupported block estimator")
        for name in ("block_length", "draws", "chunk_size"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError("positive integral block/draw/chunk limits required")
        if type(self.seed) is not int or self.seed < 0 or not 0 < self.confidence < 1:
            raise ValueError("explicit seed and valid confidence required")


def moment_intervals(values, *, policy=BlockPolicy(), statistics_policy=StatisticsPolicy()):
    values = vector(values)
    original = moments(values, policy=statistics_policy)
    base = {"formula_id": policy.version, "scope": "FIXED_PATH_NOT_SELECTOR_UNCERTAINTY",
            "policy": asdict(policy), "sample_count": len(values), "invalid_draws": 0,
            "intervals": None, "status": "INSUFFICIENT", "reason": "at least two blocks and 32 observations required"}
    if len(values) < max(32, 2 * policy.block_length):
        return base
    if original.status != "VALID":
        return base | {"status": original.status, "reason": original.reason}
    rng = np.random.default_rng(policy.seed)
    n = len(values)
    blocks = (n + policy.block_length - 1) // policy.block_length
    offsets = np.arange(policy.block_length)
    samples = []
    invalid = 0
    for first in range(0, policy.draws, policy.chunk_size):
        count = min(policy.chunk_size, policy.draws-first)
        starts = rng.integers(0, n, size=(count, blocks))
        for row in starts:
            indices = ((row[:, None] + offsets) % n).reshape(-1)[:n]
            observed = moments(values[indices], policy=statistics_policy)
            if observed.status != "VALID":
                invalid += 1
            else:
                samples.append((observed.mean, observed.sharpe_period, observed.skew, observed.kurtosis_ordinary))
    if invalid:
        return base | {"invalid_draws": invalid, "status": "UNAVAILABLE",
                       "reason": "invalid bootstrap draws retained; intervals not conditioned on surviving draws"}
    limits = [(1-policy.confidence)/2, (1+policy.confidence)/2]
    bounds = np.quantile(np.asarray(samples), limits, axis=0, method="linear")
    names = ("mean_excess", "sharpe_period", "skew", "kurtosis_ordinary")
    return base | {"status": "VALID", "reason": None,
        "intervals": {key: tuple(float(v) for v in bounds[:, j]) for j, key in enumerate(names)},
        "effective_draws": policy.draws, "blocks_per_draw": blocks,
        "quantile_interpolation": "linear"}
