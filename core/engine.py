"""
quantbt.core.engine
-------------------
Numba-compiled simulation kernels.

Kernel entry points
~~~~~~~~~~~~~~~~~~~
_engine_units       signals are pre-scaled target units (notional / unit / signal_notional)
_engine_pct_equity  signals are raw weight fractions; units derived from live equity each bar
_engine_dca_ladder  structural DCA/grid level with High/Low limit fills
_engine_portfolio   multi-symbol portfolio loop with cross-margin buying-power gate

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
            maint_req += abs(p) * worst_p * contract_sizes[s] * maint_ratio

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

        # Funding can push equity below maintenance before new orders.
        close_maint_req = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                close_maint_req += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if close_maint_req > 0.0 and equity <= close_maint_req:
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
            equity_curve[i] = 0.0
            continue

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

            old_im = abs(current_pos[s]) * closes[i, s] * contract_sizes[s] / leverage
            new_im = abs(target) * exec_p * contract_sizes[s] / leverage
            required = (new_im - old_im) + fee_cost + slip_cost

            if required > avail:
                continue  # order rejected: insufficient margin

            equity -= fee_cost + slip_cost
            current_pos[s] = target
            avail -= required

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
            maint_req += abs(p) * worst_p * contract_sizes[s] * maint_ratio

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

        close_maint_req = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                close_maint_req += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if close_maint_req > 0.0 and equity <= close_maint_req:
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
            equity_curve[i] = 0.0
            continue

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

            old_im = abs(current_pos[s]) * closes[i, s] * contract_sizes[s] / leverage
            new_im = abs(target) * exec_p * contract_sizes[s] / leverage
            required = (new_im - old_im) + fee_cost + slip_cost

            if required > avail:
                continue

            equity -= fee_cost + slip_cost
            current_pos[s] = target
            avail -= required

        equity_curve[i] = equity

    return equity_curve, liq_flag, liq_idx


@njit(cache=True)
def _dca_check_liquidation(
    n_syms:         int,
    i:              int,
    equity:         float,
    current_pos:    np.ndarray,
    highs:          np.ndarray,
    lows:           np.ndarray,
    closes:         np.ndarray,
    contract_sizes: np.ndarray,
    maint_ratio:    float,
):
    worst_equity = equity
    maint_req    = 0.0
    for s in range(n_syms):
        p = current_pos[s]
        if p == 0.0:
            continue
        worst_p = lows[i, s] if p > 0.0 else highs[i, s]
        worst_equity += p * (worst_p - closes[i, s]) * contract_sizes[s]
        maint_req += abs(p) * worst_p * contract_sizes[s] * maint_ratio

    return maint_req > 0.0 and worst_equity <= maint_req


@njit(cache=True)
def _engine_dca_ladder(
    n_bars:              int,
    n_syms:              int,
    highs:               np.ndarray,
    lows:                np.ndarray,
    closes:              np.ndarray,
    signals:             np.ndarray,   # signed desired structural level
    funding_rates:       np.ndarray,
    is_funding_bar:      np.ndarray,
    init_capital:        float,
    leverage:            float,
    maint_ratio:         float,
    fee_rate:            float,
    contract_sizes:      np.ndarray,
    market_slippage:     float,
    base_notional:       np.ndarray,
    safety_notional:     np.ndarray,
    step_pct:            np.ndarray,
    step_scale:          np.ndarray,
    volume_scale:        np.ndarray,
    max_safety_orders:   int,
    take_profit_pct:     np.ndarray,
    allow_same_bar_exit: bool,
):
    """
    DCA ladder execution model.

    signals are structural caps, not target units:
        +N enables a long ladder up to level N, -N enables a short ladder.
        level 1 is the base order; levels 2..N are safety orders.

    Base orders and signal-zero exits execute as market-at-close with
    market_slippage. Safety orders and take-profit exits are limit fills at
    their trigger prices when High/Low touches them.
    """
    equity_curve = np.zeros(n_bars, dtype=np.float64)
    pos_out      = np.zeros((n_bars, n_syms), dtype=np.float64)
    level_out    = np.zeros((n_bars, n_syms), dtype=np.float64)

    equity       = init_capital
    current_pos  = np.zeros(n_syms, dtype=np.float64)
    current_side = np.zeros(n_syms, dtype=np.int64)
    current_lvl  = np.zeros(n_syms, dtype=np.int64)
    anchor_price = np.zeros(n_syms, dtype=np.float64)
    avg_entry    = np.zeros(n_syms, dtype=np.float64)

    liq_flag = False
    liq_idx  = -1

    equity_curve[0] = equity

    for i in range(1, n_bars):
        if liq_flag:
            equity_curve[i] = 0.0
            for s in range(n_syms):
                pos_out[i, s] = 0.0
                level_out[i, s] = 0.0
            continue

        # 1. Mark existing positions to current close.
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                equity += p * (closes[i, s] - closes[i - 1, s]) * contract_sizes[s]

        # 2. Existing-book liquidation before any new ladder orders.
        if _dca_check_liquidation(
            n_syms, i, equity, current_pos, highs, lows, closes,
            contract_sizes, maint_ratio
        ):
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                current_side[s] = 0
                current_lvl[s] = 0
                pos_out[i, s] = 0.0
                level_out[i, s] = 0.0
            equity_curve[i] = 0.0
            continue

        # 3. Funding on the position carried into the funding timestamp.
        if is_funding_bar[i]:
            for s in range(n_syms):
                p = current_pos[s]
                if p != 0.0:
                    equity -= p * closes[i, s] * contract_sizes[s] * funding_rates[i, s]

        close_maint_req = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                close_maint_req += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if close_maint_req > 0.0 and equity <= close_maint_req:
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                current_side[s] = 0
                current_lvl[s] = 0
                pos_out[i, s] = 0.0
                level_out[i, s] = 0.0
            equity_curve[i] = 0.0
            continue

        # 4. Execute structural DCA state.
        for s in range(n_syms):
            c  = closes[i, s]
            hi = highs[i, s]
            lo = lows[i, s]
            cs = contract_sizes[s]

            if c <= 0.0 or cs <= 0.0:
                continue

            raw_sig = signals[i, s]
            desired_side = 0
            if raw_sig > 0.0:
                desired_side = 1
            elif raw_sig < 0.0:
                desired_side = -1

            desired_level = int(abs(raw_sig))
            max_level = max_safety_orders + 1
            if desired_level > max_level:
                desired_level = max_level

            # Existing ladder TP has priority over a later close/flip signal.
            if current_lvl[s] > 0 and take_profit_pct[s] > 0.0:
                tp = avg_entry[s] * (
                    1.0 + take_profit_pct[s] if current_side[s] > 0
                    else 1.0 - take_profit_pct[s]
                )
                hit_tp = False
                if current_side[s] > 0 and hi >= tp:
                    hit_tp = True
                elif current_side[s] < 0 and lo <= tp:
                    hit_tp = True

                if hit_tp:
                    delta = -current_pos[s]
                    fee_cost = abs(delta) * tp * cs * fee_rate
                    equity += delta * (c - tp) * cs - fee_cost
                    current_pos[s] = 0.0
                    current_side[s] = 0
                    current_lvl[s] = 0
                    anchor_price[s] = 0.0
                    avg_entry[s] = 0.0

            # Signal-side change or signal flat closes the existing ladder.
            if current_lvl[s] > 0 and desired_side != current_side[s]:
                delta = -current_pos[s]
                exec_p = c
                if delta > 0.0:
                    exec_p = c * (1.0 + market_slippage)
                elif delta < 0.0:
                    exec_p = c * (1.0 - market_slippage)
                fee_cost = abs(delta) * exec_p * cs * fee_rate
                equity += delta * (c - exec_p) * cs - fee_cost
                current_pos[s] = 0.0
                current_side[s] = 0
                current_lvl[s] = 0
                anchor_price[s] = 0.0
                avg_entry[s] = 0.0

            if desired_side == 0 or desired_level == 0:
                continue

            filled_this_bar = False
            started_this_bar = False

            # Base order: market-at-close when a cycle starts.
            if current_lvl[s] == 0:
                delta = desired_side * base_notional[s] / c
                exec_p = c * (1.0 + market_slippage if delta > 0.0 else 1.0 - market_slippage)

                cur_im = 0.0
                for k in range(n_syms):
                    cur_im += abs(current_pos[k]) * closes[i, k] * contract_sizes[k] / leverage
                avail = equity - cur_im
                im_needed = abs(delta) * exec_p * cs / leverage

                fee_cost = abs(delta) * exec_p * cs * fee_rate
                slip_cost = abs(delta) * abs(exec_p - c) * cs

                if im_needed + fee_cost + slip_cost <= avail:
                    equity += delta * (c - exec_p) * cs - fee_cost
                    current_pos[s] = delta
                    current_side[s] = desired_side
                    current_lvl[s] = 1
                    anchor_price[s] = exec_p
                    avg_entry[s] = exec_p
                    filled_this_bar = True
                    started_this_bar = True

            # Safety orders: limit fills at the structural grid prices.
            while current_lvl[s] > 0 and current_lvl[s] < desired_level and not started_this_bar:
                next_level = current_lvl[s] + 1
                ao_idx = next_level - 2

                dev = 0.0
                step = step_pct[s]
                for k in range(ao_idx + 1):
                    dev += step
                    step *= step_scale[s]

                trigger = anchor_price[s] * (1.0 - dev if current_side[s] > 0 else 1.0 + dev)
                if trigger <= 0.0:
                    break

                touched = False
                if current_side[s] > 0 and lo <= trigger:
                    touched = True
                elif current_side[s] < 0 and hi >= trigger:
                    touched = True

                if not touched:
                    break

                notional = safety_notional[s]
                mult = 1.0
                for k in range(ao_idx):
                    mult *= volume_scale[s]
                notional *= mult

                delta = current_side[s] * notional / trigger

                cur_im = 0.0
                for k in range(n_syms):
                    cur_im += abs(current_pos[k]) * closes[i, k] * contract_sizes[k] / leverage
                avail = equity - cur_im
                im_needed = abs(delta) * trigger * cs / leverage
                fee_cost = abs(delta) * trigger * cs * fee_rate

                if im_needed + fee_cost > avail:
                    break

                old_abs = abs(current_pos[s])
                add_abs = abs(delta)
                equity += delta * (c - trigger) * cs - fee_cost
                current_pos[s] += delta
                avg_entry[s] = ((avg_entry[s] * old_abs) + (trigger * add_abs)) / (old_abs + add_abs)
                current_lvl[s] = next_level
                filled_this_bar = True

            # Take-profit: limit exit from weighted average entry.
            if (
                current_lvl[s] > 0
                and take_profit_pct[s] > 0.0
                and (allow_same_bar_exit or not filled_this_bar)
            ):
                tp = avg_entry[s] * (
                    1.0 + take_profit_pct[s] if current_side[s] > 0
                    else 1.0 - take_profit_pct[s]
                )
                hit_tp = False
                if current_side[s] > 0 and hi >= tp:
                    hit_tp = True
                elif current_side[s] < 0 and lo <= tp:
                    hit_tp = True

                if hit_tp:
                    delta = -current_pos[s]
                    fee_cost = abs(delta) * tp * cs * fee_rate
                    equity += delta * (c - tp) * cs - fee_cost
                    current_pos[s] = 0.0
                    current_side[s] = 0
                    current_lvl[s] = 0
                    anchor_price[s] = 0.0
                    avg_entry[s] = 0.0

        # 5. Conservative post-fill liquidation on same-bar extremes.
        if _dca_check_liquidation(
            n_syms, i, equity, current_pos, highs, lows, closes,
            contract_sizes, maint_ratio
        ):
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                current_side[s] = 0
                current_lvl[s] = 0
                pos_out[i, s] = 0.0
                level_out[i, s] = 0.0
            equity_curve[i] = 0.0
            continue

        for s in range(n_syms):
            pos_out[i, s] = current_pos[s]
            level_out[i, s] = current_side[s] * current_lvl[s]

        equity_curve[i] = equity

    return equity_curve, pos_out, level_out, liq_flag, liq_idx


@njit(cache=True)
def _engine_portfolio(
    n_bars:          int,
    n_syms:          int,
    highs:           np.ndarray,
    lows:            np.ndarray,
    closes:          np.ndarray,
    target_pos:      np.ndarray,
    funding_rates:   np.ndarray,
    is_funding_bar:  np.ndarray,
    init_capital:    float,
    leverages:       np.ndarray,
    maint_ratio:     float,
    fee_rate:        float,
    contract_sizes:  np.ndarray,
    use_funding:     bool,
):
    """
    Numba portfolio simulation kernel.

    target_pos is a pre-built units matrix after portfolio allocation mode.
    The kernel applies cross-margin buying-power gates and returns the actual
    accepted positions, equity, per-symbol cumulative PnL, fees, and turnover.
    """
    equity_curve = np.zeros(n_bars, dtype=np.float64)
    pos_out      = np.zeros((n_bars, n_syms), dtype=np.float64)
    sym_pnl      = np.zeros((n_bars, n_syms), dtype=np.float64)
    fee_arr      = np.zeros(n_bars, dtype=np.float64)
    turn_arr     = np.zeros(n_bars, dtype=np.float64)

    current_pos  = np.zeros(n_syms, dtype=np.float64)
    current_pnl  = np.zeros(n_syms, dtype=np.float64)
    equity       = init_capital
    liq_flag     = False
    liq_idx      = -1

    equity_curve[0] = equity

    for i in range(1, n_bars):
        if liq_flag:
            equity_curve[i] = 0.0
            for s in range(n_syms):
                pos_out[i, s] = 0.0
                sym_pnl[i, s] = current_pnl[s]
            continue

        # 1. Mark carried positions to close.
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                pnl = p * (closes[i, s] - closes[i - 1, s]) * contract_sizes[s]
                equity += pnl
                current_pnl[s] += pnl

        # 2. Intrabar liquidation using worst price.
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
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
                sym_pnl[i, s] = current_pnl[s]
            equity_curve[i] = 0.0
            continue

        # 3. Funding on carried positions. Funding rates are per event.
        if is_funding_bar[i] and use_funding:
            for s in range(n_syms):
                p = current_pos[s]
                if p != 0.0:
                    fc = p * closes[i, s] * contract_sizes[s] * funding_rates[i, s]
                    equity -= fc
                    current_pnl[s] -= fc

        close_mm = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                close_mm += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if close_mm > 0.0 and equity <= close_mm:
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
                sym_pnl[i, s] = current_pnl[s]
            equity_curve[i] = 0.0
            continue

        # 4. Cross-margin buying-power gate for target portfolio.
        cur_im = 0.0
        target_im = 0.0
        fee_est = 0.0
        for s in range(n_syms):
            c = closes[i, s]
            cs = contract_sizes[s]
            lev = leverages[s]
            cur_im += abs(current_pos[s]) * c * cs / lev
            target_im += abs(target_pos[i, s]) * c * cs / lev

            delta = target_pos[i, s] - current_pos[s]
            if abs(delta) > 1e-12:
                fee_est += abs(delta) * c * cs * fee_rate

        can_rebalance = True
        if target_im > cur_im and (target_im - cur_im) + fee_est > equity - cur_im:
            can_rebalance = False

        # 5. Execute accepted target at close.
        if can_rebalance:
            for s in range(n_syms):
                c = closes[i, s]
                cs = contract_sizes[s]
                delta = target_pos[i, s] - current_pos[s]
                if abs(delta) > 1e-12:
                    tv = abs(delta) * c * cs
                    fee = tv * fee_rate
                    equity -= fee
                    current_pnl[s] -= fee
                    fee_arr[i] += fee

                    old_notional = abs(current_pos[s]) * c * cs
                    new_notional = abs(target_pos[i, s]) * c * cs
                    turn_arr[i] += abs(new_notional - old_notional)
                    current_pos[s] = target_pos[i, s]

        # 6. Post-fee maintenance check.
        close_mm = 0.0
        for s in range(n_syms):
            p = current_pos[s]
            if p != 0.0:
                close_mm += abs(p) * closes[i, s] * contract_sizes[s] * maint_ratio

        if close_mm > 0.0 and equity <= close_mm:
            liq_flag = True
            liq_idx  = i
            equity   = 0.0
            for s in range(n_syms):
                current_pos[s] = 0.0
                pos_out[i, s] = 0.0
                sym_pnl[i, s] = current_pnl[s]
            equity_curve[i] = 0.0
            continue

        for s in range(n_syms):
            pos_out[i, s] = current_pos[s]
            sym_pnl[i, s] = current_pnl[s]

        equity_curve[i] = equity

    return equity_curve, pos_out, sym_pnl, fee_arr, turn_arr, liq_flag, liq_idx
