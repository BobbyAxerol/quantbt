"""Exact execution aggregates and retained auxiliary paths, separate from trades."""

from dataclasses import asdict, dataclass, field
import json
import math

import numpy as np

from ..report_contracts import ReportingCoverageV1
from .inputs import frozen_array, identity
from .results import MetricBuilder, ReportingResult


AGGREGATES = ("fill_count", "rejected_count", "canceled_count", "turnover", "total_fee", "total_funding")
PATHS = ("fees", "funding", "separate_slippage_cost", "gross_exposure_ratio", "initial_margin", "maintenance_margin")


@dataclass(frozen=True, kw_only=True)
class ExecutionObservations:
    coverage: ReportingCoverageV1
    currency: str
    scope_start_ns: int
    scope_end_ns: int
    witness: str
    aggregates: tuple[tuple[str, float], ...] = ()
    times_ns: np.ndarray | None = None
    paths: tuple[tuple[str, np.ndarray], ...] = ()
    identity: str = field(init=False)

    def __post_init__(self):
        if not isinstance(self.coverage, ReportingCoverageV1) or not self.currency or not self.witness:
            raise ValueError("typed coverage, currency and aggregate/path witness required")
        if type(self.scope_start_ns) is not int or type(self.scope_end_ns) is not int or self.scope_end_ns < self.scope_start_ns:
            raise ValueError("explicit aggregate observation scope required")
        aggregates = tuple(tuple(item) for item in self.aggregates)
        if len(dict(aggregates)) != len(aggregates):
            raise ValueError("duplicate aggregate")
        for name, value in aggregates:
            if name not in AGGREGATES or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("unknown/nonfinite authoritative aggregate")
            if name.endswith("count") and (value < 0 or value != int(value)):
                raise ValueError("nonnegative integer execution count required")
        paths = tuple((name, frozen_array(value, np.float64)) for name, value in self.paths)
        if len(dict(paths)) != len(paths) or any(name not in PATHS for name, _ in paths):
            raise ValueError("unknown/duplicate path")
        times = frozen_array(self.times_ns, np.int64, integer=True) if self.times_ns is not None else None
        if paths and (times is None or any(len(value) != len(times) for _, value in paths)):
            raise ValueError("aligned path times required")
        if times is not None and (not len(times) or np.any(times[1:] <= times[:-1]) or times[0] < self.scope_start_ns or times[-1] != self.scope_end_ns):
            raise ValueError("ordered paths must span declared observation scope")
        object.__setattr__(self, "aggregates", aggregates)
        object.__setattr__(self, "paths", paths)
        object.__setattr__(self, "times_ns", times)
        metadata = dict(coverage=asdict(self.coverage), currency=self.currency, start=self.scope_start_ns,
                        end=self.scope_end_ns, witness=self.witness, aggregates=aggregates,
                        paths=[name for name, _ in paths])
        object.__setattr__(self, "identity", identity(metadata, *([times] if times is not None else []), *[v for _, v in paths]))


def execution_from_native(adapter, *, coverage, currency, scope_start_ns, scope_end_ns):
    """V2 counters/costs are read exactly; V2 Sharpe/trade semantics are not reused."""
    values = adapter.metrics
    aggregates = tuple((name, values[name]) for name in AGGREGATES if name in values)
    return ExecutionObservations(coverage=coverage, currency=currency,
        scope_start_ns=scope_start_ns, scope_end_ns=scope_end_ns,
        witness="NativeResultV2 exact recorded execution aggregates, not audit row count", aggregates=aggregates)


def reduce_execution(observations, contract):
    if contract.unit != "account_period" or observations.currency != contract.currency:
        raise ValueError("account execution contract/currency mismatch")
    if contract.baseline_time_ns < observations.scope_start_ns or contract.scope_end_ns > observations.scope_end_ns:
        raise ValueError("report scope outside observed execution scope")
    builder = MetricBuilder(contract, observations.coverage)
    aggregates, paths = dict(observations.aggregates), dict(observations.paths)
    full_match = contract.baseline_time_ns == observations.scope_start_ns and contract.scope_end_ns == observations.scope_end_ns
    for name in AGGREGATES:
        unit = "count" if name.endswith("count") else contract.currency
        if full_match and name in aggregates:
            builder.add("execution." + name, aggregates[name], unit=unit)
        else:
            builder.add("execution." + name, unit=unit, status="unavailable",
                        reason="exact matched-scope aggregate missing; retained audit rows are not full counters")
    mask = None if observations.times_ns is None else (observations.times_ns >= contract.baseline_time_ns) & (observations.times_ns <= contract.scope_end_ns)
    for name in PATHS:
        reducers = ("mean", "max") if name in {"gross_exposure_ratio", "initial_margin", "maintenance_margin"} else ("sum",)
        for reducer in reducers:
            key = "execution." + reducer + "_" + name
            unit = "ratio" if name == "gross_exposure_ratio" else contract.currency
            if name not in paths or mask is None or not mask.any():
                builder.add(key, unit=unit, status="unavailable", reason="authoritative retained auxiliary path missing")
            elif name == "separate_slippage_cost" and contract.slippage_basis != "recorded_separate_cost":
                builder.add(key, unit=unit, status="unavailable", reason="embedded slippage is not an additional cash cost")
            else:
                sample = paths[name][mask]
                builder.add(key, float(getattr(sample, reducer)()), unit=unit, count=len(sample))
    return ReportingResult(contract_identity=builder.contract_identity, input_identity=observations.identity,
        metrics=tuple(builder.metrics), provenance_json=json.dumps(dict(contract=contract.to_metadata(),
            witness=observations.witness, aggregate_scope=[observations.scope_start_ns, observations.scope_end_ns],
            sample_weighting="equal observed marks, not time-weighted",
            truncated_detail_does_not_change_exact_aggregates=True), sort_keys=True, allow_nan=False))


def reconcile_account(*, baseline_equity, final_equity, closed_net_pnl, open_realized_net_pnl,
                      open_unrealized_pnl, shared_net_adjustment, currency, witness):
    """Only complete, same-scope, net allocated controls may enter reconciliation."""
    if not currency or not witness:
        raise ValueError("same-scope currency and complete allocation witness required")
    values = (baseline_equity, final_equity, closed_net_pnl, open_realized_net_pnl, open_unrealized_pnl, shared_net_adjustment)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise ValueError("complete finite reconciliation controls required")
    observed = closed_net_pnl + open_realized_net_pnl + open_unrealized_pnl + shared_net_adjustment
    return dict(currency=currency, witness=witness, accounted_net_pnl=observed,
                account_pnl=final_equity - baseline_equity,
                difference=observed - (final_equity - baseline_equity))
