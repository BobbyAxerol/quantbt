"""
quantbt.sizing.modes
--------------------
Position scaling: converts raw signal weights into target *units* (contracts)
that the numba engine can consume directly.

Five modes
~~~~~~~~~~
notional
    target_units[i] = signal[i] × (alloc / close[i])
    Units recomputed every bar → constant notional exposure.
    Generates a trade whenever signal OR price changes.  High turnover on
    intraday data; intended for EOD / multi-day bars.

unit
    target_units[i] = signal[i] × (alloc / close[0])
    Scale fixed at the *first* bar's price.  Units stable as price moves;
    notional drifts with the market.

signal_notional  ← recommended for systematic strategies
    Units are re-anchored to current price ONLY when the signal weight
    changes.  Between signal changes the unit count is frozen → no
    spurious micro-trades due to price drift.
    target_units[i] = signal[i] × (alloc / close[change_bar])

pct_equity
    Raw weight is passed straight through to the %_equity numba kernel,
    which sizes units from live equity at execution time.
    Returns the raw signal unchanged; no pre-scaling needed.

dca_ladder
    Raw signed structural level is passed straight through to the DCA ladder
    execution kernel.  The kernel turns High/Low limit touches into actual
    filled units at each grid trigger price.

Parameters
----------
signal : pd.Series       raw weight (float), e.g. 1.0 / -0.5 / 0.3
close  : pd.Series       closing price, same index as signal
alloc  : float           notional allocation per full signal unit (USD)
use_pyramiding : bool    if False, signal is clipped to {-1, 0, 1}

Returns
-------
pd.Series  target units (float), same index as signal
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def scale_notional(
    signal: pd.Series,
    close: pd.Series,
    alloc: float,
    use_pyramiding: bool = True,
) -> pd.Series:
    sig = signal if use_pyramiding else np.sign(signal)
    return sig * (alloc / close)


def scale_unit(
    signal: pd.Series,
    close: pd.Series,
    alloc: float,
    use_pyramiding: bool = True,
) -> pd.Series:
    sig   = signal if use_pyramiding else np.sign(signal)
    scale = alloc / close.iloc[0]
    return sig * scale


def scale_signal_notional(
    signal: pd.Series,
    close: pd.Series,
    alloc: float,
    use_pyramiding: bool = True,
) -> pd.Series:
    """
    Anchor-on-change scaling.

    Units are computed once per signal transition using the prevailing price
    at that bar, then held constant until the next transition.  This is the
    standard approach in institutional systematic desks to avoid phantom
    rebalancing trades.
    """
    sig_vals = signal.values if use_pyramiding else np.sign(signal.values)
    pr_vals  = close.values
    n        = len(sig_vals)
    target   = np.zeros(n, dtype=np.float64)

    current_scale = 0.0
    for i in range(n):
        if i == 0 or sig_vals[i] != sig_vals[i - 1]:
            current_scale = (alloc / pr_vals[i]) if sig_vals[i] != 0 else 0.0
        target[i] = sig_vals[i] * current_scale

    return pd.Series(target, index=signal.index)


def scale_pct_equity(
    signal: pd.Series,
    use_pyramiding: bool = True,
) -> pd.Series:
    """
    No pre-scaling.  Pass raw weight directly; the numba kernel sizes from
    live equity at execution time.
    """
    return signal if use_pyramiding else np.sign(signal).astype(float)


def scale_dca_ladder(signal: pd.Series) -> pd.Series:
    """
    No pre-scaling.  Pass signed structural levels directly:
    +1..+N for long ladders, -1..-N for short ladders, 0 for flat.
    """
    return signal.astype(float)


# ── dispatcher ──────────────────────────────────────────────────────────────

def compute_target_units(
    hedge_type:     str,
    signal:         pd.Series,
    close:          pd.Series,
    alloc:          float,
    use_pyramiding: bool = True,
) -> pd.Series:
    """
    Central dispatcher.  Returns target-unit series for any supported mode.

    Parameters
    ----------
    hedge_type : {'notional', 'unit', 'signal_notional', '%_equity', 'dca_ladder'}
    signal     : raw weight series
    close      : close price series
    alloc      : notional per full unit of signal
    use_pyramiding : allow fractional weights; if False snaps to {-1,0,1}
    """
    ht = hedge_type.lower().strip()

    if ht == "notional":
        return scale_notional(signal, close, alloc, use_pyramiding)

    if ht == "unit":
        return scale_unit(signal, close, alloc, use_pyramiding)

    if ht in ("signal_notional", "signal"):
        return scale_signal_notional(signal, close, alloc, use_pyramiding)

    if ht in ("%_equity", "pct_equity"):
        return scale_pct_equity(signal, use_pyramiding)

    if ht in ("dca_ladder", "dca"):
        return scale_dca_ladder(signal)

    raise ValueError(
        f"Unknown hedge_type '{hedge_type}'. "
        "Choose from: 'notional', 'unit', 'signal_notional', '%_equity', 'dca_ladder'."
    )
