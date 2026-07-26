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
REJECT_UNKNOWN_ORDER = 3
REJECT_INVALID_AMEND = 4
REJECT_REDUCE_ONLY_NO_POSITION = 5
REJECT_UNSUPPORTED_ACTION = 6

LIQ_NONE = 0
LIQ_INTRABAR = 1
LIQ_AFTER_FUNDING = 2
LIQ_AFTER_ORDER = 3

COMMAND_ACTION_PLACE = 0
COMMAND_ACTION_CANCEL = 1
COMMAND_ACTION_REPLACE = 2
COMMAND_ACTION_AMEND = 3
COMMAND_ACTION_CANCEL_ALL = 4

ACTIVATION_IMMEDIATE = 0
ACTIVATION_ON_PARENT_FIRST_FILL = 1
ACTIVATION_ON_PARENT_FULL_FILL = 2

ORDER_EVENT_PLACE = 0
ORDER_EVENT_CANCEL = 1
ORDER_EVENT_REPLACE = 2
ORDER_EVENT_AMEND = 3
ORDER_EVENT_FILL = 4
ORDER_EVENT_EXPIRE = 5
ORDER_EVENT_ACTIVATE = 6
ORDER_EVENT_REJECT = 7


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


@njit(cache=True)
def _record_order_event(
    event_count: int,
    event_bar: np.ndarray,
    event_command: np.ndarray,
    event_type: np.ndarray,
    event_status: np.ndarray,
    event_related_command: np.ndarray,
    bar: int,
    command_idx: int,
    event_code: int,
    status: int,
    related_command_idx: int,
):
    if event_count < event_bar.shape[0]:
        event_bar[event_count] = bar
        event_command[event_count] = command_idx
        event_type[event_count] = event_code
        event_status[event_count] = status
        event_related_command[event_count] = related_command_idx
        return event_count + 1
    return event_count


@njit(cache=True)
def _event_margin_required(
    n_syms: int,
    current_pos: np.ndarray,
    closes: np.ndarray,
    contract_sizes: np.ndarray,
    leverages: np.ndarray,
    maint_ratio: float,
    i: int,
    sym: int,
    delta: float,
    exec_price: float,
    fee_cost: float,
):
    cur_im, _ = _event_close_margin(
        n_syms, current_pos, closes, contract_sizes, leverages, maint_ratio, i
    )
    cs = contract_sizes[sym]
    c = closes[i, sym]
    old_im = abs(current_pos[sym]) * c * cs / leverages[sym]
    new_im = abs(current_pos[sym] + delta) * exec_price * cs / leverages[sym]
    margin_delta = new_im - old_im
    required = fee_cost
    if margin_delta > 0.0:
        required += margin_delta
    return required, cur_im


@njit(cache=True)
def _event_v2_touched_price(
    otype: int,
    side: int,
    price: float,
    trigger_price: float,
    high: float,
    low: float,
    close: float,
    slippage: float,
):
    touched = False
    exec_price = close
    if otype == ORDER_TYPE_MARKET:
        touched = True
        exec_price = close * (1.0 + slippage if side > 0 else 1.0 - slippage)
    elif otype == ORDER_TYPE_LIMIT:
        if side > 0 and low <= price:
            touched = True
            exec_price = price
        elif side < 0 and high >= price:
            touched = True
            exec_price = price
    elif otype == ORDER_TYPE_STOP_MARKET:
        if side > 0 and high >= trigger_price:
            touched = True
            exec_price = trigger_price * (1.0 + slippage)
        elif side < 0 and low <= trigger_price:
            touched = True
            exec_price = trigger_price * (1.0 - slippage)
    elif otype == ORDER_TYPE_STOP_LIMIT:
        if side > 0 and high >= trigger_price and low <= price:
            touched = True
            exec_price = price
        elif side < 0 and low <= trigger_price and high >= price:
            touched = True
            exec_price = price
    return touched, exec_price


@njit(cache=True)
def _engine_event_v2(
    n_bars:                 int,
    n_syms:                 int,
    n_commands:             int,
    n_ids:                  int,
    command_ptr:            np.ndarray,
    command_action:         np.ndarray,
    command_symbol:         np.ndarray,
    command_side:           np.ndarray,
    command_type:           np.ndarray,
    command_qty:            np.ndarray,
    command_price:          np.ndarray,
    command_trigger_price:  np.ndarray,
    command_tif:            np.ndarray,
    command_reduce_only:    np.ndarray,
    command_order_id:       np.ndarray,
    command_target_order_id: np.ndarray,
    command_parent_order_id: np.ndarray,
    command_group_id:       np.ndarray,
    command_oco_group_id:   np.ndarray,
    command_activation:     np.ndarray,
    command_expires_bar:    np.ndarray,
    highs:                  np.ndarray,
    lows:                   np.ndarray,
    closes:                 np.ndarray,
    funding_rates:          np.ndarray,
    is_funding_bar:         np.ndarray,
    init_capital:           float,
    leverages:              np.ndarray,
    maint_ratio:            float,
    fee_rates:              np.ndarray,
    contract_sizes:         np.ndarray,
    slippage:               float,
    use_funding:            bool,
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

    command_status = np.full(n_commands, ORDER_STATUS_PENDING, dtype=np.int64)
    reject_code    = np.zeros(n_commands, dtype=np.int64)
    fill_bar       = np.full(n_commands, -1, dtype=np.int64)
    fill_qty       = np.zeros(n_commands, dtype=np.float64)
    fill_price     = np.zeros(n_commands, dtype=np.float64)
    fill_fee       = np.zeros(n_commands, dtype=np.float64)

    active = np.zeros(n_commands, dtype=np.int64)
    waiting_parent = np.zeros(n_commands, dtype=np.int64)
    working_qty = np.copy(command_qty)
    working_price = np.copy(command_price)
    working_trigger = np.copy(command_trigger_price)
    id_to_slot = np.full(n_ids, -1, dtype=np.int64)

    max_events = n_commands * 8 + n_bars
    event_bar = np.full(max_events, -1, dtype=np.int64)
    event_command = np.full(max_events, -1, dtype=np.int64)
    event_type = np.full(max_events, -1, dtype=np.int64)
    event_status = np.full(max_events, -1, dtype=np.int64)
    event_related_command = np.full(max_events, -1, dtype=np.int64)
    event_count = 0

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

        # Expire active GTD orders before processing the current bar.
        for oid in range(n_commands):
            if active[oid] == 1 and command_status[oid] == ORDER_STATUS_PENDING:
                exp_bar = command_expires_bar[oid]
                if exp_bar >= 0 and i >= exp_bar:
                    active[oid] = 0
                    command_status[oid] = ORDER_STATUS_CANCELED
                    canceled_bar[i] += 1
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, oid,
                        ORDER_EVENT_EXPIRE, ORDER_STATUS_CANCELED, -1,
                    )

        # Apply lifecycle commands submitted for this bar.
        for k in range(command_ptr[i], command_ptr[i + 1]):
            action = command_action[k]
            if action == COMMAND_ACTION_PLACE:
                oid_code = command_order_id[k]
                if oid_code >= 0 and oid_code < n_ids:
                    id_to_slot[oid_code] = k
                if command_activation[k] == ACTIVATION_IMMEDIATE:
                    active[k] = 1
                else:
                    waiting_parent[k] = 1
                event_count = _record_order_event(
                    event_count, event_bar, event_command, event_type,
                    event_status, event_related_command, i, k,
                    ORDER_EVENT_PLACE, ORDER_STATUS_PENDING, -1,
                )
            elif action == COMMAND_ACTION_REPLACE:
                target_code = command_target_order_id[k]
                target = -1
                if target_code >= 0 and target_code < n_ids:
                    target = id_to_slot[target_code]
                if target < 0 or command_status[target] != ORDER_STATUS_PENDING:
                    command_status[k] = ORDER_STATUS_REJECTED
                    reject_code[k] = REJECT_UNKNOWN_ORDER
                    rejected_bar[i] += 1
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, k,
                        ORDER_EVENT_REJECT, ORDER_STATUS_REJECTED, target,
                    )
                else:
                    active[target] = 0
                    waiting_parent[target] = 0
                    command_status[target] = ORDER_STATUS_CANCELED
                    canceled_bar[i] += 1
                    oid_code = command_order_id[k]
                    if oid_code >= 0 and oid_code < n_ids:
                        id_to_slot[oid_code] = k
                    if target_code >= 0 and target_code < n_ids:
                        id_to_slot[target_code] = k
                    active[k] = 1
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, k,
                        ORDER_EVENT_REPLACE, ORDER_STATUS_PENDING, target,
                    )
            elif action == COMMAND_ACTION_CANCEL:
                target_code = command_target_order_id[k]
                target = -1
                if target_code >= 0 and target_code < n_ids:
                    target = id_to_slot[target_code]
                if target < 0 or command_status[target] != ORDER_STATUS_PENDING:
                    command_status[k] = ORDER_STATUS_REJECTED
                    reject_code[k] = REJECT_UNKNOWN_ORDER
                    rejected_bar[i] += 1
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, k,
                        ORDER_EVENT_REJECT, ORDER_STATUS_REJECTED, target,
                    )
                else:
                    active[target] = 0
                    waiting_parent[target] = 0
                    command_status[target] = ORDER_STATUS_CANCELED
                    command_status[k] = ORDER_STATUS_FILLED
                    canceled_bar[i] += 1
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, k,
                        ORDER_EVENT_CANCEL, ORDER_STATUS_FILLED, target,
                    )
            elif action == COMMAND_ACTION_AMEND:
                target_code = command_target_order_id[k]
                target = -1
                if target_code >= 0 and target_code < n_ids:
                    target = id_to_slot[target_code]
                if target < 0 or command_status[target] != ORDER_STATUS_PENDING:
                    command_status[k] = ORDER_STATUS_REJECTED
                    reject_code[k] = REJECT_UNKNOWN_ORDER
                    rejected_bar[i] += 1
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, k,
                        ORDER_EVENT_REJECT, ORDER_STATUS_REJECTED, target,
                    )
                else:
                    if command_qty[k] > 0.0:
                        working_qty[target] = command_qty[k]
                    if command_price[k] > 0.0:
                        working_price[target] = command_price[k]
                    if command_trigger_price[k] > 0.0:
                        working_trigger[target] = command_trigger_price[k]
                    command_status[k] = ORDER_STATUS_FILLED
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, k,
                        ORDER_EVENT_AMEND, ORDER_STATUS_FILLED, target,
                    )
            elif action == COMMAND_ACTION_CANCEL_ALL:
                for target in range(n_commands):
                    if (
                        (active[target] == 1 or waiting_parent[target] == 1)
                        and command_status[target] == ORDER_STATUS_PENDING
                    ):
                        if command_symbol[k] < 0 or command_symbol[k] == command_symbol[target]:
                            active[target] = 0
                            waiting_parent[target] = 0
                            command_status[target] = ORDER_STATUS_CANCELED
                            canceled_bar[i] += 1
                command_status[k] = ORDER_STATUS_FILLED
                event_count = _record_order_event(
                    event_count, event_bar, event_command, event_type,
                    event_status, event_related_command, i, k,
                    ORDER_EVENT_CANCEL, ORDER_STATUS_FILLED, -1,
                )
            else:
                command_status[k] = ORDER_STATUS_REJECTED
                reject_code[k] = REJECT_UNSUPPORTED_ACTION
                rejected_bar[i] += 1

        # Match active order slots. Children activated by an earlier parent fill
        # can fill in the same bar if they appear later in command order.
        for oid in range(n_commands):
            if active[oid] != 1 or command_status[oid] != ORDER_STATUS_PENDING:
                continue
            action = command_action[oid]
            if action != COMMAND_ACTION_PLACE and action != COMMAND_ACTION_REPLACE:
                continue

            sym = command_symbol[oid]
            side = command_side[oid]
            otype = command_type[oid]
            tif = command_tif[oid]

            touched, exec_price = _event_v2_touched_price(
                otype, side, working_price[oid], working_trigger[oid],
                highs[i, sym], lows[i, sym], closes[i, sym], slippage,
            )

            if not touched:
                if tif == TIF_GTC or tif == TIF_GTD:
                    continue
                active[oid] = 0
                command_status[oid] = ORDER_STATUS_CANCELED
                canceled_bar[i] += 1
                event_count = _record_order_event(
                    event_count, event_bar, event_command, event_type,
                    event_status, event_related_command, i, oid,
                    ORDER_EVENT_CANCEL, ORDER_STATUS_CANCELED, -1,
                )
                continue

            qty = working_qty[oid]
            if command_reduce_only[oid] == 1:
                current = current_pos[sym]
                if current == 0.0 or (current > 0.0 and side > 0) or (current < 0.0 and side < 0):
                    active[oid] = 0
                    command_status[oid] = ORDER_STATUS_CANCELED
                    reject_code[oid] = REJECT_REDUCE_ONLY_NO_POSITION
                    canceled_bar[i] += 1
                    event_count = _record_order_event(
                        event_count, event_bar, event_command, event_type,
                        event_status, event_related_command, i, oid,
                        ORDER_EVENT_CANCEL, ORDER_STATUS_CANCELED, -1,
                    )
                    continue
                max_reduce = abs(current)
                if qty > max_reduce:
                    qty = max_reduce

            delta = qty * side
            cs = contract_sizes[sym]
            c = closes[i, sym]
            trade_notional = abs(delta) * exec_price * cs
            fee_cost = trade_notional * fee_rates[sym]

            required, cur_im = _event_margin_required(
                n_syms, current_pos, closes, contract_sizes, leverages,
                maint_ratio, i, sym, delta, exec_price, fee_cost,
            )
            if required > equity - cur_im:
                active[oid] = 0
                command_status[oid] = ORDER_STATUS_REJECTED
                reject_code[oid] = REJECT_INSUFFICIENT_MARGIN
                rejected_bar[i] += 1
                event_count = _record_order_event(
                    event_count, event_bar, event_command, event_type,
                    event_status, event_related_command, i, oid,
                    ORDER_EVENT_REJECT, ORDER_STATUS_REJECTED, -1,
                )
                continue

            equity += delta * (c - exec_price) * cs - fee_cost
            current_pos[sym] += delta

            active[oid] = 0
            command_status[oid] = ORDER_STATUS_FILLED
            fill_bar[oid] = i
            fill_qty[oid] = qty
            fill_price[oid] = exec_price
            fill_fee[oid] = fee_cost
            fee_arr[i] += fee_cost
            turnover_arr[i] += trade_notional
            event_count = _record_order_event(
                event_count, event_bar, event_command, event_type,
                event_status, event_related_command, i, oid,
                ORDER_EVENT_FILL, ORDER_STATUS_FILLED, -1,
            )

            order_id = command_order_id[oid]
            for child in range(n_commands):
                if waiting_parent[child] == 1 and command_parent_order_id[child] == order_id:
                    if (
                        command_activation[child] == ACTIVATION_ON_PARENT_FIRST_FILL
                        or command_activation[child] == ACTIVATION_ON_PARENT_FULL_FILL
                    ):
                        waiting_parent[child] = 0
                        active[child] = 1
                        event_count = _record_order_event(
                            event_count, event_bar, event_command, event_type,
                            event_status, event_related_command, i, child,
                            ORDER_EVENT_ACTIVATE, ORDER_STATUS_PENDING, oid,
                        )

            oco_group = command_oco_group_id[oid]
            if oco_group >= 0:
                for sibling in range(n_commands):
                    if sibling != oid and active[sibling] == 1 and command_status[sibling] == ORDER_STATUS_PENDING:
                        if command_oco_group_id[sibling] == oco_group:
                            active[sibling] = 0
                            waiting_parent[sibling] = 0
                            command_status[sibling] = ORDER_STATUS_CANCELED
                            canceled_bar[i] += 1
                            event_count = _record_order_event(
                                event_count, event_bar, event_command, event_type,
                                event_status, event_related_command, i, sibling,
                                ORDER_EVENT_CANCEL, ORDER_STATUS_CANCELED, oid,
                            )

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
        command_status,
        reject_code,
        fill_bar,
        fill_qty,
        fill_price,
        fill_fee,
        active,
        waiting_parent,
        working_qty,
        working_price,
        working_trigger,
        event_count,
        event_bar,
        event_command,
        event_type,
        event_status,
        event_related_command,
        liq_flag,
        liq_idx,
        liq_reason,
    )
