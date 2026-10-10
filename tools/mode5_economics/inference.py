"""Paired common-date blocks; fixed-path uncertainty never claims recipe validity."""
from dataclasses import asdict
import math

import numpy as np

from quantbt.mode5.statistics.moments import moments
from .contracts import EconomicProtocol
from .measurement import account_summary, fixed_decay


def _annual_sr(values, periods):
    estimate = moments(values)
    return None if estimate.status != "VALID" else estimate.sharpe_period*math.sqrt(periods)


def _paired_indices(n, policy, rng):
    starts = rng.integers(0, n, size=(n + policy.block_days - 1)//policy.block_days)
    return ((starts[:, None] + np.arange(policy.block_days)) % n).reshape(-1)[:n]


def paired_economics(development_base, development_new, forward_base, forward_new, *, protocol, origins):
    if not isinstance(protocol, EconomicProtocol) or type(origins) is not int or origins != 1:
        raise ValueError("one paired horizon is exactly one origin; it cannot claim multiple qualified origins")
    accounts = (development_base, development_new, forward_base, forward_new)
    for first in (0, 2):
        a, b = accounts[first:first+2]
        if (not np.array_equal(a.times, b.times) or a.economic_contract != b.economic_contract
                or a.terminal_policy != b.terminal_policy):
            raise ValueError("same calendar, account/cost and terminal policy required; no inner join")
    if development_base.times[-1] >= forward_base.times[0]:
        raise ValueError("chronological disjoint windows required")
    for i in (0, 1):
        if accounts[i].params_digest != accounts[i+2].params_digest:
            raise ValueError("each recipe must keep its actual fixed vector across forward horizon")
    summary = [account_summary(a, annual_periods=protocol.annual_periods) for a in accounts]
    base = dict(version="mode5.paired_economics.v1", protocol=asdict(protocol), protocol_id=protocol.identity,
        interval_scope="FIXED_PATH_NOT_SAMPLER_RECIPE_UNCERTAINTY", origins=origins,
        whole_procedure_validation=False, deployment_authorized=False,
        primary_unit="decimal_net_account_per_day", primary_family_policy="Bonferroni across registered alpha mean contrasts",
        secondary_interval_policy="marginal intervals, not simultaneous coverage of all metrics",
        marginal_confidence=protocol.marginal_confidence, paths=[a.identity for a in accounts],
        summary=summary, observed=None, intervals=None, support=None)
    if any(s["status"] != "VALID" for s in summary):
        return base | dict(status="INVALID_NOT_EVALUABLE", reason="nonfinite/insolvent/unverified actual path", invalid_draws=0)
    a, b, c, d = summary
    delta_is = None if a["annualized_sharpe"] is None or b["annualized_sharpe"] is None else b["annualized_sharpe"]-a["annualized_sharpe"]
    delta_fwd = None if c["annualized_sharpe"] is None or d["annualized_sharpe"] is None else d["annualized_sharpe"]-c["annualized_sharpe"]
    observed = dict(forward_mean_net_change=d["mean_daily_net"]-c["mean_daily_net"],
        development_sharpe_change=delta_is, forward_sharpe_change=delta_fwd,
        decay_change=None if delta_is is None or delta_fwd is None else delta_is-delta_fwd)
    gaps = []
    for i, account in enumerate(accounts):
        required_days = protocol.development_days if i < 2 else protocol.forward_days
        for name, value, required in (("days", len(account.returns), required_days),
                ("fills", account.fills, protocol.minimum_fills),
                ("campaigns", account.campaigns, protocol.minimum_campaigns)):
            if value is None or value < required:
                gaps.append(dict(path=i, field=name, observed=value, required=required))
    if origins < protocol.minimum_origins:
        gaps.append(dict(field="qualified_origins", observed=origins, required=protocol.minimum_origins))
    support = dict(status="ADEQUATE_REGISTERED_SUPPORT" if not gaps else "INSUFFICIENT_EVIDENCE", gaps=gaps)
    rows = [x.returns for x in accounts]
    ndev, nfwd = len(rows[0]), len(rows[2])
    if min(ndev, nfwd) < max(32, 2*protocol.block_days):
        return base | dict(observed=observed, support=support, status="INCONCLUSIVE",
                           reason="insufficient block duration", invalid_draws=0)
    rng = np.random.default_rng(protocol.seed)
    mean_draws, sr_draws, decay_draws, invalid = [], [], [], 0
    for _ in range(protocol.draws):
        dev_ids, fwd_ids = _paired_indices(ndev, protocol, rng), _paired_indices(nfwd, protocol, rng)
        sampled = (rows[0][dev_ids], rows[1][dev_ids], rows[2][fwd_ids], rows[3][fwd_ids])
        mean_draws.append(math.fsum(float(v/len(sampled[3])) for v in sampled[3])
                          - math.fsum(float(v/len(sampled[2])) for v in sampled[2]))
        sr = [_annual_sr(x, protocol.annual_periods) for x in sampled]
        if any(v is None for v in sr):
            invalid += 1
        else:
            sr_draws.append(sr[3]-sr[2])
            decay_draws.append((sr[1]-sr[3])-(sr[0]-sr[2]))
    q = [(1-protocol.marginal_confidence)/2, (1+protocol.marginal_confidence)/2]
    def bounds(values):
        return tuple(float(x) for x in np.quantile(values, q, method="linear"))
    intervals = dict(forward_mean_net_change=bounds(mean_draws),
        forward_sharpe_change=None if invalid else bounds(sr_draws), decay_change=None if invalid else bounds(decay_draws))
    mean_lo, mean_hi = intervals["forward_mean_net_change"]
    mean_evidence = ("WHOLLY_HARMFUL_MEAN" if mean_hi < 0 else
        "EXCLUDES_REGISTERED_MEAN_HURDLE" if mean_hi < protocol.mean_hurdle_daily else
        "EXCEEDS_REGISTERED_MEAN_HURDLE" if mean_lo > protocol.mean_hurdle_daily else
        "MEAN_INTERVAL_CROSSES_HURDLE")
    if gaps or invalid or observed["decay_change"] is None:
        status, reason = "INCONCLUSIVE", "support or SR interval unavailable; no conditioning on surviving draws"
    elif intervals["forward_mean_net_change"][0] > protocol.mean_hurdle_daily and intervals["forward_sharpe_change"][0] >= 0 and intervals["decay_change"][1] < 0:
        status, reason = "POSITIVE_WITHIN_REGISTERED_SCOPE", "net hurdle plus forward quality and decay pass jointly"
    elif intervals["forward_mean_net_change"][1] < protocol.mean_hurdle_daily:
        status, reason = "NEGATIVE_WITHIN_REGISTERED_SCOPE", "upper bound excludes registered meaningful net improvement"
    else:
        status, reason = "INCONCLUSIVE", "joint meaningful improvement not established"
    return base | dict(observed=observed, intervals=intervals, support=support, status=status, reason=reason,
        fixed_path_mean_evidence=mean_evidence,
        invalid_draws=invalid, decay_baseline=fixed_decay(accounts[0], accounts[2], annual_periods=protocol.annual_periods),
        decay_challenger=fixed_decay(accounts[1], accounts[3], annual_periods=protocol.annual_periods),
        lower_is_only_does_not_establish_forward_gain=observed["forward_mean_net_change"] <= 0)
