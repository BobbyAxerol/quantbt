"""Common objective builders for domain-agnostic optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .result import ObjectiveResult


MetricMap = Mapping[str, float]
ConstraintBuilder = Callable[[MetricMap, Mapping[str, Any], Any], float]


class MissingOptimizationMetricError(KeyError):
    """Raised when an objective/constraint metric is required but unavailable."""


_METRIC_ALIASES = {
    "trades": "num_trades",
    "trade_count": "num_trades",
    "max_drawdown": "max_drawdown_pct",
    "mdd": "max_drawdown_pct",
    "margin_util": "margin_utilization",
    "rejections": "rejection_rate",
}


def normalize_metric_name(name: str) -> str:
    """Return the canonical QuantBT objective metric name."""

    key = str(name).strip()
    return _METRIC_ALIASES.get(key, key)


def result_full_report(result: Any, *, trading_days: int = 365, scope: str = "auto") -> dict[str, Any]:
    """Extract the standard metrics report from a QuantBT result-like object."""

    if hasattr(result, "full_report") and callable(result.full_report):
        return dict(result.full_report(trading_days=trading_days, scope=scope))
    metadata = dict(getattr(result, "metadata", {}) or {})
    for key in ("report", "full_report", "metrics"):
        value = metadata.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    raise TypeError("result must expose full_report(...) or metadata report/metrics")


def metric_from_result(
    result: Any,
    name: str,
    *,
    trading_days: int = 365,
    scope: str = "auto",
    required: bool = True,
    default: Optional[float] = None,
) -> float:
    """Read a common objective metric from report, diagnostics, or metadata."""

    canonical = normalize_metric_name(name)
    report = result_full_report(result, trading_days=trading_days, scope=scope)
    if canonical in report:
        return float(report[canonical])
    metadata = dict(getattr(result, "metadata", {}) or {})
    if canonical in metadata:
        return float(metadata[canonical])
    if canonical == "margin_utilization":
        value = _margin_utilization(result)
        if value is not None:
            return value
    if canonical == "rejection_rate":
        value = _rejection_rate(result)
        if value is not None:
            return value
    if required:
        raise MissingOptimizationMetricError(f"missing required optimization metric: {canonical}")
    return float(0.0 if default is None else default)


def metrics_from_result(
    result: Any,
    *,
    names: Sequence[str] = ("sharpe", "max_drawdown_pct", "num_trades", "profit_factor"),
    trading_days: int = 365,
    scope: str = "auto",
) -> dict[str, float]:
    """Extract optional display metrics from a QuantBT result.

    Missing display metrics are omitted. Metrics used as objective values or
    formal constraints must be requested through `metric_from_result(...,
    required=True)` or the constraint helper functions below.
    """

    metrics: dict[str, float] = {}
    report = result_full_report(result, trading_days=trading_days, scope=scope)
    for name in names:
        canonical = normalize_metric_name(name)
        if canonical in report:
            metrics[canonical] = float(report[canonical])
        else:
            try:
                metrics[canonical] = metric_from_result(result, canonical, trading_days=trading_days, scope=scope, required=True)
            except MissingOptimizationMetricError:
                pass
    return metrics


def max_drawdown_constraint(max_drawdown_pct: float) -> ConstraintBuilder:
    """Constraint: realized max drawdown must be <= `max_drawdown_pct`."""

    limit = float(max_drawdown_pct)
    return lambda metrics, params, result: _required_metric(metrics, "max_drawdown_pct") - limit


def min_trades_constraint(min_trades: float) -> ConstraintBuilder:
    """Constraint: realized number of trades must be >= `min_trades`."""

    required = float(min_trades)
    return lambda metrics, params, result: required - _required_metric(metrics, "num_trades")


def max_turnover_constraint(max_turnover: float) -> ConstraintBuilder:
    """Constraint: realized turnover must be <= `max_turnover`."""

    limit = float(max_turnover)
    return lambda metrics, params, result: _required_metric(metrics, "turnover") - limit


def max_margin_utilization_constraint(max_margin_utilization: float) -> ConstraintBuilder:
    """Constraint: maximum margin utilization must be <= limit."""

    limit = float(max_margin_utilization)
    return lambda metrics, params, result: _required_metric(metrics, "margin_utilization") - limit


def max_rejection_rate_constraint(max_rejection_rate: float) -> ConstraintBuilder:
    """Constraint: package/order rejection rate must be <= limit."""

    limit = float(max_rejection_rate)
    return lambda metrics, params, result: _required_metric(metrics, "rejection_rate") - limit


@dataclass(frozen=True)
class ReportMetricObjective:
    """Build an ObjectiveResult from QuantBT full-report metrics.

    Formal constraints keep Optuna's convention: values `<= 0` are feasible.
    The score itself is not polluted by arbitrary penalties when a constraint
    can express the domain rule explicitly.
    """

    value_metrics: Sequence[str] = ("sharpe",)
    metric_names: Sequence[str] = (
        "sharpe",
        "max_drawdown_pct",
        "num_trades",
        "turnover",
        "profit_factor",
        "margin_utilization",
        "rejection_rate",
    )
    trading_days: int = 365
    scope: str = "auto"
    constraints: Sequence[ConstraintBuilder] = field(default_factory=tuple)
    metadata_builder: Optional[Callable[[Any, Mapping[str, Any], MetricMap], Mapping[str, Any]]] = None

    def __call__(self, result: Any, params: Mapping[str, Any]) -> ObjectiveResult:
        metrics = metrics_from_result(result, names=self.metric_names, trading_days=self.trading_days, scope=self.scope)
        values = tuple(metric_from_result(result, name, trading_days=self.trading_days, scope=self.scope, required=True) for name in self.value_metrics)
        constraints = tuple(float(builder(metrics, params, result)) for builder in self.constraints)
        metadata = {} if self.metadata_builder is None else dict(self.metadata_builder(result, params, metrics))
        return ObjectiveResult(values=values, metrics=metrics, constraints=constraints, metadata=metadata)


@dataclass(frozen=True)
class SharpeObjective(ReportMetricObjective):
    """Single-objective Sharpe score with optional formal constraints."""

    value_metrics: Sequence[str] = ("sharpe",)


def _required_metric(metrics: MetricMap, name: str) -> float:
    canonical = normalize_metric_name(name)
    if canonical not in metrics:
        raise MissingOptimizationMetricError(f"missing required optimization metric: {canonical}")
    return float(metrics[canonical])


def _margin_utilization(result: Any) -> Optional[float]:
    margin = getattr(result, "margin", None)
    equity = getattr(result, "equity", None)
    try:
        if margin is not None and equity is not None and len(margin) and len(equity):
            initial = margin["initial_margin"] if "initial_margin" in margin else margin.iloc[:, 0]
            util = (initial.astype(float) / equity.astype(float).replace(0.0, float("nan"))).max()
            return float(0.0 if util != util else util)
    except Exception:
        pass
    return None


def _rejection_rate(result: Any) -> Optional[float]:
    metadata = dict(getattr(result, "metadata", {}) or {})
    for key in ("rejection_rate", "package_rejection_rate"):
        if key in metadata:
            return float(metadata[key])
    rejected = metadata.get("rejected_count", metadata.get("rejections"))
    fills = metadata.get("fill_count", metadata.get("fills_count"))
    if rejected is not None and fills is not None:
        denom = float(rejected) + float(fills)
        return 0.0 if denom <= 0.0 else float(rejected) / denom
    fills_obj = getattr(result, "fills", ())
    try:
        fill_count = len(fills_obj)
        if "rejected_count" not in metadata:
            return None
        rejected_count = int(metadata["rejected_count"])
        denom = fill_count + rejected_count
        return 0.0 if denom <= 0 else float(rejected_count) / float(denom)
    except Exception:
        return None
