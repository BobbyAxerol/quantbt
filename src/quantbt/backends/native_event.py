"""
quantbt.backends.native_event
-----------------------------
Native event-driven backend using a Numba matching kernel.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import math
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from ..core.event import (
    ACTIVATION_IMMEDIATE,
    ACTIVATION_ON_PARENT_FIRST_FILL,
    ACTIVATION_ON_PARENT_FULL_FILL,
    COMMAND_ACTION_AMEND,
    COMMAND_ACTION_CANCEL,
    COMMAND_ACTION_CANCEL_ALL,
    COMMAND_ACTION_PLACE,
    COMMAND_ACTION_REPLACE,
    LIQ_AFTER_FUNDING,
    LIQ_AFTER_ORDER,
    LIQ_INTRABAR,
    LIQ_NONE,
    ORDER_EVENT_ACTIVATE,
    ORDER_EVENT_AMEND,
    ORDER_EVENT_CANCEL,
    ORDER_EVENT_EXPIRE,
    ORDER_EVENT_FILL,
    ORDER_EVENT_PLACE,
    ORDER_EVENT_REJECT,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_REJECTED,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_STOP_LIMIT,
    ORDER_TYPE_STOP_MARKET,
    REJECT_INSUFFICIENT_MARGIN,
    REJECT_REDUCE_ONLY_NO_POSITION,
    REJECT_UNKNOWN_ORDER,
    SIDE_BUY,
    SIDE_SELL,
    TIF_FOK,
    TIF_GTC,
    TIF_GTD,
    TIF_IOC,
    _engine_event_v1,
    _engine_event_v2,
)
from ..core.constraints import build_quantity_constraints, quantize_signed_quantity
from ..core.arbitrage import (
    ArbitrageSpec,
    ArbitragePlan,
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    CrossExchangeArbSpec,
    FundingArbitrageSpec,
    IndexBasketArbSpec,
    OptionsVolArbSpec,
    PackageExecutionKind,
    PackageRejection,
    SizingPolicyKind,
    SpotPerpCashCarrySpec,
    StatArbPairSpec,
    TriangularArbSpec,
    build_arbitrage_order_plan,
)
from ..core.basket import build_frozen_basket_orders
from ..core.order_compiler import (
    CompiledOrderArrays,
    CompiledOrderCommandArrays,
    compile_order_commands,
    compile_order_intents,
)
from ..core.orders import Fill, OrderAction, OrderActivationPolicy, OrderCommand, OrderIntent
from ..core.preprocessor import (
    PreparedMarketArrays,
    align_series,
    build_market_arrays,
    make_funding_mask,
    prepare_funding,
    validate_datetime,
)
from ..core.results import (
    BacktestResultV2,
    NativeAccountingArrays,
    NativeEventScalarScoreResult,
    NativeEventScoreResult,
)
from ..core.reactive import (
    NativeActiveOrderSnapshot,
    NativeEventStrategyError,
    NativeFillEvent,
    NativeOrderEvent,
    NativeStrategyContext,
)
from ..core.schema import (
    AccountConfig,
    BasketLegSpec,
    BasketSpec,
    ExecutionConfig,
    LiquiditySide,
    OrderSide,
    OrderType,
    TimeInForce,
    InstrumentSpec,
)
from ._native_event_rust import (
    NativeEventBackendSelection,
    NativeEventRustBackendError,
    RustBatchedRunner,
    RustFullRunner,
    RustReactiveSessionAdapter,
    resolve_native_event_backend,
)


def _event_type_name(event_type: int) -> str:
    return {
        0: "place",
        1: "cancel",
        2: "replace",
        3: "amend",
        4: "fill",
        5: "expire",
        6: "activate",
        7: "reject",
    }.get(int(event_type), "unknown")


@dataclass(frozen=True)
class NativeEventConfig:
    account: AccountConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fee_rate: Union[float, Dict[str, float]] = 0.0
    use_funding: bool = True
    report_level: str = "audit"
    audit_sink: str = "memory"
    audit_sink_path: Optional[str] = None
    reactive_kernel_mode: str = "replay_certified"
    native_backend: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.fee_rate, dict):
            if any(float(rate) < 0.0 for rate in self.fee_rate.values()):
                raise ValueError("fee_rate must be >= 0")
        elif float(self.fee_rate) < 0.0:
            raise ValueError("fee_rate must be >= 0")
        object.__setattr__(self, "report_level", _normalize_native_event_report_level(self.report_level))
        object.__setattr__(self, "audit_sink", _normalize_native_event_audit_sink(self.audit_sink))
        object.__setattr__(self, "reactive_kernel_mode", _normalize_reactive_kernel_mode(self.reactive_kernel_mode))
        if self.native_backend is not None:
            selected = str(self.native_backend).lower().strip()
            if selected not in {"python", "rust", "auto", "replay_certified"}:
                raise ValueError(
                    "native_backend must be one of: auto, python, replay_certified, rust"
                )
            object.__setattr__(self, "native_backend", selected)


@dataclass(frozen=True)
class NativeEventArtifactPlan:
    keep_equity_path: bool
    keep_position_path: bool
    keep_fee_path: bool
    keep_funding_path: bool
    keep_margin_path: bool
    keep_fill_ledger: bool
    keep_command_terminal_state: bool
    keep_event_ledger: bool
    keep_command_tape: bool
    materialize_pandas: bool
    materialize_python_objects: bool
    materialize_active_orders: bool


@dataclass(frozen=True, slots=True)
class NativeEventScoreRequirements:
    """Internal retention contract for direct prepared-score execution.

    The public ``PreparedNativeEventStrategyRunner.score`` compatibility
    contract exposes accounting arrays.  Prepared optimization uses
    ``scalar_score_contract()`` instead, which relies on online metrics and
    keeps only live reactive state. Context flags are separate from ledger
    retention: a strategy may consume current-bar fills without retaining the
    complete fill history.
    """

    need_equity_path: bool = False
    need_position_path: bool = False
    need_fee_path: bool = False
    need_funding_path: bool = False
    need_margin_path: bool = False
    need_turnover_path: bool = False
    need_rejection_path: bool = False
    need_cancellation_path: bool = False
    need_trade_stats: bool = True
    need_fill_ledger: bool = False
    need_event_ledger: bool = False
    need_terminal_orders: bool = False
    need_context_fills: bool = True
    need_context_events: bool = True
    need_context_active_orders: bool = True
    need_context_positions: bool = True
    need_context_margin: bool = True
    need_command_tape: bool = False

    @classmethod
    def public_score_contract(cls) -> "NativeEventScoreRequirements":
        """Return the compatible array set required by ``NativeEventScoreResult``."""
        return cls(
            need_equity_path=True,
            need_position_path=True,
            need_fee_path=True,
            need_funding_path=True,
            need_margin_path=True,
            need_trade_stats=False,
        )

    @classmethod
    def scalar_score_contract(cls) -> "NativeEventScoreRequirements":
        """Return the low-retention contract used by prepared optimization."""
        return cls(
            need_equity_path=False,
            need_position_path=False,
            need_fee_path=False,
            need_funding_path=False,
            need_margin_path=False,
            need_turnover_path=False,
            need_rejection_path=False,
            need_cancellation_path=False,
            need_trade_stats=True,
            need_fill_ledger=False,
            need_event_ledger=False,
            need_terminal_orders=False,
            need_context_fills=True,
            need_context_events=True,
            need_context_active_orders=True,
            need_context_positions=True,
            need_context_margin=True,
            need_command_tape=False,
        )

    @classmethod
    def from_strategy(
        cls,
        strategy,
        *,
        base: Optional["NativeEventScoreRequirements"] = None,
    ) -> "NativeEventScoreRequirements":
        """Apply an optional strategy context declaration to a base contract."""
        requirements = base or cls.scalar_score_contract()
        declaration = getattr(strategy, "native_context_requirements", None)
        if declaration is None:
            return requirements
        if not isinstance(declaration, Mapping):
            raise TypeError("native_context_requirements must be a mapping")
        aliases = {
            "fills": "need_context_fills",
            "events": "need_context_events",
            "active_orders": "need_context_active_orders",
            "positions": "need_context_positions",
            "margin": "need_context_margin",
        }
        valid = set(aliases) | set(aliases.values())
        updates = {}
        for key, value in declaration.items():
            if key not in valid:
                raise ValueError(f"unsupported native context requirement: {key!r}")
            updates[aliases.get(key, key)] = bool(value)
        return replace(requirements, **updates)


@dataclass(frozen=True)
class CompactFillLedger:
    bar: np.ndarray
    command_index: np.ndarray
    original_index: np.ndarray
    order_id_code: np.ndarray
    symbol_code: np.ndarray
    side: np.ndarray
    qty: np.ndarray
    price: np.ndarray
    fee: np.ndarray
    id_values: tuple[str, ...]
    symbols: tuple[str, ...]

    @property
    def fill_count(self) -> int:
        return int(len(self.bar))


@dataclass(frozen=True)
class CompactCommandLedger:
    original_index: np.ndarray
    command_bar: np.ndarray
    action: np.ndarray
    symbol_code: np.ndarray
    side: np.ndarray
    order_type: np.ndarray
    order_id_code: np.ndarray
    target_order_id_code: np.ndarray
    parent_order_id_code: np.ndarray
    group_id_code: np.ndarray
    oco_group_id_code: np.ndarray
    status: np.ndarray
    reject_code: np.ndarray
    fill_bar: np.ndarray
    fill_qty: np.ndarray
    fill_price: np.ndarray
    fill_fee: np.ndarray
    active: np.ndarray
    waiting_parent: np.ndarray
    working_qty: np.ndarray
    working_price: np.ndarray
    working_trigger: np.ndarray
    id_values: tuple[str, ...]
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class CompactOrderEventLedger:
    bar: np.ndarray
    command_index: np.ndarray
    event_type: np.ndarray
    status: np.ndarray
    related_command_index: np.ndarray

    @property
    def event_count(self) -> int:
        return int(len(self.bar))


def _normalize_native_event_report_level(report_level: str) -> str:
    level = str(report_level or "audit").lower().strip()
    aliases = {"full": "audit", "debug": "audit", "research": "standard", "optimizer": "score", "scoring": "score"}
    level = aliases.get(level, level)
    if level not in {"score", "minimal", "standard", "audit"}:
        raise ValueError("native_event report_level must be score, minimal, standard, audit, or full")
    return level


def _normalize_native_event_audit_sink(audit_sink: str) -> str:
    sink = str(audit_sink or "memory").lower().strip()
    if sink not in {"none", "memory", "jsonl", "parquet"}:
        raise ValueError("native_event audit_sink must be none, memory, jsonl, or parquet")
    return sink


def _normalize_reactive_kernel_mode(reactive_kernel_mode: str) -> str:
    mode = str(reactive_kernel_mode or "replay_certified").lower().strip()
    aliases = {"replay": "replay_certified", "certified": "replay_certified", "stateful": "single_pass"}
    mode = aliases.get(mode, mode)
    if mode not in {"replay_certified", "single_pass"}:
        raise ValueError("reactive_kernel_mode must be replay_certified or single_pass")
    return mode


def _native_event_artifact_plan(report_level: str) -> NativeEventArtifactPlan:
    level = _normalize_native_event_report_level(report_level)
    if level == "score":
        return NativeEventArtifactPlan(
            keep_equity_path=True,
            keep_position_path=True,
            keep_fee_path=True,
            keep_funding_path=True,
            keep_margin_path=True,
            keep_fill_ledger=False,
            keep_command_terminal_state=False,
            keep_event_ledger=False,
            keep_command_tape=False,
            materialize_pandas=False,
            materialize_python_objects=False,
            materialize_active_orders=False,
        )
    if level == "minimal":
        return NativeEventArtifactPlan(
            keep_equity_path=True,
            keep_position_path=True,
            keep_fee_path=True,
            keep_funding_path=True,
            keep_margin_path=True,
            keep_fill_ledger=True,
            keep_command_terminal_state=True,
            keep_event_ledger=False,
            keep_command_tape=False,
            materialize_pandas=True,
            materialize_python_objects=False,
            materialize_active_orders=False,
        )
    if level == "standard":
        return NativeEventArtifactPlan(
            keep_equity_path=True,
            keep_position_path=True,
            keep_fee_path=True,
            keep_funding_path=True,
            keep_margin_path=True,
            keep_fill_ledger=True,
            keep_command_terminal_state=True,
            keep_event_ledger=False,
            keep_command_tape=False,
            materialize_pandas=True,
            materialize_python_objects=True,
            materialize_active_orders=False,
        )
    return NativeEventArtifactPlan(
        keep_equity_path=True,
        keep_position_path=True,
        keep_fee_path=True,
        keep_funding_path=True,
        keep_margin_path=True,
        keep_fill_ledger=True,
        keep_command_terminal_state=True,
        keep_event_ledger=True,
        keep_command_tape=True,
        materialize_pandas=True,
        materialize_python_objects=True,
        materialize_active_orders=True,
    )


@dataclass(slots=True)
class _ReactiveOrderState:
    command: OrderCommand
    command_index: int
    symbol_col: int
    status: int = ORDER_STATUS_PENDING
    active: bool = False
    waiting_parent: bool = False
    working_qty: float = 0.0
    working_price: float = 0.0
    working_trigger: float = 0.0
    reject_code: int = 0


def _compact_score_command(command: OrderCommand) -> OrderCommand:
    """Drop non-execution metadata from a score-only pending order.

    Static score runs do not expose fills, events, active-order snapshots, or
    terminal order objects.  Parent/OCO/group/tag fields remain because they
    affect lifecycle matching; strategy metadata is deliberately not retained
    on the hot state.  Public command objects and audit runs are untouched.
    """

    if not command.metadata:
        return command
    return replace(command, metadata={})


class _OnlineScoreState:
    """Streaming equivalent of the array-first performance metric helpers."""

    __slots__ = (
        "initial_capital", "n_symbols", "trading_days", "prev_equity", "first_equity",
        "last_equity", "peak", "max_drawdown", "drawdown_sum", "drawdown_count",
        "bar_count", "bar_mean", "bar_m2", "bar_downside_sq", "bar_downside_count", "bar_gain", "bar_loss",
        "bar_win_sum", "bar_win_count", "bar_loss_sum", "bar_loss_count", "daily_day",
        "daily_close", "last_daily_close", "daily_points", "daily_mean", "daily_m2",
        "daily_downside_sq", "daily_downside_count", "daily_gain", "daily_loss", "daily_win_sum", "daily_win_count",
        "daily_loss_sum", "daily_loss_count", "daily_peak", "daily_dd_run", "daily_dd_runs",
        "prev_positions", "trade_count", "long_total", "short_total", "long_wins",
        "short_wins", "last_timestamp_ns", "last_observed_bar", "max_initial_margin", "max_maintenance_margin",
    )

    def __init__(self, initial_capital: float, n_symbols: int, trading_days: int = 365) -> None:
        self.initial_capital = float(initial_capital)
        self.n_symbols = int(n_symbols)
        self.trading_days = int(trading_days)
        self.prev_equity = None
        self.first_equity = None
        self.last_equity = float(initial_capital)
        self.peak = -np.inf
        self.max_drawdown = 0.0
        self.drawdown_sum = 0.0
        self.drawdown_count = 0
        self.bar_count = 0
        self.bar_mean = 0.0
        self.bar_m2 = 0.0
        self.bar_downside_sq = 0.0
        self.bar_downside_count = 0
        self.bar_gain = 0.0
        self.bar_loss = 0.0
        self.bar_win_sum = 0.0
        self.bar_win_count = 0
        self.bar_loss_sum = 0.0
        self.bar_loss_count = 0
        self.daily_day = None
        self.daily_close = None
        self.last_daily_close = None
        self.daily_points = 0
        self.daily_mean = 0.0
        self.daily_m2 = 0.0
        self.daily_downside_sq = 0.0
        self.daily_downside_count = 0
        self.daily_gain = 0.0
        self.daily_loss = 0.0
        self.daily_win_sum = 0.0
        self.daily_win_count = 0
        self.daily_loss_sum = 0.0
        self.daily_loss_count = 0
        self.daily_peak = -np.inf
        self.daily_dd_run = 0
        self.daily_dd_runs: List[int] = []
        self.prev_positions = np.zeros(self.n_symbols, dtype=np.float64)
        self.trade_count = self.n_symbols
        self.long_total = np.zeros(self.n_symbols, dtype=np.int64)
        self.short_total = np.zeros(self.n_symbols, dtype=np.int64)
        self.long_wins = np.zeros(self.n_symbols, dtype=np.int64)
        self.short_wins = np.zeros(self.n_symbols, dtype=np.int64)
        self.last_timestamp_ns = None
        self.last_observed_bar = -1
        self.max_initial_margin = 0.0
        self.max_maintenance_margin = 0.0

    @staticmethod
    def _update_moments(value: float, count: int, mean: float, m2: float) -> tuple[int, float, float]:
        count += 1
        delta = value - mean
        mean += delta / count
        m2 += delta * (value - mean)
        return count, mean, m2

    def _observe_return(self, value: float, *, daily: bool) -> None:
        if not np.isfinite(value):
            return
        if daily:
            if value > 0.0:
                self.daily_gain += float(value)
                self.daily_win_sum += float(value)
                self.daily_win_count += 1
            elif value < 0.0:
                self.daily_loss += float(-value)
                self.daily_loss_sum += float(value)
                self.daily_loss_count += 1
            if value < 0.0:
                self.daily_downside_sq += float(value * value)
                self.daily_downside_count += 1
            self.daily_points, self.daily_mean, self.daily_m2 = self._update_moments(
                float(value), self.daily_points - 1, self.daily_mean, self.daily_m2
            )
        else:
            if value > 0.0:
                self.bar_gain += float(value)
                self.bar_win_sum += float(value)
                self.bar_win_count += 1
            elif value < 0.0:
                self.bar_loss += float(-value)
                self.bar_loss_sum += float(value)
                self.bar_loss_count += 1
            if value < 0.0:
                self.bar_downside_sq += float(value * value)
                self.bar_downside_count += 1
            self.bar_count, self.bar_mean, self.bar_m2 = self._update_moments(
                float(value), self.bar_count, self.bar_mean, self.bar_m2
            )

    def _close_day(self) -> None:
        if self.daily_close is None:
            return
        close = float(self.daily_close)
        if self.last_daily_close is not None:
            base = float(self.last_daily_close)
            daily_return = (close - base) / base if base != 0.0 else 0.0
            self._observe_return(float(daily_return), daily=True)
        self.last_daily_close = close
        self.daily_points += 1
        self.daily_peak = max(self.daily_peak, close)
        in_drawdown = self.daily_peak != close
        if in_drawdown:
            self.daily_dd_run += 1
        elif self.daily_dd_run > 0:
            self.daily_dd_runs.append(self.daily_dd_run)
            self.daily_dd_run = 0

    def observe(
        self,
        timestamp,
        equity: float,
        positions: np.ndarray,
        initial_margin: float,
        maintenance_margin: float,
    ) -> None:
        """Consume one canonical post-bar accounting observation."""
        value = float(equity)
        if self.first_equity is None:
            self.first_equity = value
        if self.prev_equity is None or self.prev_equity == 0.0:
            bar_return = 0.0
        else:
            bar_return = value / float(self.prev_equity) - 1.0
        if math.isfinite(float(bar_return)):
            bar_return = float(bar_return)
            self.bar_count += 1
            delta = bar_return - self.bar_mean
            self.bar_mean += delta / self.bar_count
            self.bar_m2 += delta * (bar_return - self.bar_mean)
            if bar_return > 0.0:
                self.bar_gain += bar_return
                self.bar_win_sum += bar_return
                self.bar_win_count += 1
            elif bar_return < 0.0:
                self.bar_loss += -bar_return
                self.bar_loss_sum += bar_return
                self.bar_loss_count += 1
                self.bar_downside_sq += bar_return * bar_return
                self.bar_downside_count += 1

        self.peak = max(self.peak, value)
        drawdown = (self.peak - value) / self.peak if self.peak != 0.0 else 0.0
        self.max_drawdown = max(self.max_drawdown, float(drawdown))
        if drawdown > 0.0:
            self.drawdown_sum += float(drawdown)
            self.drawdown_count += 1

        current = positions
        for j in range(self.n_symbols):
            position = float(current[j])
            if self.bar_count > 1 and position != self.prev_positions[j]:
                self.trade_count += 1
            if position > 0.0:
                self.long_total[j] += 1
                if bar_return > 0.0:
                    self.long_wins[j] += 1
            elif position < 0.0:
                self.short_total[j] += 1
                if bar_return > 0.0:
                    self.short_wins[j] += 1
            self.prev_positions[j] = position
        self.prev_equity = value
        self.last_equity = value
        self.last_timestamp_ns = int(timestamp) if isinstance(timestamp, (int, np.integer)) else int(pd.Timestamp(timestamp).value)
        self.max_initial_margin = max(self.max_initial_margin, float(initial_margin))
        self.max_maintenance_margin = max(self.max_maintenance_margin, float(maintenance_margin))

        day = self.last_timestamp_ns // 86_400_000_000_000
        if self.daily_day is not None and day != self.daily_day:
            self._close_day()
        self.daily_day = day
        self.daily_close = value

    def finish(self, timestamps: pd.DatetimeIndex) -> Dict[str, float]:
        self._close_day()
        if self.daily_dd_run > 0:
            self.daily_dd_runs.append(self.daily_dd_run)
            self.daily_dd_run = 0

        use_daily = self.daily_points >= 2
        count = self.daily_points - 1 if use_daily else self.bar_count
        mean = self.daily_mean if use_daily else self.bar_mean
        m2 = self.daily_m2 if use_daily else self.bar_m2
        downside_sq = self.daily_downside_sq if use_daily else self.bar_downside_sq
        downside_count = self.daily_downside_count if use_daily else self.bar_downside_count
        gain = self.daily_gain if use_daily else self.bar_gain
        loss = self.daily_loss if use_daily else self.bar_loss
        win_sum = self.daily_win_sum if use_daily else self.bar_win_sum
        win_count = self.daily_win_count if use_daily else self.bar_win_count
        loss_sum = self.daily_loss_sum if use_daily else self.bar_loss_sum
        loss_count = self.daily_loss_count if use_daily else self.bar_loss_count

        if use_daily:
            periods = float(self.trading_days)
        else:
            ns = np.asarray(timestamps.view("int64"), dtype=np.int64)
            deltas = np.diff(ns).astype(np.float64) / 1_000_000_000.0
            deltas = deltas[deltas > 0.0]
            median_seconds = float(np.median(deltas)) if len(deltas) else 0.0
            periods = 365.25 * 24.0 * 60.0 * 60.0 / median_seconds if median_seconds > 0.0 else float(self.trading_days)

        std = float(np.sqrt(m2 / (count - 1))) if count >= 2 and m2 > 0.0 else 0.0
        sharpe_value = float(mean / std * np.sqrt(periods)) if std > 0.0 else 0.0
        downside = float(np.sqrt(downside_sq / downside_count)) if downside_count > 0 else 0.0
        sortino_value = float(mean / downside * np.sqrt(periods)) if downside > 0.0 else (np.inf if mean > 0.0 else 0.0)
        omega_value = float(gain / loss) if loss > 0.0 else np.inf
        pf_value = omega_value
        elapsed_days = 0.0
        if len(timestamps) >= 2:
            elapsed_days = (timestamps[-1] - timestamps[0]).total_seconds() / 86_400.0
        years = elapsed_days / 365.25 if elapsed_days > 0.0 else 0.0
        total_ret = (self.last_equity - self.initial_capital) / self.initial_capital
        if 0.0 < elapsed_days < 1.0:
            cagr_value = total_ret
        elif years <= 0.0:
            cagr_value = 0.0
        elif self.first_equity is None or self.last_equity / self.first_equity <= 0.0:
            cagr_value = -1.0
        else:
            annual_log = np.log(self.last_equity / self.first_equity) / years
            cagr_value = float(np.expm1(np.clip(annual_log, -50.0, 50.0)))
        long_hr = np.divide(self.long_wins, self.long_total, out=np.zeros_like(self.long_wins, dtype=np.float64), where=self.long_total != 0) * 100.0
        short_hr = np.divide(self.short_wins, self.short_total, out=np.zeros_like(self.short_wins, dtype=np.float64), where=self.short_total != 0) * 100.0
        avg_win = win_sum / win_count * 100.0 if win_count else 0.0
        avg_loss = loss_sum / loss_count * 100.0 if loss_count else 0.0
        hit_rate = (float(np.mean(long_hr)) + float(np.mean(short_hr))) / 200.0
        avg_dd = self.drawdown_sum / self.drawdown_count if self.drawdown_count else 0.0
        max_duration = max(self.daily_dd_runs) if self.daily_dd_runs else 0
        avg_duration = float(np.mean(self.daily_dd_runs)) if self.daily_dd_runs else 0.0
        return {
            "initial_capital": float(self.initial_capital),
            "final_equity": float(self.last_equity),
            "total_return_pct": float(total_ret * 100.0),
            "cagr_pct": float(cagr_value * 100.0),
            "sharpe": sharpe_value,
            "sortino": sortino_value,
            "calmar": float(cagr_value / self.max_drawdown) if self.max_drawdown > 0.0 else 0.0,
            "omega": omega_value,
            "max_drawdown_pct": float(self.max_drawdown * 100.0),
            "avg_drawdown_pct": float(avg_dd * 100.0),
            "max_dd_duration_days": int(max_duration),
            "avg_dd_duration_days": int(avg_duration),
            "profit_factor": pf_value,
            "long_hitrate_pct": float(np.mean(long_hr)),
            "short_hitrate_pct": float(np.mean(short_hr)),
            "avg_win_pct": float(avg_win),
            "avg_loss_pct": float(avg_loss),
            "expectancy_pct": float(hit_rate * avg_win + (1.0 - hit_rate) * avg_loss),
            "num_trades": int(self.trade_count),
        }


class _NativeEventReactiveSession:
    """
    Lightweight per-bar state used only to feed reactive strategy callbacks.

    Final accounting still replays the emitted command tape through the Numba
    v2 kernel once. Keeping this session Python-level avoids repeated compile
    and report construction while preserving a single final source of truth.
    """

    def __init__(
        self,
        *,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        market_arrays: PreparedMarketArrays,
        opens_arr: np.ndarray,
        volumes_arr: np.ndarray,
        constraints,
        contract_sizes: np.ndarray,
        leverages: np.ndarray,
        fee_rates: np.ndarray,
        initial_capital: float,
        maintenance_ratio: float,
        slippage: float,
        use_funding: bool,
        retain_terminal_orders: bool = True,
        score_requirements: Optional[NativeEventScoreRequirements] = None,
    ) -> None:
        self.idx = idx
        self.symbols = symbols
        self.symbols_tuple = tuple(symbols)
        self.n_symbols = len(symbols)
        self.symbol_to_col = {symbol: j for j, symbol in enumerate(symbols)}
        self.market_arrays = market_arrays
        self.opens_arr = opens_arr
        self.volumes_arr = volumes_arr
        self.constraints = constraints
        # Quantity policy is immutable for a session.  Cache the decision once
        # so score/research loops do not scan every constraint array per bar.
        self.constraints_enabled = bool(constraints.enabled)
        self.contract_sizes = contract_sizes
        self.leverages = leverages
        self.fee_rates = fee_rates
        self.initial_capital = float(initial_capital)
        self.maintenance_ratio = float(maintenance_ratio)
        self.slippage = float(slippage)
        self.use_funding = bool(use_funding)
        self.retain_terminal_orders = bool(retain_terminal_orders)
        self.score_requirements = score_requirements
        self.retain_fill_ledger = bool(
            score_requirements is None or score_requirements.need_fill_ledger
        )
        self.retain_event_ledger = bool(
            score_requirements is None or score_requirements.need_event_ledger
        )
        self.emit_context_fills = bool(
            score_requirements is None or score_requirements.need_context_fills
        )
        self.emit_context_events = bool(
            score_requirements is None or score_requirements.need_context_events
        )
        self.emit_context_active_orders = bool(
            score_requirements is None or score_requirements.need_context_active_orders
        )
        self.emit_context_positions = bool(
            score_requirements is None or score_requirements.need_context_positions
        )
        self.emit_context_margin = bool(
            score_requirements is None or score_requirements.need_context_margin
        )
        self.compact_score_state = bool(
            score_requirements is not None
            and not score_requirements.need_context_fills
            and not score_requirements.need_context_events
            and not score_requirements.need_context_active_orders
            and not score_requirements.need_context_positions
            and not score_requirements.need_context_margin
            and not score_requirements.need_fill_ledger
            and not score_requirements.need_event_ledger
            and not score_requirements.need_terminal_orders
        )

        self.current_pos = np.zeros(len(symbols), dtype=np.float64)
        self.equity = float(initial_capital)
        self.liquidated = False
        self.liquidation_bar = -1
        self.liquidation_reason = LIQ_NONE
        self.command_seq = 0
        self.orders: List[_ReactiveOrderState] = []
        self.pending: List[_ReactiveOrderState] = []
        self.id_to_order: Dict[str, _ReactiveOrderState] = {}
        self.scheduled: Dict[int, List[OrderCommand]] = {}
        self.fills_by_bar: Dict[int, List[NativeFillEvent]] = {}
        self.events_by_bar: Dict[int, List[NativeOrderEvent]] = {}
        self.fills: List[NativeFillEvent] = []
        self.events: List[NativeOrderEvent] = []
        self.fill_count = 0
        self.event_count = 0
        self.rejected_count = 0
        self.canceled_count = 0
        self.expired_count = 0
        self.total_fee = 0.0
        self.total_funding = 0.0
        self.total_turnover = 0.0
        self.children_by_parent_id: Dict[str, List[_ReactiveOrderState]] = {}
        self.members_by_oco_group: Dict[str, List[_ReactiveOrderState]] = {}
        self.expiry_by_bar: Dict[int, List[_ReactiveOrderState]] = {}
        self.processed_bar = -1
        self.last_initial_margin = 0.0
        self.last_maintenance_margin = 0.0
        self.margin_bar = -1
        self.margin_dirty = True
        self.size_helper = NativeEventBackend._reactive_size_helper(
            symbols=self.symbols,
            constraints=self.constraints,
            contract_sizes=self.contract_sizes,
        )
        self.empty_fills: tuple[NativeFillEvent, ...] = ()
        self.empty_events: tuple[NativeOrderEvent, ...] = ()
        self.empty_active_orders: tuple[NativeActiveOrderSnapshot, ...] = ()
        self._active_snapshot_cache: tuple[NativeActiveOrderSnapshot, ...] = self.empty_active_orders
        self._active_snapshot_dirty = True
        self.execution_counters = {
            "bars_processed": 0,
            "bars_with_commands": 0,
            "contexts_materialized": 0,
            "timestamp_objects_materialized": 0,
            "active_snapshot_materializations": 0,
            "empty_command_batches_skipped": 0,
            "constraint_preflight_calls": 0,
            "constraint_preflight_skipped": 0,
            "commands_retimed": 0,
            "commands_quantized": 0,
        }
        n_bars = len(idx)
        n_syms = len(symbols)
        requirements = score_requirements
        self.equity_path = np.zeros(n_bars, dtype=np.float64) if requirements is None or requirements.need_equity_path else None
        self.pos_path = np.zeros((n_bars, n_syms), dtype=np.float64) if requirements is None or requirements.need_position_path else None
        self.fee_path = np.zeros(n_bars, dtype=np.float64) if requirements is None or requirements.need_fee_path else None
        self.turnover_path = np.zeros(n_bars, dtype=np.float64) if requirements is None or requirements.need_turnover_path else None
        self.funding_path = np.zeros(n_bars, dtype=np.float64) if requirements is None or requirements.need_funding_path else None
        self.initial_margin_path = np.zeros(n_bars, dtype=np.float64) if requirements is None or requirements.need_margin_path else None
        self.maintenance_margin_path = np.zeros(n_bars, dtype=np.float64) if requirements is None or requirements.need_margin_path else None
        self.rejected_bar = np.zeros(n_bars, dtype=np.int64) if requirements is None or requirements.need_rejection_path else None
        self.canceled_bar = np.zeros(n_bars, dtype=np.int64) if requirements is None or requirements.need_cancellation_path else None
        self.online_score = (
            _OnlineScoreState(self.initial_capital, n_syms)
            if requirements is not None and requirements.need_trade_stats
            else None
        )
        self._record_bar(0)

    def schedule(self, bar: int, commands: Sequence[OrderCommand]) -> None:
        if not commands or bar >= len(self.idx):
            return
        self.scheduled.setdefault(int(bar), []).extend(commands)

    def release_bar_payload(self, bar: int) -> None:
        self.fills_by_bar.pop(int(bar), None)
        self.events_by_bar.pop(int(bar), None)

    def process_bar(self, bar: int) -> None:
        if bar <= self.processed_bar:
            return
        for i in range(self.processed_bar + 1, int(bar) + 1):
            self._process_single_bar(i)
            self.processed_bar = i
            self.execution_counters["bars_processed"] += 1

    def context(self, bar: int) -> NativeStrategyContext:
        self.process_bar(bar)
        self.execution_counters["contexts_materialized"] += 1
        self.execution_counters["timestamp_objects_materialized"] += 1
        init_margin, maint_margin = self._refresh_close_margin(bar)
        if self.emit_context_positions and self.n_symbols == 1:
            positions = {self.symbols[0]: float(self.current_pos[0])}
        elif self.emit_context_positions:
            positions = {symbol: float(self.current_pos[j]) for j, symbol in enumerate(self.symbols)}
        else:
            positions = {}
        if self.emit_context_fills:
            fills_this_bar = tuple(self.fills_by_bar.get(int(bar), self.empty_fills))
        else:
            fills_this_bar = self.empty_fills
        if self.emit_context_events:
            events_this_bar = tuple(self.events_by_bar.get(int(bar), self.empty_events))
        else:
            events_this_bar = self.empty_events
        if not self.emit_context_margin:
            init_margin = 0.0
            maint_margin = 0.0
        return NativeStrategyContext(
            bar_index=int(bar),
            timestamp=self.idx[int(bar)],
            open=self.opens_arr[int(bar)],
            high=self.market_arrays.highs[int(bar)],
            low=self.market_arrays.lows[int(bar)],
            close=self.market_arrays.closes[int(bar)],
            volume=self.volumes_arr[int(bar)],
            equity=float(self.equity),
            available_equity=float(self.equity - init_margin),
            initial_margin=float(init_margin),
            maintenance_margin=float(maint_margin),
            positions=positions,
            fills_this_bar=fills_this_bar,
            order_events_this_bar=events_this_bar,
            active_orders=self._active_snapshots() if self.emit_context_active_orders else self.empty_active_orders,
            liquidated=bool(self.liquidated),
            symbols=self.symbols_tuple,
            size_order=self.size_helper,
        )

    def _process_single_bar(self, bar: int) -> None:
        if self.liquidated:
            self._record_bar(bar)
            return
        if bar > 0:
            for s in range(len(self.symbols)):
                p = self.current_pos[s]
                if p != 0.0:
                    self.equity += (
                        p
                        * (self.market_arrays.closes[bar, s] - self.market_arrays.closes[bar - 1, s])
                        * self.contract_sizes[s]
                    )
        if bar > 0 and self._liquidated_intrabar(bar):
            self._liquidate(bar, LIQ_INTRABAR)
            self._record_bar(bar)
            return
        if bar > 0 and self.use_funding and self.market_arrays.is_funding_bar[bar]:
            funding_cost = 0.0
            for s in range(len(self.symbols)):
                p = self.current_pos[s]
                if p != 0.0:
                    funding_cost += (
                        p
                        * self.market_arrays.closes[bar, s]
                        * self.contract_sizes[s]
                        * self.market_arrays.funding[bar, s]
                    )
            self.equity -= funding_cost
            self.total_funding += float(funding_cost)
            if self.funding_path is not None:
                self.funding_path[bar] += funding_cost
        if bar > 0:
            _, close_mm = self._refresh_close_margin(bar)
            if close_mm > 0.0 and self.equity <= close_mm:
                self._liquidate(bar, LIQ_AFTER_FUNDING)
                self._record_bar(bar)
                return

        self._expire_orders(bar)
        for command in self.scheduled.pop(bar, ()):
            self._apply_command(bar, command)
        self._match_orders(bar)
        self._compact_pending()
        _, close_mm = self._refresh_close_margin(bar)
        if close_mm > 0.0 and self.equity <= close_mm:
            self._liquidate(bar, LIQ_AFTER_ORDER)
        self._record_bar(bar)

    def _record_bar(self, bar: int) -> None:
        if bar < 0 or bar >= len(self.idx):
            return
        init_margin, maint_margin = self._refresh_close_margin(bar)
        if self.equity_path is not None:
            self.equity_path[bar] = float(self.equity)
        if self.pos_path is not None:
            self.pos_path[bar, :] = self.current_pos
        if self.initial_margin_path is not None:
            self.initial_margin_path[bar] = float(init_margin)
        if self.maintenance_margin_path is not None:
            self.maintenance_margin_path[bar] = float(maint_margin)
        if self.online_score is not None and self.online_score.last_observed_bar != int(bar):
            self.online_score.observe(
                self.idx.asi8[bar],
                self.equity,
                self.current_pos,
                init_margin,
                maint_margin,
            )
            self.online_score.last_observed_bar = int(bar)

    def _apply_command(self, bar: int, command: OrderCommand) -> None:
        action = command.action
        if action is OrderAction.PLACE:
            self._place_order(bar, command, "place")
        elif action is OrderAction.REPLACE:
            target = self._lookup_pending(command.target_order_id)
            if target is None:
                self._event(bar, command, "reject", ORDER_STATUS_REJECTED, target_order_id=command.target_order_id)
            else:
                self._cancel_state(bar, target, "replace", ORDER_STATUS_CANCELED, command)
                replacement = self._place_order(bar, command, "replace")
                if command.target_order_id and replacement is not None:
                    self.id_to_order[command.target_order_id] = replacement
        elif action is OrderAction.CANCEL:
            target = self._lookup_pending(command.target_order_id)
            if target is None:
                self._event(bar, command, "reject", ORDER_STATUS_REJECTED, target_order_id=command.target_order_id)
            else:
                self._cancel_state(bar, target, "cancel", ORDER_STATUS_FILLED, command)
        elif action is OrderAction.AMEND:
            target = self._lookup_pending(command.target_order_id)
            if target is None:
                self._event(bar, command, "reject", ORDER_STATUS_REJECTED, target_order_id=command.target_order_id)
            else:
                if command.qty is not None and command.qty > 0.0:
                    target.working_qty = float(command.qty)
                if command.price is not None and command.price > 0.0:
                    target.working_price = float(command.price)
                if command.trigger_price is not None and command.trigger_price > 0.0:
                    target.working_trigger = float(command.trigger_price)
                self._event(bar, command, "amend", ORDER_STATUS_FILLED, target_order_id=command.target_order_id)
        elif action is OrderAction.CANCEL_ALL:
            targets = self.pending if self._cancel_all_unfiltered(command) else tuple(self.pending)
            for target in targets:
                if self._is_pending(target) and self._cancel_all_matches(command, target.command):
                    self._cancel_state(bar, target, "cancel", ORDER_STATUS_CANCELED, command)
            self._event(bar, command, "cancel", ORDER_STATUS_FILLED)
        else:
            self._event(bar, command, "reject", ORDER_STATUS_REJECTED)

    def _place_order(self, bar: int, command: OrderCommand, event_name: str) -> Optional[_ReactiveOrderState]:
        if command.symbol is None or command.symbol not in self.symbol_to_col:
            self._event(bar, command, "reject", ORDER_STATUS_REJECTED)
            return None
        stored_command = _compact_score_command(command) if self.compact_score_state else command
        state = _ReactiveOrderState(
            command=stored_command,
            command_index=self.command_seq,
            symbol_col=self.symbol_to_col[command.symbol],
            active=command.activation_policy is OrderActivationPolicy.IMMEDIATE,
            waiting_parent=command.activation_policy is not OrderActivationPolicy.IMMEDIATE,
            working_qty=0.0 if command.qty is None else float(command.qty),
            working_price=0.0 if command.price is None else float(command.price),
            working_trigger=0.0 if command.trigger_price is None else float(command.trigger_price),
        )
        self.command_seq += 1
        self.pending.append(state)
        if self.retain_terminal_orders:
            self.orders.append(state)
        if command.order_id:
            self.id_to_order[command.order_id] = state
        if command.parent_order_id:
            self.children_by_parent_id.setdefault(command.parent_order_id, []).append(state)
        if command.oco_group_id:
            self.members_by_oco_group.setdefault(command.oco_group_id, []).append(state)
        if command.expires_at is not None:
            expiry_bar = max(self._expiry_bar(command.expires_at), int(bar) + 1)
            if 0 <= expiry_bar < len(self.idx):
                self.expiry_by_bar.setdefault(expiry_bar, []).append(state)
        self._active_snapshot_dirty = True
        self._event(bar, command, event_name, ORDER_STATUS_PENDING)
        return state

    def _match_orders(self, bar: int) -> None:
        for state in tuple(self.pending):
            if not state.active or state.status != ORDER_STATUS_PENDING:
                continue
            command = state.command
            if command.side is None or command.order_type is None:
                continue
            touched, exec_price = self._touched_price(
                command.order_type,
                command.side,
                state.working_price,
                state.working_trigger,
                self.market_arrays.highs[bar, state.symbol_col],
                self.market_arrays.lows[bar, state.symbol_col],
                self.market_arrays.closes[bar, state.symbol_col],
            )
            if not touched:
                if command.tif in (TimeInForce.GTC, TimeInForce.GTD):
                    continue
                self._cancel_state(bar, state, "cancel", ORDER_STATUS_CANCELED, command)
                continue

            qty = float(state.working_qty)
            side_sign = command.side.sign
            if command.reduce_only:
                current = self.current_pos[state.symbol_col]
                if current == 0.0 or (current > 0.0 and side_sign > 0) or (current < 0.0 and side_sign < 0):
                    state.reject_code = REJECT_REDUCE_ONLY_NO_POSITION
                    self._cancel_state(bar, state, "cancel", ORDER_STATUS_CANCELED, command)
                    continue
                qty = min(qty, abs(current))

            delta = qty * side_sign
            cs = float(self.contract_sizes[state.symbol_col])
            close = float(self.market_arrays.closes[bar, state.symbol_col])
            trade_notional = abs(delta) * float(exec_price) * cs
            fee_cost = trade_notional * float(self.fee_rates[state.symbol_col])
            required, cur_im = self._margin_required(bar, state.symbol_col, delta, float(exec_price), fee_cost)
            if required > self.equity - cur_im:
                state.status = ORDER_STATUS_REJECTED
                state.reject_code = REJECT_INSUFFICIENT_MARGIN
                self._event(bar, command, "reject", ORDER_STATUS_REJECTED)
                self._terminalize_state(state)
                continue

            self.equity += delta * (close - float(exec_price)) * cs - fee_cost
            self.current_pos[state.symbol_col] += delta
            self.margin_dirty = True
            if self.fee_path is not None:
                self.fee_path[bar] += fee_cost
            if self.turnover_path is not None:
                self.turnover_path[bar] += trade_notional
            self.total_fee += float(fee_cost)
            self.total_turnover += float(trade_notional)
            state.status = ORDER_STATUS_FILLED
            fill = None
            if self.emit_context_fills or self.retain_fill_ledger:
                fill = NativeFillEvent(
                    timestamp=self.idx[bar],
                    symbol=command.symbol or self.symbols[state.symbol_col],
                    side=command.side,
                    qty=float(qty),
                    price=float(exec_price),
                    fee=float(fee_cost),
                    order_id=command.order_id,
                    tag=command.tag,
                    campaign_id=command.metadata.get("campaign_id"),
                    cycle_id=command.metadata.get("cycle_id"),
                    level_id=command.metadata.get("level_id"),
                    parent_order_id=command.parent_order_id,
                    oco_group_id=command.oco_group_id,
                    metadata=dict(command.metadata),
                )
            if self.emit_context_fills:
                self.fills_by_bar.setdefault(bar, []).append(fill)
            self.fill_count += 1
            if self.retain_fill_ledger and fill is not None:
                self.fills.append(fill)
            self._event(bar, command, "fill", ORDER_STATUS_FILLED)
            self._terminalize_state(state)
            self._activate_children(bar, state)
            self._cancel_oco_siblings(bar, state)

    def _activate_children(self, bar: int, parent: _ReactiveOrderState) -> None:
        parent_id = parent.command.order_id
        if not parent_id:
            return
        children = self.children_by_parent_id.get(parent_id, ())
        for child in tuple(children):
            if child.waiting_parent and child.command.parent_order_id == parent_id:
                if child.command.activation_policy in (
                    OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                    OrderActivationPolicy.ON_PARENT_FULL_FILL,
                ):
                    child.waiting_parent = False
                    child.active = True
                    self._active_snapshot_dirty = True
                    self._event(bar, child.command, "activate", ORDER_STATUS_PENDING, related_order_id=parent_id)
        self.children_by_parent_id[parent_id] = [child for child in children if self._is_pending(child)]
        if not self.children_by_parent_id[parent_id]:
            self.children_by_parent_id.pop(parent_id, None)

    def _cancel_oco_siblings(self, bar: int, filled: _ReactiveOrderState) -> None:
        group = filled.command.oco_group_id
        if not group:
            return
        siblings = self.members_by_oco_group.get(group, ())
        for sibling in tuple(siblings):
            if sibling is filled:
                continue
            if self._is_pending(sibling) and sibling.command.oco_group_id == group:
                self._cancel_state(bar, sibling, "cancel", ORDER_STATUS_CANCELED, filled.command)
        self.members_by_oco_group[group] = [sibling for sibling in siblings if self._is_pending(sibling)]
        if not self.members_by_oco_group[group]:
            self.members_by_oco_group.pop(group, None)

    def _expire_orders(self, bar: int) -> None:
        for state in tuple(self.expiry_by_bar.pop(int(bar), ())):
            if not self._is_pending(state) or state.command.expires_at is None:
                continue
            self._cancel_state(bar, state, "expire", ORDER_STATUS_CANCELED, state.command)

    def _cancel_state(
        self,
        bar: int,
        state: _ReactiveOrderState,
        event_name: str,
        event_status: int,
        command: OrderCommand,
    ) -> None:
        state.active = False
        state.waiting_parent = False
        state.status = ORDER_STATUS_CANCELED
        self.canceled_count += 1
        if self.canceled_bar is not None:
            self.canceled_bar[bar] += 1
        self._event(
            bar,
            command,
            event_name,
            event_status,
            target_order_id=state.command.order_id,
            related_order_id=state.command.order_id,
        )
        self._terminalize_state(state)

    def _event(
        self,
        bar: int,
        command: OrderCommand,
        event_name: str,
        status: int,
        *,
        target_order_id: Optional[str] = None,
        related_order_id: Optional[str] = None,
    ) -> None:
        if event_name == "reject":
            self.rejected_count += 1
            if self.rejected_bar is not None:
                self.rejected_bar[bar] += 1
        if event_name == "expire":
            self.expired_count += 1
        event = None
        if self.emit_context_events or self.retain_event_ledger:
            event = NativeOrderEvent(
                timestamp=self.idx[bar],
                bar=int(bar),
                event_name=event_name,
                status=int(status),
                order_id=command.order_id,
                target_order_id=target_order_id or command.target_order_id,
                parent_order_id=command.parent_order_id,
                oco_group_id=command.oco_group_id,
                tag=command.tag,
                campaign_id=command.metadata.get("campaign_id"),
                cycle_id=command.metadata.get("cycle_id"),
                level_id=command.metadata.get("level_id"),
                original_index=-1,
                related_original_index=-1,
            )
        if self.emit_context_events and event is not None:
            self.events_by_bar.setdefault(bar, []).append(event)
        self.event_count += 1
        if self.retain_event_ledger and event is not None:
            self.events.append(event)

    def _lookup_pending(self, order_id: Optional[str]) -> Optional[_ReactiveOrderState]:
        if not order_id:
            return None
        state = self.id_to_order.get(order_id)
        if state is None or not self._is_pending(state):
            return None
        return state

    @staticmethod
    def _is_pending(state: _ReactiveOrderState) -> bool:
        return state.status == ORDER_STATUS_PENDING and (state.active or state.waiting_parent)

    def _terminalize_state(self, state: _ReactiveOrderState) -> None:
        state.active = False
        state.waiting_parent = False
        order_id = state.command.order_id
        if order_id and self.id_to_order.get(order_id) is state:
            self.id_to_order.pop(order_id, None)
        parent_id = state.command.parent_order_id
        if parent_id and parent_id in self.children_by_parent_id:
            children = [child for child in self.children_by_parent_id[parent_id] if child is not state and self._is_pending(child)]
            if children:
                self.children_by_parent_id[parent_id] = children
            else:
                self.children_by_parent_id.pop(parent_id, None)
        group = state.command.oco_group_id
        if group and group in self.members_by_oco_group:
            members = [member for member in self.members_by_oco_group[group] if member is not state and self._is_pending(member)]
            if members:
                self.members_by_oco_group[group] = members
            else:
                self.members_by_oco_group.pop(group, None)
        self._active_snapshot_dirty = True

    def _expiry_bar(self, expires_at) -> int:
        exp = pd.Timestamp(expires_at)
        if exp.tz is None:
            exp = exp.tz_localize("UTC")
        else:
            exp = exp.tz_convert("UTC")
        return int(self.idx.searchsorted(exp, side="left"))

    def _active_snapshots(self) -> tuple[NativeActiveOrderSnapshot, ...]:
        if not self.pending:
            self._active_snapshot_cache = self.empty_active_orders
            self._active_snapshot_dirty = False
            return self.empty_active_orders
        if not self._active_snapshot_dirty:
            return self._active_snapshot_cache
        self.execution_counters["active_snapshot_materializations"] += 1
        out: List[NativeActiveOrderSnapshot] = []
        for state in self.pending:
            if not self._is_pending(state):
                continue
            command = state.command
            out.append(
                NativeActiveOrderSnapshot(
                    order_id=command.order_id,
                    symbol=command.symbol,
                    side=None if command.side is None else command.side.value,
                    order_type=None if command.order_type is None else command.order_type.value,
                    status=int(state.status),
                    remaining_qty=float(state.working_qty),
                    price=float(state.working_price),
                    trigger_price=float(state.working_trigger),
                    reduce_only=bool(command.reduce_only),
                    parent_order_id=command.parent_order_id,
                    group_id=command.group_id,
                    oco_group_id=command.oco_group_id,
                    tag=command.tag,
                    campaign_id=command.metadata.get("campaign_id"),
                    cycle_id=command.metadata.get("cycle_id"),
                    level_id=command.metadata.get("level_id"),
                )
            )
        self._active_snapshot_cache = tuple(out) if out else self.empty_active_orders
        self._active_snapshot_dirty = False
        return self._active_snapshot_cache

    def _refresh_close_margin(self, bar: int) -> tuple[float, float]:
        bar = int(bar)
        if not self.margin_dirty and self.margin_bar == bar:
            return self.last_initial_margin, self.last_maintenance_margin
        init_margin = 0.0
        maint_margin = 0.0
        for s in range(len(self.symbols)):
            p = self.current_pos[s]
            if p != 0.0:
                notional = abs(p) * self.market_arrays.closes[bar, s] * self.contract_sizes[s]
                init_margin += notional / self.leverages[s]
                maint_margin += notional * self.maintenance_ratio
        self.last_initial_margin = float(init_margin)
        self.last_maintenance_margin = float(maint_margin)
        self.margin_bar = bar
        self.margin_dirty = False
        return self.last_initial_margin, self.last_maintenance_margin

    def _close_margin(self, bar: int) -> tuple[float, float]:
        return self._refresh_close_margin(bar)

    def _margin_required(self, bar: int, sym: int, delta: float, exec_price: float, fee_cost: float) -> tuple[float, float]:
        cur_im, _ = self._refresh_close_margin(bar)
        close = float(self.market_arrays.closes[bar, sym])
        old_im = abs(self.current_pos[sym]) * close * self.contract_sizes[sym] / self.leverages[sym]
        new_im = abs(self.current_pos[sym] + delta) * exec_price * self.contract_sizes[sym] / self.leverages[sym]
        required = float(fee_cost)
        margin_delta = new_im - old_im
        if margin_delta > 0.0:
            required += margin_delta
        return float(required), float(cur_im)

    def _liquidated_intrabar(self, bar: int) -> bool:
        worst_equity = self.equity
        worst_mm = 0.0
        for s in range(len(self.symbols)):
            p = self.current_pos[s]
            if p == 0.0:
                continue
            worst_price = self.market_arrays.lows[bar, s] if p > 0.0 else self.market_arrays.highs[bar, s]
            worst_equity += p * (worst_price - self.market_arrays.closes[bar, s]) * self.contract_sizes[s]
            worst_mm += abs(p) * worst_price * self.contract_sizes[s] * self.maintenance_ratio
        return worst_mm > 0.0 and worst_equity <= worst_mm

    def _liquidate(self, bar: int, reason: int) -> None:
        self.liquidated = True
        self.liquidation_bar = int(bar)
        self.liquidation_reason = int(reason)
        self.equity = 0.0
        self.current_pos[:] = 0.0
        self.margin_dirty = True
        self._active_snapshot_dirty = True

    def _touched_price(
        self,
        order_type: OrderType,
        side: OrderSide,
        price: float,
        trigger_price: float,
        high: float,
        low: float,
        close: float,
    ) -> tuple[bool, float]:
        if order_type is OrderType.MARKET:
            return True, float(close * (1.0 + self.slippage if side is OrderSide.BUY else 1.0 - self.slippage))
        if order_type is OrderType.LIMIT:
            if side is OrderSide.BUY and low <= price:
                return True, float(price)
            if side is OrderSide.SELL and high >= price:
                return True, float(price)
        if order_type is OrderType.STOP_MARKET:
            if side is OrderSide.BUY and high >= trigger_price:
                return True, float(trigger_price * (1.0 + self.slippage))
            if side is OrderSide.SELL and low <= trigger_price:
                return True, float(trigger_price * (1.0 - self.slippage))
        if order_type is OrderType.STOP_LIMIT:
            if side is OrderSide.BUY and high >= trigger_price and low <= price:
                return True, float(price)
            if side is OrderSide.SELL and low <= trigger_price and high >= price:
                return True, float(price)
        return False, float(close)

    @staticmethod
    def _cancel_all_unfiltered(command: OrderCommand) -> bool:
        return (
            command.symbol is None
            and command.side is None
            and command.order_type is None
            and command.parent_order_id is None
            and command.group_id is None
            and command.oco_group_id is None
            and command.tag is None
            and command.tag_prefix is None
            and not command.metadata
        )

    @staticmethod
    def _cancel_all_matches(cancel_command: OrderCommand, target: OrderCommand) -> bool:
        if cancel_command.symbol is not None and cancel_command.symbol != target.symbol:
            return False
        if cancel_command.side is not None and cancel_command.side is not target.side:
            return False
        if cancel_command.order_type is not None and cancel_command.order_type is not target.order_type:
            return False
        if cancel_command.parent_order_id is not None and cancel_command.parent_order_id != target.parent_order_id:
            return False
        if cancel_command.group_id is not None and cancel_command.group_id != target.group_id:
            return False
        if cancel_command.oco_group_id is not None and cancel_command.oco_group_id != target.oco_group_id:
            return False
        if cancel_command.tag is not None and cancel_command.tag != target.tag:
            return False
        if cancel_command.tag_prefix is not None and not (target.tag or "").startswith(cancel_command.tag_prefix):
            return False
        for key in ("campaign_id", "cycle_id", "level_id"):
            if key in cancel_command.metadata and cancel_command.metadata.get(key) != target.metadata.get(key):
                return False
        return True

    def _compact_pending(self) -> None:
        if not self.pending:
            return
        self.pending = [state for state in self.pending if self._is_pending(state)]
        self._active_snapshot_dirty = True


class NativeEventBackend:
    """
    Event-driven backend for explicit OrderIntent sequences.

    Phase 3 supports market and limit orders on OHLC bars. Limit orders fill at
    the order price when high/low touches the level. Market orders fill at the
    current close with configured slippage.
    """

    def __init__(self, config: NativeEventConfig):
        self.config = config
        # Phase 46E: selection is explicit and capability-gated. ``auto``
        # remains Python for the release; direct Rust is limited to the
        # certified single-symbol batched tape path.
        self._backend_selection = resolve_native_event_backend(requested=config.native_backend)
        # Keys use object identity in addition to the immutable market
        # signature: open/volume are callback-visible and are not part of the
        # OHLC/funding signature. Reuse is therefore safe only for the exact
        # prepared arrays owned by one prepared runner.
        self._rust_prepared_market_cores: Dict[tuple, object] = {}

    def _create_reactive_session(
        self,
        *,
        backend_selection: NativeEventBackendSelection,
        **kwargs,
    ) -> _NativeEventReactiveSession | RustReactiveSessionAdapter:
        """Create the selected reactive session without changing endpoint APIs.

        Rust's per-bar adapter remains a correctness/debug path. Unsupported
        execution semantics fail explicitly under backend='rust' rather than
        silently switching domain behavior.
        """
        if backend_selection.resolved == "rust":
            market_arrays = kwargs["market_arrays"]
            key = (market_arrays.signature, id(kwargs["opens_arr"]), id(kwargs["volumes_arr"]))
            kwargs["prepared_market_core"] = self._rust_prepared_market_cores.get(key)
            session = RustReactiveSessionAdapter(**kwargs)
            prepared_core = getattr(session, "prepared_market_core", None)
            if prepared_core is not None:
                self._rust_prepared_market_cores.setdefault(key, prepared_core)
            return session
        return _NativeEventReactiveSession(**kwargs)

    def _backend_selection_metadata(self) -> dict:
        selection = self._backend_selection
        return {
            "native_event_backend_requested": selection.requested,
            "native_event_backend_resolved": selection.resolved,
            "native_event_rust_available": bool(selection.extension.available),
            "native_event_rust_compatible": bool(selection.extension.compatible),
            "native_event_rust_capabilities": dict(selection.extension.capabilities),
            "native_event_rust_canonical_capabilities": dict(selection.extension.canonical_capabilities),
        }

    def prepare_market_arrays(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        symbols: Optional[Sequence[str]] = None,
    ) -> PreparedMarketArrays:
        """
        Normalize OHLC/funding inputs into immutable ndarray-backed market arrays.

        This helper is intended for higher-level optimizers and WFO loops that
        replay many order packages over the same market tape. The returned
        object carries a datetime/symbol signature and `run_orders` rejects it
        if reused against a different index or symbol layout.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(closes.keys())
        close_dict = align_series(closes, symbol_list, idx)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
        return build_market_arrays(
            symbols=symbol_list,
            idx=idx,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            funding_dict=funding_dict,
        )

    def prepare_rust_batched_runner(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        *,
        symbols: Optional[Sequence[str]] = None,
        contract_size: float = 1.0,
        leverage: Optional[float] = None,
        fee_rate: Optional[float] = None,
        initial_capital: Optional[float] = None,
        maintenance_ratio: Optional[float] = None,
        slippage: Optional[float] = None,
        prepared_market_core=None,
    ) -> RustFullRunner:
        """Prepare the explicit experimental Rust full-tape runner.

        This helper does not change endpoint defaults and never accepts a
        Python strategy callback. Callers compile a static ``OrderCommand``
        tape once and pass it to ``run_tape_score`` or ``run_tape_audit``.
        The selected Rust 0.4 full-contract capability set is checked before
        crossing the boundary.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(closes.keys())
        market_arrays = self.prepare_market_arrays(
            datetime_index=idx,
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rate=funding_rate if self.config.use_funding else 0.0,
            symbols=symbol_list,
        )
        configured_fee = self.config.fee_rate
        if isinstance(configured_fee, dict):
            configured_fee = configured_fee.get(symbol_list[0], 0.0)
        return RustFullRunner(
            idx=idx,
            symbols=symbol_list,
            market_arrays=market_arrays,
            contract_sizes=self._per_symbol_array(contract_size, symbol_list, default=1.0),
            leverages=self._per_symbol_array(
                self.config.account.leverage if leverage is None else leverage,
                symbol_list,
                default=self.config.account.leverage,
            ),
            fee_rates=self._per_symbol_array(configured_fee if fee_rate is None else fee_rate, symbol_list, default=0.0),
            initial_capital=float(
                self.config.account.initial_capital if initial_capital is None else initial_capital
            ),
            maintenance_ratio=float(
                self.config.account.maintenance_ratio if maintenance_ratio is None else maintenance_ratio
            ),
            slippage=float(self.config.execution.slippage_rate if slippage is None else slippage),
            use_funding=bool(self.config.use_funding),
            prepared_market_core=prepared_market_core,
        )

    @staticmethod
    def compile_orders(
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        orders: Sequence[OrderIntent],
        symbols: Optional[Sequence[str]] = None,
    ) -> CompiledOrderArrays:
        """
        Compile explicit `OrderIntent` objects into contiguous kernel arrays.

        Use this when the same order package is replayed against the same
        market tape. If `symbols` is omitted it is inferred from first
        occurrence in the order sequence, which is convenient for standalone
        simulations; passing the exact market symbol order is safer for
        multi-symbol portfolio and arbitrage packages.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(dict.fromkeys(order.symbol for order in orders))
        return compile_order_intents(idx=idx, orders=orders, symbol_to_col={s: j for j, s in enumerate(symbol_list)})

    @staticmethod
    def compile_order_commands(
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        commands: Sequence[OrderCommand],
        symbols: Optional[Sequence[str]] = None,
    ) -> CompiledOrderCommandArrays:
        """
        Compile lifecycle commands for the native-event v2 contract.

        Phase 30A exposes this helper for adapters and strategy services. It
        does not route commands into the v1 matching kernel; the v2 lifecycle
        kernel is a later phase.
        """
        idx = validate_datetime(datetime_index)
        if symbols is None:
            symbol_list = list(dict.fromkeys(command.symbol for command in commands if command.symbol is not None))
        else:
            symbol_list = list(symbols)
        return compile_order_commands(
            idx=idx,
            commands=commands,
            symbol_to_col={s: j for j, s in enumerate(symbol_list)},
        )

    def run_order_commands(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        commands: Sequence[OrderCommand],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
        compiled_commands: Optional[CompiledOrderCommandArrays] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        report_level: Optional[str] = None,
        audit_sink: Optional[str] = None,
        audit_sink_path: Optional[str] = None,
        _force_python_backend: bool = False,
    ) -> BacktestResultV2:
        """
        Execute Phase 30B lifecycle `OrderCommand` tapes through event v2.

        This is intentionally opt-in. Existing `run_orders(OrderIntent...)`
        remains routed to event v1 until endpoint parity is promoted in a later
        phase.
        """
        idx = validate_datetime(datetime_index)
        requested_report_level = self.config.report_level if report_level is None else report_level
        level = _normalize_native_event_report_level(requested_report_level)
        plan = _native_event_artifact_plan(level)
        sink = self.config.audit_sink if audit_sink is None else _normalize_native_event_audit_sink(audit_sink)
        sink_path = self.config.audit_sink_path if audit_sink_path is None else audit_sink_path
        if symbols is None:
            symbol_list = list(closes.keys())
        else:
            symbol_list = list(symbols)

        if market_arrays is None:
            market_arrays = self.prepare_market_arrays(
                datetime_index=idx,
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=funding_rate,
                symbols=symbol_list,
            )
        elif market_arrays.signature != self._market_signature(idx, symbol_list):
            raise ValueError("prepared market arrays do not match datetime_index/symbols")

        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        constraints = build_quantity_constraints(
            symbol_list,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        if self._backend_selection.resolved == "rust" and not _force_python_backend:
            status = self._backend_selection.extension
            required = {
                "native_event_v2_full_contract",
                "native_event_v2_multisymbol",
                "native_event_v2_funding",
                "native_event_v2_liquidation",
                "native_event_v2_cancel_all_oco",
                "native_event_v2_tif_expiry",
                "native_event_v2_relationships",
            }
            missing = sorted(name for name in required if not status.capabilities.get(name, False))
            if missing:
                raise NativeEventRustBackendError(
                    "native_backend='rust' requires full-contract capabilities: " + ", ".join(missing)
                )
        effective_commands, quantity_preflight = self._apply_command_quantity_constraints(
            idx=idx,
            commands=commands,
            closes=market_arrays.closes,
            symbol_list=symbol_list,
            contract_sizes=contract_sizes,
            constraints=constraints,
        )
        if quantity_preflight["changed_count"] or quantity_preflight["dropped_count"]:
            compiled_commands = None
            commands = tuple(effective_commands)
        else:
            effective_commands = tuple(commands)

        if compiled_commands is None:
            compiled_commands = self.compile_order_commands(
                datetime_index=idx,
                commands=effective_commands,
                symbols=symbol_list,
            )
        elif (
            compiled_commands.index_signature != market_arrays.signature
            or compiled_commands.symbols != tuple(symbol_list)
        ):
            raise ValueError("compiled commands do not match prepared market arrays")

        if self._backend_selection.resolved == "rust" and not _force_python_backend:
            contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
            leverages = self._per_symbol_array(
                self.config.account.leverage if leverage is None else leverage,
                symbol_list,
                default=self.config.account.leverage,
            )
            configured_fee = self.config.fee_rate if fee_rate is None else fee_rate
            fee_rates = self._per_symbol_array(configured_fee, symbol_list, default=0.0)
            runner = RustFullRunner(
                idx=idx,
                symbols=symbol_list,
                market_arrays=market_arrays,
                contract_sizes=contract_sizes,
                leverages=leverages,
                fee_rates=fee_rates,
                initial_capital=float(self.config.account.initial_capital),
                maintenance_ratio=float(self.config.account.maintenance_ratio),
                slippage=float(self.config.execution.slippage_rate),
                use_funding=bool(self.config.use_funding),
            )
            audit = runner.run_tape_audit(compiled_commands)
            result = audit.to_backtest_result(
                datetime_index=idx,
                closes=pd.DataFrame({symbol: market_arrays.closes[:, col] for col, symbol in enumerate(symbol_list)}, index=idx),
                symbols=symbol_list,
                initial_capital=float(self.config.account.initial_capital),
                leverage=float(np.mean(leverages)),
                metadata={
                    **self._backend_selection_metadata(),
                    "quantity_preflight": quantity_preflight,
                    "fee_rate_oneway": self._fee_rate_metadata(fee_rates, symbol_list),
                    "slippage_bps": self.config.execution.slippage_bps,
                    "rust_contract": "native_event_v2_full_contract",
                    "use_funding": bool(self.config.use_funding),
                },
            )
            return result

        leverages = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        fee_rates = self._per_symbol_array(
            self.config.fee_rate if fee_rate is None else fee_rate,
            symbol_list,
            default=0.0,
        )

        (
            equity_arr,
            pos_arr,
            fee_arr,
            turnover_arr,
            funding_arr,
            init_margin_arr,
            maint_margin_arr,
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
        ) = _engine_event_v2(
            n_bars=len(idx),
            n_syms=len(symbol_list),
            n_commands=compiled_commands.n_commands,
            n_ids=len(compiled_commands.id_values),
            command_ptr=compiled_commands.command_ptr,
            command_action=compiled_commands.command_action,
            command_symbol=compiled_commands.command_symbol,
            command_side=compiled_commands.command_side,
            command_type=compiled_commands.command_type,
            command_qty=compiled_commands.command_qty,
            command_price=compiled_commands.command_price,
            command_trigger_price=compiled_commands.command_trigger_price,
            command_tif=compiled_commands.command_tif,
            command_reduce_only=compiled_commands.command_reduce_only,
            command_order_id=compiled_commands.command_order_id,
            command_target_order_id=compiled_commands.command_target_order_id,
            command_parent_order_id=compiled_commands.command_parent_order_id,
            command_group_id=compiled_commands.command_group_id,
            command_oco_group_id=compiled_commands.command_oco_group_id,
            command_activation=compiled_commands.command_activation,
            command_expires_bar=compiled_commands.command_expires_bar,
            highs=market_arrays.highs,
            lows=market_arrays.lows,
            closes=market_arrays.closes,
            funding_rates=market_arrays.funding,
            is_funding_bar=market_arrays.is_funding_bar,
            init_capital=self.config.account.initial_capital,
            leverages=leverages,
            maint_ratio=self.config.account.maintenance_ratio,
            fee_rates=fee_rates,
            contract_sizes=contract_sizes,
            slippage=self.config.execution.slippage_rate,
            use_funding=bool(self.config.use_funding),
        )

        fill_ledger = self._build_compact_fill_ledger(
            compiled_commands=compiled_commands,
            fill_bar=fill_bar,
            fill_qty=fill_qty,
            fill_price=fill_price,
            fill_fee=fill_fee,
        )
        command_ledger = self._build_compact_command_ledger(
            compiled_commands=compiled_commands,
            command_status=command_status,
            reject_code=reject_code,
            fill_bar=fill_bar,
            fill_qty=fill_qty,
            fill_price=fill_price,
            fill_fee=fill_fee,
            active=active,
            waiting_parent=waiting_parent,
            working_qty=working_qty,
            working_price=working_price,
            working_trigger=working_trigger,
        )
        event_ledger = self._build_compact_order_event_ledger(
            event_count=int(event_count),
            event_bar=event_bar,
            event_command=event_command,
            event_type=event_type,
            event_status=event_status,
            event_related_command=event_related_command,
        )
        fills = (
            self._build_fills(compiled_commands.sorted_commands, idx, fill_bar, fill_qty, fill_price, fill_fee)
            if plan.materialize_python_objects
            else ()
        )
        equity = pd.Series(equity_arr, index=idx, name="equity")
        positions = pd.DataFrame(
            {f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": market_arrays.closes[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        diagnostics = pd.DataFrame(
            {
                "turnover": turnover_arr,
                "rejected_orders": rejected_bar,
                "canceled_orders": canceled_bar,
            },
            index=idx,
        )
        if level in {"standard", "audit"}:
            command_report = self._build_command_report(
                compiled_commands,
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
            )
        else:
            command_report = pd.DataFrame()
        if level == "audit" and sink != "none":
            order_events = self._build_order_events(
                idx=idx,
                compiled_commands=compiled_commands,
                event_count=int(event_count),
                event_bar=event_bar,
                event_command=event_command,
                event_type=event_type,
                event_status=event_status,
                event_related_command=event_related_command,
            )
        else:
            order_events = pd.DataFrame()
        if command_report.empty or not plan.materialize_active_orders:
            active_orders = pd.DataFrame()
        else:
            active_orders = command_report[
                (command_report["active"] == True) | (command_report["waiting_parent"] == True)  # noqa: E712
            ].copy()
        audit_artifacts = self._write_native_event_audit_sink(
            sink=sink,
            sink_path=sink_path,
            command_report=command_report,
            order_events=order_events,
            fill_ledger=fill_ledger,
            command_ledger=command_ledger,
            event_ledger=event_ledger,
            report_level=level,
        )
        lifecycle_counters = {
            "fill_count": int(fill_ledger.fill_count),
            "event_count": int(event_count),
            "rejected_count": int(np.sum(command_status == ORDER_STATUS_REJECTED)),
            "canceled_count": int(np.sum(command_status == ORDER_STATUS_CANCELED)),
            "filled_command_count": int(np.sum(command_status == ORDER_STATUS_FILLED)),
            "pending_command_count": int(np.sum(command_status == ORDER_STATUS_PENDING)),
            "expired_event_count": int(np.sum(event_ledger.event_type == ORDER_EVENT_EXPIRE)),
        }
        metadata = {
            "backend": "native_event",
            "engine": "event_v2_lifecycle",
            **self._backend_selection_metadata(),
            "report_level": level,
            "report_level_requested": str(requested_report_level),
            "artifact_plan": asdict(plan),
            "audit_sink": sink,
            "audit_sink_path": sink_path,
            "audit_artifacts": audit_artifacts,
            "fee_rate_oneway": self._fee_rate_metadata(fee_rates, symbol_list),
            "slippage_bps": self.config.execution.slippage_bps,
            "order_report": command_report,
            "command_report": command_report,
            "order_events": order_events,
            "active_orders": active_orders,
            "compact_fill_ledger": fill_ledger if plan.keep_fill_ledger else None,
            "compact_command_ledger": command_ledger if plan.keep_command_terminal_state else None,
            "compact_order_event_ledger": event_ledger if plan.keep_event_ledger and sink == "memory" else None,
            "id_values": compiled_commands.id_values,
            "quantity_constraints": constraints.as_dict(),
            "quantity_preflight": quantity_preflight,
            "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
            "liquidation_reason": int(liq_reason),
            "lifecycle_counters": lifecycle_counters,
        }

        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().fillna(0.0),
            positions=positions,
            closes=close_df,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
            orders=self._commands_to_order_intents(compiled_commands.sorted_commands) if plan.materialize_python_objects else (),
            fills=tuple(fills),
            fees=pd.Series(fee_arr, index=idx, name="fees"),
            funding=pd.Series(funding_arr, index=idx, name="funding"),
            margin=pd.DataFrame(
                {
                    "initial_margin": init_margin_arr,
                    "maintenance_margin": maint_margin_arr,
                },
                index=idx,
            ),
            diagnostics=diagnostics,
            metadata=metadata,
        )

    def run_strategy(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        strategy,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        opens: Optional[Dict[str, pd.Series]] = None,
        volumes: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        execution_mode: str = "fast",
        command_effective_phase: str = "next_bar",
        reactive_kernel_mode: Optional[str] = None,
        report_level: Optional[str] = None,
        audit_sink: Optional[str] = None,
        audit_sink_path: Optional[str] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
        opens_arr: Optional[np.ndarray] = None,
        volumes_arr: Optional[np.ndarray] = None,
        _score_requirements: Optional[NativeEventScoreRequirements] = None,
        _return_score: bool = False,
        _trading_days: int = 365,
    ) -> Union[BacktestResultV2, NativeEventScoreResult]:
        """
        Run a reactive strategy against native-event v2 lifecycle semantics.

        Strategy callbacks observe post-bar engine state and may emit commands
        for the next bar. The emitted tape is replayed once at the end through
        `run_order_commands`, making the final result reproducible by static
        lifecycle replay.
        """
        if strategy is None:
            raise ValueError("run_strategy requires a strategy object")
        if str(command_effective_phase).lower().strip() != "next_bar":
            raise NotImplementedError("reactive native-event MVP supports command_effective_phase='next_bar' only")
        execution_mode = str(execution_mode).lower().strip()
        if execution_mode not in {"fast", "audit"}:
            raise ValueError("execution_mode must be 'fast' or 'audit'")
        backend_selection = self._backend_selection
        kernel_mode = _normalize_reactive_kernel_mode(
            self.config.reactive_kernel_mode if reactive_kernel_mode is None else reactive_kernel_mode
        )
        if backend_selection.resolved == "replay_certified":
            kernel_mode = "replay_certified"
        requested_report_level = self.config.report_level if report_level is None else report_level
        level = _normalize_native_event_report_level(requested_report_level)
        plan = _native_event_artifact_plan(level)
        if _return_score:
            if level != "score":
                raise ValueError("internal direct score execution requires report_level='score'")
            if kernel_mode != "single_pass" or execution_mode != "fast":
                raise ValueError("internal direct score execution requires fast single_pass mode")
            score_requirements = _score_requirements or NativeEventScoreRequirements.public_score_contract()
        else:
            score_requirements = None

        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(closes.keys())
        if market_arrays is None:
            market_arrays = self.prepare_market_arrays(
                datetime_index=idx,
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=funding_rate,
                symbols=symbol_list,
            )
        elif market_arrays.signature != self._market_signature(idx, symbol_list):
            raise ValueError("prepared market arrays do not match datetime_index/symbols")
        if opens_arr is None:
            open_dict = align_series(opens, symbol_list, idx, fallback=align_series(closes, symbol_list, idx))
            opens_arr = np.ascontiguousarray(np.column_stack([open_dict[s].to_numpy(dtype=np.float64) for s in symbol_list]))
        else:
            opens_arr = np.ascontiguousarray(opens_arr, dtype=np.float64)
        if volumes_arr is None:
            volume_dict = align_series(volumes, symbol_list, idx, fallback={s: pd.Series(0.0, index=idx) for s in symbol_list})
            volumes_arr = np.ascontiguousarray(np.column_stack([volume_dict[s].to_numpy(dtype=np.float64) for s in symbol_list]))
        else:
            volumes_arr = np.ascontiguousarray(volumes_arr, dtype=np.float64)
        if opens_arr.shape != market_arrays.closes.shape or volumes_arr.shape != market_arrays.closes.shape:
            raise ValueError("prepared opens/volumes arrays must match market array shape")
        opens_arr.setflags(write=False)
        volumes_arr.setflags(write=False)

        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        constraints = build_quantity_constraints(
            symbol_list,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        leverages = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        fee_rates = self._per_symbol_array(
            self.config.fee_rate if fee_rate is None else fee_rate,
            symbol_list,
            default=0.0,
        )
        session = self._create_reactive_session(
            backend_selection=backend_selection,
            idx=idx,
            symbols=symbol_list,
            market_arrays=market_arrays,
            opens_arr=opens_arr,
            volumes_arr=volumes_arr,
            constraints=constraints,
            contract_sizes=contract_sizes,
            leverages=leverages,
            fee_rates=fee_rates,
            initial_capital=self.config.account.initial_capital,
            maintenance_ratio=self.config.account.maintenance_ratio,
            slippage=self.config.execution.slippage_rate,
            use_funding=bool(self.config.use_funding),
            retain_terminal_orders=level != "score",
            score_requirements=score_requirements,
        )
        execution_counters = getattr(session, "execution_counters", None)
        if execution_counters is None:
            execution_counters = {}
        constraints_enabled = bool(getattr(session, "constraints_enabled", constraints.enabled))
        if getattr(session, "online_score", None) is not None:
            session.online_score.trading_days = int(_trading_days)

        # Keep execution and audit tape distinct: next-bar semantics prohibit
        # executing a final-close command, while audit still needs to preserve
        # that strategy intent for replayability and review.
        emitted: list[OrderCommand] = []
        emitted_audit_tape: list[OrderCommand] = []
        emitted_order_ids: set[str] = set()
        emitted_command_count = 0
        emitted_executable_command_count = 0
        callback_count = 0
        ignored_commands_after_end = 0

        def record_scheduled(commands: Sequence[OrderCommand]) -> None:
            nonlocal emitted_command_count, emitted_executable_command_count
            count = len(commands)
            emitted_command_count += count
            emitted_executable_command_count += count
            if not _return_score:
                emitted.extend(commands)
                emitted_audit_tape.extend(commands)

        def record_outside_tape(commands: Sequence[OrderCommand]) -> None:
            nonlocal emitted_command_count
            emitted_command_count += len(commands)
            if not _return_score:
                emitted_audit_tape.extend(commands)

        initial_context = session.context(0)
        last_context = initial_context

        def quantize_reactive_schedule(commands: Sequence[OrderCommand]) -> tuple[OrderCommand, ...]:
            if not commands:
                if execution_counters:
                    execution_counters["empty_command_batches_skipped"] += 1
                return ()
            if not constraints_enabled:
                if execution_counters:
                    execution_counters["constraint_preflight_skipped"] += 1
                return tuple(commands)
            if execution_counters:
                execution_counters["constraint_preflight_calls"] += 1
            effective, _ = self._apply_command_quantity_constraints(
                idx=idx,
                commands=commands,
                closes=market_arrays.closes,
                symbol_list=symbol_list,
                contract_sizes=contract_sizes,
                constraints=constraints,
            )
            if execution_counters:
                execution_counters["commands_quantized"] += len(commands)
            return effective

        def schedule_reactive_batch(
            commands: Sequence[OrderCommand],
            effective_bar: int,
        ) -> tuple[tuple[OrderCommand, ...], int]:
            if not commands:
                if execution_counters:
                    execution_counters["empty_command_batches_skipped"] += 1
                return (), 0
            if execution_counters:
                execution_counters["bars_with_commands"] += 1
                execution_counters["commands_retimed"] += 1
            scheduled, ignored = self._retime_reactive_commands(
                commands=commands,
                effective_bar=effective_bar,
                idx=idx,
                emitted_order_ids=emitted_order_ids,
            )
            if scheduled:
                record_scheduled(scheduled)
                session.schedule(effective_bar, quantize_reactive_schedule(scheduled))
            return scheduled, ignored

        initial_commands = self._expand_scoped_cancel_all_commands(
            self._call_strategy_callback(strategy, "initialize", initial_context),
            initial_context,
        )
        scheduled, ignored = schedule_reactive_batch(initial_commands, 1)
        ignored_commands_after_end += ignored
        if ignored:
            record_outside_tape(
                self._record_reactive_commands_outside_tape(
                    commands=initial_commands,
                    effective_bar=1,
                    emitted_order_ids=emitted_order_ids,
                )
            )

        for bar in range(len(idx)):
            context = session.context(bar)
            last_context = context
            callback_count += 1
            if context.liquidated:
                session.release_bar_payload(bar)
                break
            commands = self._expand_scoped_cancel_all_commands(
                self._call_strategy_callback(strategy, "on_bar_close", context),
                context,
            )
            session.release_bar_payload(bar)
            scheduled, ignored = schedule_reactive_batch(commands, bar + 1)
            ignored_commands_after_end += ignored
            if ignored:
                record_outside_tape(
                    self._record_reactive_commands_outside_tape(
                        commands=commands,
                        effective_bar=bar + 1,
                        emitted_order_ids=emitted_order_ids,
                    )
                )

        if last_context is not None and not last_context.liquidated:
            final_commands = self._expand_scoped_cancel_all_commands(
                self._call_strategy_callback(strategy, "finalize", last_context),
                last_context,
            )
            if final_commands:
                if execution_counters:
                    execution_counters["bars_with_commands"] += 1
                    execution_counters["commands_retimed"] += 1
                scheduled, ignored = self._retime_reactive_commands(
                    commands=final_commands,
                    effective_bar=len(idx),
                    idx=idx,
                    emitted_order_ids=emitted_order_ids,
                )
            else:
                scheduled, ignored = (), 0
            record_scheduled(scheduled)
            ignored_commands_after_end += ignored
            if ignored:
                record_outside_tape(
                    self._record_reactive_commands_outside_tape(
                        commands=final_commands,
                        effective_bar=len(idx),
                        emitted_order_ids=emitted_order_ids,
                    )
                )

        replay_required = kernel_mode == "replay_certified" or level in {"standard", "audit"} or execution_mode == "audit"
        if _return_score:
            return self._reactive_session_score_result(
                session=session,
                symbol_list=symbol_list,
                leverages=leverages,
                requirements=score_requirements,
                trading_days=_trading_days,
                metadata={
                    "backend": "native_event",
                    "engine": "event_v2_reactive_score",
                    "report_level": "score",
                    "artifact_plan": asdict(plan),
                    "score_requirements": asdict(score_requirements),
                    "reactive_execution_mode": execution_mode,
                    "reactive_kernel_mode": kernel_mode,
                    "command_effective_phase": "next_bar",
                    "emitted_command_count": int(emitted_command_count),
                    "emitted_executable_command_count": int(emitted_executable_command_count),
                    "ignored_commands_after_end": int(ignored_commands_after_end),
                    "strategy_callback_count": int(callback_count),
                    "static_replay_available": False,
                    "reactive_static_replay_count": 0,
                    "reactive_session_liquidated": bool(session.liquidated),
                    "reactive_session_liquidation_bar": int(session.liquidation_bar),
                    "execution_counters": dict(getattr(session, "execution_counters", {})),
                    **self._backend_selection_metadata(),
                },
            )
        replay_result = None
        if replay_required:
            replay_result = self.run_order_commands(
                datetime_index=idx,
                commands=tuple(emitted),
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=funding_rate,
                contract_size=contract_size,
                leverage=leverage,
                fee_rate=fee_rate,
                symbols=symbol_list,
                market_arrays=market_arrays,
                instruments=instruments,
                qty_step=qty_step,
                lot_size=lot_size,
                slot_size=slot_size,
                min_qty=min_qty,
                min_notional=min_notional,
                report_level=level,
                audit_sink=audit_sink,
                audit_sink_path=audit_sink_path,
                _force_python_backend=True,
            )
        if kernel_mode == "replay_certified":
            final_result = replay_result
            engine_name = "event_v2_reactive_incremental"
        else:
            if replay_result is not None:
                self._assert_reactive_session_replay_parity(session, replay_result)
            final_result = self._reactive_session_result(
                session=session,
                symbol_list=symbol_list,
                market_arrays=market_arrays,
                leverages=leverages,
                report_level=level,
                plan=plan,
                replay_result=replay_result,
                audit_sink=audit_sink,
                audit_sink_path=audit_sink_path,
            )
            engine_name = "event_v2_reactive_single_pass"
        final_result.metadata.update(
            {
                "engine": engine_name,
                **self._backend_selection_metadata(),
                "reactive_execution_mode": execution_mode,
                "reactive_kernel_mode": kernel_mode,
                "command_effective_phase": "next_bar",
                "emitted_command_tape": tuple(emitted_audit_tape) if plan.keep_command_tape else (),
                "emitted_command_tape_retained": bool(plan.keep_command_tape),
                "emitted_command_count": int(emitted_command_count),
                "emitted_executable_command_count": int(emitted_executable_command_count),
                "ignored_commands_after_end": int(ignored_commands_after_end),
                "strategy_callback_count": int(callback_count),
                "static_replay_available": bool(replay_result is not None),
                "reactive_static_replay_count": int(replay_result is not None),
                "reactive_context_builder": "incremental_session_v1",
                "reactive_incremental_compile_replays": 0,
                "reactive_session_liquidated": bool(session.liquidated),
                "reactive_session_liquidation_bar": int(session.liquidation_bar),
            }
        )
        if backend_selection.resolved == "rust":
            final_result.metadata["rust_r1_session_fills"] = tuple(session.fills) if plan.materialize_python_objects else ()
            final_result.metadata["rust_r1_session_events"] = tuple(session.events) if plan.keep_event_ledger else ()
        if execution_mode == "audit" and replay_result is not None:
            replay_last_pos = {
                symbol: float(replay_result.positions[f"Position_{symbol}"].iloc[-1])
                for symbol in symbol_list
            }
            session_last_pos = {symbol: float(last_context.positions[symbol]) for symbol in symbol_list}
            final_result.metadata["reactive_audit"] = {
                "final_equity_diff": float(abs(float(replay_result.equity.iloc[-1]) - float(last_context.equity))),
                "final_position_diff": {
                    symbol: float(abs(replay_last_pos.get(symbol, 0.0) - session_last_pos.get(symbol, 0.0)))
                    for symbol in symbol_list
                },
            }
        return final_result

    def run_strategy_score(
        self,
        *args,
        trading_days: int = 365,
        score_requirements: Optional[NativeEventScoreRequirements] = None,
        **kwargs,
    ) -> Union[NativeEventScoreResult, NativeEventScalarScoreResult]:
        """Execute a prepared reactive score without pandas/result materialization.

        This is an internal prepared-runner path. Public ``run_strategy`` keeps
        returning ``BacktestResultV2`` for every report level, including
        ``score``; callers that need an audit trace must use that public path.
        """
        kwargs.update(
            {
                "reactive_kernel_mode": "single_pass",
                "report_level": "score",
                "audit_sink": "none",
                "_score_requirements": score_requirements,
                "_return_score": True,
                "_trading_days": int(trading_days),
            }
        )
        result = self.run_strategy(*args, **kwargs)
        if not isinstance(result, (NativeEventScoreResult, NativeEventScalarScoreResult)):  # pragma: no cover
            raise TypeError("native-event direct score did not return a native-event score result")
        return result

    def run_compiled_tape_score(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        compiled_commands: CompiledOrderCommandArrays,
        *,
        market_arrays: PreparedMarketArrays,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        initial_capital: Optional[float] = None,
        maintenance_ratio: Optional[float] = None,
        slippage: Optional[float] = None,
        use_funding: Optional[bool] = None,
        trading_days: int = 365,
    ) -> NativeEventScalarScoreResult:
        """Run a prepared static command tape and retain scalar state only.

        This is the Python-side apples-to-apples score contract for the Rust
        batched runner. It accepts already prepared market arrays and compiled
        commands, schedules the existing lifecycle commands without pandas
        reports or full ledgers, and returns the same scalar accounting fields
        as :class:`RustBatchedScoreResult` via the result properties and
        metadata.

        The method is intentionally internal-facing: quantity preflight and
        capability validation must happen before compiling the tape. It does
        not change the public endpoint default or the audit ``run_orders``
        contract.
        """
        if market_arrays is None:
            raise ValueError("run_compiled_tape_score requires prepared market_arrays")
        idx = validate_datetime(datetime_index)
        symbol_list = list(compiled_commands.symbols)
        if not symbol_list:
            raise ValueError("compiled command tape must contain at least one symbol")
        if market_arrays.signature != self._market_signature(idx, symbol_list):
            raise ValueError("prepared market arrays do not match datetime_index/symbols")
        if compiled_commands.index_signature != market_arrays.signature:
            raise ValueError("compiled commands do not match prepared market arrays")

        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        leverages = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        configured_fee = self.config.fee_rate if fee_rate is None else fee_rate
        fee_rates = self._per_symbol_array(configured_fee, symbol_list, default=0.0)
        initial = float(self.config.account.initial_capital if initial_capital is None else initial_capital)
        maint = float(
            self.config.account.maintenance_ratio if maintenance_ratio is None else maintenance_ratio
        )
        slip = float(self.config.execution.slippage_rate if slippage is None else slippage)
        funding_enabled = bool(self.config.use_funding if use_funding is None else use_funding)
        if initial <= 0.0 or maint < 0.0 or slip < 0.0 or np.any(contract_sizes <= 0.0) or np.any(leverages <= 0.0):
            raise ValueError("invalid scalar score account or execution configuration")

        if self._backend_selection.resolved == "rust":
            runner = RustFullRunner(
                idx=idx,
                symbols=symbol_list,
                market_arrays=market_arrays,
                contract_sizes=contract_sizes,
                leverages=leverages,
                fee_rates=fee_rates,
                initial_capital=initial,
                maintenance_ratio=maint,
                slippage=slip,
                use_funding=funding_enabled,
            )
            # ``run_compiled_tape_score`` is the legacy/public score facade
            # and promises dense accounting arrays for metric computation.
            # Keep the Rust runner's scalar score ABI minimal, but use its
            # typed audit projection here rather than manufacturing missing
            # paths or changing the public result contract.
            audit = runner.run_tape_audit(compiled_commands)
            equity = np.ascontiguousarray(np.asarray(audit.equity, dtype=np.float64))
            positions = np.ascontiguousarray(np.asarray(audit.positions, dtype=np.float64))
            returns = np.zeros_like(equity)
            if len(equity) > 1:
                with np.errstate(divide="ignore", invalid="ignore"):
                    returns[1:] = equity[1:] / equity[:-1] - 1.0
                returns[~np.isfinite(returns)] = 0.0
            from ..metrics.performance import compute_performance_metrics

            metrics = compute_performance_metrics(
                timestamps=idx,
                equity=equity,
                returns=returns,
                positions=positions,
                symbols=tuple(symbol_list),
                initial_capital=initial,
                liquidated=bool(audit.liquidated),
                trading_days=int(trading_days),
            )
            metadata = {
                "backend": "native_event",
                "engine": "event_v2_compiled_tape_score_facade_rust_full",
                "report_level": "score",
                "score_pandas_materialized": False,
                "score_full_ledgers_materialized": False,
                "compiled_tape_commands": int(compiled_commands.n_commands),
                "compiled_tape_symbols": tuple(symbol_list),
                "use_funding": funding_enabled,
                "total_fee": float(audit.total_fee),
                "total_funding": float(audit.total_funding),
                "total_turnover": float(audit.total_turnover),
                "lifecycle_counters": {
                    "fill_count": int(audit.fill_count),
                    "event_count": int(audit.event_count),
                    "rejected_count": int(audit.rejected_count),
                    "canceled_count": int(audit.canceled_count),
                },
                "trading_days": int(trading_days),
                "rust_contract": "native_event_v2_full_contract",
            }
            metrics.update({
                "total_fee": float(audit.total_fee),
                "total_funding": float(audit.total_funding),
                "total_turnover": float(audit.total_turnover),
                "max_initial_margin": float(audit.max_initial_margin),
                "max_maintenance_margin": float(audit.max_maintenance_margin),
            })
            return NativeEventScalarScoreResult(
                final_equity=float(audit.equity[-1]),
                final_positions=np.asarray(audit.positions[-1], dtype=np.float64),
                fill_count=int(audit.fill_count),
                rejection_count=int(audit.rejected_count),
                cancellation_count=int(audit.canceled_count),
                liquidated=bool(audit.liquidated),
                liquidation_bar=int(audit.liquidation_bar),
                metrics=metrics,
                metadata=metadata,
            )

        requirements = NativeEventScoreRequirements(
            need_trade_stats=True,
            need_context_fills=False,
            need_context_events=False,
            need_context_active_orders=False,
            need_context_positions=False,
            need_context_margin=False,
        )
        opens_arr = np.ascontiguousarray(market_arrays.closes, dtype=np.float64)
        volumes_arr = np.zeros_like(opens_arr, dtype=np.float64)
        session = _NativeEventReactiveSession(
            idx=idx,
            symbols=symbol_list,
            market_arrays=market_arrays,
            opens_arr=opens_arr,
            volumes_arr=volumes_arr,
            constraints=build_quantity_constraints(symbol_list),
            contract_sizes=contract_sizes,
            leverages=leverages,
            fee_rates=fee_rates,
            initial_capital=initial,
            maintenance_ratio=maint,
            slippage=slip,
            use_funding=funding_enabled,
            retain_terminal_orders=False,
            score_requirements=requirements,
        )
        session.online_score.trading_days = int(trading_days)

        for bar in range(len(idx)):
            start = int(compiled_commands.command_ptr[bar])
            stop = int(compiled_commands.command_ptr[bar + 1])
            if stop > start:
                session.schedule(
                    bar,
                    tuple(compiled_commands.sorted_commands[row][1] for row in range(start, stop)),
                )
        session.process_bar(len(idx) - 1)
        result = self._reactive_session_score_result(
            session=session,
            symbol_list=symbol_list,
            leverages=leverages,
            requirements=requirements,
            trading_days=int(trading_days),
            metadata={
                "backend": "native_event",
                "engine": "event_v2_compiled_tape_scalar_python",
                "report_level": "score",
                "score_pandas_materialized": False,
                "score_full_ledgers_materialized": False,
                "compiled_tape_commands": int(compiled_commands.n_commands),
                "compiled_tape_symbols": tuple(symbol_list),
                "use_funding": funding_enabled,
                "total_fee": float(session.total_fee),
                "total_funding": float(session.total_funding),
                "total_turnover": float(session.total_turnover),
            },
        )
        if not isinstance(result, NativeEventScalarScoreResult):  # pragma: no cover
            raise TypeError("compiled tape scalar path unexpectedly retained dense accounting")
        return result

    def run_orders(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        orders: Sequence[OrderIntent],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
        compiled_orders: Optional[CompiledOrderArrays] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(closes.keys())

        if market_arrays is None:
            market_arrays = self.prepare_market_arrays(
                datetime_index=idx,
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=funding_rate,
                symbols=symbol_list,
            )
        elif market_arrays.signature != self._market_signature(idx, symbol_list):
            raise ValueError("prepared market arrays do not match datetime_index/symbols")

        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        constraints = build_quantity_constraints(
            symbol_list,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        effective_orders, quantity_preflight = self._apply_order_quantity_constraints(
            idx=idx,
            orders=orders,
            closes=market_arrays.closes,
            symbol_list=symbol_list,
            contract_sizes=contract_sizes,
            constraints=constraints,
        )
        if quantity_preflight["changed_count"] or quantity_preflight["dropped_count"]:
            compiled_orders = None
            orders = tuple(effective_orders)
        else:
            effective_orders = tuple(orders)

        if compiled_orders is None:
            compiled_orders = self.compile_orders(datetime_index=idx, orders=effective_orders, symbols=symbol_list)
        elif (
            compiled_orders.index_signature != market_arrays.signature
            or compiled_orders.symbols != tuple(symbol_list)
        ):
            raise ValueError("compiled orders do not match prepared market arrays")
        n_orders = compiled_orders.n_orders
        leverages = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        fee_rates = self._per_symbol_array(
            self.config.fee_rate if fee_rate is None else fee_rate,
            symbol_list,
            default=0.0,
        )

        (
            equity_arr,
            pos_arr,
            fee_arr,
            turnover_arr,
            funding_arr,
            init_margin_arr,
            maint_margin_arr,
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
        ) = _engine_event_v1(
            n_bars=len(idx),
            n_syms=len(symbol_list),
            n_orders=n_orders,
            order_ptr=compiled_orders.order_ptr,
            order_symbol=compiled_orders.order_symbol,
            order_side=compiled_orders.order_side,
            order_type=compiled_orders.order_type,
            order_qty=compiled_orders.order_qty,
            order_price=compiled_orders.order_price,
            order_tif=compiled_orders.order_tif,
            highs=market_arrays.highs,
            lows=market_arrays.lows,
            closes=market_arrays.closes,
            funding_rates=market_arrays.funding,
            is_funding_bar=market_arrays.is_funding_bar,
            init_capital=self.config.account.initial_capital,
            leverages=leverages,
            maint_ratio=self.config.account.maintenance_ratio,
            fee_rates=fee_rates,
            contract_sizes=contract_sizes,
            slippage=self.config.execution.slippage_rate,
            use_funding=bool(self.config.use_funding),
        )

        fills = self._build_fills(compiled_orders.sorted_orders, idx, fill_bar, fill_qty, fill_price, fill_fee)
        equity = pd.Series(equity_arr, index=idx, name="equity")
        positions = pd.DataFrame(
            {f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": market_arrays.closes[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )

        diagnostics = pd.DataFrame(
            {
                "turnover": turnover_arr,
                "rejected_orders": rejected_bar,
                "canceled_orders": canceled_bar,
            },
            index=idx,
        )
        order_report = pd.DataFrame(
            {
                "original_index": compiled_orders.original_index,
                "status": order_status,
                "reject_code": reject_code,
                "fill_bar": fill_bar,
                "fill_qty": fill_qty,
                "fill_price": fill_price,
                "fill_fee": fill_fee,
            }
        ).sort_values("original_index", kind="stable")

        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().fillna(0.0),
            positions=positions,
            closes=close_df,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
            orders=tuple(orders),
            fills=tuple(fills),
            fees=pd.Series(fee_arr, index=idx, name="fees"),
            funding=pd.Series(funding_arr, index=idx, name="funding"),
            margin=pd.DataFrame(
                {
                    "initial_margin": init_margin_arr,
                    "maintenance_margin": maint_margin_arr,
                },
                index=idx,
            ),
            diagnostics=diagnostics,
            metadata={
                "backend": "native_event",
                "engine": "event_v1",
                "fee_rate_oneway": self._fee_rate_metadata(fee_rates, symbol_list),
                "slippage_bps": self.config.execution.slippage_bps,
                "order_report": order_report,
                "quantity_constraints": constraints.as_dict(),
                "quantity_preflight": quantity_preflight,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
            },
        )

    @staticmethod
    def _apply_order_quantity_constraints(
        *,
        idx: pd.DatetimeIndex,
        orders: Sequence[OrderIntent],
        closes: np.ndarray,
        symbol_list: List[str],
        contract_sizes: np.ndarray,
        constraints,
    ) -> tuple[tuple[OrderIntent, ...], Dict]:
        if not constraints.enabled:
            return tuple(orders), {"changed_count": 0, "dropped_count": 0, "dropped_orders": []}
        sym_to_col = {symbol: j for j, symbol in enumerate(symbol_list)}
        changed = 0
        dropped = []
        out: list[OrderIntent] = []
        idx_ns = idx.view("int64")
        for order_idx, order in enumerate(orders):
            col = sym_to_col[order.symbol]
            ts = pd.Timestamp(order.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            bar = int(np.searchsorted(idx_ns, ts.value, side="left"))
            if bar >= len(idx):
                bar = len(idx) - 1
            price = float(order.price) if order.price is not None else float(closes[bar, col])
            signed = order.signed_qty
            q = abs(
                quantize_signed_quantity(
                    signed,
                    price,
                    float(contract_sizes[col]),
                    float(constraints.qty_step[col]),
                    float(constraints.min_qty[col]),
                    float(constraints.min_notional[col]),
                )
            )
            if q <= 0.0:
                dropped.append({"original_index": order_idx, "symbol": order.symbol, "requested_qty": float(order.qty)})
                continue
            if abs(q - float(order.qty)) > 1e-12:
                changed += 1
                out.append(
                    OrderIntent(
                        timestamp=order.timestamp,
                        symbol=order.symbol,
                        side=order.side,
                        order_type=order.order_type,
                        qty=q,
                        price=order.price,
                        trigger_price=order.trigger_price,
                        tif=order.tif,
                        reduce_only=order.reduce_only,
                        order_id=order.order_id,
                        tag=order.tag,
                        metadata={**order.metadata, "requested_qty": float(order.qty), "quantity_quantized": True},
                    )
                )
            else:
                out.append(order)
        return tuple(out), {"changed_count": changed, "dropped_count": len(dropped), "dropped_orders": dropped}

    @staticmethod
    def _apply_command_quantity_constraints(
        *,
        idx: pd.DatetimeIndex,
        commands: Sequence[OrderCommand],
        closes: np.ndarray,
        symbol_list: List[str],
        contract_sizes: np.ndarray,
        constraints,
    ) -> tuple[tuple[OrderCommand, ...], Dict]:
        if not constraints.enabled:
            return tuple(commands), {"changed_count": 0, "dropped_count": 0, "dropped_orders": []}
        sym_to_col = {symbol: j for j, symbol in enumerate(symbol_list)}
        changed = 0
        dropped = []
        out: list[OrderCommand] = []
        idx_ns = idx.view("int64")
        for command_idx, command in enumerate(commands):
            if command.action not in (OrderAction.PLACE, OrderAction.REPLACE) or command.symbol is None:
                out.append(command)
                continue
            if command.symbol not in sym_to_col:
                raise ValueError(f"command symbol {command.symbol!r} is not in symbols")
            col = sym_to_col[command.symbol]
            ts = pd.Timestamp(command.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            bar = int(np.searchsorted(idx_ns, ts.value, side="left"))
            if bar >= len(idx):
                bar = len(idx) - 1
            price = float(command.price) if command.price is not None else float(closes[bar, col])
            signed = command.signed_qty
            q = abs(
                quantize_signed_quantity(
                    signed,
                    price,
                    float(contract_sizes[col]),
                    float(constraints.qty_step[col]),
                    float(constraints.min_qty[col]),
                    float(constraints.min_notional[col]),
                )
            )
            if q <= 0.0:
                dropped.append(
                    {
                        "original_index": command_idx,
                        "symbol": command.symbol,
                        "requested_qty": None if command.qty is None else float(command.qty),
                    }
                )
                continue
            if command.qty is not None and abs(q - float(command.qty)) > 1e-12:
                changed += 1
                out.append(
                    OrderCommand(
                        timestamp=command.timestamp,
                        action=command.action,
                        symbol=command.symbol,
                        side=command.side,
                        order_type=command.order_type,
                        qty=q,
                        price=command.price,
                        trigger_price=command.trigger_price,
                        tif=command.tif,
                        reduce_only=command.reduce_only,
                        order_id=command.order_id,
                        target_order_id=command.target_order_id,
                        parent_order_id=command.parent_order_id,
                        group_id=command.group_id,
                        oco_group_id=command.oco_group_id,
                        activation_policy=command.activation_policy,
                        expires_at=command.expires_at,
                        tag=command.tag,
                        tag_prefix=command.tag_prefix,
                        metadata={
                            **command.metadata,
                            "requested_qty": float(command.qty),
                            "quantity_quantized": True,
                        },
                    )
                )
            else:
                out.append(command)
        return tuple(out), {"changed_count": changed, "dropped_count": len(dropped), "dropped_orders": dropped}

    @staticmethod
    def _reactive_session_score_result(
        *,
        session,
        symbol_list: List[str],
        leverages: np.ndarray,
        requirements: NativeEventScoreRequirements,
        trading_days: int,
        metadata: Dict[str, object],
    ) -> NativeEventScoreResult:
        """Build direct score arrays from session state without pandas objects."""
        required = {
            "equity_path": session.equity_path,
            "pos_path": session.pos_path,
            "fee_path": session.fee_path,
            "funding_path": session.funding_path,
            "initial_margin_path": session.initial_margin_path,
            "maintenance_margin_path": session.maintenance_margin_path,
        }
        counters = {
            "fill_count": int(session.fill_count),
            "event_count": int(session.event_count),
            "rejected_count": int(session.rejected_count),
            "canceled_count": int(session.canceled_count),
            "filled_command_count": int(session.fill_count),
            "pending_command_count": int(sum(1 for state in session.pending if session._is_pending(state))),
            "expired_event_count": int(getattr(session, "expired_count", 0)),
        }
        score_metadata = {
            **metadata,
            "lifecycle_counters": counters,
            "execution_counters": dict(getattr(session, "execution_counters", {})),
            "score_direct_arrays": True,
            "score_pandas_materialized": False,
            "score_full_ledgers_materialized": False,
            "score_requirements": asdict(requirements),
            "score_primitive_order_state": bool(getattr(session, "compact_score_state", False)),
            "trading_days": int(trading_days),
        }
        all_paths = all(value is not None for value in required.values())
        if all_paths:
            equity = required["equity_path"]
            returns = np.zeros_like(equity)
            if len(equity) > 1:
                with np.errstate(divide="ignore", invalid="ignore"):
                    returns[1:] = equity[1:] / equity[:-1] - 1.0
                returns[~np.isfinite(returns)] = 0.0
            accounting = NativeAccountingArrays(
                timestamps=np.ascontiguousarray(session.idx.asi8, dtype=np.int64),
                equity=equity,
                returns=returns,
                positions=required["pos_path"],
                fees=required["fee_path"],
                funding=required["funding_path"],
                initial_margin=required["initial_margin_path"],
                maintenance_margin=required["maintenance_margin_path"],
                symbols=tuple(symbol_list),
                initial_capital=float(session.initial_capital),
                leverage=float(np.mean(leverages)),
                liquidated=bool(session.liquidated),
                liquidation_bar=int(session.liquidation_bar),
            )
            from ..metrics.performance import compute_performance_metrics

            metrics = compute_performance_metrics(
                timestamps=session.idx,
                equity=accounting.equity,
                returns=accounting.returns,
                positions=accounting.positions,
                symbols=accounting.symbols,
                initial_capital=accounting.initial_capital,
                liquidated=bool(session.liquidated),
                trading_days=int(trading_days),
            )
            return NativeEventScoreResult(
                accounting=accounting,
                final_positions=accounting.positions[-1].copy(),
                fill_count=counters["fill_count"],
                rejection_count=counters["rejected_count"],
                cancellation_count=counters["canceled_count"],
                liquidated=bool(session.liquidated),
                liquidation_bar=int(session.liquidation_bar),
                metrics=metrics,
                metadata=score_metadata,
            )

        online = getattr(session, "online_score", None)
        if online is None:
            raise RuntimeError("scalar native-event score requires online metric state")
        metrics = online.finish(session.idx)
        metrics["liquidated"] = bool(session.liquidated)
        metrics["total_fee"] = float(getattr(session, "total_fee", 0.0))
        metrics["total_funding"] = float(getattr(session, "total_funding", 0.0))
        metrics["total_turnover"] = float(getattr(session, "total_turnover", 0.0))
        metrics["max_initial_margin"] = float(online.max_initial_margin)
        metrics["max_maintenance_margin"] = float(online.max_maintenance_margin)
        score_metadata["score_scalar"] = True
        score_metadata["score_retained_paths"] = {
            name: bool(value is not None) for name, value in required.items()
        }
        score_metadata["total_fee"] = float(getattr(session, "total_fee", 0.0))
        score_metadata["total_funding"] = float(getattr(session, "total_funding", 0.0))
        score_metadata["total_turnover"] = float(getattr(session, "total_turnover", 0.0))
        return NativeEventScalarScoreResult(
            final_equity=float(online.last_equity),
            final_positions=np.asarray(session.current_pos, dtype=np.float64).copy(),
            fill_count=counters["fill_count"],
            rejection_count=counters["rejected_count"],
            cancellation_count=counters["canceled_count"],
            liquidated=bool(session.liquidated),
            liquidation_bar=int(session.liquidation_bar),
            metrics=metrics,
            metadata=score_metadata,
        )

    def _reactive_session_result(
        self,
        *,
        session: _NativeEventReactiveSession,
        symbol_list: List[str],
        market_arrays: PreparedMarketArrays,
        leverages: np.ndarray,
        report_level: str,
        plan: NativeEventArtifactPlan,
        replay_result: Optional[BacktestResultV2],
        audit_sink: Optional[str],
        audit_sink_path: Optional[str],
    ) -> BacktestResultV2:
        idx = session.idx
        equity = pd.Series(session.equity_path.copy(), index=idx, name="equity")
        returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        positions = pd.DataFrame(
            {f"Position_{symbol}": session.pos_path[:, j].copy() for j, symbol in enumerate(symbol_list)},
            index=idx,
        )
        closes = pd.DataFrame(
            {f"Close_{symbol}": market_arrays.closes[:, j].copy() for j, symbol in enumerate(symbol_list)},
            index=idx,
        )
        margin = pd.DataFrame(
            {
                "initial_margin": session.initial_margin_path.copy(),
                "maintenance_margin": session.maintenance_margin_path.copy(),
            },
            index=idx,
        )
        diagnostics = pd.DataFrame(
            {
                "turnover": session.turnover_path.copy(),
                "rejected_orders": session.rejected_bar.copy(),
                "canceled_orders": session.canceled_bar.copy(),
            },
            index=idx,
        )
        session_fills = self._fills_from_reactive_session(session)
        fill_ledger = self._compact_fill_ledger_from_session(session, symbol_list)
        lifecycle_counters = {
            "fill_count": int(len(session_fills)),
            "event_count": int(len(session.events)),
            "rejected_count": int(np.sum(session.rejected_bar)),
            "canceled_count": int(np.sum(session.canceled_bar)),
            "filled_command_count": int(len(session_fills)),
            "pending_command_count": int(sum(1 for state in session.pending if session._is_pending(state))),
            "expired_event_count": int(sum(1 for event in session.events if event.event_name == "expire")),
        }
        command_report = pd.DataFrame()
        order_events = pd.DataFrame()
        active_orders = pd.DataFrame()
        orders = ()
        fills = tuple(session_fills) if plan.materialize_python_objects else ()
        compact_command_ledger = None
        compact_order_event_ledger = None
        audit_artifacts = {}
        quantity_preflight = {"changed_count": 0, "dropped_count": 0, "dropped_orders": []}
        if replay_result is not None:
            command_report = replay_result.metadata.get("command_report", pd.DataFrame())
            order_events = replay_result.metadata.get("order_events", pd.DataFrame())
            active_orders = replay_result.metadata.get("active_orders", pd.DataFrame())
            orders = replay_result.orders if plan.materialize_python_objects else ()
            fills = replay_result.fills if plan.materialize_python_objects else ()
            compact_command_ledger = replay_result.metadata.get("compact_command_ledger")
            compact_order_event_ledger = replay_result.metadata.get("compact_order_event_ledger")
            audit_artifacts = replay_result.metadata.get("audit_artifacts", {})
            quantity_preflight = replay_result.metadata.get("quantity_preflight", quantity_preflight)

        metadata = {
            "backend": "native_event",
            "engine": "event_v2_reactive_single_pass",
            "report_level": report_level,
            "artifact_plan": asdict(plan),
            "audit_sink": self.config.audit_sink if audit_sink is None else _normalize_native_event_audit_sink(audit_sink),
            "audit_sink_path": self.config.audit_sink_path if audit_sink_path is None else audit_sink_path,
            "audit_artifacts": audit_artifacts,
            "fee_rate_oneway": self._fee_rate_metadata(session.fee_rates, symbol_list),
            "slippage_bps": self.config.execution.slippage_bps,
            "order_report": command_report,
            "command_report": command_report,
            "order_events": order_events,
            "active_orders": active_orders,
            "compact_fill_ledger": fill_ledger if plan.keep_fill_ledger else None,
            "compact_command_ledger": compact_command_ledger if plan.keep_command_terminal_state else None,
            "compact_order_event_ledger": compact_order_event_ledger if plan.keep_event_ledger else None,
            "quantity_constraints": session.constraints.as_dict(),
            "quantity_preflight": quantity_preflight,
            "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
            "liquidation_reason": int(session.liquidation_reason),
            "lifecycle_counters": lifecycle_counters,
            "execution_counters": dict(getattr(session, "execution_counters", {})),
            "single_pass_accounting_source": "reactive_session_state",
            "single_pass_replay_certified": bool(replay_result is not None),
        }
        return BacktestResultV2(
            equity=equity,
            returns=returns,
            positions=positions,
            closes=closes,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=bool(session.liquidated),
            liquidation_bar=int(session.liquidation_bar),
            orders=orders,
            fills=fills,
            fees=pd.Series(session.fee_path.copy(), index=idx, name="fees"),
            funding=pd.Series(session.funding_path.copy(), index=idx, name="funding"),
            margin=margin,
            diagnostics=diagnostics,
            metadata=metadata,
        )

    @staticmethod
    def _fills_from_reactive_session(session: _NativeEventReactiveSession) -> tuple[Fill, ...]:
        fills: list[Fill] = []
        for fill in session.fills:
            fills.append(
                Fill(
                    timestamp=fill.timestamp,
                    symbol=fill.symbol,
                    side=fill.side,
                    qty=float(fill.qty),
                    price=float(fill.price),
                    fee=float(fill.fee),
                    order_id=fill.order_id,
                    metadata={
                        **dict(fill.metadata),
                        "tag": fill.tag,
                        "campaign_id": fill.campaign_id,
                        "cycle_id": fill.cycle_id,
                        "level_id": fill.level_id,
                        "parent_order_id": fill.parent_order_id,
                        "oco_group_id": fill.oco_group_id,
                    },
                )
            )
        return tuple(fills)

    @staticmethod
    def _compact_fill_ledger_from_session(
        session: _NativeEventReactiveSession,
        symbol_list: List[str],
    ) -> CompactFillLedger:
        id_map: Dict[str, int] = {}
        symbol_to_col = {symbol: j for j, symbol in enumerate(symbol_list)}
        bars = []
        command_index = []
        original_index = []
        order_id_code = []
        symbol_code = []
        side = []
        qty = []
        price = []
        fee = []
        for fill_index, fill in enumerate(session.fills):
            code = -1
            if fill.order_id:
                if fill.order_id not in id_map:
                    id_map[fill.order_id] = len(id_map)
                code = id_map[fill.order_id]
            bars.append(int(session.idx.searchsorted(pd.Timestamp(fill.timestamp), side="left")))
            command_index.append(fill_index)
            original_index.append(-1)
            order_id_code.append(code)
            symbol_code.append(symbol_to_col.get(fill.symbol, -1))
            side.append(fill.side.sign)
            qty.append(float(fill.qty))
            price.append(float(fill.price))
            fee.append(float(fill.fee))
        return CompactFillLedger(
            bar=np.asarray(bars, dtype=np.int64),
            command_index=np.asarray(command_index, dtype=np.int64),
            original_index=np.asarray(original_index, dtype=np.int64),
            order_id_code=np.asarray(order_id_code, dtype=np.int64),
            symbol_code=np.asarray(symbol_code, dtype=np.int64),
            side=np.asarray(side, dtype=np.int64),
            qty=np.asarray(qty, dtype=np.float64),
            price=np.asarray(price, dtype=np.float64),
            fee=np.asarray(fee, dtype=np.float64),
            id_values=tuple(sorted(id_map, key=id_map.get)),
            symbols=tuple(symbol_list),
        )

    @staticmethod
    def _compact_fill_ledger_from_fills(fills: Sequence[Fill], symbol_list: List[str]) -> CompactFillLedger:
        id_map: Dict[str, int] = {}
        symbol_to_col = {symbol: j for j, symbol in enumerate(symbol_list)}
        bars = []
        command_index = []
        original_index = []
        order_id_code = []
        symbol_code = []
        side = []
        qty = []
        price = []
        fee = []
        for n, fill in enumerate(fills):
            code = -1
            if fill.order_id:
                if fill.order_id not in id_map:
                    id_map[fill.order_id] = len(id_map)
                code = id_map[fill.order_id]
            bars.append(n)
            command_index.append(n)
            original_index.append(-1)
            order_id_code.append(code)
            symbol_code.append(symbol_to_col.get(fill.symbol, -1))
            side.append(fill.side.sign)
            qty.append(float(fill.qty))
            price.append(float(fill.price))
            fee.append(float(fill.fee))
        return CompactFillLedger(
            bar=np.asarray(bars, dtype=np.int64),
            command_index=np.asarray(command_index, dtype=np.int64),
            original_index=np.asarray(original_index, dtype=np.int64),
            order_id_code=np.asarray(order_id_code, dtype=np.int64),
            symbol_code=np.asarray(symbol_code, dtype=np.int64),
            side=np.asarray(side, dtype=np.int64),
            qty=np.asarray(qty, dtype=np.float64),
            price=np.asarray(price, dtype=np.float64),
            fee=np.asarray(fee, dtype=np.float64),
            id_values=tuple(sorted(id_map, key=id_map.get)),
            symbols=tuple(symbol_list),
        )

    @staticmethod
    def _assert_reactive_session_replay_parity(
        session: _NativeEventReactiveSession,
        replay_result: BacktestResultV2,
        *,
        atol: float = 1e-9,
    ) -> None:
        checks = {
            "equity": (session.equity_path, replay_result.equity.to_numpy(dtype=np.float64)),
            "fees": (session.fee_path, replay_result.fees.to_numpy(dtype=np.float64)),
            "funding": (session.funding_path, replay_result.funding.to_numpy(dtype=np.float64)),
            "positions": (
                session.pos_path,
                replay_result.positions[[f"Position_{symbol}" for symbol in replay_result.symbols]].to_numpy(dtype=np.float64),
            ),
            "initial_margin": (session.initial_margin_path, replay_result.margin["initial_margin"].to_numpy(dtype=np.float64)),
            "maintenance_margin": (
                session.maintenance_margin_path,
                replay_result.margin["maintenance_margin"].to_numpy(dtype=np.float64),
            ),
        }
        for name, (left, right) in checks.items():
            if not np.allclose(left, right, rtol=0.0, atol=atol, equal_nan=True):
                diff = float(np.nanmax(np.abs(left - right)))
                raise AssertionError(f"reactive single-pass replay parity failed for {name}: max_diff={diff}")
        if bool(session.liquidated) != bool(replay_result.liquidated):
            raise AssertionError("reactive single-pass replay parity failed for liquidated flag")
        if int(session.liquidation_bar) != int(replay_result.liquidation_bar):
            raise AssertionError("reactive single-pass replay parity failed for liquidation_bar")

    def _reactive_replay(
        self,
        *,
        idx: pd.DatetimeIndex,
        commands: Sequence[OrderCommand],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]],
        lows: Optional[Dict[str, pd.Series]],
        funding_rate,
        contract_size,
        leverage,
        fee_rate,
        symbols: List[str],
        market_arrays: Optional[PreparedMarketArrays],
        instruments,
        qty_step,
        lot_size,
        slot_size,
        min_qty,
        min_notional,
    ) -> BacktestResultV2:
        return self.run_order_commands(
            datetime_index=idx,
            commands=tuple(commands),
            closes={symbol: closes[symbol].reindex(idx).ffill().bfill() for symbol in symbols},
            highs=None if highs is None else {symbol: highs[symbol].reindex(idx).ffill().bfill() for symbol in symbols},
            lows=None if lows is None else {symbol: lows[symbol].reindex(idx).ffill().bfill() for symbol in symbols},
            funding_rate=funding_rate,
            contract_size=contract_size,
            leverage=leverage,
            fee_rate=fee_rate,
            symbols=symbols,
            market_arrays=market_arrays,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )

    def _reactive_context_from_result(
        self,
        *,
        bar_index: int,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        result: BacktestResultV2,
        opens_arr: np.ndarray,
        highs_arr: np.ndarray,
        lows_arr: np.ndarray,
        closes_arr: np.ndarray,
        volumes_arr: np.ndarray,
        constraints,
        contract_sizes: np.ndarray,
    ) -> NativeStrategyContext:
        local_bar = min(int(bar_index), len(result.equity) - 1)
        ts = idx[int(bar_index)]
        margin_row = result.margin.iloc[local_bar] if not result.margin.empty else None
        init_margin = 0.0 if margin_row is None else float(margin_row.get("initial_margin", 0.0))
        maint_margin = 0.0 if margin_row is None else float(margin_row.get("maintenance_margin", 0.0))
        equity = float(result.equity.iloc[local_bar])
        position_row = result.positions.iloc[local_bar]
        positions = {
            symbol: float(position_row.get(f"Position_{symbol}", 0.0))
            for symbol in symbols
        }
        fills_this_bar = tuple(
            self._fill_to_native_event(fill)
            for fill in result.fills
            if pd.Timestamp(fill.timestamp).value == ts.value
        )
        events_this_bar = self._native_order_events_for_bar(result.metadata.get("order_events"), int(bar_index))
        active_orders = self._native_active_snapshots(result.metadata.get("active_orders"))
        size_helper = self._reactive_size_helper(
            symbols=symbols,
            constraints=constraints,
            contract_sizes=contract_sizes,
        )
        return NativeStrategyContext(
            bar_index=int(bar_index),
            timestamp=ts,
            open=np.ascontiguousarray(opens_arr[int(bar_index)].copy()),
            high=np.ascontiguousarray(highs_arr[int(bar_index)].copy()),
            low=np.ascontiguousarray(lows_arr[int(bar_index)].copy()),
            close=np.ascontiguousarray(closes_arr[int(bar_index)].copy()),
            volume=np.ascontiguousarray(volumes_arr[int(bar_index)].copy()),
            equity=equity,
            available_equity=equity - init_margin,
            initial_margin=init_margin,
            maintenance_margin=maint_margin,
            positions=positions,
            fills_this_bar=fills_this_bar,
            order_events_this_bar=events_this_bar,
            active_orders=active_orders,
            liquidated=bool(result.liquidated),
            symbols=tuple(symbols),
            size_order=size_helper,
        )

    @staticmethod
    def _expand_scoped_cancel_all_commands(
        commands: Sequence[OrderCommand],
        context: NativeStrategyContext,
    ) -> tuple[OrderCommand, ...]:
        """
        Make string-scoped cancel-all replayable by the Numba command kernel.

        Kernel v2 can scope CANCEL_ALL by numeric fields such as symbol, side,
        order type, parent id, group id, and OCO id. Tag/prefix/campaign scopes
        are expanded here into explicit target CANCEL commands using the active
        snapshot visible to the strategy at the close of the current bar.
        """
        if commands is None:
            return ()
        out: list[OrderCommand] = []
        for command in tuple(commands):
            if not isinstance(command, OrderCommand):
                raise TypeError("reactive strategy callbacks must return OrderCommand objects")
            if command.action is not OrderAction.CANCEL_ALL or not NativeEventBackend._has_string_cancel_scope(command):
                out.append(command)
                continue
            for snapshot in context.active_orders:
                if snapshot.order_id is None:
                    continue
                if not NativeEventBackend._cancel_all_snapshot_matches(command, snapshot):
                    continue
                out.append(
                    OrderCommand(
                        timestamp=command.timestamp,
                        action=OrderAction.CANCEL,
                        target_order_id=snapshot.order_id,
                        tag=command.tag,
                        metadata={
                            **dict(command.metadata),
                            "expanded_from_cancel_all": True,
                            "cancel_scope_tag_prefix": command.tag_prefix,
                            "cancel_scope_tag": command.tag,
                        },
                    )
                )
        return tuple(out)

    @staticmethod
    def _has_string_cancel_scope(command: OrderCommand) -> bool:
        if command.tag is not None or command.tag_prefix is not None:
            return True
        return any(key in command.metadata for key in ("campaign_id", "cycle_id", "level_id"))

    @staticmethod
    def _cancel_all_snapshot_matches(command: OrderCommand, snapshot: NativeActiveOrderSnapshot) -> bool:
        if command.symbol is not None and command.symbol != snapshot.symbol:
            return False
        if command.side is not None and command.side.value != snapshot.side:
            return False
        if command.order_type is not None and command.order_type.value != snapshot.order_type:
            return False
        if command.parent_order_id is not None and command.parent_order_id != snapshot.parent_order_id:
            return False
        if command.group_id is not None and command.group_id != snapshot.group_id:
            return False
        if command.oco_group_id is not None and command.oco_group_id != snapshot.oco_group_id:
            return False
        if command.tag is not None and command.tag != snapshot.tag:
            return False
        if command.tag_prefix is not None and not (snapshot.tag or "").startswith(command.tag_prefix):
            return False
        for key, attr in (("campaign_id", "campaign_id"), ("cycle_id", "cycle_id"), ("level_id", "level_id")):
            if key in command.metadata and command.metadata.get(key) != getattr(snapshot, attr):
                return False
        return True

    @staticmethod
    def _retime_reactive_commands(
        *,
        commands: Sequence[OrderCommand],
        effective_bar: int,
        idx: pd.DatetimeIndex,
        emitted_order_ids: set[str],
    ) -> tuple[tuple[OrderCommand, ...], int]:
        if commands is None:
            return (), 0
        if effective_bar >= len(idx):
            return (), len(tuple(commands))
        out: list[OrderCommand] = []
        ignored = 0
        effective_ts = idx[int(effective_bar)]
        for seq, command in enumerate(tuple(commands)):
            if not isinstance(command, OrderCommand):
                raise TypeError("reactive strategy callbacks must return OrderCommand objects")
            order_id = command.order_id
            if command.action in (OrderAction.PLACE, OrderAction.REPLACE):
                if order_id is None:
                    order_id = command.tag or f"reactive-{effective_bar}-{seq}"
                if order_id in emitted_order_ids:
                    raise ValueError(f"duplicate reactive order_id={order_id!r}")
                emitted_order_ids.add(order_id)
            out.append(replace(command, timestamp=effective_ts, order_id=order_id))
        return tuple(out), ignored

    @staticmethod
    def _record_reactive_commands_outside_tape(
        *,
        commands: Sequence[OrderCommand],
        effective_bar: int,
        emitted_order_ids: set[str],
    ) -> tuple[OrderCommand, ...]:
        """Retain non-executable callback output without replaying a fake fill.

        A final-close command has valid strategy intent but no next market bar.
        It belongs in the audit tape, marked as outside executable data, while
        the static replay consumes only the executable tape.
        """
        out: list[OrderCommand] = []
        for seq, command in enumerate(tuple(commands)):
            if not isinstance(command, OrderCommand):
                raise TypeError("reactive strategy callbacks must return OrderCommand objects")
            order_id = command.order_id
            if command.action in (OrderAction.PLACE, OrderAction.REPLACE):
                if order_id is None:
                    order_id = command.tag or f"reactive-{effective_bar}-{seq}"
                if order_id in emitted_order_ids:
                    raise ValueError(f"duplicate reactive order_id={order_id!r}")
                emitted_order_ids.add(order_id)
            out.append(
                replace(
                    command,
                    order_id=order_id,
                    metadata={
                        **dict(command.metadata),
                        "reactive_effective_bar": int(effective_bar),
                        "outside_executable_tape": True,
                    },
                )
            )
        return tuple(out)

    @staticmethod
    def _call_strategy_callback(strategy, callback: str, context: NativeStrategyContext) -> tuple[OrderCommand, ...]:
        fn = getattr(strategy, callback, None)
        if fn is None:
            return ()
        try:
            commands = fn(context)
        except Exception as exc:
            raise NativeEventStrategyError(callback, context.bar_index, context.timestamp, exc) from exc
        if commands is None:
            return ()
        return tuple(commands)

    @staticmethod
    def _fill_to_native_event(fill: Fill) -> NativeFillEvent:
        metadata = dict(fill.metadata or {})
        return NativeFillEvent(
            timestamp=pd.Timestamp(fill.timestamp),
            symbol=fill.symbol,
            side=fill.side,
            qty=float(fill.qty),
            price=float(fill.price),
            fee=float(fill.fee),
            order_id=fill.order_id,
            tag=metadata.get("tag"),
            campaign_id=metadata.get("campaign_id"),
            cycle_id=metadata.get("cycle_id"),
            level_id=metadata.get("level_id"),
            parent_order_id=metadata.get("parent_order_id"),
            oco_group_id=metadata.get("oco_group_id"),
            metadata=metadata,
        )

    @staticmethod
    def _native_order_events_for_bar(events, bar: int) -> tuple[NativeOrderEvent, ...]:
        if events is None or len(events) == 0:
            return ()
        frame = events[events["bar"] == int(bar)]
        out = []
        for row in frame.to_dict("records"):
            out.append(
                NativeOrderEvent(
                    timestamp=pd.Timestamp(row["timestamp"]),
                    bar=int(row["bar"]),
                    event_name=str(row["event_name"]),
                    status=int(row["status"]),
                    order_id=row.get("order_id"),
                    target_order_id=row.get("target_order_id"),
                    parent_order_id=row.get("parent_order_id"),
                    oco_group_id=row.get("oco_group_id"),
                    tag=row.get("tag"),
                    campaign_id=row.get("campaign_id"),
                    cycle_id=row.get("cycle_id"),
                    level_id=row.get("level_id"),
                    original_index=int(row.get("original_index", -1)),
                    related_original_index=int(row.get("related_original_index", -1)),
                )
            )
        return tuple(out)

    @staticmethod
    def _native_active_snapshots(active_orders) -> tuple[NativeActiveOrderSnapshot, ...]:
        if active_orders is None or len(active_orders) == 0:
            return ()
        out = []
        for row in active_orders.to_dict("records"):
            out.append(
                NativeActiveOrderSnapshot(
                    order_id=row.get("order_id"),
                    symbol=row.get("symbol"),
                    side=row.get("side"),
                    order_type=row.get("order_type"),
                    status=int(row.get("status", 0)),
                    remaining_qty=float(row.get("working_qty", 0.0)),
                    price=float(row.get("working_price", 0.0)),
                    trigger_price=float(row.get("working_trigger_price", 0.0)),
                    reduce_only=bool(row.get("reduce_only", False)),
                    parent_order_id=row.get("parent_order_id"),
                    group_id=row.get("group_id"),
                    oco_group_id=row.get("oco_group_id"),
                    tag=row.get("tag"),
                    campaign_id=row.get("campaign_id"),
                    cycle_id=row.get("cycle_id"),
                    level_id=row.get("level_id"),
                )
            )
        return tuple(out)

    @staticmethod
    def _reactive_size_helper(symbols: List[str], constraints, contract_sizes: np.ndarray):
        symbol_to_col = {symbol: j for j, symbol in enumerate(symbols)}

        def size_order(symbol: str, notional: float, price: float, side: OrderSide = OrderSide.BUY) -> float:
            if symbol not in symbol_to_col:
                raise ValueError(f"unknown symbol={symbol!r}")
            if price <= 0.0:
                raise ValueError("price must be > 0")
            col = symbol_to_col[symbol]
            signed_qty = (float(notional) / (float(price) * float(contract_sizes[col]))) * side.sign
            return abs(
                quantize_signed_quantity(
                    signed_qty,
                    float(price),
                    float(contract_sizes[col]),
                    float(constraints.qty_step[col]),
                    float(constraints.min_qty[col]),
                    float(constraints.min_notional[col]),
                )
            )

        return size_order

    @staticmethod
    def _build_compact_fill_ledger(
        *,
        compiled_commands: CompiledOrderCommandArrays,
        fill_bar: np.ndarray,
        fill_qty: np.ndarray,
        fill_price: np.ndarray,
        fill_fee: np.ndarray,
    ) -> CompactFillLedger:
        mask = (fill_bar >= 0) & (fill_qty != 0.0)
        command_index = np.nonzero(mask)[0].astype(np.int64)
        return CompactFillLedger(
            bar=np.ascontiguousarray(fill_bar[mask], dtype=np.int64),
            command_index=np.ascontiguousarray(command_index, dtype=np.int64),
            original_index=np.ascontiguousarray(compiled_commands.original_index[mask], dtype=np.int64),
            order_id_code=np.ascontiguousarray(compiled_commands.command_order_id[mask], dtype=np.int64),
            symbol_code=np.ascontiguousarray(compiled_commands.command_symbol[mask], dtype=np.int64),
            side=np.ascontiguousarray(compiled_commands.command_side[mask], dtype=np.int64),
            qty=np.ascontiguousarray(fill_qty[mask], dtype=np.float64),
            price=np.ascontiguousarray(fill_price[mask], dtype=np.float64),
            fee=np.ascontiguousarray(fill_fee[mask], dtype=np.float64),
            id_values=tuple(compiled_commands.id_values),
            symbols=tuple(compiled_commands.symbols),
        )

    @staticmethod
    def _build_compact_command_ledger(
        *,
        compiled_commands: CompiledOrderCommandArrays,
        command_status: np.ndarray,
        reject_code: np.ndarray,
        fill_bar: np.ndarray,
        fill_qty: np.ndarray,
        fill_price: np.ndarray,
        fill_fee: np.ndarray,
        active: np.ndarray,
        waiting_parent: np.ndarray,
        working_qty: np.ndarray,
        working_price: np.ndarray,
        working_trigger: np.ndarray,
    ) -> CompactCommandLedger:
        return CompactCommandLedger(
            original_index=np.ascontiguousarray(compiled_commands.original_index, dtype=np.int64),
            command_bar=np.ascontiguousarray(compiled_commands.command_bar, dtype=np.int64),
            action=np.ascontiguousarray(compiled_commands.command_action, dtype=np.int64),
            symbol_code=np.ascontiguousarray(compiled_commands.command_symbol, dtype=np.int64),
            side=np.ascontiguousarray(compiled_commands.command_side, dtype=np.int64),
            order_type=np.ascontiguousarray(compiled_commands.command_type, dtype=np.int64),
            order_id_code=np.ascontiguousarray(compiled_commands.command_order_id, dtype=np.int64),
            target_order_id_code=np.ascontiguousarray(compiled_commands.command_target_order_id, dtype=np.int64),
            parent_order_id_code=np.ascontiguousarray(compiled_commands.command_parent_order_id, dtype=np.int64),
            group_id_code=np.ascontiguousarray(compiled_commands.command_group_id, dtype=np.int64),
            oco_group_id_code=np.ascontiguousarray(compiled_commands.command_oco_group_id, dtype=np.int64),
            status=np.ascontiguousarray(command_status, dtype=np.int64),
            reject_code=np.ascontiguousarray(reject_code, dtype=np.int64),
            fill_bar=np.ascontiguousarray(fill_bar, dtype=np.int64),
            fill_qty=np.ascontiguousarray(fill_qty, dtype=np.float64),
            fill_price=np.ascontiguousarray(fill_price, dtype=np.float64),
            fill_fee=np.ascontiguousarray(fill_fee, dtype=np.float64),
            active=np.ascontiguousarray(active, dtype=np.int64),
            waiting_parent=np.ascontiguousarray(waiting_parent, dtype=np.int64),
            working_qty=np.ascontiguousarray(working_qty, dtype=np.float64),
            working_price=np.ascontiguousarray(working_price, dtype=np.float64),
            working_trigger=np.ascontiguousarray(working_trigger, dtype=np.float64),
            id_values=tuple(compiled_commands.id_values),
            symbols=tuple(compiled_commands.symbols),
        )

    @staticmethod
    def _build_compact_order_event_ledger(
        *,
        event_count: int,
        event_bar: np.ndarray,
        event_command: np.ndarray,
        event_type: np.ndarray,
        event_status: np.ndarray,
        event_related_command: np.ndarray,
    ) -> CompactOrderEventLedger:
        n = max(int(event_count), 0)
        return CompactOrderEventLedger(
            bar=np.ascontiguousarray(event_bar[:n], dtype=np.int64),
            command_index=np.ascontiguousarray(event_command[:n], dtype=np.int64),
            event_type=np.ascontiguousarray(event_type[:n], dtype=np.int64),
            status=np.ascontiguousarray(event_status[:n], dtype=np.int64),
            related_command_index=np.ascontiguousarray(event_related_command[:n], dtype=np.int64),
        )

    @staticmethod
    def _write_native_event_audit_sink(
        *,
        sink: str,
        sink_path: Optional[str],
        command_report: pd.DataFrame,
        order_events: pd.DataFrame,
        fill_ledger: CompactFillLedger,
        command_ledger: CompactCommandLedger,
        event_ledger: CompactOrderEventLedger,
        report_level: str,
    ) -> Dict:
        if sink in {"none", "memory"} or report_level != "audit":
            return {}
        if not sink_path:
            raise ValueError("native_event audit_sink='jsonl' or 'parquet' requires audit_sink_path")
        root = Path(sink_path)
        root.mkdir(parents=True, exist_ok=True)
        if sink == "jsonl":
            command_path = root / "command_report.jsonl"
            event_path = root / "order_events.jsonl"
            fill_path = root / "fill_ledger.jsonl"
            command_report.to_json(command_path, orient="records", lines=True, date_format="iso")
            order_events.to_json(event_path, orient="records", lines=True, date_format="iso")
            pd.DataFrame(
                {
                    "bar": fill_ledger.bar,
                    "command_index": fill_ledger.command_index,
                    "original_index": fill_ledger.original_index,
                    "order_id_code": fill_ledger.order_id_code,
                    "symbol_code": fill_ledger.symbol_code,
                    "side": fill_ledger.side,
                    "qty": fill_ledger.qty,
                    "price": fill_ledger.price,
                    "fee": fill_ledger.fee,
                }
            ).to_json(fill_path, orient="records", lines=True, date_format="iso")
            return {
                "format": "jsonl",
                "command_report": str(command_path),
                "order_events": str(event_path),
                "fill_ledger": str(fill_path),
                "event_count": int(event_ledger.event_count),
                "fill_count": int(fill_ledger.fill_count),
            }
        command_path = root / "command_report.parquet"
        event_path = root / "order_events.parquet"
        fill_path = root / "fill_ledger.parquet"
        command_report.to_parquet(command_path, index=False)
        order_events.to_parquet(event_path, index=False)
        pd.DataFrame(
            {
                "bar": fill_ledger.bar,
                "command_index": fill_ledger.command_index,
                "original_index": fill_ledger.original_index,
                "order_id_code": fill_ledger.order_id_code,
                "symbol_code": fill_ledger.symbol_code,
                "side": fill_ledger.side,
                "qty": fill_ledger.qty,
                "price": fill_ledger.price,
                "fee": fill_ledger.fee,
            }
        ).to_parquet(fill_path, index=False)
        return {
            "format": "parquet",
            "command_report": str(command_path),
            "order_events": str(event_path),
            "fill_ledger": str(fill_path),
            "event_count": int(event_ledger.event_count),
            "fill_count": int(fill_ledger.fill_count),
        }

    @staticmethod
    def _build_command_report(
        compiled_commands: CompiledOrderCommandArrays,
        command_status: np.ndarray,
        reject_code: np.ndarray,
        fill_bar: np.ndarray,
        fill_qty: np.ndarray,
        fill_price: np.ndarray,
        fill_fee: np.ndarray,
        active: np.ndarray,
        waiting_parent: np.ndarray,
        working_qty: np.ndarray,
        working_price: np.ndarray,
        working_trigger: np.ndarray,
    ) -> pd.DataFrame:
        rows = []
        for sorted_idx, (original_idx, command) in enumerate(compiled_commands.sorted_commands):
            rows.append(
                {
                    "original_index": int(original_idx),
                    "sorted_index": int(sorted_idx),
                    "timestamp": command.timestamp,
                    "action": command.action.value,
                    "symbol": command.symbol,
                    "side": None if command.side is None else command.side.value,
                    "order_type": None if command.order_type is None else command.order_type.value,
                    "order_id": command.order_id,
                    "target_order_id": command.target_order_id,
                    "parent_order_id": command.parent_order_id,
                    "group_id": command.group_id,
                    "oco_group_id": command.oco_group_id,
                    "campaign_id": command.metadata.get("campaign_id"),
                    "cycle_id": command.metadata.get("cycle_id"),
                    "level_id": command.metadata.get("level_id"),
                    "activation_policy": command.activation_policy.value,
                    "status": int(command_status[sorted_idx]),
                    "reject_code": int(reject_code[sorted_idx]),
                    "fill_bar": int(fill_bar[sorted_idx]),
                    "fill_qty": float(fill_qty[sorted_idx]),
                    "fill_price": float(fill_price[sorted_idx]),
                    "fill_fee": float(fill_fee[sorted_idx]),
                    "active": bool(active[sorted_idx]),
                    "waiting_parent": bool(waiting_parent[sorted_idx]),
                    "working_qty": float(working_qty[sorted_idx]),
                    "working_price": float(working_price[sorted_idx]),
                    "working_trigger_price": float(working_trigger[sorted_idx]),
                    "reduce_only": bool(command.reduce_only),
                    "tag": command.tag,
                    "tag_prefix": command.tag_prefix,
                }
            )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("original_index", kind="stable").reset_index(drop=True)

    @staticmethod
    def _build_order_events(
        *,
        idx: pd.DatetimeIndex,
        compiled_commands: CompiledOrderCommandArrays,
        event_count: int,
        event_bar: np.ndarray,
        event_command: np.ndarray,
        event_type: np.ndarray,
        event_status: np.ndarray,
        event_related_command: np.ndarray,
    ) -> pd.DataFrame:
        rows = []
        for n in range(event_count):
            command_idx = int(event_command[n])
            related_idx = int(event_related_command[n])
            original_idx = -1
            related_original_idx = -1
            command = None
            if 0 <= command_idx < len(compiled_commands.sorted_commands):
                original_idx = int(compiled_commands.sorted_commands[command_idx][0])
                command = compiled_commands.sorted_commands[command_idx][1]
            if 0 <= related_idx < len(compiled_commands.sorted_commands):
                related_original_idx = int(compiled_commands.sorted_commands[related_idx][0])
            bar = int(event_bar[n])
            rows.append(
                {
                    "timestamp": idx[bar] if 0 <= bar < len(idx) else pd.NaT,
                    "bar": bar,
                    "sorted_index": command_idx,
                    "original_index": original_idx,
                    "event_type": int(event_type[n]),
                    "event_name": _event_type_name(int(event_type[n])),
                    "status": int(event_status[n]),
                    "related_sorted_index": related_idx,
                    "related_original_index": related_original_idx,
                    "order_id": None if command is None else command.order_id,
                    "target_order_id": None if command is None else command.target_order_id,
                    "parent_order_id": None if command is None else command.parent_order_id,
                    "oco_group_id": None if command is None else command.oco_group_id,
                    "tag": None if command is None else command.tag,
                    "campaign_id": None if command is None else command.metadata.get("campaign_id"),
                    "cycle_id": None if command is None else command.metadata.get("cycle_id"),
                    "level_id": None if command is None else command.metadata.get("level_id"),
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _commands_to_order_intents(sorted_commands) -> tuple[OrderIntent, ...]:
        orders: list[OrderIntent] = []
        for _, command in sorted_commands:
            if command.action in (OrderAction.PLACE, OrderAction.REPLACE):
                if command.symbol is None or command.side is None or command.order_type is None or command.qty is None:
                    continue
                orders.append(
                    OrderIntent(
                        timestamp=command.timestamp,
                        symbol=command.symbol,
                        side=command.side,
                        order_type=command.order_type,
                        qty=float(command.qty),
                        price=command.price,
                        trigger_price=command.trigger_price,
                        tif=command.tif,
                        reduce_only=command.reduce_only,
                        order_id=command.order_id,
                        tag=command.tag,
                        metadata=dict(command.metadata),
                    )
                )
        return tuple(orders)

    def run_basket(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        basket: BasketSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        rebalance_threshold: Optional[float] = None,
        symbols: Optional[List[str]] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
    ) -> BacktestResultV2:
        """
        Build frozen basket orders from a scalar signal and execute them.

        Basket legs are sized once on signal transitions and held constant until
        the next transition. Phase 4 carries all-or-none policy in metadata; the
        current matching kernel executes generated leg orders best-effort.
        """
        plan = build_frozen_basket_orders(
            datetime_index=datetime_index,
            basket=basket,
            signal=signal,
            closes=closes,
            hedge_ratios=hedge_ratios,
            order_type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            rebalance_threshold=rebalance_threshold,
        )
        result = self.run_orders(
            datetime_index=datetime_index,
            orders=plan.orders,
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rate=funding_rate,
            contract_size=contract_size,
            leverage=leverage,
            fee_rate=fee_rate,
            symbols=symbols,
            market_arrays=market_arrays,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        result.metadata["basket_plan"] = plan
        result.metadata["basket_target_units"] = plan.target_units
        result.metadata["basket_execution_policy"] = basket.execution_policy.value
        return result

    def run_stat_arb_pair_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: StatArbPairSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
    ) -> BacktestResultV2:
        """
        Execute a Phase D stat-arb pair through the frozen basket planner.

        Dynamic hedge-ratio series are sampled at entry and held frozen until
        exit. If `spec.hedge_policy.rebalance_threshold` is set, only hedge
        ratio drift beyond that threshold can trigger a package rebalance; price
        movement alone does not create micro-rebalancing orders.
        """
        if not isinstance(spec, StatArbPairSpec):
            raise TypeError("run_stat_arb_pair_arbitrage requires a StatArbPairSpec")
        basket = self._stat_arb_basket_from_spec(spec)
        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        stat_funding = self._funding_for_spec(spec, funding_rate)
        rebalance_threshold = spec.hedge_policy.rebalance_threshold
        if not spec.hedge_policy.freeze_on_entry and rebalance_threshold is None:
            rebalance_threshold = 0.0

        plan = build_frozen_basket_orders(
            datetime_index=idx,
            basket=basket,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
            order_type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            rebalance_threshold=rebalance_threshold,
        )
        arb_plan = self._apply_atomic_package_margin_policy(
            idx=idx,
            plan=ArbitragePlan(
                spec=spec,
                orders=plan.orders,
                target_units=plan.target_units,
                signals=plan.signals,
                entry_ratios=plan.entry_ratios,
                rejections=(),
                metadata=plan.metadata,
            ),
            closes=close_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
            leverage=leverage,
        )

        result = self.run_orders(
            datetime_index=idx,
            orders=arb_plan.orders,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=stat_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
            market_arrays=market_arrays,
        )
        funding_dict = prepare_funding(stat_funding if self.config.use_funding else 0.0, symbols, idx)
        roles = self._stat_arb_roles(spec)
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles=roles,
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        beta_drift_report = self._stat_arb_beta_drift_report(
            idx=idx,
            spec=spec,
            plan=arb_plan,
            rebalance_threshold=rebalance_threshold,
        )
        diagnostics = result.diagnostics.copy()
        diagnostics["package_pnl"] = package_report["package_pnl"]
        diagnostics["package_pnl_residual"] = package_report["pnl_residual"]
        result.diagnostics = diagnostics
        result.metadata.update(
            {
                "backend": "native_event",
                "engine": "event_v1_stat_arb_pair",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": arb_plan,
                "package_target_units": arb_plan.target_units,
                "package_rejection_report": arb_plan.rejection_report,
                "basket_plan": plan,
                "basket_target_units": arb_plan.target_units,
                "beta_drift_report": beta_drift_report,
                "spread_report": self._stat_arb_spread_report(idx, spec, close_dict, arb_plan),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "rebalance_threshold": rebalance_threshold,
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    def run_basis_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: BasisArbitrageSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
    ) -> BacktestResultV2:
        """
        Execute a minimal native-event USDM linear basis arbitrage backtest.

        Phase C models a package trade: signal transitions generate all leg
        orders at the same timestamp, units are frozen until the next signal
        transition, and reports decompose package PnL into leg-level mark,
        fill, fee, and funding components.
        """
        if not isinstance(spec, BasisArbitrageSpec):
            raise TypeError("run_basis_arbitrage requires a BasisArbitrageSpec")

        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        basis_funding = self._funding_for_spec(spec, funding_rate)

        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        result = self.run_orders(
            datetime_index=idx,
            orders=plan.orders,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=basis_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
            market_arrays=market_arrays,
        )

        funding_dict = prepare_funding(basis_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._basis_leg_pnl_report(
            idx=idx,
            spec=spec,
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
        )
        package_pnl = leg_pnl_report.groupby("timestamp", sort=False)["total_pnl"].sum().reindex(idx, fill_value=0.0)
        package_report = pd.DataFrame(
            {
                "package_pnl": package_pnl,
                "equity_delta": result.equity.diff().fillna(0.0),
            },
            index=idx,
        )
        package_report["pnl_residual"] = package_report["equity_delta"] - package_report["package_pnl"]
        spread_report = self._basis_spread_report(idx, spec, close_dict, plan.target_units)

        diagnostics = result.diagnostics.copy()
        diagnostics["package_pnl"] = package_report["package_pnl"]
        diagnostics["package_pnl_residual"] = package_report["pnl_residual"]
        result.diagnostics = diagnostics
        result.metadata.update(
            {
                "backend": "native_event",
                "engine": "event_v1_basis_arbitrage",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "package_rejection_report": plan.rejection_report,
                "spread_report": spread_report,
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    def run_package_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: ArbitrageSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
    ) -> BacktestResultV2:
        """
        Execute Phase G package-style advanced arbitrage specs.

        This route is intentionally limited to advanced arbitrage types whose
        execution can be represented as frozen package target units. Types that
        require sequencing, cross-venue account state, or options Greeks remain
        explicit NotImplemented paths.
        """
        unsupported = (CrossExchangeArbSpec, TriangularArbSpec, OptionsVolArbSpec)
        if isinstance(spec, unsupported):
            raise NotImplementedError(
                f"{type(spec).__name__} is schema-validated but requires a specialized arbitrage engine; "
                "do not route it through generic package execution. "
                "Use QuantBTEndpoint.arbitrage_support_matrix() to inspect supported routes."
            )
        supported = (CalendarSpreadSpec, FundingArbitrageSpec, SpotPerpCashCarrySpec, IndexBasketArbSpec)
        if not isinstance(spec, supported):
            raise TypeError("run_package_arbitrage requires a Phase G package-style arbitrage spec")

        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        package_funding = self._funding_for_spec(spec, funding_rate)
        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        result = self.run_orders(
            datetime_index=idx,
            orders=plan.orders,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=package_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
            market_arrays=market_arrays,
        )

        funding_dict = prepare_funding(package_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._basis_leg_pnl_report(
            idx=idx,
            spec=spec,
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
        )
        package_pnl = leg_pnl_report.groupby("timestamp", sort=False)["total_pnl"].sum().reindex(idx, fill_value=0.0)
        package_report = pd.DataFrame(
            {
                "package_pnl": package_pnl,
                "equity_delta": result.equity.diff().fillna(0.0),
            },
            index=idx,
        )
        package_report["pnl_residual"] = package_report["equity_delta"] - package_report["package_pnl"]
        diagnostics = result.diagnostics.copy()
        diagnostics["package_pnl"] = package_report["package_pnl"]
        diagnostics["package_pnl_residual"] = package_report["pnl_residual"]
        result.diagnostics = diagnostics
        result.metadata.update(
            {
                "backend": "native_event",
                "engine": f"event_v1_{spec.arb_type.value}",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "package_rejection_report": plan.rejection_report,
                "spread_report": self._basis_spread_report(idx, spec, close_dict, plan.target_units),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "carry_report": self._carry_report(idx, spec, result, close_dict, funding_dict, contract_sizes),
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    @staticmethod
    def _bar_index(idx: pd.DatetimeIndex, timestamp) -> int:
        ts = pd.Timestamp(timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        pos = idx.searchsorted(ts, side="left")
        if pos >= len(idx):
            raise ValueError("order timestamp is after the available data")
        return int(pos)

    def _apply_atomic_package_margin_policy(
        self,
        idx: pd.DatetimeIndex,
        plan: ArbitragePlan,
        closes: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
        leverage: Optional[Union[float, Dict[str, float]]],
    ) -> ArbitragePlan:
        spec = plan.spec
        if spec.execution_policy.kind not in (PackageExecutionKind.ATOMIC_ALL_OR_NONE, PackageExecutionKind.BEST_EFFORT):
            return plan

        symbols = [leg.symbol for leg in spec.legs]
        current_units = {symbol: 0.0 for symbol in symbols}
        equity = float(self.config.account.initial_capital)
        target_rows = []
        orders = []
        rejections = list(plan.rejections)
        leverages = self._leverage_mapping(leverage, symbols)
        slippage = self.config.execution.slippage_rate

        for i, ts in enumerate(idx):
            if i > 0:
                prev_ts = idx[i - 1]
                for symbol in symbols:
                    units = current_units[symbol]
                    if units != 0.0:
                        equity += units * (
                            float(closes[symbol].loc[ts]) - float(closes[symbol].loc[prev_ts])
                        ) * float(contract_sizes[symbol])

            original_desired = {symbol: float(plan.target_units.loc[ts, symbol]) for symbol in symbols}
            changed_symbols = [
                symbol for symbol in symbols
                if abs(original_desired[symbol] - current_units[symbol]) > 1e-12
            ]
            if changed_symbols:
                if spec.execution_policy.kind is PackageExecutionKind.ATOMIC_ALL_OR_NONE:
                    allowed, details = self._atomic_package_has_margin(
                        ts=ts,
                        symbols=symbols,
                        current_units=current_units,
                        desired_units=original_desired,
                        closes=closes,
                        contract_sizes=contract_sizes,
                        fee_rates=fee_rates,
                        leverages=leverages,
                        equity=equity,
                        slippage=slippage,
                    )
                    if not allowed:
                        rejections.append(
                            PackageRejection(
                                timestamp=ts,
                                arb_id=spec.arb_id,
                                reason="insufficient_margin_atomic",
                                failed_legs=tuple(changed_symbols),
                                metadata={"details": details, "policy": spec.execution_policy.kind.value},
                            )
                        )
                    else:
                        self._append_package_orders(orders, ts, spec, symbols, current_units, original_desired)
                        equity -= float(details.get("cost", 0.0))
                        current_units = original_desired
                else:
                    for symbol in symbols:
                        if abs(original_desired[symbol] - current_units[symbol]) <= 1e-12:
                            continue
                        candidate_units = dict(current_units)
                        candidate_units[symbol] = original_desired[symbol]
                        allowed, details = self._atomic_package_has_margin(
                            ts=ts,
                            symbols=symbols,
                            current_units=current_units,
                            desired_units=candidate_units,
                            closes=closes,
                            contract_sizes=contract_sizes,
                            fee_rates=fee_rates,
                            leverages=leverages,
                            equity=equity,
                            slippage=slippage,
                        )
                        if not allowed:
                            rejections.append(
                                PackageRejection(
                                    timestamp=ts,
                                    arb_id=spec.arb_id,
                                    reason="insufficient_margin_best_effort",
                                    failed_legs=(symbol,),
                                    metadata={"details": details, "policy": spec.execution_policy.kind.value},
                                )
                            )
                            continue
                        self._append_package_orders(orders, ts, spec, [symbol], current_units, candidate_units)
                        equity -= float(details.get("cost", 0.0))
                        current_units = candidate_units

            target_rows.append({symbol: current_units[symbol] for symbol in symbols})

        return ArbitragePlan(
            spec=spec,
            orders=tuple(orders),
            target_units=pd.DataFrame(target_rows, index=idx),
            signals=plan.signals,
            entry_ratios=plan.entry_ratios,
            rejections=tuple(rejections),
            metadata={**plan.metadata, "execution_margin_policy": "package_preflight"},
        )

    @staticmethod
    def _append_package_orders(
        orders: List[OrderIntent],
        ts,
        spec: ArbitrageSpec,
        symbols: List[str],
        current_units: Dict[str, float],
        desired_units: Dict[str, float],
    ) -> None:
        for symbol in symbols:
            delta = desired_units[symbol] - current_units[symbol]
            if abs(delta) <= 1e-12:
                continue
            side = OrderSide.BUY if delta > 0.0 else OrderSide.SELL
            orders.append(
                OrderIntent(
                    timestamp=ts,
                    symbol=symbol,
                    side=side,
                    order_type=spec.execution_policy.order_type,
                    qty=abs(delta),
                    tif=spec.execution_policy.tif,
                    tag=spec.arb_id,
                    metadata={
                        "arb_id": spec.arb_id,
                        "arb_type": spec.arb_type.value,
                        "package_policy": spec.execution_policy.kind.value,
                        "hedge_policy": spec.hedge_policy.kind.value,
                        "sizing_policy": spec.sizing_policy.kind.value,
                        "target_units": desired_units[symbol],
                        "previous_units": current_units[symbol],
                    },
                )
            )

    def _atomic_package_has_margin(
        self,
        ts,
        symbols: List[str],
        current_units: Dict[str, float],
        desired_units: Dict[str, float],
        closes: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
        leverages: Dict[str, float],
        equity: float,
        slippage: float,
    ) -> tuple[bool, Dict[str, float]]:
        cur_im = 0.0
        margin_delta_sum = 0.0
        cost_sum = 0.0
        for symbol in symbols:
            close_price = float(closes[symbol].loc[ts])
            cs = float(contract_sizes[symbol])
            lev = float(leverages[symbol])
            current = float(current_units[symbol])
            target = float(desired_units[symbol])
            cur_im += abs(current) * close_price * cs / lev
            delta = target - current
            if abs(delta) <= 1e-12:
                continue
            exec_price = close_price * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)
            old_im = abs(current) * close_price * cs / lev
            new_im = abs(target) * exec_price * cs / lev
            margin_delta_sum += new_im - old_im
            cost_sum += abs(delta) * exec_price * cs * float(fee_rates[symbol])
            cost_sum += abs(delta) * abs(exec_price - close_price) * cs

        available = max(0.0, float(equity) - cur_im)
        required = cost_sum + max(0.0, margin_delta_sum)
        return required <= available + 1e-12, {
            "available": available,
            "required": required,
            "current_initial_margin": cur_im,
            "margin_delta": margin_delta_sum,
            "cost": cost_sum,
        }

    def _leverage_mapping(self, leverage, symbols: List[str]) -> Dict[str, float]:
        default = float(self.config.account.leverage)
        if isinstance(leverage, dict):
            return {symbol: float(leverage.get(symbol, default)) for symbol in symbols}
        if leverage is None:
            return {symbol: default for symbol in symbols}
        return {symbol: float(leverage) for symbol in symbols}

    @staticmethod
    def _side_code(side: OrderSide) -> int:
        return 1 if side is OrderSide.BUY else -1

    @staticmethod
    def _order_type_code(order_type: OrderType) -> int:
        if order_type is OrderType.MARKET:
            return ORDER_TYPE_MARKET
        if order_type is OrderType.LIMIT:
            return ORDER_TYPE_LIMIT
        raise NotImplementedError(f"unsupported order_type={order_type!r}")

    @staticmethod
    def _tif_code(tif: TimeInForce) -> int:
        if tif is TimeInForce.GTC:
            return TIF_GTC
        if tif is TimeInForce.IOC:
            return TIF_IOC
        if tif is TimeInForce.FOK:
            return TIF_FOK
        if tif is TimeInForce.GTD:
            return TIF_GTD
        raise NotImplementedError(f"unsupported tif={tif!r}")

    @staticmethod
    def _per_symbol_array(value, symbols: List[str], default: float) -> np.ndarray:
        if isinstance(value, dict):
            return np.array([float(value.get(s, default)) for s in symbols], dtype=np.float64)
        return np.full(len(symbols), float(value), dtype=np.float64)

    @staticmethod
    def _market_signature(idx: pd.DatetimeIndex, symbols: List[str]):
        from ..core.preprocessor import market_data_signature

        return market_data_signature(idx, symbols)

    @staticmethod
    def _fee_rate_metadata(fee_rates: np.ndarray, symbols: List[str]):
        if len(fee_rates) == 0:
            return 0.0
        if np.allclose(fee_rates, fee_rates[0]):
            return float(fee_rates[0])
        return {symbol: float(fee_rates[i]) for i, symbol in enumerate(symbols)}

    def _fee_rate_for_spec(self, spec: ArbitrageSpec) -> Dict[str, float]:
        default_rates = self.config.fee_rate
        out: Dict[str, float] = {}
        for leg in spec.legs:
            if leg.fee_rate is not None:
                out[leg.symbol] = float(leg.fee_rate)
            elif isinstance(default_rates, dict):
                out[leg.symbol] = float(default_rates.get(leg.symbol, 0.0))
            else:
                out[leg.symbol] = float(default_rates)
        return out

    @staticmethod
    def _contract_size_for_spec(
        spec: ArbitrageSpec,
        contract_size: Optional[Union[float, Dict[str, float]]],
    ) -> Dict[str, float]:
        out = {leg.symbol: float(leg.contract_size) for leg in spec.legs}
        if contract_size is None:
            return out
        if isinstance(contract_size, dict):
            out.update({symbol: float(value) for symbol, value in contract_size.items()})
            return out
        return {leg.symbol: float(contract_size) for leg in spec.legs}

    @staticmethod
    def _funding_for_spec(spec: ArbitrageSpec, funding_rate: Union[float, pd.Series, Dict]):
        funding_symbols = {leg.symbol for leg in spec.legs if leg.funding_enabled}
        if isinstance(funding_rate, dict):
            return {
                leg.symbol: funding_rate.get(leg.symbol, 0.0) if leg.symbol in funding_symbols else 0.0
                for leg in spec.legs
            }
        return {leg.symbol: funding_rate if leg.symbol in funding_symbols else 0.0 for leg in spec.legs}

    @staticmethod
    def _stat_arb_basket_from_spec(spec: StatArbPairSpec) -> BasketSpec:
        if spec.sizing_policy.kind is not SizingPolicyKind.TARGET_GROSS_NOTIONAL:
            raise NotImplementedError("Phase D StatArbPairSpec requires target_gross_notional sizing")
        return BasketSpec(
            basket_id=spec.arb_id,
            legs=tuple(BasketLegSpec(symbol=leg.symbol, ratio=float(leg.ratio)) for leg in spec.legs),
            gross_notional=float(spec.sizing_policy.notional),
            freeze_hedge=bool(spec.hedge_policy.freeze_on_entry),
            hedged_margin_offset=float(spec.margin_model.hedged_margin_offset),
            metadata={
                "arb_type": spec.arb_type.value,
                "hedge_policy": spec.hedge_policy.kind.value,
                "sizing_policy": spec.sizing_policy.kind.value,
            },
        )

    @staticmethod
    def _stat_arb_roles(spec: StatArbPairSpec) -> Dict[str, str]:
        symbols = [leg.symbol for leg in spec.legs]
        roles = {leg.symbol: str(leg.role or "leg") for leg in spec.legs}
        if len(symbols) >= 2 and len(set(roles.values())) == 1:
            roles[symbols[0]] = "leg"
            roles[symbols[1]] = "hedge"
        return roles

    @staticmethod
    def _stat_arb_beta_drift_report(
        idx: pd.DatetimeIndex,
        spec: StatArbPairSpec,
        plan,
        rebalance_threshold: Optional[float],
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        reference_symbol = symbols[0]
        rows = []
        for ts in idx:
            ref_units = float(plan.target_units.loc[ts, reference_symbol])
            ref_ratio = float(plan.entry_ratios.loc[ts, reference_symbol])
            active = abs(ref_units) > 1e-12 and abs(ref_ratio) > 1e-12
            for symbol in symbols:
                units = float(plan.target_units.loc[ts, symbol])
                current_ratio = float(plan.entry_ratios.loc[ts, symbol])
                if active:
                    frozen_ratio_to_ref = units / ref_units
                    current_ratio_to_ref = current_ratio / ref_ratio
                    abs_drift = abs(current_ratio_to_ref - frozen_ratio_to_ref)
                    rel_drift = abs_drift / max(abs(frozen_ratio_to_ref), 1e-12)
                else:
                    frozen_ratio_to_ref = 0.0
                    current_ratio_to_ref = 0.0
                    abs_drift = 0.0
                    rel_drift = 0.0
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "reference_symbol": reference_symbol,
                        "target_units": units,
                        "frozen_ratio_to_ref": frozen_ratio_to_ref,
                        "current_ratio_to_ref": current_ratio_to_ref,
                        "abs_beta_drift": abs_drift,
                        "rel_beta_drift": rel_drift,
                        "rebalance_threshold": rebalance_threshold,
                        "breached": (
                            rebalance_threshold is not None
                            and rel_drift > rebalance_threshold
                            and symbol != reference_symbol
                        ),
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _stat_arb_spread_report(
        idx: pd.DatetimeIndex,
        spec: StatArbPairSpec,
        closes: Dict[str, pd.Series],
        plan,
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        leg_symbol = symbols[0]
        hedge_symbol = symbols[1] if len(symbols) > 1 else symbols[0]
        leg_close = closes[leg_symbol].astype(float)
        hedge_close = closes[hedge_symbol].astype(float)
        ref_ratio = plan.entry_ratios[leg_symbol].replace(0.0, np.nan).astype(float)
        hedge_ratio = (plan.entry_ratios[hedge_symbol].astype(float) / ref_ratio).fillna(0.0)
        spread = leg_close + hedge_ratio * hedge_close
        return pd.DataFrame(
            {
                "leg_symbol": leg_symbol,
                "hedge_symbol": hedge_symbol,
                "leg_close": leg_close,
                "hedge_close": hedge_close,
                "hedge_ratio_to_leg": hedge_ratio,
                "spread": spread,
                "abs_spread": spread.abs(),
            },
            index=idx,
        )

    def _leg_pnl_report(
        self,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        roles: Dict[str, str],
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
    ) -> pd.DataFrame:
        fill_rows = {}
        for fill in result.fills:
            ts = pd.Timestamp(fill.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            key = (ts, fill.symbol)
            fee, fill_pnl = fill_rows.get(key, (0.0, 0.0))
            close_price = float(closes[fill.symbol].loc[ts])
            cs = float(contract_sizes[fill.symbol])
            fill_pnl += fill.signed_qty * (close_price - float(fill.price)) * cs
            fee += float(fill.fee)
            fill_rows[key] = (fee, fill_pnl)

        funding_mask = make_funding_mask(idx)
        cumulative = {symbol: 0.0 for symbol in symbols}
        rows = []
        for i, ts in enumerate(idx):
            for symbol in symbols:
                cs = float(contract_sizes[symbol])
                close_price = float(closes[symbol].iloc[i])
                prev_units = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                units = float(result.positions[f"Position_{symbol}"].iloc[i])
                price_pnl = 0.0
                if i > 0:
                    price_pnl = prev_units * (close_price - float(closes[symbol].iloc[i - 1])) * cs
                funding_cost = 0.0
                if self.config.use_funding and funding_mask[i]:
                    funding_cost = prev_units * close_price * cs * float(funding[symbol].iloc[i])
                fee, fill_pnl = fill_rows.get((ts, symbol), (0.0, 0.0))
                total_pnl = price_pnl + fill_pnl - fee - funding_cost
                cumulative[symbol] += total_pnl
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": roles.get(symbol, "leg"),
                        "units": units,
                        "close": close_price,
                        "notional": abs(units) * close_price * cs,
                        "price_pnl": price_pnl,
                        "fill_pnl": fill_pnl,
                        "fee": fee,
                        "funding_pnl": -funding_cost,
                        "total_pnl": total_pnl,
                        "cumulative_pnl": cumulative[symbol],
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _package_pnl_report(idx: pd.DatetimeIndex, result: BacktestResultV2, leg_pnl_report: pd.DataFrame) -> pd.DataFrame:
        grouped = leg_pnl_report.groupby("timestamp", sort=False)
        package_pnl = grouped["total_pnl"].sum().reindex(idx, fill_value=0.0)
        price_pnl = grouped["price_pnl"].sum().reindex(idx, fill_value=0.0)
        fill_pnl = grouped["fill_pnl"].sum().reindex(idx, fill_value=0.0)
        fees = grouped["fee"].sum().reindex(idx, fill_value=0.0)
        funding_pnl = grouped["funding_pnl"].sum().reindex(idx, fill_value=0.0)
        role_pnl = leg_pnl_report.pivot_table(
            index="timestamp",
            columns="role",
            values="total_pnl",
            aggfunc="sum",
            fill_value=0.0,
        ).reindex(idx, fill_value=0.0)
        leg_pnl = role_pnl["leg"] if "leg" in role_pnl else pd.Series(0.0, index=idx)
        hedge_pnl = role_pnl["hedge"] if "hedge" in role_pnl else pd.Series(0.0, index=idx)
        report = pd.DataFrame(
            {
                "price_pnl": price_pnl,
                "fill_pnl": fill_pnl,
                "fees": fees,
                "funding_pnl": funding_pnl,
                "leg_pnl": leg_pnl,
                "hedge_pnl": hedge_pnl,
                "spread_pnl": leg_pnl + hedge_pnl,
                "package_pnl": package_pnl,
                "equity_delta": result.equity.diff().fillna(0.0),
            },
            index=idx,
        )
        report["pnl_residual"] = report["equity_delta"] - report["package_pnl"]
        return report

    def _basis_leg_pnl_report(
        self,
        idx: pd.DatetimeIndex,
        spec: BasisArbitrageSpec,
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
    ) -> pd.DataFrame:
        fill_rows = {}
        for fill in result.fills:
            ts = pd.Timestamp(fill.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            key = (ts, fill.symbol)
            fee, fill_pnl = fill_rows.get(key, (0.0, 0.0))
            close_price = float(closes[fill.symbol].loc[ts])
            cs = float(contract_sizes[fill.symbol])
            fill_pnl += fill.signed_qty * (close_price - float(fill.price)) * cs
            fee += float(fill.fee)
            fill_rows[key] = (fee, fill_pnl)

        funding_mask = make_funding_mask(idx)
        cumulative = {leg.symbol: 0.0 for leg in spec.legs}
        rows = []
        for i, ts in enumerate(idx):
            for leg in spec.legs:
                symbol = leg.symbol
                cs = float(contract_sizes[symbol])
                close_price = float(closes[symbol].iloc[i])
                prev_pos = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                units = float(result.positions[f"Position_{symbol}"].iloc[i])
                price_pnl = 0.0
                if i > 0:
                    price_pnl = prev_pos * (close_price - float(closes[symbol].iloc[i - 1])) * cs
                funding_cost = 0.0
                if self.config.use_funding and funding_mask[i]:
                    funding_cost = prev_pos * close_price * cs * float(funding[symbol].iloc[i])
                fee, fill_pnl = fill_rows.get((ts, symbol), (0.0, 0.0))
                total_pnl = price_pnl + fill_pnl - fee - funding_cost
                cumulative[symbol] += total_pnl
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": leg.role,
                        "units": units,
                        "close": close_price,
                        "notional": abs(units) * close_price * cs,
                        "price_pnl": price_pnl,
                        "fill_pnl": fill_pnl,
                        "fee": fee,
                        "funding_pnl": -funding_cost,
                        "total_pnl": total_pnl,
                        "cumulative_pnl": cumulative[symbol],
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _basis_spread_report(
        idx: pd.DatetimeIndex,
        spec: ArbitrageSpec,
        closes: Dict[str, pd.Series],
        target_units: pd.DataFrame,
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        base_symbol = spec.spread_formula.base_symbol
        quote_symbol = spec.spread_formula.quote_symbol
        if base_symbol is None:
            base_symbol = next((leg.symbol for leg in spec.legs if leg.ratio < 0.0), symbols[0])
        if quote_symbol is None:
            quote_symbol = next((leg.symbol for leg in spec.legs if leg.ratio > 0.0), symbols[-1])

        base_close = closes[base_symbol].astype(float)
        quote_close = closes[quote_symbol].astype(float)
        spread = quote_close - base_close
        ratio_spread = quote_close / base_close.replace(0.0, np.nan) - 1.0
        expiry = next((leg.expiry for leg in spec.legs if leg.symbol == quote_symbol and leg.expiry is not None), None)
        if expiry is None:
            expiry = next((leg.expiry for leg in spec.legs if leg.expiry is not None), None)
        if expiry is None:
            annualized = pd.Series(np.nan, index=idx, dtype=float)
        else:
            days_to_expiry = pd.Series(
                [(expiry - ts).total_seconds() / 86_400.0 for ts in idx],
                index=idx,
                dtype=float,
            )
            annualized = ratio_spread * (365.0 / days_to_expiry.where(days_to_expiry > 0.0))

        report = pd.DataFrame(
            {
                "base_symbol": base_symbol,
                "quote_symbol": quote_symbol,
                "base_close": base_close,
                "quote_close": quote_close,
                "spread": spread,
                "ratio_spread": ratio_spread,
                "annualized_basis": annualized,
            },
            index=idx,
        )
        for symbol in symbols:
            report[f"target_units_{symbol}"] = target_units[symbol]
        return report

    @staticmethod
    def _carry_report(
        idx: pd.DatetimeIndex,
        spec: ArbitrageSpec,
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
    ) -> pd.DataFrame:
        rows = []
        funding_mask = make_funding_mask(idx)
        for i, ts in enumerate(idx):
            for leg in spec.legs:
                symbol = leg.symbol
                prev_units = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                close_price = float(closes[symbol].iloc[i])
                notional = abs(prev_units) * close_price * float(contract_sizes[symbol])
                funding_cost = 0.0
                if funding_mask[i] and leg.funding_enabled:
                    funding_cost = prev_units * close_price * float(contract_sizes[symbol]) * float(funding[symbol].iloc[i])
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": leg.role,
                        "funding_enabled": bool(leg.funding_enabled),
                        "borrow_rate": float(spec.carry_model.borrow_rate),
                        "cash_yield": float(spec.carry_model.cash_yield),
                        "notional": notional,
                        "funding_cost": funding_cost,
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _build_fills(sorted_orders, idx, fill_bar, fill_qty, fill_price, fill_fee) -> List[Fill]:
        fills: List[Fill] = []
        filled_indices = np.flatnonzero(fill_bar >= 0)
        for sorted_idx in filled_indices:
            order = sorted_orders[int(sorted_idx)][1]
            bar = int(fill_bar[sorted_idx])
            metadata = dict(getattr(order, "metadata", {}) or {})
            if getattr(order, "tag", None) is not None:
                metadata.setdefault("tag", order.tag)
            if getattr(order, "parent_order_id", None) is not None:
                metadata.setdefault("parent_order_id", order.parent_order_id)
            if getattr(order, "oco_group_id", None) is not None:
                metadata.setdefault("oco_group_id", order.oco_group_id)
            fills.append(
                Fill(
                    timestamp=idx[bar],
                    symbol=order.symbol,
                    side=order.side,
                    qty=float(fill_qty[sorted_idx]),
                    price=float(fill_price[sorted_idx]),
                    fee=float(fill_fee[sorted_idx]),
                    liquidity=(
                        LiquiditySide.TAKER
                        if order.order_type is OrderType.MARKET
                        else LiquiditySide.MAKER
                    ),
                    order_id=order.order_id,
                    metadata={**metadata, "source": "native_event"},
                )
            )
        return fills
