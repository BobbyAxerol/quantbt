"""Stationary index generation with the same NumPy RNG on both paths."""

from __future__ import annotations

import numpy as np

try:
    from numba import njit
except Exception:  # Match WFO's optional-Numba guard, including binary import failures.
    njit = None


def _stationary_indices(rng, n_obs: int, n_samples: int, block_length: int):
    p = 1.0 / max(1.0, float(block_length))
    indices = np.empty((n_samples, n_obs), dtype=np.int64)
    for sample in range(n_samples):
        current = int(rng.integers(0, n_obs))
        indices[sample, 0] = current
        for i in range(1, n_obs):
            if rng.random() < p:
                current = int(rng.integers(0, n_obs))
            else:
                current = (current + 1) % n_obs
            indices[sample, i] = current
    return indices


_compiled_stationary_indices = (
    njit(cache=True)(_stationary_indices) if njit is not None else None
)


def stationary_indices(n_obs, n_samples, block_length, seed, *, use_numba=False):
    if n_obs <= 0:
        raise ValueError("n_obs must be > 0")
    rng = np.random.default_rng(int(seed))
    implementation = (
        _compiled_stationary_indices
        if use_numba and _compiled_stationary_indices is not None
        else _stationary_indices
    )
    # Pass the Generator itself: reseeding another RNG or pre-drawing restart
    # offsets would change the interleaved reference stream.
    return implementation(rng, int(n_obs), int(n_samples), block_length)
