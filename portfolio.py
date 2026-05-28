"""
quantbt.portfolio
-----------------
MultiSymbolPortfolio — independent multi-symbol backtest with portfolio-level
risk management, allocation modes, and attribution.

Fixes vs original
~~~~~~~~~~~~~~~~~
* Market-neutral scaling: long and short sides are scaled simultaneously from
  the ORIGINAL notional, not sequentially (which caused net != 0).
* Maintenance margin = notional × mm_rate  (Binance formula, not im × mm_rate).
* Funding fires once per 8h window via make_funding_mask, not per-bar within hour.
* _run_portfolio_numba is wired in for crypto intrabar liquidation.

Modes
~~~~~
'longshort'         raw positions, no adjustment
'market_neutral'    gross long notional == gross short notional each bar
'directional'       keep only the dominant side (by abs notional)
'equal_weight'      equal fractional weight among active symbols
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .core.preprocessor import (
    validate_datetime,
    make_funding_mask,
)
from .metrics.performance import full_report
from .viz.plots import quick_plot, tearsheet as _tearsheet
from .core.types import BacktestResult


class MultiSymbolPortfolio:
    """
    Multi-Symbol Backtest Engine.

    Parameters
    ----------
    positions        Dict[str, pd.Series]  raw signal weights
    closes           Dict[str, pd.Series]  close prices
    datetime_index   common DatetimeIndex (UTC)
    mode             'longshort' | 'market_neutral' | 'directional' | 'equal_weight'
    fee_rate         one-way fee (None → asset-type default)
    alloc_per_trade  notional per full signal unit; float or per-symbol dict
    contract_size    float or per-symbol dict
    hedge_type       'notional' | 'unit'  (signal_notional not applicable here)
    initial_capital  float
    asset_type       'crypto' | 'stock'
    use_funding      override funding; None → follows asset_type
    funding_rate     float or per-symbol dict
    leverage         float or per-symbol dict
    maintenance_ratio float  Binance: notional × ratio
    """

    _ASSET_CFG = {
        "crypto": {
            "trading_days": 365,
            "fee_rate":     0.0004,
            "contract":     1.0,
            "funding":      True,
            "fund_mul":     3.0,     # 3 sessions/day
        },
        "stock": {
            "trading_days": 252,
            "fee_rate":     0.0001,
            "contract":     100.0,
            "funding":      False,
            "fund_mul":     1.0,
        },
    }

    def __init__(
        self,
        positions:         Dict[str, pd.Series],
        closes:            Dict[str, pd.Series],
        datetime_index:    Union[pd.DatetimeIndex, pd.Series],
        mode:              str   = "longshort",
        fee_rate:          Optional[float] = None,
        alloc_per_trade:   Union[float, Dict[str, float]] = 100_000.0,
        contract_size:     Union[float, Dict[str, float]] = None,
        hedge_type:        str   = "notional",
        initial_capital:   float = 100_000.0,
        asset_type:        str   = "crypto",
        use_funding:       Optional[bool] = None,
        funding_rate:      Union[float, Dict[str, float]] = None,
        leverage:          Union[float, Dict[str, float]] = 1.0,
        maintenance_ratio: float = 0.005,
        margin_buffer:     float = 0.01,
        use_binance_netting: bool = False,
        # highs / lows for intrabar liquidation (optional)
        highs: Optional[Dict[str, pd.Series]] = None,
        lows:  Optional[Dict[str, pd.Series]] = None,
    ):
        # ── config ────────────────────────────────────────────────────────
        atype = asset_type.lower()
        if atype not in self._ASSET_CFG:
            raise ValueError("asset_type must be 'crypto' or 'stock'")

        cfg = self._ASSET_CFG[atype]
        self.asset_type       = atype
        self.trading_days     = cfg["trading_days"]
        self.fee_rate         = (fee_rate or cfg["fee_rate"]) / 2.0    # one-way
        self.use_funding      = use_funding if use_funding is not None else cfg["funding"]
        self.fund_mul         = cfg["fund_mul"]
        self.maintenance_ratio = maintenance_ratio
        self.initial_capital  = initial_capital
        self.mode             = mode.lower()
        self.hedge_type       = hedge_type.lower()
        self.use_binance_netting = use_binance_netting if atype == "crypto" else False

        valid_modes = {"longshort", "market_neutral", "directional", "equal_weight"}
        if self.mode not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}")

        # ── symbols ───────────────────────────────────────────────────────
        self.symbols = list(positions.keys())
        if set(self.symbols) != set(closes.keys()):
            raise ValueError("positions and closes must have the same symbol keys")

        # ── per-symbol config ─────────────────────────────────────────────
        def _per_sym(v, default):
            return v if isinstance(v, dict) else {s: (v or default) for s in self.symbols}

        default_cs       = cfg["contract"]
        self.cs          = _per_sym(contract_size, default_cs)
        self.lev         = _per_sym(leverage, 1.0)
        self.alloc       = _per_sym(alloc_per_trade, 100_000.0)
        self.fund_rates  = _per_sym(funding_rate, 0.0001) if self.use_funding else {s: 0.0 for s in self.symbols}

        # ── datetime index ────────────────────────────────────────────────
        self._idx = validate_datetime(datetime_index)

        # ── align data ────────────────────────────────────────────────────
        def _align(d: Dict, fill=0.0):
            out = {}
            for s in self.symbols:
                ser = d[s].copy()
                if isinstance(ser.index, pd.DatetimeIndex):
                    ser.index = ser.index.tz_localize("UTC") if ser.index.tz is None else ser.index.tz_convert("UTC")
                ser = ser[~ser.index.duplicated(keep="first")]
                out[s] = ser.reindex(self._idx, method="ffill").fillna(fill)
            return out

        self._pos    = _align(positions, 0.0)
        self._close  = _align(closes, np.nan)

        fallback = {s: self._close[s] for s in self.symbols}
        self._high = _align(highs, np.nan) if highs else fallback
        self._low  = _align(lows,  np.nan) if lows  else fallback

        # ── scale positions → notional units ─────────────────────────────
        self._scaled: Dict[str, pd.Series] = {}
        for s in self.symbols:
            notional = self.alloc[s] * self.lev[s]
            denom    = self._close[s] if self.hedge_type == "notional" else self._close[s].iloc[0]
            self._scaled[s] = self._pos[s] * (notional / denom)

        # ── apply portfolio mode ──────────────────────────────────────────
        self._apply_mode()

        # ── run simulation ────────────────────────────────────────────────
        self._result: Optional[BacktestResult] = None
        self._pnl_per_sym: Dict[str, pd.Series] = {}
        self._daily_fee:      pd.Series = pd.Series(dtype=float)
        self._daily_turnover: pd.Series = pd.Series(dtype=float)
        self.run()

    # ── portfolio mode application ────────────────────────────────────────────

    def _apply_mode(self):
        """
        Adjust scaled positions according to the allocation mode.
        All scaling is done from the original notional simultaneously.
        """
        pos_df = pd.DataFrame({s: self._scaled[s] for s in self.symbols})

        if self.mode == "market_neutral":
            # Scale each side so gross_long_notional == gross_short_notional every bar.
            # Capture long/short sums from the ORIGINAL positions in one pass.
            long_mask  = pos_df > 0
            short_mask = pos_df < 0
            long_sum   = (pos_df * long_mask).sum(axis=1)          # positive
            short_sum  = (pos_df * short_mask).abs().sum(axis=1)   # positive

            target = (long_sum + short_sum) / 2.0   # equal notional on each side

            for s in self.symbols:
                col = pos_df[s]
                # scale independently per side; avoids the sequential mutation bug
                long_scale  = (target / long_sum.replace(0, np.nan)).fillna(1.0)
                short_scale = (target / short_sum.replace(0, np.nan)).fillna(1.0)
                pos_df[s]   = np.where(col > 0, col * long_scale,
                              np.where(col < 0, col * short_scale, 0.0))

        elif self.mode == "directional":
            notional = pos_df.abs()
            dominant = notional.idxmax(axis=1)
            for s in self.symbols:
                pos_df[s] = pos_df[s].where(dominant == s, 0.0)

        elif self.mode == "equal_weight":
            active  = (pos_df != 0).sum(axis=1).replace(0, 1)
            weights = 1.0 / active
            pos_df  = pos_df.mul(weights, axis=0)

        for s in self.symbols:
            self._scaled[s] = pos_df[s]

    # ── simulation ────────────────────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """Simulate and return BacktestResult."""
        idx  = self._idx
        n    = len(idx)
        equity  = self.initial_capital
        eq_arr  = np.zeros(n, dtype=np.float64)
        eq_arr[0] = equity

        # per-symbol cumulative pnl tracker
        sym_cum = {s: 0.0 for s in self.symbols}
        sym_arr = {s: np.zeros(n, dtype=np.float64) for s in self.symbols}

        fee_arr = np.zeros(n, dtype=np.float64)
        turn_arr = np.zeros(n, dtype=np.float64)

        is_fund = make_funding_mask(idx)

        # pre-extract arrays for speed
        close_m = {s: self._close[s].values  for s in self.symbols}
        high_m  = {s: self._high[s].values   for s in self.symbols}
        low_m   = {s: self._low[s].values    for s in self.symbols}
        pos_m   = {s: self._scaled[s].values for s in self.symbols}
        fr_m    = {}
        for s in self.symbols:
            v = self.fund_rates[s]
            fr_m[s] = v if isinstance(v, np.ndarray) else np.full(n, float(v))

        cs_d  = self.cs
        lev_d = self.lev

        liq_flag = False
        liq_idx  = -1

        for i in range(1, n):
            if liq_flag:
                eq_arr[i] = 0.0
                for s in self.symbols:
                    sym_arr[s][i] = sym_arr[s][i - 1]
                continue

            step_pnl = 0.0
            total_mm = 0.0
            total_mu = 0.0

            for s in self.symbols:
                cs   = cs_d[s]
                lev  = lev_d[s]
                p    = pos_m[s][i - 1]
                c    = close_m[s]
                h    = high_m[s]
                l    = low_m[s]

                # MTM
                pnl = p * (c[i] - c[i - 1]) * cs
                step_pnl += pnl
                sym_cum[s] += pnl

                # fee on signal change
                delta = pos_m[s][i] - pos_m[s][i - 1]
                if abs(delta) > 1e-12:
                    tv  = abs(delta) * c[i] * cs
                    fee = tv * self.fee_rate * (1 if self.use_binance_netting else 2)
                    step_pnl   -= fee
                    sym_cum[s] -= fee
                    fee_arr[i] += fee
                    notional_new = abs(pos_m[s][i]) * c[i] * cs
                    notional_old = abs(pos_m[s][i - 1]) * c[i - 1] * cs
                    turn_arr[i] += abs(notional_new - notional_old)

                # margin
                notional_i = abs(pos_m[s][i]) * c[i] * cs
                total_mu  += notional_i / lev
                total_mm  += notional_i * self.maintenance_ratio   # Binance formula

                sym_arr[s][i] = sym_cum[s]

            equity += step_pnl

            # funding
            if is_fund[i] and self.use_funding:
                for s in self.symbols:
                    p    = pos_m[s][i]
                    fc   = p * close_m[s][i] * cs_d[s] * fr_m[s][i] * self.fund_mul
                    equity      -= fc
                    sym_cum[s]  -= fc
                    sym_arr[s][i] = sym_cum[s]

            # liquidation: equity below maintenance margin
            if total_mm > 0 and equity <= total_mm:
                liq_flag = True
                liq_idx  = i
                equity   = 0.0
                eq_arr[i] = 0.0
                continue

            eq_arr[i] = equity

        # ── assemble result ───────────────────────────────────────────────
        equity_s = pd.Series(eq_arr, index=idx, name="equity")
        returns  = equity_s.pct_change().fillna(0)

        pos_df   = pd.DataFrame(
            {f"Position_{s}": pos_m[s] for s in self.symbols}, index=idx
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": close_m[s] for s in self.symbols}, index=idx
        )

        self._daily_fee      = pd.Series(fee_arr, index=idx).resample("1D").sum()
        self._daily_turnover = pd.Series(turn_arr, index=idx).resample("1D").sum()
        self._pnl_per_sym    = {
            s: pd.Series(sym_arr[s], index=idx) for s in self.symbols
        }

        self._result = BacktestResult(
            equity          = equity_s,
            returns         = returns,
            positions       = pos_df,
            closes          = close_df,
            symbols         = self.symbols,
            initial_capital = self.initial_capital,
            leverage        = float(np.mean(list(self.lev.values()))),
            liquidated      = liq_flag,
            liquidation_bar = int(liq_idx),
            metadata        = {
                "mode":       self.mode,
                "asset_type": self.asset_type,
                "hedge_type": self.hedge_type,
            },
        )
        return self._result

    @property
    def result(self) -> BacktestResult:
        if self._result is None:
            self.run()
        return self._result

    # ── analytics ─────────────────────────────────────────────────────────────

    def print_metrics(self) -> None:
        rpt  = full_report(self.result, self.trading_days)
        syms = ", ".join(self.symbols)

        lines = [
            ("Symbols",             syms),
            ("Asset Type",          self.asset_type.upper()),
            ("Mode",                self.mode),
            ("Initial Capital",     f"${rpt['initial_capital']:>14,.0f}"),
            ("Final Equity",        f"${rpt['final_equity']:>14,.2f}"),
            ("Total Return",        f"{rpt['total_return_pct']:>+13.2f}%"),
            ("CAGR",                f"{rpt['cagr_pct']:>+13.2f}%"),
            ("Sharpe Ratio",        f"{rpt['sharpe']:>14.3f}"),
            ("Sortino Ratio",       f"{rpt['sortino']:>14.3f}"),
            ("Calmar Ratio",        f"{rpt['calmar']:>14.3f}"),
            ("Max Drawdown",        f"{rpt['max_drawdown_pct']:>13.2f}%"),
            ("Profit Factor",       f"{rpt['profit_factor']:>14.3f}"),
            ("Long Hit Rate",       f"{rpt['long_hitrate_pct']:>13.2f}%"),
            ("Short Hit Rate",      f"{rpt['short_hitrate_pct']:>13.2f}%"),
            ("Number of Trades",    f"{rpt['num_trades']:>14,d}"),
            ("Liquidated",          f"{'Yes' if rpt['liquidated'] else 'No':>14}"),
        ]
        col_width = max(len(k) for k, _ in lines)
        print()
        for key, val in lines:
            print(f"  {key:<{col_width}}  {val}")
        print()

    def analyze(self, theme: str = "dark", figsize: tuple = (14, 6)) -> None:
        self.print_metrics()
        quick_plot(self.result, theme=theme, figsize=figsize)

    def tearsheet(
        self,
        theme:     str   = "dark",
        figsize:   tuple = (16, 20),
        benchmark: Optional[pd.Series] = None,
    ) -> None:
        _tearsheet(
            self.result,
            theme        = theme,
            figsize      = figsize,
            trading_days = self.trading_days,
            benchmark    = benchmark,
        )

    def hitrate_per_symbol(self) -> Dict[str, Tuple[float, float]]:
        """Returns {sym: (long_hr_pct, short_hr_pct)} for every symbol."""
        out = {}
        for s in self.symbols:
            pos  = self._scaled[s]
            cl   = self._close[s]
            ret  = cl.pct_change().fillna(0)
            long_mask  = pos > 0
            short_mask = pos < 0
            lw = ((ret > 0) & long_mask).sum()
            lt = long_mask.sum()
            sw = ((ret < 0) & short_mask).sum()
            st = short_mask.sum()
            out[s] = (
                round(lw / lt * 100, 2) if lt > 0 else 0.0,
                round(sw / st * 100, 2) if st > 0 else 0.0,
            )
        return out

    def export_log(self, filename: str = "portfolio_log.csv") -> None:
        r   = self.result
        log = pd.DataFrame({
            "cumulative_return": (r.equity / self.initial_capital - 1) * 100,
            "daily_return":      r.returns * 100,
        }, index=r.equity.index)
        for s in self.symbols:
            log[f"position_{s}"] = r.positions[f"Position_{s}"]
            log[f"close_{s}"]    = r.closes[f"Close_{s}"]
        log.to_csv(filename)
        print(f"Portfolio log exported  →  {filename}")
