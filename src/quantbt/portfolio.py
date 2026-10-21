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

from dataclasses import replace
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .core.preprocessor import (
    validate_datetime,
    make_funding_mask,
    prepare_funding,
    align_series,
    build_market_arrays,
)
from .core.constraints import build_quantity_constraints, quantize_target_units_matrix
from .core.schema import InstrumentSpec
from .metrics.performance import full_report
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
    fee_rate         canonical one-way fee per accepted trade side
    fee              optional legacy round-trip fee; halved internally
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
        margin_buffer:     float = 0.0,
        use_binance_netting: bool = False,
        # highs / lows for intrabar liquidation (optional)
        highs: Optional[Dict[str, pd.Series]] = None,
        lows:  Optional[Dict[str, pd.Series]] = None,
        fee: Optional[float] = None,
        slippage: float = 0.0,
        use_pyramiding: bool = True,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        min_order_notional: float = 0.0,
    ):
        # ── config ────────────────────────────────────────────────────────
        atype = asset_type.lower()
        if atype not in self._ASSET_CFG:
            raise ValueError("asset_type must be 'crypto' or 'stock'")

        cfg = self._ASSET_CFG[atype]
        self.asset_type       = atype
        self.trading_days     = cfg["trading_days"]
        if fee_rate is not None:
            self.fee_rate = float(fee_rate)
        elif fee is not None:
            self.fee_rate = float(fee) / 2.0
        else:
            self.fee_rate = float(cfg["fee_rate"]) / 2.0
        self.use_funding      = use_funding if use_funding is not None else cfg["funding"]
        self.maintenance_ratio = maintenance_ratio
        self.initial_capital  = initial_capital
        self.mode             = mode.lower()
        self.hedge_type       = hedge_type.lower()
        self.use_binance_netting = use_binance_netting if atype == "crypto" else False
        self.slippage = float(slippage)

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

        if not np.isfinite(initial_capital) or initial_capital <= 0.0:
            raise ValueError("initial_capital must be finite and > 0")
        if any(not np.isfinite(v) or v <= 0.0 for v in self.lev.values()):
            raise ValueError("leverage must be finite and > 0")
        if any(not np.isfinite(v) or v <= 0.0 for v in self.cs.values()):
            raise ValueError("contract_size must be finite and > 0")
        if any(not np.isfinite(v) or v < 0.0 for v in self.alloc.values()):
            raise ValueError("alloc_per_trade must be finite and >= 0")
        if not np.isfinite(maintenance_ratio) or maintenance_ratio < 0.0:
            raise ValueError("maintenance_ratio must be finite and >= 0")
        if not np.isfinite(self.fee_rate) or self.fee_rate < 0.0:
            raise ValueError("fee_rate must be finite and >= 0")
        if not np.isfinite(self.slippage) or not 0.0 <= self.slippage < 1.0:
            raise ValueError("slippage must be finite and in [0, 1)")
        if not np.isfinite(margin_buffer) or margin_buffer != 0.0:
            raise ValueError("MultiSymbolPortfolio does not support nonzero margin_buffer")
        if not np.isfinite(min_order_notional) or min_order_notional < 0.0:
            raise ValueError("min_order_notional must be finite and >= 0")

        self._quantity_constraints = build_quantity_constraints(
            self.symbols,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        self._quantity_constraints = replace(
            self._quantity_constraints,
            min_notional=np.maximum(self._quantity_constraints.min_notional, min_order_notional),
        )

        # ── datetime index ────────────────────────────────────────────────
        self._idx = validate_datetime(datetime_index)
        if not self.symbols or len(self._idx) == 0:
            raise ValueError("portfolio requires at least one symbol and timestamp")

        # ── align data ────────────────────────────────────────────────────
        self._pos = {
            s: series.fillna(0.0)
            for s, series in align_series(positions, self.symbols, self._idx, fill_val=0.0).items()
        }
        if any(not np.isfinite(series.to_numpy(dtype=float)).all() for series in self._pos.values()):
            raise ValueError("positions must be finite")
        raw_close = align_series(closes, self.symbols, self._idx)
        raw_high = align_series(highs, self.symbols, self._idx, fallback=raw_close)
        raw_low = align_series(lows, self.symbols, self._idx, fallback=raw_close)
        market = build_market_arrays(
            self.symbols, self._idx, raw_close, raw_high, raw_low,
            {s: pd.Series(0.0, index=self._idx) for s in self.symbols},
        )
        self._close = {s: pd.Series(market.closes[:, j], index=self._idx) for j, s in enumerate(self.symbols)}
        self._high = {s: pd.Series(market.highs[:, j], index=self._idx) for j, s in enumerate(self.symbols)}
        self._low = {s: pd.Series(market.lows[:, j], index=self._idx) for j, s in enumerate(self.symbols)}
        from .backends.native_portfolio import NativePortfolioBackend

        self._tradable = NativePortfolioBackend._tradable_matrix(
            closes=closes, idx=self._idx, symbols=self.symbols, market=market,
        )

        # ── scale positions → notional units ─────────────────────────────
        self._scaled: Dict[str, pd.Series] = {}
        for s in self.symbols:
            self._scaled[s] = compute_target_units(
                hedge_type=self.hedge_type,
                signal=self._pos[s],
                close=self._close[s],
                alloc=self.alloc[s],
                use_pyramiding=use_pyramiding,
                contract_size=self.cs[s],
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

        funding_input = {
            s: pd.Series(rate, index=idx) if isinstance(rate, np.ndarray) else rate
            for s, rate in self.fund_rates.items()
        }
        funding = prepare_funding(funding_input, self.symbols, idx)

        for j, s in enumerate(self.symbols):
            closes_m[:, j] = self._close[s].fillna(0.0).values
            highs_m[:, j]  = self._high[s].fillna(self._close[s]).values
            lows_m[:, j]   = self._low[s].fillna(self._close[s]).values
            target_m[:, j] = self._scaled[s].fillna(0.0).values
            cs_arr[j]      = float(self.cs[s])
            lev_arr[j]     = float(self.lev[s])

            funding_m[:, j] = funding[s].to_numpy(dtype=np.float64)

        qc = self._quantity_constraints
        target_m = quantize_target_units_matrix(target_m, closes_m, cs_arr, qc, check_minima=False)
        attribution = np.zeros((n, m, 4), dtype=np.float64)
        funding_paid = np.zeros(n, dtype=np.float64)

        (
            eq_arr,
            pos_arr,
            sym_arr,
            fee_arr,
            slippage_arr,
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
            slippage_rate  = self.slippage,
            contract_sizes = cs_arr,
            use_funding    = bool(self.use_funding),
            tradable       = self._tradable,
            qty_steps      = qc.qty_step,
            min_qtys       = qc.min_qty,
            min_notionals  = qc.min_notional,
            funding_paid   = funding_paid,
            attribution    = attribution,
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
            attribution=attribution,
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
                "initial_buying_power": (
                    self.initial_capital * float(lev_arr[0]) if np.all(lev_arr == lev_arr[0]) else None
                ),
                "buying_power_by_symbol": {s: self.initial_capital * self.lev[s] for s in self.symbols},
                "buying_power_semantics": "single_symbol_capacity_not_shared_budget",
                "funding_rate_unit":    "per_event_or_carried_interval_sum",
                "funding_calendar":     "utc_8h_events_close_proxy_interval_settlement_v2",
                "account_contract":     "linear_gross_cross_netting_close_v2",
                "liquidation_contract": "simultaneous_adverse_ohlc_zero_equity_legacy",
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
                "fee_rate_oneway":      float(self.fee_rate),
                "canonical_one_way_fee_rate": float(self.fee_rate),
                "turnover_total":       float(np.sum(turn_arr)),
                "slippage":             self.slippage,
                "slippage_series":      pd.Series(slippage_arr, index=idx, name="slippage"),
                "slippage_total":       float(np.sum(slippage_arr)),
                "funding_cost_series":  pd.Series(funding_paid, index=idx, name="funding_cost"),
                "funding_cost_total":   float(np.sum(funding_paid)),
                "quantity_constraints": qc.as_dict(),
                "positions_semantics":  "accepted_contract_units",
                "hitrate_per_symbol_population": "carried_side_symbol_bars_net_pnl",
            },
        )
        return self._result

    def _build_symbol_pnl_report(
        self,
        accepted_units: pd.DataFrame,
        closes: pd.DataFrame,
        attribution: np.ndarray,
    ) -> pd.DataFrame:
        frames = []
        for j, s in enumerate(self.symbols):
            units = accepted_units[s].astype(float)
            close = closes[s].astype(float)
            prev_units = units.shift(1).fillna(0.0)
            prev_close = close.shift(1).fillna(close)
            cs = float(self.cs[s])
            mark_pnl = prev_units * (close - prev_close) * cs
            fee = pd.Series(attribution[:, j, 0], index=self._idx)
            slippage = pd.Series(attribution[:, j, 1], index=self._idx)
            funding_cost = pd.Series(attribution[:, j, 2], index=self._idx)
            liquidation_adjustment = pd.Series(attribution[:, j, 3], index=self._idx)
            total_pnl = self._pnl_per_sym[s].diff().fillna(0.0)
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
                    "slippage": slippage.to_numpy(dtype=float),
                    "slippage_pnl": (-slippage).to_numpy(dtype=float),
                    "liquidation_adjustment": liquidation_adjustment.to_numpy(dtype=float),
                    "liquidation_pnl": (-liquidation_adjustment).to_numpy(dtype=float),
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
                    "slippage",
                    "slippage_pnl",
                    "liquidation_adjustment",
                    "liquidation_pnl",
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
                "buying_power": (
                    equity * float(lev.iloc[0]) if (lev == lev.iloc[0]).all() else np.nan
                ),
                "available_margin": (equity - initial_margin).clip(lower=0.0),
            },
            index=self._idx,
        )
        out["gross_leverage"] = out["gross_notional"] / out["equity"].replace(0.0, np.nan)
        out["net_exposure_pct"] = out["net_notional"] / out["equity"].replace(0.0, np.nan)
        out["gross_leverage"] = out["gross_leverage"].fillna(0.0)
        out["net_exposure_pct"] = out["net_exposure_pct"].fillna(0.0)
        return out

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
        from .viz.plots import quick_plot

        self.print_metrics()
        quick_plot(self.result, theme=theme, figsize=figsize)

    def tearsheet(
        self,
        theme:     str   = "dark",
        figsize:   tuple = (16, 20),
        benchmark: Optional[pd.Series] = None,
    ) -> None:
        from .viz.plots import tearsheet as _tearsheet

        _tearsheet(
            self.result,
            theme        = theme,
            figsize      = figsize,
            trading_days = self.trading_days,
            benchmark    = benchmark,
        )

    def hitrate_per_symbol(self) -> Dict[str, Tuple[float, float]]:
        """Return long/short carried-bar net-PnL hit rates, not trade win rates."""
        out = {}
        r = self.result
        for s in self.symbols:
            pos  = r.positions[f"Position_{s}"].shift(1).fillna(0.0)
            pnl  = self._pnl_per_sym[s].diff().fillna(0.0)
            long_mask  = pos > 0
            short_mask = pos < 0
            lw = ((pnl > 0) & long_mask).sum()
            lt = long_mask.sum()
            sw = ((pnl > 0) & short_mask).sum()
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
