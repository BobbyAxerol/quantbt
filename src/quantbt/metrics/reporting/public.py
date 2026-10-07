"""Adapt completed results on demand; never infer execution or retain trial state."""

from dataclasses import dataclass

from .account import reduce_account
from .adapters import account_from_completed
from .execution import ExecutionObservations, reduce_execution
from .ledger import reduce_ledger
from .ledger_inputs import LedgerObservations
from .request import ReportingRequest


@dataclass(frozen=True)
class CompletedReport:
    request: ReportingRequest
    groups: tuple
    unavailable: tuple

    def to_metadata(self):
        groups = {name: dict(status="available", **report.to_metadata()) for name, report in self.groups}
        groups.update({name: dict(status="unavailable", reason=reason, metrics=[])
                       for name, reason in self.unavailable})
        return dict(reporting_version=self.request.account.version,
                    result_identity=self.request.result_identity,
                    contract=self.request.account.to_metadata(), groups=groups)


def build_completed_report(result, request, *, scope="auto"):
    if not isinstance(request, ReportingRequest):
        raise TypeError("reporting must be a ReportingRequest")
    if scope not in {"auto", request.account.scope}:
        raise ValueError("reporting contract owns exact scope; do not apply legacy OOS/auto slicing")
    groups, unavailable = [], []

    def reduce(kind, observations, contract, **options):
        if request.cache is not None:
            return request.cache.reduce(kind, observations, contract, **options)
        reducer = {"account": reduce_account, "ledger": reduce_ledger, "execution": reduce_execution}[kind]
        return reducer(observations, contract, **options)

    try:
        obs = account_from_completed(result, request.account, result_identity=request.result_identity,
            profile=request.profile, index=request.index, naive_timezone=request.naive_timezone,
            partial_mask=request.partial_mask, return_witness=request.return_witness)
    except LookupError as error:
        unavailable.append(("account_period", str(error)))
    else:
        groups.append(("account_period", reduce("account", obs, request.account,
            backend=request.backend, retain_episodes=request.retain_episodes)))
    contracts = {contract.unit: contract for contract in request.ledger_contracts}
    for unit in ("closed_trade", "closed_action"):
        if request.ledger is None or unit not in contracts:
            unavailable.append((unit, "recorded outcome ledger, completeness and matching/grouping contract required"))
        else:
            if not isinstance(request.ledger, LedgerObservations):
                raise TypeError("ledger must be immutable LedgerObservations, not signals/fills to replay")
            if request.ledger.coverage.result_identity != request.result_identity:
                raise ValueError("ledger witness belongs to a different completed result")
            groups.append((unit, reduce("ledger", request.ledger, contracts[unit], backend=request.backend)))
    if request.execution is None:
        unavailable.append(("execution", "recorded aggregate/path execution witness required; no inference from targets"))
    else:
        if not isinstance(request.execution, ExecutionObservations):
            raise TypeError("execution must be ExecutionObservations")
        if request.execution.coverage.result_identity != request.result_identity:
            raise ValueError("execution witness belongs to a different completed result")
        groups.append(("execution", reduce("execution", request.execution, request.account)))
    return CompletedReport(request=request, groups=tuple(groups), unavailable=tuple(unavailable))


def reporting_metadata(result, request, *, scope="auto"):
    return build_completed_report(result, request, scope=scope).to_metadata()


def format_reporting_report(report):
    """Fixed alignment, explicit population, status and units; no scientific aliases."""
    contract = report["contract"]
    lines = [f"Reporting V1 | {contract['currency']} | {contract['scope']} | {contract['sampling']}",
             f"Clock: {contract['equity_clock']} | annual periods: {contract['annual_periods']:g}"]
    for name in ("account_period", "execution", "closed_trade", "closed_action"):
        group = report["groups"][name]
        lines.extend(["", name.replace("_", " ").title()])
        if group["status"] == "unavailable":
            lines.append("  N/A: " + group["reason"])
            continue
        for metric in group["metrics"]:
            label = metric["metric_id"].removeprefix("reporting.")
            if metric["status"] != "valid":
                value = "No Loss" if metric["status"] == "no_loss" else "N/A"
                detail = f" [{metric['status']}: {metric['reason']}]"
            else:
                percent = (label in {"account.total_return", "account.cagr_elapsed", "period.cagr_period_count",
                    "period.mean_arithmetic", "period.mean_geometric", "period.avg_win", "period.avg_loss",
                    "period.win_rate", "period.nonzero_win_rate"} or label.endswith(".win_rate")
                    or label.startswith("drawdown.") and metric["unit"] == "ratio")
                value = format_metric_value(metric["value"], "fraction" if percent else metric["unit"], contract["currency"])
                detail = f" [n={metric['sample_count']}]"
            lines.append(f"  {label:<44} {value:>20}{detail}")
    return "\n".join(lines)


def format_metric_value(value, unit, currency):
    if unit == "nanoseconds":
        return f"{value / 3_600_000_000_000:.3f} h ({value / 86_400_000_000_000:.3f} d)"
    if unit == "fraction":
        return f"{value * 100:.3f}%"
    if unit == currency:
        return f"{value:,.4f} {currency}"
    if unit in {"count", "bars"}:
        return f"{value:,.0f}"
    return f"{value:,.6g} {unit}"


def plot_completed_report(result, request, *, scope="auto", theme="dark", figsize=(14, 6)):
    from .plot import plot_reporting_account
    return plot_reporting_account(result, request, scope=scope, theme=theme, figsize=figsize)
