"""
quantbt.portfolio
-----------------
MultiSymbolPortfolio — independent multi-symbol backtest with portfolio-level
risk management, allocation modes, and attribution.

Fixes vs original
~~~~~~~~~~~~~~~~~
* Signal-notional portfolio sizing freezes units until signal changes, avoiding
  price-drift micro-rebalancing.
* Market-neutral scaling: long and short sides are scaled simultaneously from
  the ORIGINAL signed notional, not unit counts.
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
from .core.engine import _engine_portfolio
from .sizing.modes import compute_target_units


class MultiSymbolPortfolio:
    """
    Multi-Symbol Backtest Engine.

    Parameters
    ----------
    positions        Dict[str, pd.Series]  raw signal weights
    closes           Dict[str, pd.Series]  close prices
    datetime_index   common DatetimeIndex (UTC)
    mode             'longshort' | 'market_neutral' | 'directional' | 'equal_weight'
    fee_rate         round-trip fee; halved internally to one-way
    alloc_per_trade  notional per full signal unit; float or per-symbol dict
    contract_size    float or per-symbol dict
    hedge_type       'signal_notional' | 'notional' | 'unit'
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
        },
        "stock": {
            "trading_days": 252,
            "fee_rate":     0.0001,
            "contract":     100.0,
            "funding":      False,
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
        hedge_type:        str   = "signal_notional",
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
        self.fee_rate         = (fee_rate if fee_rate is not None else cfg["fee_rate"]) / 2.0    # one-way
        self.use_funding      = use_funding if use_funding is not None else cfg["funding"]
        self.maintenance_ratio = maintenance_ratio
        self.initial_capital  = initial_capital
        self.mode             = mode.lower()
        self.hedge_type       = hedge_type.lower()
        self.use_binance_netting = use_binance_netting if atype == "crypto" else False

        valid_modes = {"longshort", "market_neutral", "directional", "equal_weight"}
        if self.mode not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}")
        valid_hedge_types = {"signal_notional", "signal", "notional", "unit"}
        if self.hedge_type not in valid_hedge_types:
            raise ValueError(f"portfolio hedge_type must be one of {valid_hedge_types}")

        # ── symbols ───────────────────────────────────────────────────────
        self.symbols = list(positions.keys())
        if set(self.symbols) != set(closes.keys()):
            raise ValueError("positions and closes must have the same symbol keys")

        # ── per-symbol config ─────────────────────────────────────────────
        def _per_sym(v, default):
            return v if isinstance(v, dict) else {s: (default if v is None else v) for s in self.symbols}

        default_cs       = cfg["contract"]
        self.cs          = _per_sym(contract_size, default_cs)
        self.lev         = _per_sym(leverage, 1.0)
        self.alloc       = _per_sym(alloc_per_trade, 100_000.0)
        self.fund_rates  = _per_sym(funding_rate, 0.0001) if self.use_funding else {s: 0.0 for s in self.symbols}

        if initial_capital <= 0.0:
            raise ValueError("initial_capital must be > 0")
        if any(v <= 0.0 for v in self.lev.values()):
            raise ValueError("leverage must be > 0")
        if any(v <= 0.0 for v in self.cs.values()):
            raise ValueError("contract_size must be > 0")
        if any(v < 0.0 for v in self.alloc.values()):
            raise ValueError("alloc_per_trade must be >= 0")
        if maintenance_ratio < 0.0:
            raise ValueError("maintenance_ratio must be >= 0")

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
            self._scaled[s] = compute_target_units(
                hedge_type=self.hedge_type,
                signal=self._pos[s],
                close=self._close[s],
                alloc=self.alloc[s],
                use_pyramiding=True,
            )

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
        close_df = pd.DataFrame({s: self._close[s] for s in self.symbols})
        cs = pd.Series({s: float(self.cs[s]) for s in self.symbols})

        def _signed_notional(units: pd.DataFrame) -> pd.DataFrame:
            return units.mul(close_df, axis=0).mul(cs, axis=1)

        if self.mode == "market_neutral":
            # Scale each side so gross_long_notional == gross_short_notional every bar.
            # Capture long/short sums from the ORIGINAL signed notional in one pass.
            notional_df = _signed_notional(pos_df)
            long_mask  = notional_df > 0
            short_mask = notional_df < 0
            long_sum   = (notional_df * long_mask).sum(axis=1)          # positive
            short_sum  = (notional_df * short_mask).abs().sum(axis=1)   # positive

            target = (long_sum + short_sum) / 2.0   # equal notional on each side

            for s in self.symbols:
                col = notional_df[s]
                original_units = pos_df[s]
                # scale independently per side; avoids the sequential mutation bug
                long_scale  = (target / long_sum.replace(0, np.nan)).fillna(1.0)
                short_scale = (target / short_sum.replace(0, np.nan)).fillna(1.0)
                pos_df[s]   = np.where(col > 0, original_units * long_scale,
                              np.where(col < 0, original_units * short_scale, 0.0))

        elif self.mode == "directional":
            notional = _signed_notional(pos_df).abs()
            dominant = notional.idxmax(axis=1)
            for s in self.symbols:
                pos_df[s] = pos_df[s].where(dominant == s, 0.0)

        elif self.mode == "equal_weight":
            notional_df = _signed_notional(pos_df)
            active = (notional_df != 0).sum(axis=1)
            gross = notional_df.abs().sum(axis=1)
            target_abs = (gross / active.replace(0, np.nan)).fillna(0.0)
            for s in self.symbols:
                denom = (close_df[s] * float(self.cs[s])).replace(0.0, np.nan)
                sign = np.sign(notional_df[s])
                pos_df[s] = (sign * target_abs / denom).fillna(0.0)

        for s in self.symbols:
            self._scaled[s] = pos_df[s]

    def run(self) -> BacktestResult:
        """Simulate and return BacktestResult."""
        idx  = self._idx
        n    = len(idx)
        m    = len(self.symbols)
        is_fund = make_funding_mask(idx)

        closes_m = np.zeros((n, m), dtype=np.float64)
        highs_m  = np.zeros((n, m), dtype=np.float64)
        lows_m   = np.zeros((n, m), dtype=np.float64)
        target_m = np.zeros((n, m), dtype=np.float64)
        funding_m = np.zeros((n, m), dtype=np.float64)
        cs_arr   = np.zeros(m, dtype=np.float64)
        lev_arr  = np.zeros(m, dtype=np.float64)

        for j, s in enumerate(self.symbols):
            closes_m[:, j] = self._close[s].fillna(0.0).values
            highs_m[:, j]  = self._high[s].fillna(self._close[s]).values
            lows_m[:, j]   = self._low[s].fillna(self._close[s]).values
            target_m[:, j] = self._scaled[s].fillna(0.0).values
            cs_arr[j]      = float(self.cs[s])
            lev_arr[j]     = float(self.lev[s])

            fr = self.fund_rates[s]
            if isinstance(fr, pd.Series):
                ser = fr.copy()
                if isinstance(ser.index, pd.DatetimeIndex):
                    ser.index = ser.index.tz_localize("UTC") if ser.index.tz is None else ser.index.tz_convert("UTC")
                funding_m[:, j] = ser.reindex(idx, method="ffill").fillna(0.0).values
            elif isinstance(fr, np.ndarray):
                if len(fr) != n:
                    raise ValueError(f"funding_rate array for {s} must have length {n}")
                funding_m[:, j] = fr.astype(np.float64)
            else:
                funding_m[:, j] = float(fr)

        (
            eq_arr,
            pos_arr,
            sym_arr,
            fee_arr,
            _slippage_arr,
            turn_arr,
            liq_flag,
            liq_idx,
        ) = _engine_portfolio(
            n_bars         = n,
            n_syms         = m,
            highs          = highs_m,
            lows           = lows_m,
            closes         = closes_m,
            target_pos     = target_m,
            funding_rates  = funding_m,
            is_funding_bar = is_fund,
            init_capital   = self.initial_capital,
            leverages      = lev_arr,
            maint_ratio    = self.maintenance_ratio,
            fee_rate       = self.fee_rate,
            slippage_rate  = 0.0,
            contract_sizes = cs_arr,
            use_funding    = bool(self.use_funding),
            tradable       = np.ones((n, m), dtype=np.bool_),
        )

        # ── assemble result ───────────────────────────────────────────────
        equity_s = pd.Series(eq_arr, index=idx, name="equity")
        returns  = equity_s.pct_change().fillna(0)

        pos_df   = pd.DataFrame(
            {f"Position_{s}": pos_arr[:, j] for j, s in enumerate(self.symbols)}, index=idx
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": closes_m[:, j] for j, s in enumerate(self.symbols)}, index=idx
        )

        self._daily_fee      = pd.Series(fee_arr, index=idx).resample("1D").sum()
        self._daily_turnover = pd.Series(turn_arr, index=idx).resample("1D").sum()
        self._pnl_per_sym    = {
            s: pd.Series(sym_arr[:, j], index=idx) for j, s in enumerate(self.symbols)
        }
        target_units_report = pd.DataFrame(
            {s: target_m[:, j] for j, s in enumerate(self.symbols)}, index=idx
        )
        accepted_units_report = pd.DataFrame(
            {s: pos_arr[:, j] for j, s in enumerate(self.symbols)}, index=idx
        )
        close_report = pd.DataFrame(
            {s: closes_m[:, j] for j, s in enumerate(self.symbols)}, index=idx
        )
        symbol_pnl_report = self._build_symbol_pnl_report(
            accepted_units=accepted_units_report,
            closes=close_report,
            funding_rates=pd.DataFrame({s: funding_m[:, j] for j, s in enumerate(self.symbols)}, index=idx),
            is_funding_bar=pd.Series(is_fund, index=idx),
        )
        exposure_report = self._build_exposure_report(
            accepted_units=accepted_units_report,
            target_units=target_units_report,
            closes=close_report,
            equity=equity_s,
        )
        rebalance_report = self._build_rebalance_report(
            target_units=target_units_report,
            accepted_units=accepted_units_report,
            closes=close_report,
        )

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
                "mode":                 self.mode,
                "asset_type":           self.asset_type,
                "hedge_type":           self.hedge_type,
                "engine":               "numba_portfolio",
                "initial_buying_power": self.initial_capital * float(np.mean(list(self.lev.values()))),
                "funding_rate_unit":    "per_event",
                "target_units_report":  target_units_report,
                "accepted_units_report": accepted_units_report,
                "target_notional_report": target_units_report.mul(close_report, axis=0).mul(pd.Series(self.cs), axis=1),
                "accepted_notional_report": accepted_units_report.mul(close_report, axis=0).mul(pd.Series(self.cs), axis=1),
                "exposure_report":      exposure_report,
                "symbol_pnl_report":    symbol_pnl_report,
                "rebalance_report":     rebalance_report,
                "fee_series":           pd.Series(fee_arr, index=idx, name="fee"),
                "turnover_series":      pd.Series(turn_arr, index=idx, name="turnover"),
                "fee_total":            float(np.sum(fee_arr)),
                "turnover_total":       float(np.sum(turn_arr)),
            },
        )
        return self._result

    def _build_symbol_pnl_report(
        self,
        accepted_units: pd.DataFrame,
        closes: pd.DataFrame,
        funding_rates: pd.DataFrame,
        is_funding_bar: pd.Series,
    ) -> pd.DataFrame:
        frames = []
        funding_mask = is_funding_bar.astype(bool) & bool(self.use_funding)
        for s in self.symbols:
            units = accepted_units[s].astype(float)
            close = closes[s].astype(float)
            prev_units = units.shift(1).fillna(0.0)
            prev_close = close.shift(1).fillna(close)
            delta = units.diff().fillna(units)
            cs = float(self.cs[s])
            mark_pnl = prev_units * (close - prev_close) * cs
            funding_cost = prev_units * close * cs * funding_rates[s].astype(float)
            funding_cost = funding_cost.where(funding_mask, 0.0)
            fee = delta.abs() * close * cs * float(self.fee_rate)
            total_pnl = mark_pnl - funding_cost - fee
            frame = pd.DataFrame(
                {
                    "timestamp": self._idx,
                    "symbol": s,
                    "position_units": units.to_numpy(dtype=float),
                    "close": close.to_numpy(dtype=float),
                    "mark_pnl": mark_pnl.to_numpy(dtype=float),
                    "funding_cost": funding_cost.to_numpy(dtype=float),
                    "funding_pnl": (-funding_cost).to_numpy(dtype=float),
                    "fee": fee.to_numpy(dtype=float),
                    "fee_pnl": (-fee).to_numpy(dtype=float),
                    "total_pnl": total_pnl.to_numpy(dtype=float),
                }
            )
            frames.append(frame)
        if not frames:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "symbol",
                    "position_units",
                    "close",
                    "mark_pnl",
                    "funding_cost",
                    "funding_pnl",
                    "fee",
                    "fee_pnl",
                    "total_pnl",
                ]
            )
        return pd.concat(frames, ignore_index=True, copy=False)

    def _build_exposure_report(
        self,
        accepted_units: pd.DataFrame,
        target_units: pd.DataFrame,
        closes: pd.DataFrame,
        equity: pd.Series,
    ) -> pd.DataFrame:
        cs = pd.Series({s: float(self.cs[s]) for s in self.symbols})
        lev = pd.Series({s: float(self.lev[s]) for s in self.symbols})
        accepted_notional = accepted_units.mul(closes, axis=0).mul(cs, axis=1)
        target_notional = target_units.mul(closes, axis=0).mul(cs, axis=1)
        abs_accepted = accepted_notional.abs()
        initial_margin = abs_accepted.div(lev, axis=1).sum(axis=1)
        maintenance_margin = abs_accepted.sum(axis=1) * float(self.maintenance_ratio)
        out = pd.DataFrame(
            {
                "long_notional": accepted_notional.clip(lower=0.0).sum(axis=1),
                "short_notional": accepted_notional.clip(upper=0.0).abs().sum(axis=1),
                "gross_notional": abs_accepted.sum(axis=1),
                "net_notional": accepted_notional.sum(axis=1),
                "target_gross_notional": target_notional.abs().sum(axis=1),
                "initial_margin": initial_margin,
                "maintenance_margin": maintenance_margin,
                "equity": equity,
                "available_equity_after_im": equity - initial_margin,
                "buying_power": equity * float(np.mean(list(self.lev.values()))),
            },
            index=self._idx,
        )
        out["gross_leverage"] = out["gross_notional"] / out["equity"].replace(0.0, np.nan)
        out["net_exposure_pct"] = out["net_notional"] / out["equity"].replace(0.0, np.nan)
        return out.fillna(0.0)

    def _build_rebalance_report(
        self,
        target_units: pd.DataFrame,
        accepted_units: pd.DataFrame,
        closes: pd.DataFrame,
    ) -> pd.DataFrame:
        diff = target_units - accepted_units
        cs = pd.Series({s: float(self.cs[s]) for s in self.symbols})
        mask = diff.abs() > 1e-10
        if not mask.to_numpy().any():
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "symbol",
                    "target_units",
                    "accepted_units",
                    "unit_diff",
                    "notional_diff",
                    "reason",
                ]
            )
        notional_diff = diff.mul(closes, axis=0).mul(cs, axis=1)
        stacked = diff.where(mask).stack(future_stack=True).dropna()
        index = stacked.index
        target_stacked = target_units.stack(future_stack=True)
        accepted_stacked = accepted_units.stack(future_stack=True)
        notional_stacked = notional_diff.stack(future_stack=True)
        return pd.DataFrame(
            {
                "timestamp": index.get_level_values(0),
                "symbol": index.get_level_values(1),
                "target_units": target_stacked.reindex(index).to_numpy(dtype=float),
                "accepted_units": accepted_stacked.reindex(index).to_numpy(dtype=float),
                "unit_diff": stacked.to_numpy(dtype=float),
                "notional_diff": notional_stacked.reindex(index).to_numpy(dtype=float),
                "reason": "margin_or_portfolio_gate",
            }
        )

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
        r = self.result
        for s in self.symbols:
            pos  = r.positions[f"Position_{s}"]
            cl   = r.closes[f"Close_{s}"]
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
