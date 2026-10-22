"""Sealed-cell ingestion and dependent calendar attribution, never execution.

Pins must come from the original retained inventory, not be minted from the
files being ingested. An opaque execution key is retained, not reconstructed.
This helper certifies neither six matrices nor a completed empirical battery.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import numpy as np

from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations, ReturnObservations, reduce_account
from quantbt.metrics.reporting.drawdown import scan_drawdown
from quantbt.metrics.reporting.results import ReportingResult
from quantbt.mode5.artifacts import file_identity
from tools.mode5_diagnostics.evidence import FrozenBuffer
from tools.mode5_diagnostics.identity import canonical, digest
from tools.mode5_selection.objectives import economic_utility
from tools.mode5_statistics.analysis import partition_pnl
from tools.mode5_statistics.contracts import MetricValue
from tools.mode5_statistics.tails import expected_shortfall

from .protocol import ResearchProtocol

DAY_NS = 86_400_000_000_000
HOUR_NS = DAY_NS // 24
UNAVAILABLE_CAMPAIGNS = "no sealed campaign ledger; fills/close positions are not independent campaigns"


def _ns(value):
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    if date.utcoffset().total_seconds() != 0:
        raise ValueError("UTC calendar required")
    delta = date - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def _read(pin):
    if file_identity(pin["path"]) != dict(pin):
        raise ValueError("sealed artifact identity mismatch")
    data = Path(pin["path"]).read_bytes()
    if len(data) != pin["bytes"] or sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("sealed artifact changed during ingestion")
    return data


def _json(pin):
    value = json.loads(_read(pin))
    canonical(value)
    return value


@dataclass(frozen=True)
class CandidateProvenance:
    study_id: str
    diagnostic_revision: str
    alpha_id: str
    candidate_id: str
    raw_params_digest: str
    effective_params_digest: str
    branch_id: str
    trial_refs: tuple[int, ...]
    execution_id: str
    design_id: str
    symbol: str
    data_role: str
    outcome_timing_disclosure: str
    warmup_start_ns: int
    data_cutoff_ns: int
    artifact_creation_cutoff_ns: int
    knowledge_cutoff_ns: int
    actual_route: str
    evidence_refs: tuple[tuple[str, str], ...]
    chronology_claim: str = "current-knowledge retrospective attribution, not historical calibration"


@dataclass(frozen=True)
class VerifiedCell:
    provenance: CandidateProvenance
    start_ns: int
    stop_ns: int
    contract: ReportingContractV1
    observations: AccountObservations | None
    buffers: tuple[FrozenBuffer, ...]
    campaigns_json: str | None
    fills_json: str | None
    original_metrics_json: str
    compute_status: str
    reason: str | None

    def arrays(self):
        return {buffer.name: buffer.array() for buffer in self.buffers}


@dataclass(frozen=True)
class UtilityPolicy:
    preference_id: str
    dd_weight: float
    tail_weight: float
    drawdown_basis: str = "scope_entry"

    def __post_init__(self):
        if self.drawdown_basis != "scope_entry":
            raise ValueError("carried-watermark utility requires a separately approved scientific contract")


@dataclass(frozen=True)
class EnvironmentValuation:
    equity: float
    as_of_ns: int
    source_kind: str
    execution_id: str
    path_digest: str
    reporting_contract_identity: str | None

    @property
    def identity(self):
        return digest(asdict(self))

    def to_metadata(self):
        return dict(asdict(self), identity=self.identity)


@dataclass(frozen=True)
class DailyAttribution:
    day_ns: int
    equity_before: float
    equity_after: float
    money_pnl: float
    simple_return: float | None
    observed_bars: int
    exposed_bars: int


@dataclass(frozen=True)
class CandidateEnvironmentRow:
    provenance: CandidateProvenance
    environment_id: str
    environment_family: str
    start_ns: int
    stop_ns: int
    status: str
    compute_status: str
    reason: str | None
    actual_bar_count: int
    calendar_days: int
    exposure_days: int | None
    exposed_bars: int | None
    zero_return_days: int | None
    closed_campaigns: int | None
    open_campaigns: int | None
    fills: int | None
    money_pnl: float | None
    metrics: tuple[MetricValue, ...]
    raw_account_metrics: ReportingResult | None
    metric_contract_ids: tuple[str, ...]
    null_reasons: tuple[tuple[str, str], ...]
    environment_baseline: EnvironmentValuation | None = None
    carried_watermark: EnvironmentValuation | None = None
    utility_horizon: str = "actual contiguous period; no duration normalization"
    estimand_id: str = "CONTINUOUS_PATH_ATTRIBUTION"
    scenario_id: str = "deterministic_actual_path"
    independent_information_count: None = None
    clean_oos: bool = False
    battery_statuses: tuple[tuple[str, str], ...] = (("B4", "NOT_RUN"), ("B5", "NOT_RUN"))
    caveats: tuple[str, ...] = (
        "annual/full views share one account and dates; not independent experiments",
        "primary drawdown/utility use scope-entry valuation; carried_watermark_drawdown is a separate diagnostic",
        "close-mark exposure cannot recover unretained intrabar activity",
        "campaign support counts closures and boundary-censored holdings, not daily PnL allocations",
        "opaque execution key retained; original source seals required, not an execution requalification",
        "dated registrations are artifact-cutoff gated; undated paths are current-knowledge seals, not historical availability witnesses",
        "software attribution only; no full-panel, six-matrix, battery or exact sensitivity claim",
    )

    def metric(self, name):
        return next(metric for metric in self.metrics if metric.metric_id == "mode5.panel." + name)


def load_cell(cell_path, *, artifact_pins, source_pins, contract, cutoff_ns,
              study_id, diagnostic_revision, data_cutoff_ns=None, artifact_creation_cutoff_ns=None):
    """Read actual cell/request/path schemas using independent, caller-sealed pins.

    Required pins: cell, request, design, registration, resources, analysis,
    execution_budget, access, paths
    (paths only for PASS). Optional campaigns/fills are never trusted unsealed.
    Source pins include alpha_source and finance_driver from original provenance.
    The caller supplies the original account contract, including scope-entry mark.
    cutoff_ns is current analysis knowledge, not a historical calibration origin.
    The data cutoff defaults to the development stop; the separate creation gate
    for dated registrations defaults to the knowledge cutoff. Undated path seals
    do not establish decision-vintage availability.
    No private request parameters or source paths appear in the returned rows.
    """
    required = {"cell", "request", "design", "registration", "resources", "access", "analysis", "execution_budget"}
    if not isinstance(contract, ReportingContractV1):
        raise TypeError("original typed reporting contract required")
    if not required <= artifact_pins.keys() or not {"alpha_source", "finance_driver"} <= source_pins.keys():
        raise ValueError("original artifact/source inventory required")
    if type(cutoff_ns) is not int or not study_id or not diagnostic_revision:
        raise ValueError("explicit study/revision and exact access cutoff required")
    cell_path = Path(cell_path).resolve()
    for name, filename in (("cell", "cell.json"), ("request", "request.json"),
                           ("access", "development_access.json"), ("paths", "paths.npz"),
                           ("campaigns", "campaigns.json"), ("fills", "fills.json")):
        if name in artifact_pins and Path(artifact_pins[name]["path"]) != cell_path.parent / filename:
            raise ValueError("artifact path is not the original cell sibling")
    if Path(artifact_pins["cell"]["path"]) != cell_path:
        raise ValueError("cell identity mismatch")
    for pin in source_pins.values():
        if file_identity(pin["path"]) != dict(pin):
            raise ValueError("original source identity mismatch")
    cell, request, design, registration, resources, access = (
        _json(artifact_pins[name]) for name in ("cell", "request", "design", "registration", "resources", "access"))
    protocol = ResearchProtocol(**registration["protocol"])
    analysis, budget = (_json(artifact_pins[name]) for name in ("analysis", "execution_budget"))
    if (registration["protocol_id"] != protocol.identity
            or resources["resource_protocol"] != registration["protocol"]
            or registration["financial_outcomes_used_to_choose_design"] is not False
            or registration["forward_selection"] is not False):
        raise ValueError("registered independence/resource protocol mismatch")
    environment = analysis["environment_contract"]
    if (analysis["registration"] != artifact_pins["registration"]
            or analysis["execution_budget"] != artifact_pins["execution_budget"]
            or budget["original_registration"] != artifact_pins["registration"]
            or budget["original_resource_registration"] != artifact_pins["resources"]
            or analysis["clean_independent_claim"] is not False or analysis["forward_snapshot_allowed"] is not False
            or analysis["incomplete_matrix_is_complete_phase"] is not False
            or environment["mode"] != "CONTINUOUS_PATH_ATTRIBUTION" or environment["account_reset"] is not False
            or environment["annual_sharpe_average_is_whole_sharpe"] is not False
            or environment["overlapping_families_independent"] is not False
            or environment["annual_days"] != contract.annual_periods
            or analysis["screening"]["exact_sobol_claim"] is not False
            or not analysis["outcome_timing_disclosure"]):
        raise ValueError("reviewed exploratory analysis identity/attribution mismatch")
    if (budget["scientific_protocol_changed"] is not False or budget["core_or_alpha_changed"] is not False
            or budget["economic_outcome_filtering"] is not False or budget["publication"] is not False
            or budget["automatic_phase_promotion"] is not False or budget["numeric_threads_per_worker"] != 1
            or type(budget["financial_workers"]) is not int or budget["financial_workers"] < 1):
        raise ValueError("registered execution resource extension mismatch")
    for receipt in (analysis, budget):
        if file_identity(receipt["source"]["path"]) != receipt["source"]:
            raise ValueError("original registration source changed")
    if (access["future_tape_opened"] is not False or access["original_contract_preserved"] is not True
            or access["allowed_stop"] != protocol.development_stop
            or access["finance_driver"] != source_pins["finance_driver"]):
        raise ValueError("original development/source access witness mismatch")
    if access.get("mutable_strategy_or_account_reused") is True:
        raise ValueError("mutable candidate state was reused")
    if "orchestrator" in access and access["orchestrator"] != source_pins.get("orchestrator"):
        raise ValueError("original orchestrator identity required")
    # The data/source identities are checked independently of result metadata.
    if file_identity(access["witness"]["path"]) != access["witness"]:
        raise ValueError("development data identity mismatch")
    if (cell["request"] != request or request["alpha"] != design["alpha"]
            or request["design_id"] != design["design_id"]
            or request["symbol"] != registration["symbols"][request["alpha"]]
            or request["start"] != protocol.development_start or request["stop"] != protocol.development_stop
            or request["role"] != "NEUTRAL_BROAD_DISCOVERY"
            or not request["account_mode"].startswith("continuous_development")):
        raise ValueError("original request/design/scope identity mismatch")
    selected = [row for row in design["rows"] if row["row_id"] == request["proposal_row"]]
    if len(selected) != 1:
        raise ValueError("unique original proposal required")
    proposal = selected[0]
    if proposal["candidate_id"] != request["candidate_id"] or proposal["effective"] != request["params"]:
        raise ValueError("original effective candidate mismatch")
    if cell["status"] != "STRUCTURAL_INVALID" and (proposal["admitted"] is not True or proposal["status"] != "READY"):
        raise ValueError("execution is not a structurally admitted proposal")
    start, stop = _ns(request["start"]), _ns(request["stop"])
    data_cutoff_ns = stop if data_cutoff_ns is None else data_cutoff_ns
    artifact_creation_cutoff_ns = cutoff_ns if artifact_creation_cutoff_ns is None else artifact_creation_cutoff_ns
    if type(data_cutoff_ns) is not int or type(artifact_creation_cutoff_ns) is not int:
        raise ValueError("exact separate data/artifact creation cutoffs required")
    if (stop > data_cutoff_ns or data_cutoff_ns > cutoff_ns or artifact_creation_cutoff_ns > cutoff_ns
            or any(_ns(receipt["created_at"]) > artifact_creation_cutoff_ns
                   for receipt in (registration, analysis, budget))):
        raise PermissionError("future or immature development/registration")
    if (not isinstance(contract, ReportingContractV1) or contract.unit != "account_period"
            or contract.sampling != "observed_daily_utc" or contract.annual_periods != 365.
            or contract.partial_periods != "include_disclosed" or contract.equity_clock != "bar_close"
            or contract.baseline_time_ns != start - HOUR_NS or contract.scope_end_ns != stop - HOUR_NS):
        raise ValueError("original complete-hour UTC account contract required")
    refs = {**{name: pin["sha256"] for name, pin in artifact_pins.items()},
            **{"source." + name: pin["sha256"] for name, pin in source_pins.items()},
            "development_data": access["witness"]["sha256"]}
    provenance = CandidateProvenance(study_id, diagnostic_revision, request["alpha"], request["candidate_id"],
        digest(proposal["requested"]), digest(proposal["effective"]), proposal["direction"],
        (request["proposal_row"],), cell["execution_key"], design["design_id"], request["symbol"],
        analysis["role"], analysis["outcome_timing_disclosure"], _ns(protocol.preload_start),
        data_cutoff_ns, artifact_creation_cutoff_ns, cutoff_ns,
        cell.get("route", "NOT_EXECUTED"),
        tuple(sorted(refs.items())))
    status = cell["status"]
    if status in {"STRUCTURAL_INVALID", "RUNTIME_FAILED"}:
        reason = cell.get("reason")
        if not reason or cell.get("metrics"):
            raise ValueError("failure requires a reason and no economic sentinel")
        return VerifiedCell(provenance, start, stop, contract, None, (), None, None, "{}", status, reason)
    if status != "PASS" or "paths" not in artifact_pins or cell["path"] != artifact_pins["paths"]:
        raise ValueError("complete actual path required; unsupported compute status")
    if cell["clean_oos"] is not False or request["alpha"] not in analysis["alpha_roster"]:
        raise ValueError("reviewed development is not clean independent OOS")
    with np.load(BytesIO(_read(artifact_pins["paths"])), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if not {"times_ns", "equity", "positions", "daily_returns"} <= arrays.keys():
        raise ValueError("actual timestamp/account/daily-return paths required")
    times = arrays["times_ns"]
    count, days = (stop-start)//HOUR_NS, (stop-start)//DAY_NS
    if (start % DAY_NS or stop % DAY_NS or times.dtype != np.dtype("int64") or times.shape != (count,)
            or not np.array_equal(times, np.arange(start, stop, HOUR_NS, dtype=np.int64))
            or cell["scored_bars"] != count or cell["scored_days"] != days):
        raise ValueError("complete chronological hourly path required; no gaps/reset/splicing")
    actual_years = list(range(datetime.fromtimestamp(start/10**9, timezone.utc).year,
                             datetime.fromtimestamp((stop-HOUR_NS)/10**9, timezone.utc).year+1))
    if (environment["years"] != actual_years or type(cell["actual_execution_calls"]) is not int
            or cell["actual_execution_calls"] < 1 or cell["visited_bars"] != cell["actual_execution_calls"]*count
            or not np.isfinite([cell["wall_seconds"], cell["peak_rss_mib"]]).all()
            or min(cell["wall_seconds"], cell["peak_rss_mib"]) < 0):
        raise ValueError("actual scope/resource accounting mismatch")
    for name in ("equity", "positions", "fees", "funding", "turnover"):
        if name in arrays and (arrays[name].shape != times.shape or not np.isfinite(arrays[name]).all()):
            raise ValueError("finite aligned account stream required")
    coverage = ReportingCoverageV1(result_identity=artifact_pins["paths"]["sha256"],
        producer="sealed actual account path", profile="compact", ledger="omitted", retained_rows=0,
        dropped_rows=0, reason="campaign ledger is separately retained or unavailable")
    obs = AccountObservations(times_ns=times, equity=arrays["equity"], coverage=coverage)
    if arrays["daily_returns"].shape != (days,):
        raise ValueError("retained daily return cardinality mismatch")
    if np.all(obs.equity > 0):
        obs = obs.with_derived_returns(contract, partial_mask=np.zeros(days, dtype=bool),
                                       witness="sealed full-hour UTC days; original scope-entry valuation")
        if (arrays["daily_returns"].shape != (days,)
                or not np.allclose(obs.returns.values, arrays["daily_returns"], rtol=0, atol=1e-12)):
            raise ValueError("retained daily returns differ from metric authority")
    raw = reduce_account(obs, contract, backend="python")
    for source, target in (("account.total_return", "total_return"), ("drawdown.max_depth", "max_drawdown"),
                           ("period.sharpe", "sharpe")):
        expected, retained = raw.metric(source).value, cell["metrics"][target]
        if ((expected is None) != (retained is None)
                or (expected is not None and not np.isclose(expected, retained, rtol=0, atol=1e-10))):
            raise ValueError("original raw account metrics differ from metric authority")
    campaigns = _json(artifact_pins["campaigns"]) if "campaigns" in artifact_pins else None
    fills = _json(artifact_pins["fills"]) if "fills" in artifact_pins else None
    if campaigns is not None:
        if set(campaigns) != {"closed", "open"}:
            raise ValueError("original closed/censored campaign schema required")
        for kind, rows in campaigns.items():
            if len(rows) != cell["support"][kind + "_campaigns"]:
                raise ValueError("campaign support identity mismatch")
            for row in rows:
                opened = _ns(row["start"])
                ended = _ns(row["end"]) if kind == "closed" else stop - HOUR_NS
                if not start <= opened <= ended < stop:
                    raise ValueError("campaign outside actual account calendar")
        pnl = sum(row["net_pnl"] for row in campaigns["closed"])
        pnl += sum(row["marked_net_pnl"] for row in campaigns["open"])
        whole = partition_pnl(obs.equity, initial_equity=contract.baseline_equity, block_ends=(len(times)-1,))
        if not np.isclose(pnl, whole[0]["money_pnl"], rtol=0, atol=1e-8):
            raise ValueError("closed/censored campaign PnL does not reconcile")
    if fills is not None:
        fill_times = [_ns(row["timestamp"]) for row in fills]
        if (len(fills) != cell["support"]["fills"] or any(t < start or t >= stop for t in fill_times)
                or any(a > b for a, b in zip(fill_times, fill_times[1:]))):
            raise ValueError("original fill support/calendar mismatch")
    buffers = tuple(FrozenBuffer.from_array(name, values) for name, values in sorted(arrays.items())
                    if name in {"positions", "fees", "funding", "turnover"})
    return VerifiedCell(provenance, start, stop, contract, obs, buffers,
        canonical(campaigns) if campaigns is not None else None,
        canonical(fills) if fills is not None else None, canonical(cell["metrics"]), status, None)


def daily_attribution(cell):
    """Partition existing marks through the original monetary metric authority."""
    if cell.observations is None:
        return ()
    obs, positions = cell.observations, cell.arrays()["positions"]
    ends = tuple(range(23, len(obs.equity), 24))
    parts = partition_pnl(obs.equity, initial_equity=cell.contract.baseline_equity, block_ends=ends)
    return tuple(DailyAttribution(int(obs.times_ns[end]//DAY_NS*DAY_NS), part["pre_block_equity"],
        part["terminal_equity"], part["money_pnl"], part["simple_return"], 24,
        int(np.count_nonzero(positions[end-23:end+1]))) for end, part in zip(ends, parts))


def continuous_annual_rows(cell, *, utility_policy, backend="python"):
    """Return full-path plus annual dependent views; never average their Sharpes."""
    if not isinstance(cell, VerifiedCell) or not isinstance(utility_policy, UtilityPolicy):
        raise TypeError("verified cell and explicit frozen utility preference required")
    if cell.observations is None:
        return (CandidateEnvironmentRow(cell.provenance, "whole_path", "continuous_account",
            cell.start_ns, cell.stop_ns, cell.compute_status, cell.compute_status, cell.reason,
            0, 0, None, None, None, None, None, None, None, (), None, (),
            (("account_metrics", cell.reason),)),)
    obs, arrays, daily = cell.observations, cell.arrays(), daily_attribution(cell)
    years = sorted({_ns(f"{datetime.fromtimestamp(day.day_ns/10**9, timezone.utc).year}-01-01") for day in daily})
    views = [("whole_path", cell.start_ns, cell.stop_ns)]
    for start in years:
        year = datetime.fromtimestamp(start/10**9, timezone.utc).year
        views.append((str(year), max(start, cell.start_ns), min(_ns(f"{year+1}-01-01"), cell.stop_ns)))
    campaigns = json.loads(cell.campaigns_json) if cell.campaigns_json is not None else None
    fills = json.loads(cell.fills_json) if cell.fills_json is not None else None
    rows = []
    for name, start, stop in views:
        lo, hi = (start-cell.start_ns)//HOUR_NS, (stop-cell.start_ns)//HOUR_NS
        dlo, dhi = lo//24, hi//24
        previous = cell.contract.baseline_equity if lo == 0 else float(obs.equity[lo-1])
        watermark = max(cell.contract.baseline_equity, float(obs.equity[:lo].max())) if lo else previous
        carried = replace(cell.contract, scope="full" if name == "whole_path" else "scoped",
            baseline_equity=watermark, baseline_time_ns=start-HOUR_NS, scope_end_ns=stop-HOUR_NS)
        contract = replace(carried, baseline_equity=previous) if previous > 0 else None
        path_digest = dict(cell.provenance.evidence_refs)["paths"]
        baseline = EnvironmentValuation(previous, start-HOUR_NS,
            "original_initial_capital" if lo == 0 else "prior_actual_close", cell.provenance.execution_id,
            path_digest, contract.identity if contract is not None else None)
        carried_valuation = EnvironmentValuation(watermark, start-HOUR_NS, "prior_global_watermark",
            cell.provenance.execution_id, path_digest, carried.identity)
        subset = daily[dlo:dhi]
        raw, metrics, contract_ids = None, [], [carried.identity]
        if previous > 0:
            returns = None if obs.returns is None else ReturnObservations(values=obs.returns.values[dlo:dhi],
                end_times_ns=obs.returns.end_times_ns[dlo:dhi], partial_mask=obs.returns.partial_mask[dlo:dhi],
                sampling=obs.returns.sampling, witness=obs.returns.witness)
            scoped = AccountObservations(times_ns=obs.times_ns[lo:hi], equity=obs.equity[lo:hi],
                                         coverage=obs.coverage, returns=returns)
            if returns is None and np.all(scoped.equity > 0):
                scoped = scoped.with_derived_returns(contract, partial_mask=np.zeros(dhi-dlo, dtype=bool),
                    witness="sealed annual UTC days; carried previous close; no future suffix used")
            returns = scoped.returns
            raw = reduce_account(scoped, contract, backend=backend)
            contract_ids = [contract.identity, carried.identity]
            for target, source in (("net_return", "account.total_return"), ("sharpe", "period.sharpe"),
                                   ("daily_mean_return", "period.mean_arithmetic"),
                                   ("return_step_pf", "period.profit_factor"), ("drawdown", "drawdown.max_depth")):
                metric = raw.metric(source)
                metrics.append(MetricValue("mode5.panel."+target, "decimal_return" if target in
                    {"net_return", "daily_mean_return", "drawdown"} else "ratio", metric.sample_count, metric.value,
                    metric.status.upper(), metric.reason, components=(("reporting_contract_identity", contract.identity),
                        ("environment_baseline_identity", baseline.identity))))
            raw = replace(raw, provenance_json=canonical(json.loads(raw.provenance_json) | dict(
                environment_id=name, environment_baseline=baseline.to_metadata(),
                carried_watermark=carried_valuation.to_metadata(), primary_drawdown_basis=utility_policy.drawdown_basis)))
        else:
            metrics = [MetricValue("mode5.panel."+target, unit, dhi-dlo, status="BANKRUPT",
                reason="nonpositive carried scope-entry mark") for target, unit in (
                    ("net_return", "decimal_return"), ("sharpe", "ratio"),
                    ("daily_mean_return", "decimal_return"), ("return_step_pf", "ratio"), ("drawdown", "decimal_return"))]
            scoped = AccountObservations(times_ns=obs.times_ns[lo:hi], equity=obs.equity[lo:hi], coverage=obs.coverage)
        drawdown = scan_drawdown(scoped, carried, backend=backend)[0][0]
        metrics.append(MetricValue("mode5.panel.carried_watermark_drawdown", "decimal_return", hi-lo,
            float(drawdown), components=(("basis", "carried_global_watermark"),
                ("reporting_contract_identity", carried.identity), ("valuation_identity", carried_valuation.identity))))
        qualified_returns = None if previous <= 0 else returns
        es = expected_shortfall(-qualified_returns.values, .95) if qualified_returns is not None else MetricValue(
            "mode5.panel.daily_loss_es", "decimal_return", dhi-dlo, status="BANKRUPT",
            reason="daily returns after nonpositive marks are not qualified")
        metrics.append(replace(es, metric_id="mode5.panel.daily_loss_es"))
        by_name = {metric.metric_id: metric for metric in metrics}
        utility = economic_utility(*(by_name["mode5.panel."+target] for target in
            ("net_return", "drawdown", "daily_loss_es")), dd_weight=utility_policy.dd_weight,
            tail_weight=utility_policy.tail_weight, preference_id=utility_policy.preference_id)
        metrics.append(replace(utility, metric_id="mode5.panel.economic_utility", components=utility.components + (
            ("drawdown_basis", utility_policy.drawdown_basis),
            ("drawdown_contract_identity", baseline.reporting_contract_identity),
            ("drawdown_valuation_identity", baseline.identity))))
        nulls = [(metric.metric_id, metric.reason) for metric in metrics if metric.value is None]
        closed = opened = fill_count = None
        if campaigns is not None:
            closed = sum(start <= _ns(row["end"]) < stop for row in campaigns["closed"])
            opened = sum(_ns(row["start"]) < stop <= _ns(row["end"]) for row in campaigns["closed"])
            opened += sum(_ns(row["start"]) < stop for row in campaigns["open"])
        else:
            nulls.extend((key, UNAVAILABLE_CAMPAIGNS) for key in ("closed_campaigns", "open_campaigns"))
        if fills is not None:
            fill_count = sum(start <= _ns(row["timestamp"]) < stop for row in fills)
        else:
            nulls.append(("fills", "no sealed accepted-fill ledger"))
        nulls.extend((("campaign_pf", "campaign metric contract unavailable; return-step PF is distinct"),
                      ("independent_information_count", "shared account/dates; no independence estimator supplied")))
        for stream in ("fees", "funding", "turnover"):
            value = float(arrays[stream][lo:hi].sum()) if stream in arrays else None
            metrics.append(MetricValue("mode5.panel."+stream, cell.contract.currency, hi-lo, value,
                "VALID" if value is not None else "UNAVAILABLE", None if value is not None else "stream not retained",
                components=(("measure", "executed_fill_notional" if stream == "turnover" else "recorded_net_cost"),
                    ("aggregation", "sum_actual_bars"), ("normalization", "none"))))
            if value is None:
                nulls.append((stream, "stream not retained"))
        if qualified_returns is None:
            nulls.append(("zero_return_days", "daily return population not qualified after nonpositive marks"))
        pnl = float(sum(day.money_pnl for day in subset))
        exposed = sum(day.exposed_bars for day in subset)
        status = "VALID_UNPROFITABLE" if pnl < 0 else "VALID_PROFITABLE" if pnl > 0 else "VALID_ZERO_RETURN"
        if pnl == 0 and exposed == 0 and fill_count == 0 and closed == opened == 0:
            status = "VALID_NO_TRADE"
        rows.append(CandidateEnvironmentRow(cell.provenance, name,
            "continuous_account" if name == "whole_path" else "annual_anchor", start, stop,
            status, cell.compute_status, None, hi-lo, dhi-dlo, sum(day.exposed_bars > 0 for day in subset),
            exposed, sum(day.simple_return == 0 for day in subset) if qualified_returns is not None else None,
            closed, opened, fill_count, pnl, tuple(metrics), raw, tuple(dict.fromkeys(contract_ids)), tuple(nulls),
            environment_baseline=baseline, carried_watermark=carried_valuation))
    return tuple(rows)
