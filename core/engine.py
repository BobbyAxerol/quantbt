"""
quantbt.core.engine
-------------------
Numba-compiled simulation kernels.

Two entry points
~~~~~~~~~~~~~~~~
_engine_units       signals are pre-scaled target units (notional / unit / signal_notional)
_engine_pct_equity  signals are raw weight fractions; units derived from live equity each bar

Simulation contract
~~~~~~~~~~~~~~~~~~~
equity              realised + unrealised MTM, updated close-to-close every bar
liquidation         intrabar worst-case: Low for longs, High for shorts
maintenance_margin  abs(pos) × price × cs × mm_rate        (Binance notional-based formula)
funding             fires once per is_funding_bar=True bar  (caller marks the FIRST bar of each 8h window)
fee_rate            ONE-WAY rate; caller passes fee/2 if fee is round-trip
slippage            fraction applied at execution price; always a cost
"""

import numpy as np
from numba import njit


@njit(cache=True)
def _engine_units(
    n_bars:          int,
    n_syms:          int,
    highs:           np.ndarray,   # (n_bars, n_syms) float64
    lows:            np.ndarray,   # (n_bars, n_syms) float64
    closes:          np.ndarray,   # (n_bars, n_syms) float64
    signals:         np.ndarray,   # (n_bars, n_syms) float64  pre-scaled target units
    funding_rates:   np.ndarray,   # (n_bars, n_syms) float64
    is_funding_bar:  np.ndarray,   # (n_bars,)        bool
    init_capital:    float,
    leverage:        float,
    maint_ratio:     float,
    fee_rate:        float,
    contract_sizes:  np.ndarray,   # (n_syms,)        float64
    slippage:        float,
):
    equity_curve = np.zeros(n_bars, dtype=np.float64)
    equity       = init_capital
    current_pos  = np.zeros(n_syms, dtype=np.float64)
    liq_flag     = False
    liq_idx      = -1

    equity_curve[0] = equity

    for i in range(1, n_bars):
        if liq_flag:
            equity_curve[i] = 0.0
            continue

        # 1 ── Mark-to-market (close-to-close) ───────────────────────────
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                equity += p * (closes[i, s] - closes[i - 1, s]) * contract_sizes[s]

        # 2 ── Intrabar liquidation check ─────────────────────────────────
        worst_equity = equity
        maint_req    = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p == 0.0:
                continue
            worst_p = lows[i, s] if p > 0.0 else highs[i, s]
            worst_equity += p * (worst_p - closes[i, s]) * contract_sizes[s]
            # Binance: maintenance_margin = notional × mm_rate
            maint_req += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if maint_req > 0.0 and worst_equity <= maint_req:
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
            equity_curve[i] = 0.0
            continue

        # 3 ── Funding fee ─────────────────────────────────────────────────
        if is_funding_bar[i]:
            for s in range(n_syms):
                p = current_pos[s]
                if p != 0.0:
                    # Long pays positive rate; short earns positive rate
                    equity -= p * closes[i, s] * contract_sizes[s] * funding_rates[i, s]

        # 4 ── Execute signal changes ──────────────────────────────────────
        cur_im = 0.0
        for s in range(n_syms):
            cur_im += abs(current_pos[s]) * closes[i, s] * contract_sizes[s] / leverage

        avail = equity - cur_im
        if avail < 0.0:
            avail = 0.0

        for s in range(n_syms):
            target = signals[i, s]
            if abs(target - current_pos[s]) < 1e-12:
                continue

            delta  = target - current_pos[s]
            exec_p = closes[i, s] * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)

            fee_cost   = abs(delta) * exec_p * contract_sizes[s] * fee_rate
            # equity already marked to close; exec_p deviates → always a cost
            slip_cost  = abs(delta) * abs(exec_p - closes[i, s]) * contract_sizes[s]

            im_needed = 0.0
            if abs(target) > abs(current_pos[s]):
                added = (abs(target) - abs(current_pos[s])) * exec_p * contract_sizes[s]
                im_needed = added / leverage

            if im_needed > avail:
                continue  # order rejected: insufficient margin

            equity -= fee_cost + slip_cost
            current_pos[s] = target
            if im_needed > 0.0:
                avail -= im_needed

        equity_curve[i] = equity

    return equity_curve, liq_flag, liq_idx


@njit(cache=True)
def _engine_pct_equity(
    n_bars:          int,
    n_syms:          int,
    highs:           np.ndarray,
    lows:            np.ndarray,
    closes:          np.ndarray,
    signals:         np.ndarray,   # (n_bars, n_syms) raw weight  e.g. 1.0 / -0.5 / 0.0
    funding_rates:   np.ndarray,
    is_funding_bar:  np.ndarray,
    init_capital:    float,
    leverage:        float,
    maint_ratio:     float,
    fee_rate:        float,
    contract_sizes:  np.ndarray,
    slippage:        float,
    alloc_pct:       np.ndarray,   # (n_syms,) fraction of equity, in (0, 1]
):
    """
    Target units = equity × alloc_pct[s] × weight[i,s] / (close[i,s] × cs[s])
    Recalculated only when weight changes; no drift-rebalancing between bars.
    """
    equity_curve = np.zeros(n_bars, dtype=np.float64)
    equity       = init_capital
    current_pos  = np.zeros(n_syms, dtype=np.float64)
    liq_flag     = False
    liq_idx      = -1

    equity_curve[0] = equity

    for i in range(1, n_bars):
        if liq_flag:
            equity_curve[i] = 0.0
            continue

        # MTM
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                equity += p * (closes[i, s] - closes[i - 1, s]) * contract_sizes[s]

        # Liquidation
        worst_equity = equity
        maint_req    = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p == 0.0:
                continue
            worst_p = lows[i, s] if p > 0.0 else highs[i, s]
            worst_equity += p * (worst_p - closes[i, s]) * contract_sizes[s]
            maint_req += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if maint_req > 0.0 and worst_equity <= maint_req:
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
            equity_curve[i] = 0.0
            continue

        # Funding
        if is_funding_bar[i]:
            for s in range(n_syms):
                p = current_pos[s]
                if p != 0.0:
                    equity -= p * closes[i, s] * contract_sizes[s] * funding_rates[i, s]

        # Execute on weight-change only
        cur_im = 0.0
        for s in range(n_syms):
            cur_im += abs(current_pos[s]) * closes[i, s] * contract_sizes[s] / leverage

        avail = equity - cur_im
        if avail < 0.0:
            avail = 0.0

        for s in range(n_syms):
            if signals[i, s] == signals[i - 1, s]:
                continue

            denom = closes[i, s] * contract_sizes[s]
            if denom == 0.0:
                continue

            target = (equity * alloc_pct[s] * signals[i, s]) / denom

            if abs(target - current_pos[s]) < 1e-12:
                continue

            delta  = target - current_pos[s]
            exec_p = closes[i, s] * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)

            fee_cost  = abs(delta) * exec_p * contract_sizes[s] * fee_rate
            slip_cost = abs(delta) * abs(exec_p - closes[i, s]) * contract_sizes[s]

            im_needed = 0.0
            if abs(target) > abs(current_pos[s]):
                added     = (abs(target) - abs(current_pos[s])) * exec_p * contract_sizes[s]
                im_needed = added / leverage

            if im_needed > avail:
                continue

            equity -= fee_cost + slip_cost
            current_pos[s] = target
            if im_needed > 0.0:
                avail -= im_needed

        equity_curve[i] = equity

    return equity_curve, liq_flag, liq_idx
