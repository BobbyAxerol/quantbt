"""
quantbt.core.results
--------------------
Richer result contract for upgraded backends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence

import numpy as np
import pandas as pd

from .orders import Fill, OrderIntent, Trade
from .types import BacktestResult


@dataclass
class BacktestResultV2:
    equity: pd.Series
    returns: pd.Series
    positions: pd.DataFrame
    closes: pd.DataFrame
    symbols: List[str]
    initial_capital: float
    leverage: float = 1.0
    liquidated: bool = False
    liquidation_bar: int = -1
    orders: Sequence[OrderIntent] = field(default_factory=tuple)
    fills: Sequence[Fill] = field(default_factory=tuple)
    trades: Sequence[Trade] = field(default_factory=tuple)
    fees: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    funding: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    margin: pd.DataFrame = field(default_factory=pd.DataFrame)
    diagnostics: pd.DataFrame = field(default_factory=pd.DataFrame)
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.initial_capital <= 0.0:
            raise ValueError("initial_capital must be > 0")
        if self.leverage <= 0.0:
            raise ValueError("leverage must be > 0")
        if not isinstance(self.equity.index, pd.DatetimeIndex):
            raise ValueError("equity must be indexed by DatetimeIndex")
        if len(self.returns) != len(self.equity):
            raise ValueError("returns must have the same length as equity")
        if len(self.positions) != len(self.equity):
            raise ValueError("positions must have the same length as equity")
        if len(self.closes) != len(self.equity):
            raise ValueError("closes must have the same length as equity")

    @property
    def drawdown(self) -> pd.Series:
        peak = self.equity.cummax()
        return (peak - self.equity) / peak.replace(0, np.nan)

    @property
    def daily_equity(self) -> pd.Series:
        return self.equity.resample("1D").last().ffill().dropna()

    @property
    def daily_returns(self) -> pd.Series:
        return self.daily_equity.pct_change().dropna()

    def full_report(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        """Return the standard QuantBT metrics dictionary for this result."""
        from .scopes import scoped_result
        from ..metrics.performance import full_report

        return full_report(scoped_result(self, scope=scope), trading_days=trading_days)

    def show_metrics(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        """Print a legacy-style metrics report and return the metrics dict."""
        from ..endpoint import format_metrics_report

        report = self.full_report(trading_days=trading_days, scope=scope)
        print(format_metrics_report(report))
        return report

    def quick_plot(self, theme: str = "dark", figsize: tuple = (14, 6), scope: str = "auto"):
        """Plot cumulative return and drawdown for this result."""
        from ..viz import quick_plot

        return quick_plot(self, theme=theme, figsize=figsize, scope=scope)

    def tearsheet(self, theme: str = "dark", benchmark=None, scope: str = "auto"):
        """Render the QuantBT tearsheet for this result."""
        from ..viz import tearsheet

        return tearsheet(self, theme=theme, benchmark=benchmark, scope=scope)

    @classmethod
    def from_legacy(cls, result: BacktestResult) -> "BacktestResultV2":
        return cls(
            equity=result.equity.copy(),
            returns=result.returns.copy(),
            positions=result.positions.copy(),
            closes=result.closes.copy(),
            symbols=list(result.symbols),
            initial_capital=float(result.initial_capital),
            leverage=float(result.leverage),
            liquidated=bool(result.liquidated),
            liquidation_bar=int(result.liquidation_bar),
            metadata=dict(result.metadata),
        )

    def to_legacy(self) -> BacktestResult:
        return BacktestResult(
            equity=self.equity.copy(),
            returns=self.returns.copy(),
            positions=self.positions.copy(),
            closes=self.closes.copy(),
            symbols=list(self.symbols),
            initial_capital=float(self.initial_capital),
            leverage=float(self.leverage),
            liquidated=bool(self.liquidated),
            liquidation_bar=int(self.liquidation_bar),
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class NativeAccountingArrays:
    timestamps: np.ndarray
    equity: np.ndarray
    returns: np.ndarray
    positions: np.ndarray
    fees: np.ndarray
    funding: np.ndarray
    initial_margin: np.ndarray
    maintenance_margin: np.ndarray
    symbols: tuple[str, ...]
    initial_capital: float
    leverage: float = 1.0
    liquidated: bool = False
    liquidation_bar: int = -1

    @classmethod
    def from_result(cls, result: BacktestResultV2) -> "NativeAccountingArrays":
        position_cols = [f"Position_{symbol}" for symbol in result.symbols]
        return cls(
            timestamps=result.equity.index.view("int64").copy(),
            equity=result.equity.to_numpy(dtype=np.float64, copy=True),
            returns=result.returns.to_numpy(dtype=np.float64, copy=True),
            positions=result.positions[position_cols].to_numpy(dtype=np.float64, copy=True),
            fees=result.fees.to_numpy(dtype=np.float64, copy=True),
            funding=result.funding.to_numpy(dtype=np.float64, copy=True),
            initial_margin=result.margin.get("initial_margin", pd.Series(0.0, index=result.equity.index)).to_numpy(
                dtype=np.float64,
                copy=True,
            ),
            maintenance_margin=result.margin.get(
                "maintenance_margin",
                pd.Series(0.0, index=result.equity.index),
            ).to_numpy(dtype=np.float64, copy=True),
            symbols=tuple(result.symbols),
            initial_capital=float(result.initial_capital),
            leverage=float(result.leverage),
            liquidated=bool(result.liquidated),
            liquidation_bar=int(result.liquidation_bar),
        )

    @property
    def datetime_index(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.timestamps)


@dataclass(frozen=True)
class NativeEventScoreResult:
    accounting: NativeAccountingArrays
    final_positions: np.ndarray
    fill_count: int
    rejection_count: int
    cancellation_count: int
    liquidated: bool
    liquidation_bar: int
    metrics: Mapping[str, float]
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def equity(self) -> np.ndarray:
        return self.accounting.equity

    @property
    def returns(self) -> np.ndarray:
        return self.accounting.returns

    @property
    def positions(self) -> np.ndarray:
        return self.accounting.positions

    @property
    def fees(self) -> np.ndarray:
        return self.accounting.fees

    @property
    def funding(self) -> np.ndarray:
        return self.accounting.funding

    @property
    def initial_margin(self) -> np.ndarray:
        return self.accounting.initial_margin

    @property
    def maintenance_margin(self) -> np.ndarray:
        return self.accounting.maintenance_margin

    def full_report(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        if str(scope).lower().strip() not in {"auto", "full"}:
            raise ValueError("NativeEventScoreResult supports scope='auto' or scope='full'")

        from ..metrics.performance import compute_performance_metrics

        return compute_performance_metrics(
            timestamps=self.accounting.datetime_index,
            equity=self.accounting.equity,
            returns=self.accounting.returns,
            positions=self.accounting.positions,
            symbols=self.accounting.symbols,
            initial_capital=float(self.accounting.initial_capital),
            liquidated=bool(self.liquidated),
            trading_days=trading_days,
        )


@dataclass(frozen=True, slots=True)
class NativeEventScalarScoreResult:
    """Low-retention score contract for prepared native-event optimization.

    Unlike :class:`NativeEventScoreResult`, this result does not retain an
    equity, position, fee, funding, or margin path.  The reactive session
    computes the same report metrics online and keeps only scalar accounting
    state.  Public audit runs and the compatibility ``score()`` contract keep
    using ``NativeEventScoreResult`` with ndarray accounting.
    """

    final_equity: float
    final_positions: np.ndarray
    fill_count: int
    rejection_count: int
    cancellation_count: int
    liquidated: bool
    liquidation_bar: int
    metrics: Mapping[str, float]
    metadata: Mapping[str, object] = field(default_factory=dict)

    def _lifecycle_counter(self, name: str, default: int = 0) -> int:
        counters = self.metadata.get("lifecycle_counters", {})
        return int(counters.get(name, default)) if isinstance(counters, Mapping) else int(default)

    @property
    def event_count(self) -> int:
        """Number of lifecycle events emitted by the scalar run."""

        return self._lifecycle_counter("event_count")

    @property
    def rejected_count(self) -> int:
        """Number of rejected commands in the scalar run."""

        return int(self.rejection_count)

    @property
    def canceled_count(self) -> int:
        """Number of canceled commands in the scalar run."""

        return int(self.cancellation_count)

    @property
    def max_initial_margin(self) -> float:
        return float(self.metrics.get("max_initial_margin", 0.0))

    @property
    def max_maintenance_margin(self) -> float:
        return float(self.metrics.get("max_maintenance_margin", 0.0))

    @property
    def total_fee(self) -> float:
        return float(self.metadata.get("total_fee", 0.0))

    @property
    def total_turnover(self) -> float:
        return float(self.metadata.get("total_turnover", 0.0))

    def full_report(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        """Return the online report captured for this score run.

        A scalar score has no path from which to recompute a different
        annualization convention.  Callers requesting a different
        ``trading_days`` value must rerun the score with that value.
        """
        if str(scope).lower().strip() not in {"auto", "full"}:
            raise ValueError("NativeEventScalarScoreResult supports scope='auto' or scope='full'")
        recorded_days = int(self.metadata.get("trading_days", trading_days))
        if int(trading_days) != recorded_days:
            raise ValueError(
                "scalar score metrics were computed with trading_days="
                f"{recorded_days}; rerun the score to use trading_days={int(trading_days)}"
            )
        return dict(self.metrics)


@dataclass
class OptionBacktestResult(BacktestResultV2):
    """
    Backtest result contract for native option simulations.

    It intentionally remains a `BacktestResultV2` so existing report helpers
    keep working, while exposing option-domain audit tables explicitly.
    """

    fills_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    packages_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    cash_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    marks_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    greeks_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    settlements_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    margin_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    attribution_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    hedge_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    option_equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    combined_equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    combined_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    run_manifest: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.metadata.setdefault("fills_report", self.fills_report)
        self.metadata.setdefault("packages_report", self.packages_report)
        self.metadata.setdefault("cash_report", self.cash_report)
        self.metadata.setdefault("marks_report", self.marks_report)
        self.metadata.setdefault("greeks_report", self.greeks_report)
        self.metadata.setdefault("settlements_report", self.settlements_report)
        self.metadata.setdefault("margin_report", self.margin_report)
        self.metadata.setdefault("attribution_report", self.attribution_report)
        self.metadata.setdefault("hedge_report", self.hedge_report)
        self.metadata.setdefault("option_equity", self.option_equity)
        self.metadata.setdefault("combined_equity", self.combined_equity)
        self.metadata.setdefault("combined_returns", self.combined_returns)
        self.metadata.setdefault("run_manifest", self.run_manifest)
