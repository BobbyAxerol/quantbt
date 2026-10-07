"""Reporting-only schemas. Not connected to execution or scientific reducers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math


def _choice(name, value, choices):
    if value not in choices:
        raise ValueError(f"{name} must be one of {sorted(choices)}")


def _finite(name, value, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError(f"invalid {name}")


def _integer(name, value, *, nonnegative=False):
    if type(value) is not int or (nonnegative and value < 0):
        raise ValueError(f"{name} must be an integer")


def _full_metadata(cls, metadata):
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a full JSON object")
    expected = {f.name for f in fields(cls)}
    if set(metadata) != expected:
        raise ValueError("metadata must preserve every contract field and reject unknown fields")
    return metadata


@dataclass(frozen=True, kw_only=True)
class ReportingContractV1:
    """Immutable proposed report policy; timestamps are UTC epoch nanoseconds.

    A baseline must come from the account at scope entry, not be inferred from
    the first retained mark. Policy options never mutate the executed result.
    """

    scope: str
    unit: str
    currency: str
    baseline_equity: float
    baseline_time_ns: int
    scope_end_ns: int
    sampling: str
    annual_periods: float
    equity_clock: str
    version: str = "quantbt.reporting.v1"
    calendar: str = "UTC"
    missing_periods: str = "observed_only"
    partial_periods: str = "include_disclosed"
    cashflows: str = "none"
    cagr_basis: str = "elapsed_calendar"
    calendar_year_days: float = 365.25
    min_cagr_days: float = 1.0
    risk_free_per_period: float = 0.0
    mar_per_period: float = 0.0
    omega_threshold_per_period: float = 0.0
    variance_ddof: int = 1
    sortino_denominator: str = "all_observations"
    cost_basis: str = "authoritative_net"
    slippage_basis: str = "included_in_fill_price"
    matching: str = "none"
    grouping: str = "none"
    ledger_scope: str = "none"
    disjoint_scope: str = "reject"
    recovery_relative_tolerance: float = 0.0
    breakeven_currency_tolerance: float = 0.0

    def __post_init__(self):
        _choice("version", self.version, {"quantbt.reporting.v1"})
        _choice("scope", self.scope, {"full", "scoped"})
        _choice("unit", self.unit, {"account_period", "closed_trade", "closed_action"})
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency must be explicit")
        _finite("baseline_equity", self.baseline_equity, positive=True)
        for name in ("baseline_time_ns", "scope_end_ns"):
            _integer(name, getattr(self, name))
        if self.scope_end_ns < self.baseline_time_ns:
            raise ValueError("scope end precedes baseline")
        _choice("sampling", self.sampling, {"observed_bar", "observed_daily_utc", "explicit_period_returns"})
        _choice("equity_clock", self.equity_clock, {"bar_close", "daily_close", "recorded_event"})
        _choice("calendar", self.calendar, {"UTC"})
        _choice("missing_periods", self.missing_periods, {"observed_only"})
        _choice("partial_periods", self.partial_periods, {"include_disclosed", "exclude_disclosed"})
        if self.cashflows != "none":
            raise NotImplementedError("flow-adjusted returns require a separately certified contract")
        _choice("cagr_basis", self.cagr_basis, {"elapsed_calendar", "period_count"})
        for name in ("annual_periods", "calendar_year_days"):
            _finite(name, getattr(self, name), positive=True)
        for name in ("min_cagr_days", "recovery_relative_tolerance", "breakeven_currency_tolerance"):
            _finite(name, getattr(self, name), nonnegative=True)
        if self.recovery_relative_tolerance >= 1:
            raise ValueError("recovery tolerance must be below one")
        for name in ("risk_free_per_period", "mar_per_period", "omega_threshold_per_period"):
            _finite(name, getattr(self, name))
        _integer("variance_ddof", self.variance_ddof, nonnegative=True)
        _choice("variance_ddof", self.variance_ddof, {0, 1})
        _choice("sortino_denominator", self.sortino_denominator, {"all_observations", "negative_observations"})
        _choice("cost_basis", self.cost_basis, {"authoritative_net"})
        _choice("slippage_basis", self.slippage_basis, {"included_in_fill_price", "recorded_separate_cost"})
        _choice("matching", self.matching, {"none", "position_episode", "average_cost", "recorded_lot"})
        _choice("grouping", self.grouping, {"none", "authoritative_action_id"})
        _choice("ledger_scope", self.ledger_scope, {"none", "closed_in_scope_lifetime", "in_scope_attribution"})
        _choice("disjoint_scope", self.disjoint_scope, {"reject", "independent_segments"})
        if self.unit == "account_period":
            if (self.matching, self.grouping, self.ledger_scope) != ("none", "none", "none"):
                raise ValueError("account statistics cannot imply a trade-matching convention")
        elif self.matching == "none" or self.ledger_scope == "none":
            raise ValueError("closed populations require matching and ledger scope")
        if (self.unit == "closed_action") != (self.grouping == "authoritative_action_id"):
            raise ValueError("action statistics require authoritative grouping")

    def to_metadata(self):
        return asdict(self)

    @classmethod
    def from_metadata(cls, metadata):
        return cls(**_full_metadata(cls, metadata))

    @property
    def identity(self):
        payload = json.dumps(self.to_metadata(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class ReportingCoverageV1:
    result_identity: str
    producer: str
    profile: str
    ledger: str
    retained_rows: int
    dropped_rows: int
    reason: str | None = None

    def __post_init__(self):
        for name in ("result_identity", "producer", "profile"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        _choice("ledger", self.ledger, {"complete", "omitted", "truncated", "unsupported"})
        for name in ("retained_rows", "dropped_rows"):
            _integer(name, getattr(self, name), nonnegative=True)
        if self.ledger == "complete" and (self.dropped_rows or self.reason is not None):
            raise ValueError("complete ledger cannot have dropped rows or a missing-data reason")
        if self.ledger != "complete" and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("incomplete coverage needs a reason")
        if self.ledger == "truncated" and not self.dropped_rows:
            raise ValueError("truncated coverage must disclose dropped rows")
        if self.ledger in {"omitted", "unsupported"} and (self.retained_rows or self.dropped_rows):
            raise ValueError("absent ledger cannot claim observed rows")


@dataclass(frozen=True, kw_only=True)
class ReportingMetricV1:
    metric_id: str
    contract_identity: str
    unit: str
    status: str
    value: float | None
    sample_count: int
    coverage: ReportingCoverageV1
    reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.metric_id, str) or not self.metric_id.startswith("reporting."):
            raise ValueError("new metrics require a separate reporting namespace")
        if not isinstance(self.contract_identity, str) or len(self.contract_identity) != 64 or any(c not in "0123456789abcdef" for c in self.contract_identity):
            raise ValueError("contract identity must be SHA256")
        if not isinstance(self.unit, str) or not self.unit.strip() or not isinstance(self.coverage, ReportingCoverageV1):
            raise ValueError("unit and typed coverage are required")
        _integer("sample_count", self.sample_count, nonnegative=True)
        _choice("status", self.status, {"valid", "no_loss", "undefined", "unavailable", "insufficient", "invalid"})
        if self.status == "valid":
            _finite("value", self.value)
            if self.reason is not None:
                raise ValueError("valid metric cannot have an undefined reason")
        elif self.value is not None or not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("non-finite/unavailable metrics use null plus an explicit reason")

    def to_metadata(self):
        return asdict(self)

    @classmethod
    def from_metadata(cls, metadata):
        data = dict(_full_metadata(cls, metadata))
        data["coverage"] = ReportingCoverageV1(**_full_metadata(ReportingCoverageV1, data["coverage"]))
        return cls(**data)
