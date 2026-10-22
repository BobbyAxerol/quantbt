"""Cold-path additions over qualified reporting observations, never execution."""

import math

import numpy as np

from quantbt.metrics.reporting import reduce_account
from quantbt.metrics.reporting.ledger import recorded_net, reduce_ledger

from .contracts import MetricValue, StatisticsPolicy, vector
from .dependence import HACPolicy, sharpe_hac
from .moments import classical_psr, moments
from .tails import expected_shortfall, lower_tail
from .uncertainty import BlockPolicy, moment_intervals


def analyze_account(observations, contract, *, partial_mask=None, witness=None,
                    policy=StatisticsPolicy(), backend="numba", hac_policy=HACPolicy(),
                    block_policy=BlockPolicy(), tail_confidence=.95):
    observations.validate_contract(contract)
    if (contract.annual_periods != policy.annual_periods or contract.variance_ddof != policy.variance_ddof
            or contract.risk_free_per_period != policy.risk_free_per_period):
        raise ValueError("reporting/statistics frequency, ddof or RF differs")
    unavailable = None
    if np.any(observations.equity <= 0):
        unavailable = ("BANKRUPT", "nonpositive account marks; log/whole-period return analysis unavailable")
    elif observations.returns is None:
        if partial_mask is None or not witness:
            unavailable = ("UNAVAILABLE", "return/partial-period witness is missing")
        else:
            observations = observations.with_derived_returns(contract, partial_mask=partial_mask, witness=witness)
    raw = reduce_account(observations, contract, backend=backend)
    if observations.returns is not None:
        returns = observations.returns
        ends = returns.end_times_ns
        if contract.sampling != "observed_daily_utc":
            unavailable = ("UNAVAILABLE", "this adapter requires qualified observed daily UTC returns")
        elif len(ends) > 1 and np.any(np.diff(ends // 86_400_000_000_000) != 1):
            unavailable = ("UNAVAILABLE", "daily calendar gap; cannot certify uniform-frequency inference")
        elif contract.partial_periods != "include_disclosed":
            unavailable = ("UNAVAILABLE", "excluded partial days require a separately qualified inference population")
        elif not unavailable:
            derived = observations.with_derived_returns(contract, partial_mask=returns.partial_mask,
                                                       witness=returns.witness).returns
            if (not np.array_equal(derived.end_times_ns, returns.end_times_ns)
                    or derived.values.shape != returns.values.shape
                    or not np.allclose(derived.values, returns.values, rtol=0., atol=1e-12)):
                raise ValueError("provided return witness does not reconcile with the qualified account path")
    if unavailable:
        status, reason = unavailable
        metrics = {name: MetricValue("mode5.daily."+name, "probability" if name in {"psr", "hac_evidence"}
            else "decimal_return" if name == "loss_es" else "ratio", 0, status=status, reason=reason).to_metadata()
            for name in ("sharpe_period", "sharpe_annual", "psr", "hac_evidence", "loss_es")}
        return {"raw_reporting": raw.to_metadata(), "status": status, "reason": reason,
                "derived": metrics, "moments": None, "moment_uncertainty": None}
    values = observations.returns.values
    observed = moments(values, policy=policy, backend=backend)
    psr = classical_psr(observed)
    hac = sharpe_hac(values, policy=hac_policy, risk_free_per_period=policy.risk_free_per_period)
    period = MetricValue("mode5.daily.sharpe_period", "original_period_ratio", len(values),
        observed.sharpe_period, observed.status, observed.reason)
    annual = MetricValue("mode5.daily.sharpe_annual", "annual_ratio", len(values),
        observed.sharpe_period * math.sqrt(policy.annual_periods) if observed.status == "VALID" else None,
        observed.status, observed.reason)
    es = expected_shortfall(-values, tail_confidence)
    return {"raw_reporting": raw.to_metadata(), "status": "ANALYZED", "reason": None,
        "statistics_policy_identity": policy.identity, "moments": observed.to_metadata(),
        "daily_count": len(values), "partial_days": int(observations.returns.partial_mask.sum()),
        "derived": {name: value.to_metadata() for name, value in
            (("sharpe_period", period), ("sharpe_annual", annual), ("psr", psr), ("hac_evidence", hac), ("loss_es", es))},
        "moment_uncertainty": moment_intervals(values, policy=block_policy, statistics_policy=policy),
        "inference_scope": "fixed qualified path; no multiplicity/selection adjustment"}


def analyze_campaigns(observations, contract, *, backend="numba", tail_alpha=.25):
    if contract.unit != "closed_trade" or contract.matching != "position_episode":
        raise ValueError("closed position campaigns require explicit position-episode ledger contract")
    report = reduce_ledger(observations, contract, backend=backend)
    count = report.metric("closed_trade.closed_count")
    if count.status != "valid":
        return {"status": "UNAVAILABLE", "reason": count.reason, "raw_reporting": report.to_metadata(),
                "moments": None, "pnl_tail": None}
    selected = [row for row in observations.records if row.closed_at_ns is not None
        and contract.baseline_time_ns <= row.closed_at_ns <= contract.scope_end_ns]
    values = [recorded_net(row, contract.slippage_basis) for row in selected]
    observed = moments(values, backend=backend, population="closed_campaign_pnl")
    tail = lower_tail(values, tail_alpha, unit=contract.currency) if values else MetricValue(
        "mode5.campaign.net_pnl_tail", contract.currency, 0, status="INSUFFICIENT", reason="no closed campaigns")
    return {"status": "ANALYZED", "raw_reporting": report.to_metadata(),
            "closed_campaigns": len(values), "moments": observed.to_metadata(),
            "pnl_tail": tail.to_metadata(),
            "psr": MetricValue("mode5.campaign.psr", "probability", len(values),
                status="UNAVAILABLE", reason="currency PnL is not a qualified return series").to_metadata()}


def partition_pnl(equity, *, initial_equity, block_ends):
    values = vector(equity)
    ends = tuple(block_ends)
    if (not len(values) or not np.isfinite(values).all() or not math.isfinite(initial_equity)
            or initial_equity <= 0 or not ends or ends[-1] != len(values)-1
            or any(type(end) is not int or end < 0 for end in ends)
            or any(a >= b for a, b in zip(ends, ends[1:]))):
        raise ValueError("complete ordered non-overlapping partition and scope-entry equity required")
    rows, previous, start = [], float(initial_equity), 0
    for end in ends:
        terminal = float(values[end])
        rows.append({"start": start, "end": end, "pre_block_equity": previous,
            "terminal_equity": terminal, "money_pnl": terminal-previous,
            "simple_return": terminal/previous-1 if previous > 0 else None,
            "return_status": "VALID" if previous > 0 else "BANKRUPT"})
        previous, start = terminal, end+1
    return tuple(rows)


def separate_score_channels(record, *, raw_formula_id, objective_formula_id):
    if not raw_formula_id or not objective_formula_id or raw_formula_id == objective_formula_id:
        raise ValueError("raw and objective formulas must have separate identities")
    result = {"raw_formula_id": raw_formula_id, "objective_formula_id": objective_formula_id}
    for name, key in (("raw_sharpe", "raw_sharpe"), ("penalized_objective", "objective")):
        value = record.get(key)
        available = isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
        result[name] = {"value": value if available else None,
            "status": "VALID" if available else "REPLAY_REQUIRED",
            "reason": None if available else "explicit raw scientific channel missing; cannot invert a summary penalty"}
    return result


def summary_availability(record, requested):
    required = {"psr": ("returns", "frequency", "metric_contract"),
        "hac": ("returns", "frequency", "metric_contract", "observation_order"),
        "daily_tail": ("returns", "metric_contract"),
        "campaign_tail": ("closed_campaigns", "metric_contract")}
    if requested not in required:
        raise ValueError("unknown requested statistic")
    missing = [key for key in required[requested] if record.get(key) is None]
    return {"status": "REPLAY_REQUIRED" if missing else "INPUTS_PRESENT_UNVERIFIED", "value": None,
        "missing": missing, "action": "verify retained paths/source first; only then register missing targeted replay"}
