"""Frozen, serializable models shared by QuantBT planning and engine SPI."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, IntFlag
from typing import Any

from .fingerprints import canonical_payload, planning_fingerprint


class BackendKind(str, Enum):
    PYTHON = "python"
    RUST = "rust"


class BackendDecisionReason(str, Enum):
    EXPLICIT_PYTHON = "explicit_python"
    EXPLICIT_RUST_CERTIFIED = "explicit_rust_certified"
    AUTO_PYTHON_RELEASE_POLICY = "auto_python_release_policy"
    REPLAY_CERTIFIED_COMPATIBILITY = "replay_certified_compatibility"


class WorkloadClass(str, Enum):
    STATIC_COMMAND_TAPE = "static_command_tape"
    PYTHON_CALLBACK = "python_callback"
    SIGNAL_TAPE = "signal_tape"
    PORTFOLIO_TARGET = "portfolio_target"
    PACKAGE_TRANSACTION = "package_transaction"


class StrategyMode(str, Enum):
    STATIC_COMMANDS = "static_commands"
    PYTHON_CALLBACK_COMPAT = "python_callback_compat"
    SIGNAL = "signal"
    PORTFOLIO = "portfolio"
    PACKAGE = "package"


class RunProfile(str, Enum):
    SCORE = "score"
    MINIMAL = "minimal"
    STANDARD = "standard"
    AUDIT = "audit"


class MarketLayout(str, Enum):
    ALIGNED_OHLC = "aligned_ohlc"
    ALIGNED_OHLCV = "aligned_ohlcv"


class AccountModelRef(str, Enum):
    LINEAR_QUOTE_SETTLED_GROSS_CROSS = "linear_quote_settled_gross_cross"


class MetricMask(IntFlag):
    NONE = 0
    RETURN = 1 << 0
    RISK = 1 << 1
    TRADE_COUNTS = 1 << 2
    COSTS = 1 << 3
    MARGIN = 1 << 4
    ALL = RETURN | RISK | TRADE_COUNTS | COSTS | MARGIN


class PathMask(IntFlag):
    NONE = 0
    EQUITY = 1 << 0
    POSITIONS = 1 << 1
    FEES = 1 << 2
    FUNDING = 1 << 3
    MARGIN = 1 << 4
    TURNOVER = 1 << 5
    REJECTIONS = 1 << 6
    CANCELLATIONS = 1 << 7
    PUBLIC_DEFAULT = EQUITY | POSITIONS | FEES | FUNDING | MARGIN | TURNOVER | REJECTIONS | CANCELLATIONS


class DetailLevel(str, Enum):
    NONE = "none"
    COUNT = "count"
    COMPACT = "compact"
    FULL = "full"


class PositionProjection(str, Enum):
    NONE = "none"
    FINAL = "final"
    PER_BAR = "per_bar"


class SnapshotSchedule(str, Enum):
    NONE = "none"
    FINAL = "final"
    PER_BAR = "per_bar"


class AttributionMask(IntFlag):
    NONE = 0
    SYMBOL = 1 << 0
    PACKAGE = 1 << 1
    LIQUIDATION = 1 << 2


@dataclass(frozen=True, slots=True)
class NumericPolicy:
    float_dtype: str = "float64"
    integer_dtype: str = "int64"
    price_quantization: str = "side_order_aware_v1"
    quantity_quantization: str = "floor_to_step_v1"
    unsupported_contract_policy: str = "raise"


@dataclass(frozen=True, slots=True)
class TraceRequirements:
    enabled: bool = False
    materialize: bool = False
    fingerprint: bool = False
    stream: bool = False
    schema: str = "canonical-execution-trace-v1"


@dataclass(frozen=True, slots=True)
class OutputRequirements:
    scalar_metrics: MetricMask = MetricMask.ALL
    dense_paths: PathMask = PathMask.PUBLIC_DEFAULT
    fill_detail: DetailLevel = DetailLevel.COMPACT
    event_detail: DetailLevel = DetailLevel.NONE
    active_order_detail: DetailLevel = DetailLevel.NONE
    final_positions: PositionProjection = PositionProjection.FINAL
    per_bar_positions: PositionProjection = PositionProjection.PER_BAR
    account_snapshots: SnapshotSchedule = SnapshotSchedule.PER_BAR
    attribution: AttributionMask = AttributionMask.NONE
    public_result: bool = True
    materialize_pandas: bool = True

    @property
    def fingerprint(self) -> str:
        return planning_fingerprint(self)

    def to_dict(self) -> dict[str, Any]:
        return canonical_payload(self)


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    endpoint_mode: str
    input_mode: str
    requested_backend: str
    execution_contract_id: str
    strategy_mode: StrategyMode
    workload: WorkloadClass
    profile: RunProfile
    report_level: str
    audit_sink: str
    symbols: tuple[str, ...]
    command_count: int = 0
    market_layout: MarketLayout = MarketLayout.ALIGNED_OHLCV
    account_model: AccountModelRef = AccountModelRef.LINEAR_QUOTE_SETTLED_GROSS_CROSS
    numeric: NumericPolicy = field(default_factory=NumericPolicy)
    trace_requested: bool = False
    public_result: bool = True
    declared_strategy_requirements: bool = True
    required_capabilities: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.endpoint_mode.strip():
            raise ValueError("endpoint_mode cannot be empty")
        if not self.symbols:
            raise ValueError("BacktestRequest requires at least one symbol")
        if self.command_count < 0:
            raise ValueError("command_count must be >= 0")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be unique and ordered")

    @property
    def fingerprint(self) -> str:
        return planning_fingerprint(self)

    def to_dict(self) -> dict[str, Any]:
        return canonical_payload(self)


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    contract_id: str
    workload: WorkloadClass
    backend: BackendKind
    backend_reason: BackendDecisionReason
    strategy_mode: StrategyMode
    profile: RunProfile
    output: OutputRequirements
    trace: TraceRequirements
    numeric: NumericPolicy
    market_layout: MarketLayout
    account_model: AccountModelRef
    capability_fingerprint: str
    request_fingerprint: str
    projection_fingerprint: str
    plan_fingerprint: str = ""
    resolution_counts: tuple[tuple[str, int], ...] = (
        ("backend", 1),
        ("capability", 1),
        ("contract", 1),
        ("output", 1),
        ("profile", 1),
    )

    def __post_init__(self) -> None:
        if not self.contract_id:
            raise ValueError("contract_id cannot be empty")
        if self.plan_fingerprint:
            expected = planning_fingerprint(replace(self, plan_fingerprint=""))
            if self.plan_fingerprint != expected:
                raise ValueError("plan_fingerprint does not match resolved plan content")

    def with_fingerprint(self) -> "ExecutionPlan":
        if self.plan_fingerprint:
            return self
        return replace(self, plan_fingerprint=planning_fingerprint(self))

    def to_dict(self) -> dict[str, Any]:
        return canonical_payload(self)


__all__ = [
    "AccountModelRef",
    "AttributionMask",
    "BackendDecisionReason",
    "BackendKind",
    "BacktestRequest",
    "DetailLevel",
    "ExecutionPlan",
    "MarketLayout",
    "MetricMask",
    "NumericPolicy",
    "OutputRequirements",
    "PathMask",
    "PositionProjection",
    "RunProfile",
    "SnapshotSchedule",
    "StrategyMode",
    "TraceRequirements",
    "WorkloadClass",
]
