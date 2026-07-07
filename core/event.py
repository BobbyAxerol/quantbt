"""
quantbt.core.event
------------------
Numba kernels for the native event-driven backend.
"""

from __future__ import annotations

import numpy as np
from numba import njit


ORDER_STATUS_PENDING = 0
ORDER_STATUS_FILLED = 1
ORDER_STATUS_CANCELED = 2
ORDER_STATUS_REJECTED = 3

ORDER_TYPE_MARKET = 0
ORDER_TYPE_LIMIT = 1
ORDER_TYPE_STOP_MARKET = 2
ORDER_TYPE_STOP_LIMIT = 3

TIF_GTC = 0
TIF_IOC = 1
TIF_FOK = 2
TIF_GTD = 3

SIDE_BUY = 1
SIDE_SELL = -1

REJECT_NONE = 0
REJECT_INSUFFICIENT_MARGIN = 1
REJECT_UNSUPPORTED_ORDER_TYPE = 2

LIQ_NONE = 0
LIQ_INTRABAR = 1
LIQ_AFTER_FUNDING = 2
LIQ_AFTER_ORDER = 3


@njit(cache=True)
def _event_close_margin(
    n_syms: int,
    current_pos: np.ndarray,
    closes: np.ndarray,
    contract_sizes: np.ndarray,
    leverages: np.ndarray,
    maint_ratio: float,
    i: int,
):
    init_margin = 0.0
    maint_margin = 0.0
    for s in range(n_syms):
        p = current_pos[s]
        if p != 0.0:
            notional = abs(p) * closes[i, s] * contract_sizes[s]
            init_margin += notional / leverages[s]
            maint_margin += notional * maint_ratio
    return init_margin, maint_margin


@njit(cache=True)
def _event_liquidated(
    n_syms: int,
    equity: float,
    current_pos: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    contract_sizes: np.ndarray,
    maint_ratio: float,
    i: int,
):
    worst_equity = equity
    worst_mm = 0.0
    for s in range(n_syms):
        p = current_pos[s]
        if p == 0.0:
            continue
        worst_p = lows[i, s] if p > 0.0 else highs[i, s]
        worst_equity += p * (worst_p - closes[i, s]) * contract_sizes[s]
        worst_mm += abs(p) * worst_p * contract_sizes[s] * maint_ratio
    return worst_mm > 0.0 and worst_equity <= worst_mm


@njit(cache=True)
def _engine_event_v1(
    n_bars:          int,
    n_syms:          int,
    n_orders:        int,
    order_ptr:       np.ndarray,
    order_symbol:    np.ndarray,
    order_side:      np.ndarray,
    order_type:      np.ndarray,
    order_qty:       np.ndarray,
    order_price:     np.ndarray,
    order_tif:       np.ndarray,
    highs:           np.ndarray,
    lows:            np.ndarray,
    closes:          np.ndarray,
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
    rejected_bar = np.zeros(n_bars, dtype=np.int64)
    canceled_bar = np.zeros(n_bars, dtype=np.int64)

    order_status = np.full(n_orders, ORDER_STATUS_PENDING, dtype=np.int64)
    reject_code  = np.zeros(n_orders, dtype=np.int64)
    fill_bar     = np.full(n_orders, -1, dtype=np.int64)
    fill_qty     = np.zeros(n_orders, dtype=np.float64)
    fill_price   = np.zeros(n_orders, dtype=np.float64)
    fill_fee     = np.zeros(n_orders, dtype=np.float64)

    pending_ids = np.zeros(n_orders, dtype=np.int64)
    pending_count = 0

    current_pos = np.zeros(n_syms, dtype=np.float64)
    equity = init_capital
    liq_flag = False
    liq_idx = -1
    liq_reason = LIQ_NONE

    equity_curve[0] = equity

    for i in range(1, n_bars):
        if liq_flag:
            equity_curve[i] = 0.0
            for s in range(n_syms):
                pos_out[i, s] = 0.0
            continue

        # Mark carried positions to close.
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                equity += p * (closes[i, s] - closes[i - 1, s]) * contract_sizes[s]

        if _event_liquidated(
            n_syms, equity, current_pos, highs, lows, closes,
            contract_sizes, maint_ratio, i
        ):
            liq_flag = True
            liq_idx = i
            liq_reason = LIQ_INTRABAR
            equity = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
            equity_curve[i] = 0.0
            continue

        if is_funding_bar[i] and use_funding:
            for s in range(n_syms):
                p = current_pos[s]
                if p != 0.0:
                    cost = p * closes[i, s] * contract_sizes[s] * funding_rates[i, s]
                    equity -= cost
                    funding_arr[i] += cost

        _, close_mm = _event_close_margin(
            n_syms, current_pos, closes, contract_sizes, leverages, maint_ratio, i
        )
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

        # Activate orders submitted for this bar.
        for k in range(order_ptr[i], order_ptr[i + 1]):
            pending_ids[pending_count] = k
            pending_count += 1

        write_count = 0
        for pidx in range(pending_count):
            oid = pending_ids[pidx]
            if order_status[oid] != ORDER_STATUS_PENDING:
                continue

            sym = order_symbol[oid]
            side = order_side[oid]
            otype = order_type[oid]
            tif = order_tif[oid]

            touched = False
            exec_price = closes[i, sym]

            if otype == ORDER_TYPE_MARKET:
                touched = True
                exec_price = closes[i, sym] * (1.0 + slippage if side > 0 else 1.0 - slippage)
            elif otype == ORDER_TYPE_LIMIT:
                limit_p = order_price[oid]
                if side > 0 and lows[i, sym] <= limit_p:
                    touched = True
                    exec_price = limit_p
                elif side < 0 and highs[i, sym] >= limit_p:
                    touched = True
                    exec_price = limit_p
            else:
                order_status[oid] = ORDER_STATUS_REJECTED
                reject_code[oid] = REJECT_UNSUPPORTED_ORDER_TYPE
                rejected_bar[i] += 1
                continue

            if not touched:
                if tif == TIF_GTC:
                    pending_ids[write_count] = oid
                    write_count += 1
                else:
                    order_status[oid] = ORDER_STATUS_CANCELED
                    canceled_bar[i] += 1
                continue

            qty = order_qty[oid]
            delta = qty * side
            cs = contract_sizes[sym]
            c = closes[i, sym]
            trade_notional = abs(delta) * exec_price * cs
            fee_cost = trade_notional * fee_rates[sym]

            cur_im, _ = _event_close_margin(
                n_syms, current_pos, closes, contract_sizes, leverages, maint_ratio, i
            )
            old_im = abs(current_pos[sym]) * c * cs / leverages[sym]
            new_im = abs(current_pos[sym] + delta) * exec_price * cs / leverages[sym]
            margin_delta = new_im - old_im
            required = fee_cost
            if margin_delta > 0.0:
                required += margin_delta

            if required > equity - cur_im:
                order_status[oid] = ORDER_STATUS_REJECTED
                reject_code[oid] = REJECT_INSUFFICIENT_MARGIN
                rejected_bar[i] += 1
                continue

            # Equity is marked at close; fill price creates same-bar PnL.
            equity += delta * (c - exec_price) * cs - fee_cost
            current_pos[sym] += delta

            order_status[oid] = ORDER_STATUS_FILLED
            fill_bar[oid] = i
            fill_qty[oid] = qty
            fill_price[oid] = exec_price
            fill_fee[oid] = fee_cost
            fee_arr[i] += fee_cost
            turnover_arr[i] += trade_notional

        pending_count = write_count

        close_im, close_mm = _event_close_margin(
            n_syms, current_pos, closes, contract_sizes, leverages, maint_ratio, i
        )

        if close_mm > 0.0 and equity <= close_mm:
            liq_flag = True
            liq_idx = i
            liq_reason = LIQ_AFTER_ORDER
            equity = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
            equity_curve[i] = 0.0
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
        rejected_bar,
        canceled_bar,
        order_status,
        reject_code,
        fill_bar,
        fill_qty,
        fill_price,
        fill_fee,
        liq_flag,
        liq_idx,
        liq_reason,
    )
