"""
quantbt.core.vectorized
-----------------------
Numba kernels for the V2 native vectorized backend.
"""

from __future__ import annotations

import numpy as np
from numba import njit


REJECT_NONE = 0
REJECT_INSUFFICIENT_MARGIN = 1

LIQ_NONE = 0
LIQ_INTRABAR = 1
LIQ_AFTER_FUNDING = 2
LIQ_AFTER_REBALANCE = 3


@njit(cache=True)
def _engine_units_v2(
    n_bars:          int,
    n_syms:          int,
    highs:           np.ndarray,
    lows:            np.ndarray,
    closes:          np.ndarray,
    target_units:    np.ndarray,
    funding_rates:   np.ndarray,
    is_funding_bar:  np.ndarray,
    init_capital:    float,
    leverages:       np.ndarray,
    maint_ratio:     float,
    fee_rates:       np.ndarray,
    contract_sizes:  np.ndarray,
    slippage:        float,
    use_funding:     bool,
):
    equity_curve = np.zeros(n_bars, dtype=np.float64)
    pos_out      = np.zeros((n_bars, n_syms), dtype=np.float64)
    fee_arr      = np.zeros(n_bars, dtype=np.float64)
    turnover_arr = np.zeros(n_bars, dtype=np.float64)
    funding_arr  = np.zeros(n_bars, dtype=np.float64)
    init_margin  = np.zeros(n_bars, dtype=np.float64)
    maint_margin = np.zeros(n_bars, dtype=np.float64)
    rejected     = np.zeros(n_bars, dtype=np.int64)
    reject_code  = np.zeros(n_bars, dtype=np.int64)

    current_pos = np.zeros(n_syms, dtype=np.float64)
    equity      = init_capital
    liq_flag    = False
    liq_idx     = -1
    liq_reason  = LIQ_NONE

    equity_curve[0] = equity

    for i in range(1, n_bars):
        if liq_flag:
            equity_curve[i] = 0.0
            for s in range(n_syms):
                pos_out[i, s] = 0.0
            continue

        # Mark carried positions close-to-close.
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                equity += p * (closes[i, s] - closes[i - 1, s]) * contract_sizes[s]

        # Intrabar liquidation before funding and new orders.
        worst_equity = equity
        worst_mm = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p == 0.0:
                continue
            worst_p = lows[i, s] if p > 0.0 else highs[i, s]
            worst_equity += p * (worst_p - closes[i, s]) * contract_sizes[s]
            worst_mm += abs(p) * worst_p * contract_sizes[s] * maint_ratio

        if worst_mm > 0.0 and worst_equity <= worst_mm:
            liq_flag = True
            liq_idx = i
            liq_reason = LIQ_INTRABAR
            equity = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
            equity_curve[i] = 0.0
            continue

        # Funding on carried positions. Positive value is a cost paid.
        if is_funding_bar[i] and use_funding:
            for s in range(n_syms):
                p = current_pos[s]
                if p != 0.0:
                    cost = p * closes[i, s] * contract_sizes[s] * funding_rates[i, s]
                    equity -= cost
                    funding_arr[i] += cost

        close_mm = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                close_mm += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if close_mm > 0.0 and equity <= close_mm:
            liq_flag = True
            liq_idx = i
            liq_reason = LIQ_AFTER_FUNDING
            equity = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
            equity_curve[i] = 0.0
            continue

        cur_im = 0.0
        for s in range(n_syms):
            cur_im += abs(current_pos[s]) * closes[i, s] * contract_sizes[s] / leverages[s]

        avail = equity - cur_im
        if avail < 0.0:
            avail = 0.0

        # Execute target-unit changes at close with optional slippage.
        for s in range(n_syms):
            target = target_units[i, s]
            delta = target - current_pos[s]
            if abs(delta) < 1e-12:
                continue

            c = closes[i, s]
            cs = contract_sizes[s]
            exec_p = c * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)
            trade_notional = abs(delta) * exec_p * cs
            fee_cost = trade_notional * fee_rates[s]
            slip_cost = abs(delta) * abs(exec_p - c) * cs

            old_im = abs(current_pos[s]) * c * cs / leverages[s]
            new_im = abs(target) * exec_p * cs / leverages[s]
            margin_delta = new_im - old_im
            required = fee_cost + slip_cost
            if margin_delta > 0.0:
                required += margin_delta

            if required > avail:
                rejected[i] += 1
                reject_code[i] = REJECT_INSUFFICIENT_MARGIN
                continue

            equity -= fee_cost + slip_cost
            current_pos[s] = target
            fee_arr[i] += fee_cost
            turnover_arr[i] += trade_notional
            avail -= fee_cost + slip_cost + margin_delta
            if avail < 0.0:
                avail = 0.0

        close_im = 0.0
        close_mm = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                notional = abs(p) * closes[i, s] * contract_sizes[s]
                close_im += notional / leverages[s]
                close_mm += notional * maint_ratio

        if close_mm > 0.0 and equity <= close_mm:
            liq_flag = True
            liq_idx = i
            liq_reason = LIQ_AFTER_REBALANCE
            equity = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
            equity_curve[i] = 0.0
            init_margin[i] = 0.0
            maint_margin[i] = 0.0
            continue

        for s in range(n_syms):
            pos_out[i, s] = current_pos[s]

        init_margin[i] = close_im
        maint_margin[i] = close_mm
        equity_curve[i] = equity

    return (
        equity_curve,
        pos_out,
        fee_arr,
        turnover_arr,
        funding_arr,
        init_margin,
        maint_margin,
        rejected,
        reject_code,
        liq_flag,
        liq_idx,
        liq_reason,
    )
