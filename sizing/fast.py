"""
Fast ndarray sizing helpers.

These helpers are internal optimization paths. They must match the public
Series-based sizing functions in `quantbt.sizing.modes`.
"""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def _signal_notional_matrix_numba(
    signals: np.ndarray,
    closes: np.ndarray,
    allocs: np.ndarray,
    use_pyramiding: bool,
) -> np.ndarray:
    n_bars, n_syms = signals.shape
    out = np.zeros((n_bars, n_syms), dtype=np.float64)
    for j in range(n_syms):
        current_scale = 0.0
        prev_sig = 0.0
        for i in range(n_bars):
            sig = signals[i, j]
            if not use_pyramiding:
                if sig > 0.0:
                    sig = 1.0
                elif sig < 0.0:
                    sig = -1.0
                else:
                    sig = 0.0
            if i == 0 or sig != prev_sig:
                if sig != 0.0:
                    current_scale = allocs[j] / closes[i, j]
                else:
                    current_scale = 0.0
            out[i, j] = sig * current_scale
            prev_sig = sig
    return out


def scale_signal_notional_matrix(
    signals: np.ndarray,
    closes: np.ndarray,
    allocs: np.ndarray,
    use_pyramiding: bool = True,
) -> np.ndarray:
    """
    Return target-unit matrix for signal_notional sizing.

    The behavior is intentionally identical to `scale_signal_notional` applied
    per symbol: anchor units on signal transition and keep them frozen between
    transitions.
    """
    sig = np.ascontiguousarray(signals, dtype=np.float64)
    cls = np.ascontiguousarray(closes, dtype=np.float64)
    alc = np.ascontiguousarray(allocs, dtype=np.float64)
    if sig.shape != cls.shape:
        raise ValueError("signals and closes must have the same shape")
    if sig.ndim != 2:
        raise ValueError("signals and closes must be 2D arrays")
    if len(alc) != sig.shape[1]:
        raise ValueError("allocs length must match number of symbols")
    return _signal_notional_matrix_numba(sig, cls, alc, bool(use_pyramiding))
