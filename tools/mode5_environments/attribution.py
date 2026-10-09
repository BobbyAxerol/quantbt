"""Conditional attribution of actual account marks, never a financial simulator."""

from dataclasses import dataclass

import numpy as np

from tools.mode5_diagnostics import ExecutionEvidence, MissingInputs
from tools.mode5_diagnostics.evidence import FrozenBuffer
from tools.mode5_statistics.analysis import partition_pnl
from .manifests import calendar

DAY_NS = 86_400_000_000_000


@dataclass(frozen=True)
class DailyPath:
    execution_id: str
    mode: str
    times: FrozenBuffer
    pnl: FrozenBuffer
    returns: FrozenBuffer
    return_valid: FrozenBuffer
    equity_before: FrozenBuffer
    equity_after: FrozenBuffer
    fees: FrozenBuffer | None
    exposed_bars: FrozenBuffer
    observed_bars: FrozenBuffer
    actual_span_days: float


def daily_path(evidence, policy, *, initial_equity, evaluation_mode="CONTINUOUS_PATH_ATTRIBUTION"):
    if not isinstance(evidence, ExecutionEvidence):
        raise TypeError("qualified execution evidence required")
    policy.require(evidence.witness)
    if evaluation_mode not in {"CONTINUOUS_PATH_ATTRIBUTION", "CONTIGUOUS_RESET_EPISODES"}:
        raise ValueError("explicit account evaluation mode required")
    arrays = evidence.arrays()
    missing = {"timestamps", "equity", "positions"}-arrays.keys()
    if missing:
        raise MissingInputs(sorted(missing))
    times = calendar(arrays["timestamps"])
    equity, fees, positions = arrays["equity"], arrays.get("fees"), arrays["positions"]
    if (equity.shape != times.shape or (fees is not None and fees.shape != times.shape) or positions.ndim not in {1,2}
            or len(positions) != len(times) or times[0] < evidence.witness.start_ns
            or times[-1] >= evidence.witness.end_ns):
        raise ValueError("account/calendar/manifest cardinality mismatch")
    day = times//DAY_NS
    starts = np.r_[0, np.flatnonzero(np.diff(day))+1]
    ends = np.r_[starts[1:]-1, len(times)-1]
    # Reuse the qualified M5-03 monetary partition with scope-entry equity.
    parts = partition_pnl(equity, initial_equity=initial_equity, block_ends=tuple(int(i) for i in ends))
    pnls = np.array([p["money_pnl"] for p in parts])
    valid = np.array([p["simple_return"] is not None for p in parts])
    returns = np.array([p["simple_return"] if p["simple_return"] is not None else 0. for p in parts])
    exposure = np.abs(positions) > 0
    if positions.ndim == 2:
        exposure = exposure.any(axis=1)
    buffers = [FrozenBuffer.from_array(name, values) for name,values in (
        ("times", day[starts]*DAY_NS), ("pnl", pnls), ("returns", returns), ("return_valid",valid),
        ("equity_before", np.array([p["pre_block_equity"] for p in parts])), ("equity_after",equity[ends]),
        ("exposed_bars",np.add.reduceat(exposure.astype(np.int64),starts)),
        ("observed_bars",ends-starts+1))]
    buffers.insert(6,FrozenBuffer.from_array("fees",np.add.reduceat(fees,starts)) if fees is not None else None)
    return DailyPath(evidence.execution_id, evaluation_mode, *buffers,
                     (evidence.witness.end_ns-evidence.witness.start_ns)/DAY_NS)


def attribute_days(path, labels):
    """All days counted once, including unknown labels; no subset annualization."""
    if path.mode != "CONTINUOUS_PATH_ATTRIBUTION":
        raise ValueError("reset episodes are not a carried deployment path")
    raw_labels = np.asarray(labels)
    if raw_labels.shape != path.times.array().shape or raw_labels.dtype.kind not in "iu" or np.any(raw_labels < -1):
        raise ValueError("one exact state per observed UTC day; -1 means unavailable")
    pnl, returns, valid, exposures, counts = (b.array() for b in (
        path.pnl,path.returns,path.return_valid,path.exposed_bars,path.observed_bars))
    fees = path.fees.array() if path.fees is not None else None
    rows = []
    for state in np.unique(raw_labels):
        mask = raw_labels == state
        conditional = float(np.prod(1+returns[mask])-1) if valid[mask].all() else None
        rows.append(dict(state=int(state), days=int(mask.sum()), money_pnl=float(pnl[mask].sum()),
            fees=float(fees[mask].sum()) if fees is not None else None,
            fee_status="AVAILABLE" if fees is not None else "REPLAY_REQUIRED",
            exposed_bars=int(exposures[mask].sum()), observed_bars=int(counts[mask].sum()),
            conditional_compound=conditional, annualized_return=None,
            estimand="descriptive conditional actual-period contribution; not a deployable subset price path",
            status="UNAVAILABLE_LABEL" if state == -1 else "NO_TRADE" if not exposures[mask].any() else "SUPPORTED"))
    total = float(pnl.sum())
    whole = float(np.prod(1+returns)-1) if valid.all() else None
    return dict(execution_id=path.execution_id, mode=path.mode, rows=rows, money_pnl=total,
        summed_group_pnl=float(sum(row["money_pnl"] for row in rows)), fees=float(fees.sum()) if fees is not None else None,
        fee_status="AVAILABLE" if fees is not None else "REPLAY_REQUIRED",
        compounded_path_return=whole, whole_path_sharpe="use the existing whole-calendar reducer, not mean episode Sharpe",
        observed_days=len(raw_labels), observed_span_days=path.actual_span_days,
        calendar_gaps=int(np.sum(np.diff(path.times.array())//DAY_NS-1)),
        return_status="VALID" if valid.all() else "BANKRUPT_OR_NONPOSITIVE_BASE")


def attribute_campaigns(campaigns, times_ns, labels, *, method):
    """Allocate recorded net campaign PnL; duration weights are not mark-based PnL."""
    times = calendar(times_ns)
    labels = np.asarray(labels)
    if labels.shape != times.shape or labels.dtype.kind not in "iu" or np.any(labels < -1):
        raise ValueError("one state per actual observation required")
    if method not in {"entry_state", "duration_weighted"}:
        raise ValueError("named campaign attribution method required")
    allocated = {int(k):0. for k in np.unique(labels)}
    closed, opened, total = 0, 0, 0.
    ids = set()
    for row in campaigns:
        if set(row) != {"id", "opened_ns", "end_ns", "net_pnl", "closed"} or row["id"] in ids:
            raise ValueError("authoritative unique campaign witness required")
        ids.add(row["id"])
        if (type(row["opened_ns"]) is not int or type(row["end_ns"]) is not int
                or not times[0] <= row["opened_ns"] <= row["end_ns"] <= times[-1]
                or not np.isfinite(row["net_pnl"]) or type(row["closed"]) is not bool):
            raise ValueError("campaign boundary marks and net PnL witness required")
        mask = (times >= row["opened_ns"]) & (times <= row["end_ns"])
        if not mask.any():
            raise ValueError("campaign has no observed marks")
        if method == "entry_state":
            entry = int(np.searchsorted(times,row["opened_ns"],side="right")-1)
            allocated[int(labels[entry])] += row["net_pnl"]
        else:
            # Actual elapsed holding time, not bar counts on asynchronous calendars.
            points = np.r_[row["opened_ns"], times[mask], row["end_ns"]]
            points = np.unique(points)
            if len(points) == 1:
                allocated[int(labels[np.flatnonzero(mask)[0]])] += row["net_pnl"]
            else:
                state_at_left = labels[np.clip(np.searchsorted(times, points[:-1], side="right")-1,0,len(times)-1)]
                durations = np.diff(points).astype(np.float64)
                for state in np.unique(state_at_left):
                    allocated[int(state)] += float(row["net_pnl"]*durations[state_at_left == state].sum()/durations.sum())
        total += row["net_pnl"]
        closed += int(row["closed"])
        opened += int(not row["closed"])
    return dict(method=method, monetary_unit="recorded net campaign PnL", total_net_pnl=float(total),
        allocation=allocated, allocation_sum=float(sum(allocated.values())), closed_campaigns=closed,
        censored_open_campaigns=opened, mark_attribution=False,
        explanation="entry-state or elapsed-duration attribution; daily account marks remain authoritative")
