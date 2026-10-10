"""Reduce original retained finance once; never derive synthetic executions."""
from hashlib import sha256
import math

import numpy as np
import pandas as pd

from ..metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from ..metrics.reporting import AccountObservations, reduce_account
from .statistics.contracts import MetricValue, StatisticsPolicy
from .statistics.moments import moments, classical_psr
from .statistics.tails import expected_shortfall
from .selection.objectives import economic_utility


def array_identity(values):
    a = np.ascontiguousarray(values, dtype=np.float64)
    h = sha256(str(a.shape).encode())
    h.update(memoryview(a).cast("B"))
    return h.hexdigest()


class Mode5MetricPolicy:
    def __init__(self, calibration):
        self.calibration = calibration
        self.policy = calibration.binding.data["metrics"]
        self.evaluations = 0

    def observe(self, result, index):
        if hasattr(result, "accounting"):
            a = result.accounting
            equity = pd.Series(a.equity, index=a.datetime_index)
        else:
            equity = getattr(result, "equity", None)
        if equity is None or not equity.index.equals(index):
            raise ValueError("original complete account path required; no score-placeholder replay")
        self.evaluations += 1
        p = self.policy
        times = index.asi8
        marks = equity.to_numpy(dtype=float)
        account_id = array_identity(marks)
        contract = ReportingContractV1(scope="full", unit="account_period", currency=p["currency"],
            baseline_equity=float(result.initial_capital), baseline_time_ns=int(times[0])-p["bar_interval_ns"],
            scope_end_ns=int(times[-1]), sampling="observed_daily_utc", annual_periods=p["annual_periods"],
            equity_clock="bar_close")
        coverage = ReportingCoverageV1(result_identity=account_id, producer="original WFO endpoint account",
            profile="compact", ledger="unsupported", retained_rows=0, dropped_rows=0,
            reason="account inference does not manufacture campaign attribution")
        days = times // 86_400_000_000_000
        counts = np.unique(days, return_counts=True)[1]
        partial = counts * p["bar_interval_ns"] != 86_400_000_000_000
        obs = AccountObservations(times_ns=times, equity=marks, coverage=coverage)
        bankrupt = bool(np.any(marks <= 0))
        if not bankrupt:
            obs = obs.with_derived_returns(contract, partial_mask=partial,
                witness="observed UTC buckets; partial counts disclosed; first mark includes costs")
        raw = reduce_account(obs, contract, backend="numba")
        values = np.array([]) if bankrupt else obs.returns.values
        n = len(values)
        statistics = moments(values, policy=StatisticsPolicy(annual_periods=p["annual_periods"]))
        psr = classical_psr(statistics)
        es = expected_shortfall(-values, p["tail_confidence"])
        ret = raw.metric("account.total_return").value
        dd = raw.metric("drawdown.max_depth").value
        reason = "nonpositive account marks" if bankrupt else "undefined return or tail" if ret is None or dd is None or es.value is None else None
        def metric(name, value):
            return MetricValue("mode5.public."+name, "decimal_return", n, value)
        utility = economic_utility(metric("net_return", ret), metric("drawdown", dd), metric("es", es.value),
            dd_weight=p["dd_weight"], tail_weight=p["tail_weight"], preference_id=self.calibration.binding.identity) if reason is None else MetricValue(
                "mode5.utility.net_v1", "decimal_return", n, status="BANKRUPT" if bankrupt else "UNDEFINED", reason=reason)
        # Explicit executed closed records are not relabeled as closed actions
        # or strategy campaigns. Missing ledgers cannot satisfy a positive gate.
        trades = tuple(getattr(result, "trades", ()))
        closed = sum(getattr(t, "closed_at", None) is not None for t in trades)
        raw_sharpe = statistics.sharpe_period * math.sqrt(p["annual_periods"]) if statistics.status == "VALID" else None
        finance = {"equity": account_id}
        for name in ("positions", "fees", "funding", "margin"):
            item = getattr(result, name, None)
            if item is not None:
                finance[name] = array_identity(item.to_numpy() if hasattr(item, "to_numpy") else item)
        return dict(schema="quantbt.mode5.observation.v1", account_identity=account_id, finance=finance,
            metric_contract=contract.identity, daily_returns=values.tolist(), daily_count=n,
            partial_days=int(partial.sum()), raw_sharpe=raw_sharpe,
            utility=utility.to_metadata(), psr=psr.to_metadata(), net_return=ret,
            max_drawdown=dd, daily_loss_es=es.value, closed_records=closed,
            closed_record_unit="engine_closed_records_not_closed_actions_or_inferred_campaigns",
            support_pass=n >= p["min_daily_returns"] and closed >= p["min_closed_records"],
            risk_pass=not bankrupt and dd is not None and dd <= p["max_drawdown"],
            quality_pass=utility.value is not None and utility.value >= p["min_utility"],
            liquidated=bool(getattr(result, "liquidated", False)),
            execution_backend=result.metadata.get("backend"),
            execution_contract=result.metadata.get("execution_contract"),
            initial_capital=float(result.initial_capital), final_equity=float(marks[-1]))

    def score(self, result, index):
        row = self.observe(result, index)
        return dict(sharpe=row["raw_sharpe"] or 0., turnover=float(row["closed_records"]),
            trade_count=float(row["closed_records"]), mean_return=row["net_return"] or 0.,
            volatility=0., max_drawdown_pct=100*(row["max_drawdown"] or 0.),
            mode5_observation=row)
