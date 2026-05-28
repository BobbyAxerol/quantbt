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
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .core.engine      import _engine_units, _engine_pct_equity
from .core.types       import BacktestResult
from .core.preprocessor import (
    validate_datetime,
    align_series,
    prepare_funding,
    build_arrays,
)
from .sizing.modes     import compute_target_units
from .metrics.performance import full_report
from .viz.plots        import quick_plot, tearsheet as _tearsheet


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
        self.slippage          = slippage

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

        # ── funding rates ─────────────────────────────────────────────────
        fr_input = funding_rate if use_funding_rate else 0.0
        self._funding = prepare_funding(fr_input, self.symbols, self._idx)

        # ── alloc dict ────────────────────────────────────────────────────
        if isinstance(alloc_per_trade, dict):
            self._alloc = alloc_per_trade
        else:
            self._alloc = {s: float(alloc_per_trade) for s in self.symbols}

        # ── scale signals → target units ──────────────────────────────────
        self._target_units: Dict[str, pd.Series] = {}
        for sym in self.symbols:
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

        if self.hedge_type.lower() in ("%_equity", "pct_equity"):
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
            )
        else:
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

        equity  = pd.Series(equity_arr, index=self._idx, name="equity")
        returns = equity.pct_change().fillna(0)

        # positions DataFrame
        pos_df = pd.DataFrame(
            {f"Position_{s}": signals[:, i] for i, s in enumerate(self.symbols)},
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
                "fee_oneway":        self.fee_oneway,
                "slippage":          self.slippage,
                "maintenance_ratio": self.maintenance_ratio,
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
        theme:        str = "dark",
        figsize:      tuple = (16, 20),
        trading_days: int = 365,
        benchmark:    Optional[pd.Series] = None,
    ) -> None:
        """Full dashboard.  Optional; call explicitly when needed."""
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
