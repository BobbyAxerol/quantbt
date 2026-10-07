"""Account-period statistics under ReportingContractV1, independent of WFO scores."""

from functools import lru_cache
import json
import math

import numpy as np

from .drawdown import DAY_NS, scan_drawdown
from .results import MetricBuilder, ReportingResult


PERIOD_KEYS = ("count", "mean_arithmetic", "mean_geometric", "sharpe", "sortino", "omega",
               "profit_factor", "avg_win", "avg_loss", "win_rate", "nonzero_win_rate", "cagr_period_count")


def _period_scan(values, annual, ddof, rf, mar, omega, conditional):
    n = len(values)
    mean, m2, gain, loss, downside, og, ol, log_growth = 0., 0., 0., 0., 0., 0., 0., 0.
    wins, losses, negatives = 0, 0, 0
    geometric_valid = True
    for i in range(n):
        x = values[i]
        delta = x - mean
        mean += delta / (i + 1)
        m2 += delta * (x - mean)
        if x > 0:
            wins += 1
            gain += x
        if x < 0:
            losses += 1
            loss -= x
        if x < mar:
            negatives += 1
            downside += (x - mar) ** 2
        og += max(x - omega, 0.)
        ol += max(omega - x, 0.)
        if x <= -1:
            geometric_valid = False
        else:
            log_growth += math.log1p(x)
    variance = m2 / (n - ddof) if n > ddof else 0.
    denominator = negatives if conditional else n
    rms = math.sqrt(downside / denominator) if denominator else 0.
    return np.array((n, mean, math.expm1(log_growth / n) if geometric_valid and n else np.nan,
        (mean - rf) / math.sqrt(variance) * math.sqrt(annual) if variance > 0 else np.nan,
        (mean - mar) / rms * math.sqrt(annual) if rms else np.inf if mean > mar else np.nan,
        og / ol if ol else np.inf if og else np.nan,
        gain / loss if loss else np.inf if gain else np.nan,
        gain / wins if wins else np.nan, -loss / losses if losses else np.nan,
        wins / n if n else np.nan, wins / (wins + losses) if wins + losses else np.nan,
        np.expm1(log_growth * annual / n) if geometric_valid and n else np.nan,
        float(wins), float(losses)))


@lru_cache(maxsize=1)
def _compiled_period():
    from numba import njit
    return njit(cache=False, fastmath=False)(_period_scan)


def reduce_account(observations, contract, *, backend="python", retain_episodes=False):
    observations.validate_contract(contract)
    summary, episodes = scan_drawdown(observations, contract, backend=backend, retain_episodes=retain_episodes)
    builder = MetricBuilder(contract, observations.coverage)
    n = len(observations.equity)
    growth = observations.equity[-1] / contract.baseline_equity
    days = (int(observations.times_ns[-1]) - contract.baseline_time_ns) / DAY_NS
    builder.add("account.total_return", growth - 1., count=n)
    builder.add("account.final_equity", observations.equity[-1], unit=contract.currency, count=n)
    builder.add("account.elapsed_days", days, unit="elapsed_days", count=n)
    cagr = None
    cagr_status, cagr_reason = "undefined", "nonpositive terminal growth"
    if growth > 0:
        if days >= contract.min_cagr_days and days > 0:
            with np.errstate(over="ignore"):
                cagr = float(np.expm1(math.log(growth) * contract.calendar_year_days / days))
            cagr_status, cagr_reason = "valid", None
        else:
            cagr_status, cagr_reason = "insufficient", "elapsed sample below declared minimum CAGR horizon"
    builder.add("account.cagr_elapsed", cagr, count=n, status=cagr_status, reason=cagr_reason)
    dd_keys = ("max_depth", "mean_underwater_depth", "mean_episode_depth", "mean_recovered_duration_ns",
               "longest_recovered_duration_ns", "current_open_duration_ns", "ulcer_index", "longest_duration_ns", "episode_count")
    for name, value in zip(dd_keys, summary):
        unit = "nanoseconds" if name.endswith("_ns") else "count" if name == "episode_count" else "ratio"
        counts = {"mean_underwater_depth": summary[15], "mean_episode_depth": summary[8],
                  "mean_recovered_duration_ns": summary[9], "longest_recovered_duration_ns": summary[9],
                  "current_open_duration_ns": int(summary[8] > summary[9]), "longest_duration_ns": summary[8],
                  "episode_count": summary[8]}
        builder.add("drawdown." + name, float(value) if np.isfinite(value) else None, unit=unit, count=int(counts.get(name, n)))
    for name, value, unit in (("deepest_duration_ns", summary[12], "nanoseconds"),
                               ("mean_all_episode_duration_ns", summary[13], "nanoseconds"),
                               ("last_observed_depth", summary[14], "ratio"),
                               ("recovered_episode_count", summary[9], "count")):
        builder.add("drawdown." + name, float(value) if np.isfinite(value) else None, unit=unit,
                    count=1 if name == "last_observed_depth" else int(summary[8]))
    r = observations.returns
    retained = 0
    period_cagr = None
    if r is None:
        for name in PERIOD_KEYS:
            builder.add("period." + name, status="unavailable", reason="explicit return/partial-period witness missing")
    else:
        values = r.values if contract.partial_periods == "include_disclosed" else r.values[~r.partial_mask]
        retained = len(values)
        if not retained:
            for name in PERIOD_KEYS:
                if name == "count":
                    builder.add("period.count", 0., unit="count")
                else:
                    builder.add("period." + name, status="insufficient", reason="no retained observed periods")
        else:
            kernel = _period_scan if backend == "python" else _compiled_period()
            stats = kernel(values, contract.annual_periods, contract.variance_ddof,
                           contract.risk_free_per_period, contract.mar_per_period,
                           contract.omega_threshold_per_period,
                           contract.sortino_denominator == "negative_observations")
            period_cagr = float(stats[11]) if np.isfinite(stats[11]) else None
            for name, value in zip(PERIOD_KEYS, stats):
                samples = int(stats[12]) if name == "avg_win" else int(stats[13]) if name == "avg_loss" else int(stats[12] + stats[13]) if name == "nonzero_win_rate" else retained
                if np.isposinf(value) and name in {"profit_factor", "omega", "sortino"}:
                    builder.add("period." + name, count=samples, status="no_loss", reason="zero loss/downside denominator")
                else:
                    builder.add("period." + name, float(value) if np.isfinite(value) else None,
                                unit="count" if name == "count" else "ratio", count=samples,
                                status="invalid" if np.isinf(value) else None,
                                reason="numeric overflow" if np.isinf(value) else None)
    cagr_for_calmar = cagr if contract.cagr_basis == "elapsed_calendar" else period_cagr
    builder.add("account.calmar", cagr_for_calmar / summary[0] if cagr_for_calmar is not None and summary[0] > 0 else None, count=n)
    metadata = dict(contract=contract.to_metadata(), backend=backend,
                    baseline_source="caller-declared authoritative scope-entry valuation",
                    return_witness=r.witness if r is not None else None,
                    partial_periods=int(r.partial_mask.sum()) if r is not None else None,
                    observed_periods=len(r.values) if r is not None else 0, retained_periods=retained,
                    drawdown_clock=contract.equity_clock, unseen_extrema_certified=False,
                    deepest_episode_index=int(summary[10]), longest_episode_index=int(summary[11]),
                    episode_detail_retained=retain_episodes,
                    observation_population="all supplied marks; engine retention completeness is not inferred",
                    recovered_duration_mean_excludes_open=True, all_episode_duration_mean_includes_censored=True,
                    native_v1_reducer="NOT_IMPLEMENTED; native_metric_v2 has a different scientific contract")
    return ReportingResult(contract_identity=builder.contract_identity, input_identity=observations.identity,
                           metrics=tuple(builder.metrics), episodes=episodes,
                           provenance_json=json.dumps(metadata, sort_keys=True, allow_nan=False))


def reduce_independent_segments(segments, *, backend="python", retain_episodes=False):
    """Keep separately executed scopes separate; do not invent continuous equity."""
    results, previous_end = [], None
    for observations, contract in segments:
        if contract.disjoint_scope != "independent_segments":
            raise ValueError("independent segment reporting must be explicitly declared")
        if previous_end is not None and contract.baseline_time_ns <= previous_end:
            raise ValueError("segments must be ordered and non-overlapping")
        results.append(reduce_account(observations, contract, backend=backend, retain_episodes=retain_episodes))
        previous_end = contract.scope_end_ns
    if not results:
        raise ValueError("nonempty independently valued segments required")
    return tuple(results)
