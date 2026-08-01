"""
quantbt.backtester
------------------
BacktestEngine — single and multi-symbol futures backtest.

Key design decisions
~~~~~~~~~~~~~~~~~~~~
* Signals enter as raw weights.  Position scaling (units / notional / pct_equity)
  is handled by quantbt.sizing.modes BEFORE passing to the numba kernel.
* BacktestEngine.__init__ does data alignment + scaling.
* BacktestEngine.run() executes the simulation and returns a BacktestResult.
* analyze() is the convenience entry point: prints a text report + quick_plot.
* tearsheet() is a separate opt-in call.

hedge_type values
~~~~~~~~~~~~~~~~~
'notional'          constant notional per bar (recomputes units every bar)
'unit'              fixed unit count from first-bar price
'signal_notional'   anchor on signal change; stable between transitions  ← recommended
'%_equity'          dynamic sizing from live equity, no pre-scaling
'dca_ladder'        signed structural level; High/Low limit fills at grid triggers

Parameters (unchanged from original)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Datetime            pd.Series | pd.DatetimeIndex
Position            pd.Series | Dict[str, pd.Series]   raw signal weight
Close               pd.Series | Dict[str, pd.Series]
High / Low          optional, used for intrabar liquidation
fee                 float   round-trip fee (split internally to one-way)
use_pyramiding      bool    False → snap signal to {-1, 0, 1}
initial_capital     float
leverage            float
maintenance_ratio   float   Binance-style: notional × ratio
contract_size       float | Dict[str, float]
use_funding_rate    bool
funding_rate        float | pd.Series | Dict[str, float | pd.Series]
alloc_per_trade     float | Dict[str, float]   notional per full signal unit
hedge_type          str
slippage            float   e.g. 0.0001 = 1 bps
symbols             List[str] | None
High / Low          required for dca_ladder limit-fill detection
dca_base_notional   base order notional; defaults to alloc_per_trade
dca_safety_notional safety order notional; defaults to alloc_per_trade
dca_step_pct        AO1 distance from base entry, e.g. 0.01 = 1%
dca_step_scale      multiplier for each next AO distance increment
dca_volume_scale    multiplier for each next safety order notional
dca_take_profit_pct TP from weighted average entry; 0 disables internal TP
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .core.engine      import _engine_units, _engine_pct_equity, _engine_dca_ladder
from .core.types       import BacktestResult
from .core.preprocessor import (
    validate_datetime,
    align_series,
    prepare_funding,
    build_arrays,
)
from .core.constraints import build_quantity_constraints, quantize_target_units_matrix
from .core.schema import InstrumentSpec
from .sizing.modes     import compute_target_units
from .metrics.performance import full_report


class BacktestEngine:
    """
    Vectorised Binance-Futures backtest engine.

    Usage
    -----
    >>> bt = BacktestEngine(Datetime=dt, Position=sig, Close=close, ...)
    >>> result = bt.run()          # BacktestResult
    >>> bt.analyze()               # text report + quick plot
    >>> bt.tearsheet()             # full dashboard (optional)
    >>> bt.export_trade_log('log.csv')
    """

    def __init__(
        self,
        Datetime:           Union[pd.Series, pd.DatetimeIndex],
        Position:           Union[pd.Series, Dict[str, pd.Series]],
        Close:              Union[pd.Series, Dict[str, pd.Series]],
        fee:                float = 0.0004,
        use_pyramiding:     bool  = True,
        initial_capital:    float = 20_000.0,
        leverage:           float = 10.0,
        maintenance_ratio:  float = 0.005,
        contract_size:      Union[float, Dict[str, float]] = 1.0,
        use_funding_rate:   bool  = True,
        funding_rate:       Union[float, pd.Series, Dict] = 0.0001,
        alloc_per_trade:    Union[float, Dict[str, float]] = 100_000.0,
        hedge_type:         str   = "signal_notional",
        slippage:           float = 0.0001,
        symbols:            Optional[List[str]] = None,
        High:               Optional[Union[pd.Series, Dict[str, pd.Series]]] = None,
        Low:                Optional[Union[pd.Series, Dict[str, pd.Series]]] = None,
        dca_base_notional:   Optional[Union[float, Dict[str, float]]] = None,
        dca_safety_notional: Optional[Union[float, Dict[str, float]]] = None,
        dca_step_pct:        Union[float, Dict[str, float]] = 0.01,
        dca_step_scale:      Union[float, Dict[str, float]] = 1.0,
        dca_volume_scale:    Union[float, Dict[str, float]] = 1.0,
        dca_max_safety_orders: int = 5,
        dca_take_profit_pct: Union[float, Dict[str, float]] = 0.0,
        dca_allow_same_bar_exit: bool = False,
        instruments:        Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step:           Optional[Union[float, Dict[str, float]]] = None,
        lot_size:           Optional[Union[float, Dict[str, float]]] = None,
        slot_size:          Optional[Union[float, Dict[str, float]]] = None,
        min_qty:            Optional[Union[float, Dict[str, float]]] = None,
        min_notional:       Optional[Union[float, Dict[str, float]]] = None,
        # kept for backward compat, not used internally
        run_portfolio:      bool  = True,
        use_binance_netting: bool = True,
        margin_buffer:      float = 0.01,
    ):
        # ── store config ──────────────────────────────────────────────────
        self.fee_oneway        = fee / 2.0          # one-way
        self.use_pyramiding    = use_pyramiding
        self.initial_capital   = initial_capital
        self.leverage          = leverage
        self.maintenance_ratio = maintenance_ratio
        self.use_funding_rate  = use_funding_rate
        self.alloc_per_trade   = alloc_per_trade
        self.hedge_type        = hedge_type
        self._hedge_type_norm  = hedge_type.lower().strip()
        self._is_dca_ladder    = self._hedge_type_norm in ("dca_ladder", "dca")
        self.slippage          = slippage
        self.dca_max_safety_orders = int(dca_max_safety_orders)
        self.dca_allow_same_bar_exit = bool(dca_allow_same_bar_exit)

        if self.dca_max_safety_orders < 0:
            raise ValueError("dca_max_safety_orders must be >= 0")
        if self._is_dca_ladder and (High is None or Low is None):
            raise ValueError("hedge_type='dca_ladder' requires High and Low for limit-fill detection")
        if self.initial_capital <= 0.0:
            raise ValueError("initial_capital must be > 0")
        if self.leverage <= 0.0:
            raise ValueError("leverage must be > 0")
        if self.maintenance_ratio < 0.0:
            raise ValueError("maintenance_ratio must be >= 0")

        # ── datetime index ────────────────────────────────────────────────
        self._idx = validate_datetime(Datetime)

        # ── symbols ───────────────────────────────────────────────────────
        if symbols is not None:
            self.symbols = symbols
        elif isinstance(Position, dict):
            self.symbols = list(Position.keys())
        else:
            self.symbols = ["DEFAULT"]

        self.n_syms = len(self.symbols)
        self.n_bars = len(self._idx)

        # ── align price / signal data ──────────────────────────────────────
        self._closes   = align_series(Close,    self.symbols, self._idx)
        self._highs    = align_series(High,     self.symbols, self._idx, fallback=self._closes)
        self._lows     = align_series(Low,      self.symbols, self._idx, fallback=self._closes)
        self._positions = align_series(Position, self.symbols, self._idx, fill_val=0.0)

        # ── contract sizes ────────────────────────────────────────────────
        if isinstance(contract_size, dict):
            self._contract_sizes = np.array(
                [contract_size.get(s, 1.0) for s in self.symbols], dtype=np.float64
            )
        else:
            self._contract_sizes = np.full(self.n_syms, float(contract_size), dtype=np.float64)

        if np.any(self._contract_sizes <= 0.0):
            raise ValueError("contract_size must be > 0")

        self._quantity_constraints = build_quantity_constraints(
            self.symbols,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )

        # ── funding rates ─────────────────────────────────────────────────
        fr_input = funding_rate if use_funding_rate else 0.0
        self._funding = prepare_funding(fr_input, self.symbols, self._idx)

        # ── alloc dict ────────────────────────────────────────────────────
        if isinstance(alloc_per_trade, dict):
            self._alloc = {s: float(alloc_per_trade[s]) for s in self.symbols}
        else:
            self._alloc = {s: float(alloc_per_trade) for s in self.symbols}

        if any(v < 0.0 for v in self._alloc.values()):
            raise ValueError("alloc_per_trade must be >= 0")

        def _per_symbol_array(value, default_map):
            out = []
            for s in self.symbols:
                default = default_map[s] if isinstance(default_map, dict) else default_map
                if value is None:
                    v = default
                elif isinstance(value, dict):
                    v = value.get(s, default)
                else:
                    v = value
                out.append(float(v))
            return np.array(out, dtype=np.float64)

        # DCA ladder parameters. Defaults keep base and safety orders aligned
        # with alloc_per_trade, while the grid geometry is explicit and stable.
        self._dca_base_notional = _per_symbol_array(dca_base_notional, self._alloc)
        self._dca_safety_notional = _per_symbol_array(dca_safety_notional, self._alloc)
        self._dca_step_pct = _per_symbol_array(dca_step_pct, 0.01)
        self._dca_step_scale = _per_symbol_array(dca_step_scale, 1.0)
        self._dca_volume_scale = _per_symbol_array(dca_volume_scale, 1.0)
        self._dca_take_profit_pct = _per_symbol_array(dca_take_profit_pct, 0.0)

        if self._is_dca_ladder:
            if self.dca_max_safety_orders > 0 and np.any(self._dca_step_pct <= 0.0):
                raise ValueError("dca_step_pct must be > 0 when safety orders are enabled")
            if np.any(self._dca_base_notional <= 0.0) or np.any(self._dca_safety_notional <= 0.0):
                raise ValueError("DCA base/safety notionals must be > 0")
            if np.any(self._dca_step_scale <= 0.0) or np.any(self._dca_volume_scale <= 0.0):
                raise ValueError("DCA step/volume scales must be > 0")

        # ── scale signals → target units ──────────────────────────────────
        self._target_units: Dict[str, pd.Series] = {}
        for sym in self.symbols:
            if self._is_dca_ladder:
                self._target_units[sym] = self._positions[sym].fillna(0.0)
            else:
                self._target_units[sym] = compute_target_units(
                    hedge_type     = self.hedge_type,
                    signal         = self._positions[sym],
                    close          = self._closes[sym],
                    alloc          = self._alloc[sym],
                    use_pyramiding = self.use_pyramiding,
                )

        # run on construction so result is immediately available
        self._result: Optional[BacktestResult] = None
        self.run()

    # ── public interface ─────────────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """
        Execute the simulation and return a BacktestResult.
        Also caches the result as self.result.
        """
        closes, highs, lows, signals, funding, is_funding = build_arrays(
            symbols       = self.symbols,
            idx           = self._idx,
            closes_dict   = self._closes,
            highs_dict    = self._highs,
            lows_dict     = self._lows,
            signals_dict  = self._target_units,
            funding_dict  = self._funding,
        )

        cs = self._contract_sizes
        qc = self._quantity_constraints

        if self._is_dca_ladder:
            equity_arr, pos_arr, level_arr, liq_flag, liq_idx = _engine_dca_ladder(
                n_bars              = self.n_bars,
                n_syms              = self.n_syms,
                highs               = highs,
                lows                = lows,
                closes              = closes,
                signals             = signals,
                funding_rates       = funding,
                is_funding_bar      = is_funding,
                init_capital        = self.initial_capital,
                leverage            = self.leverage,
                maint_ratio         = self.maintenance_ratio,
                fee_rate            = self.fee_oneway,
                contract_sizes      = cs,
                market_slippage     = self.slippage,
                base_notional       = self._dca_base_notional,
                safety_notional     = self._dca_safety_notional,
                step_pct            = self._dca_step_pct,
                step_scale          = self._dca_step_scale,
                volume_scale        = self._dca_volume_scale,
                max_safety_orders   = self.dca_max_safety_orders,
                take_profit_pct     = self._dca_take_profit_pct,
                allow_same_bar_exit = self.dca_allow_same_bar_exit,
                qty_steps           = qc.qty_step,
                min_qtys            = qc.min_qty,
                min_notionals       = qc.min_notional,
            )
            result_positions = pos_arr
        elif self._hedge_type_norm in ("%_equity", "pct_equity"):
            alloc_pct = np.array(
                [self._alloc[s] for s in self.symbols], dtype=np.float64
            )
            # normalise: if value > 1 assume percentage was passed (e.g. 10 → 0.10)
            alloc_pct = np.where(alloc_pct > 1.0, alloc_pct / 100.0, alloc_pct)

            equity_arr, liq_flag, liq_idx = _engine_pct_equity(
                n_bars         = self.n_bars,
                n_syms         = self.n_syms,
                highs          = highs,
                lows           = lows,
                closes         = closes,
                signals        = signals,
                funding_rates  = funding,
                is_funding_bar = is_funding,
                init_capital   = self.initial_capital,
                leverage       = self.leverage,
                maint_ratio    = self.maintenance_ratio,
                fee_rate       = self.fee_oneway,
                contract_sizes = cs,
                slippage       = self.slippage,
                alloc_pct      = alloc_pct,
                qty_steps      = qc.qty_step,
                min_qtys       = qc.min_qty,
                min_notionals  = qc.min_notional,
            )
            result_positions = signals
        else:
            signals = quantize_target_units_matrix(signals, closes, cs, qc)
            equity_arr, liq_flag, liq_idx = _engine_units(
                n_bars         = self.n_bars,
                n_syms         = self.n_syms,
                highs          = highs,
                lows           = lows,
                closes         = closes,
                signals        = signals,
                funding_rates  = funding,
                is_funding_bar = is_funding,
                init_capital   = self.initial_capital,
                leverage       = self.leverage,
                maint_ratio    = self.maintenance_ratio,
                fee_rate       = self.fee_oneway,
                contract_sizes = cs,
                slippage       = self.slippage,
            )
            result_positions = signals

        equity  = pd.Series(equity_arr, index=self._idx, name="equity")
        returns = equity.pct_change().fillna(0)

        # positions DataFrame
        pos_df = pd.DataFrame(
            {f"Position_{s}": result_positions[:, i] for i, s in enumerate(self.symbols)},
            index=self._idx,
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": closes[:, i] for i, s in enumerate(self.symbols)},
            index=self._idx,
        )

        self._result = BacktestResult(
            equity          = equity,
            returns         = returns,
            positions       = pos_df,
            closes          = close_df,
            symbols         = self.symbols,
            initial_capital = self.initial_capital,
            leverage        = self.leverage,
            liquidated      = bool(liq_flag),
            liquidation_bar = int(liq_idx),
            metadata        = {
                "hedge_type":        self.hedge_type,
                "initial_buying_power": self.initial_capital * self.leverage,
                "fee_oneway":        self.fee_oneway,
                "slippage":          self.slippage,
                "maintenance_ratio": self.maintenance_ratio,
                "quantity_constraints": self._quantity_constraints.as_dict(),
                "dca_actual_level": (
                    pd.DataFrame(
                        {f"Level_{s}": level_arr[:, i] for i, s in enumerate(self.symbols)},
                        index=self._idx,
                    )
                    if self._is_dca_ladder else None
                ),
            },
        )
        return self._result

    @property
    def result(self) -> BacktestResult:
        if self._result is None:
            self.run()
        return self._result

    # ── convenience methods ───────────────────────────────────────────────────

    def analyze(
        self,
        trading_days: int = 365,
        theme:        str = "dark",
        figsize:      tuple = (14, 6),
    ) -> None:
        """
        Print a concise performance report, then show cumulative return + drawdown.
        """
        from .viz.plots import quick_plot

        self.print_metrics(trading_days=trading_days)
        quick_plot(self.result, theme=theme, figsize=figsize)

    def print_metrics(self, trading_days: int = 365) -> None:
        """
        Print a structured text report to stdout.
        No separators, no banner lines — clean columnar output.
        """
        rpt = full_report(self.result, trading_days)
        syms = ", ".join(self.symbols)

        lines = [
            ("Symbols",             syms),
            ("Hedge Type",          self.hedge_type),
            ("Initial Capital",     f"${rpt['initial_capital']:>14,.0f}"),
            ("Final Equity",        f"${rpt['final_equity']:>14,.2f}"),
            ("Total Return",        f"{rpt['total_return_pct']:>+13.2f}%"),
            ("CAGR",                f"{rpt['cagr_pct']:>+13.2f}%"),
            ("Sharpe Ratio",        f"{rpt['sharpe']:>14.3f}"),
            ("Sortino Ratio",       f"{rpt['sortino']:>14.3f}"),
            ("Calmar Ratio",        f"{rpt['calmar']:>14.3f}"),
            ("Omega Ratio",         f"{rpt['omega']:>14.3f}"),
            ("Max Drawdown",        f"{rpt['max_drawdown_pct']:>13.2f}%"),
            ("Avg Drawdown",        f"{rpt['avg_drawdown_pct']:>13.2f}%"),
            ("Max DD Duration",     f"{rpt['max_dd_duration_days']:>11d} days"),
            ("Profit Factor",       f"{rpt['profit_factor']:>14.3f}"),
            ("Long Hit Rate",       f"{rpt['long_hitrate_pct']:>13.2f}%"),
            ("Short Hit Rate",      f"{rpt['short_hitrate_pct']:>13.2f}%"),
            ("Avg Win",             f"{rpt['avg_win_pct']:>+13.3f}%"),
            ("Avg Loss",            f"{rpt['avg_loss_pct']:>+13.3f}%"),
            ("Expectancy",          f"{rpt['expectancy_pct']:>+13.3f}%"),
            ("Number of Trades",    f"{rpt['num_trades']:>14,d}"),
            ("Liquidated",          f"{'Yes' if rpt['liquidated'] else 'No':>14}"),
        ]

        col_width = max(len(k) for k, _ in lines)
        print()
        for key, val in lines:
            print(f"  {key:<{col_width}}  {val}")
        print()

    def tearsheet(
        self,
        theme:        str = "light",
        figsize:      tuple = (18, 24),
        trading_days: int = 365,
        benchmark:    Optional[pd.Series] = None,
    ) -> None:
        """Full dashboard.  Optional; call explicitly when needed."""
        from .viz.plots import tearsheet as _tearsheet

        _tearsheet(
            self.result,
            theme        = theme,
            figsize      = figsize,
            trading_days = trading_days,
            benchmark    = benchmark,
        )

    def export_trade_log(
        self,
        filename:          str  = "trade_log.csv",
        datetime_as_index: bool = True,
    ) -> None:
        r   = self.result
        log = pd.DataFrame({
            "returns":           r.returns,
            "cumulative_return": (r.equity / self.initial_capital - 1) * 100,
        }, index=r.equity.index)

        for sym in self.symbols:
            log[f"position_{sym}"] = r.positions[f"Position_{sym}"]
            log[f"close_{sym}"]    = r.closes[f"Close_{sym}"]

        if not datetime_as_index:
            log = log.reset_index()

        log.to_csv(filename, index=datetime_as_index)
        print(f"Trade log exported  →  {filename}")
