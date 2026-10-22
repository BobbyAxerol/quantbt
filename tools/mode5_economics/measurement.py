"""Original-frequency measurement and decay; never repairs an engine path."""
import math

import numpy as np

from quantbt.mode5.statistics.moments import moments, classical_psr
from quantbt.mode5.statistics.tails import expected_shortfall


def account_summary(account, *, annual_periods=365.):
    if not math.isfinite(annual_periods) or annual_periods <= 0:
        raise ValueError("positive common annual frequency required")
    values = account.returns
    base = dict(days=len(values), execution_id=account.execution_id, params_digest=account.params_digest,
                accounting_verified=account.accounting_verified, fills=account.fills, campaigns=account.campaigns,
                mean_daily_net=None, mean_daily_log_growth=None, annualized_sharpe=None, psr=None,
                daily_loss_es=None, annual_periods=annual_periods)
    if not account.accounting_verified or not np.isfinite(values).all():
        return base | dict(status="INVALID", reason="unverified accounting or nonfinite path; no row dropping")
    if np.any(values <= -1):
        return base | dict(status="BANKRUPT", reason="insolvent daily path; no survivor conditioning")
    estimate = moments(values)
    mean = math.fsum(float(v/len(values)) for v in values)
    return base | dict(status="VALID", reason=None, mean_daily_net=mean,
        mean_daily_log_growth=float(np.mean(np.log1p(values))),
        annualized_sharpe=None if estimate.status != "VALID" else estimate.sharpe_period*math.sqrt(annual_periods),
        sharpe_status=estimate.status, sharpe_reason=estimate.reason,
        psr=classical_psr(estimate).to_metadata(), daily_loss_es=expected_shortfall(-values, .95).to_metadata())


def profit_factor(closed_net_pnl, *, minimum_campaigns, currency="USDT"):
    if type(minimum_campaigns) is not int or minimum_campaigns < 1 or not currency:
        raise ValueError("frozen positive campaign threshold and currency required")
    if closed_net_pnl is None:
        return dict(status="UNAVAILABLE", reason="accepted closed-campaign ledger unavailable", value=None,
                    gross_profit=None, gross_loss=None, closed_campaigns=None, currency=currency)
    values = np.asarray(closed_net_pnl, dtype=np.float64)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("finite closed net campaign PnL required; fills are not campaigns")
    try:
        gp = float(math.fsum(float(v) for v in values if v > 0))
        gl = float(math.fsum(-float(v) for v in values if v < 0))
    except OverflowError:
        return dict(status="INVALID", reason="campaign aggregation overflow", value=None,
                    gross_profit=None, gross_loss=None, closed_campaigns=len(values), currency=currency)
    base = dict(value=None, gross_profit=gp, gross_loss=gl, closed_campaigns=len(values), currency=currency,
                population="actual_closed_net_campaigns")
    if len(values) < minimum_campaigns:
        return base | dict(status="INSUFFICIENT", reason="closed-campaign support below registration")
    if gp == 0 or gl == 0:
        return base | dict(status="UNDEFINED", reason="strictly positive GP and GL required for finite positive PF/log decay")
    value = gp / gl
    if not math.isfinite(value) or value <= 0:
        return base | dict(status="INVALID", reason="profit-factor arithmetic overflow/underflow")
    return base | dict(status="VALID", reason=None, value=value)


def fixed_decay(development, forward, *, development_pf=None, forward_pf=None, annual_periods=365.):
    if (development.params_digest != forward.params_digest
            or development.economic_contract != forward.economic_contract
            or development.terminal_policy != forward.terminal_policy):
        raise ValueError("same actual fixed vector, costs/account and terminal contract required")
    if development.times[-1] >= forward.times[0]:
        raise ValueError("chronologically disjoint development/forward windows required")
    a, b = (account_summary(x, annual_periods=annual_periods) for x in (development, forward))
    def difference(name):
        return None if a[name] is None or b[name] is None else a[name] - b[name]
    pf = None
    if development_pf and forward_pf:
        if development_pf["currency"] != forward_pf["currency"]:
            raise ValueError("common currency required for campaign PF comparison")
        if development_pf["status"] == forward_pf["status"] == "VALID":
            pf = math.log(development_pf["value"]) - math.log(forward_pf["value"])
    return dict(version="mode5.fixed_vector_decay.v1", development=a, forward=b,
        sharpe_decay=difference("annualized_sharpe"), mean_return_decay=difference("mean_daily_net"),
        log_growth_decay=difference("mean_daily_log_growth"), log_profit_factor_decay=pf,
        pf_development=development_pf, pf_forward=forward_pf, ratio_not_used=True,
        units=dict(sharpe="annualized_daily_ratio", mean_return="decimal_account_per_day",
                   log_growth="log_account_growth_per_day", pf="log_closed_net_campaign_pf"))


def cost_margin(*, incremental_one_way_fee, position_turnover_per_day, account_allocation):
    values = (incremental_one_way_fee, position_turnover_per_day, account_allocation)
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("finite nonnegative one-way fee, position turnover and account allocation required")
    result = math.prod(values)
    if not math.isfinite(result):
        raise ValueError("cost margin overflow")
    return dict(decimal_account_per_day=result, bps_account_per_day=result*10000,
                definition="incremental_one_way_fee * position_turnover * account_allocation",
                already_in_net_returns_not_deducted_twice=True,
                business_hurdle_is_separate_preference=True)
