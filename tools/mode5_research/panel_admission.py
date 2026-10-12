"""Explicit full-panel admission of existing, source-admitted account readers.

The owner captures ReaderCertification immediately after a successful load_cell
or load_recovery_cell call, using independently approved inventories. Certificates
and the canonical original-design digest must be retained outside the later
subject input. This module neither issues source approval nor requalifies finance.
Only analysis completion becomes PASS; source status, role and oracle coverage
are preserved. It opens no files, strategies, future tapes or account engines.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json

import numpy as np

from quantbt.metrics.report_contracts import ReportingContractV1
from tools.mode5_diagnostics.identity import canonical, digest
from tools.mode5_statistics.contracts import MetricValue

from . import panels
from .probe_views import row_metadata
from .recovery_cells import RecoveryCell, RECOVERY_SCHEMA, RECOVERY_STATUS

PANEL_SCHEMA = "source_admitted_continuous_panel_v1"
ORIGINAL_SCHEMA = "panels.load_cell_v1"
ORIGINAL_ORACLE = "NOT_RETAINED_BY_ORIGINAL_VERIFIED_CELL"
ENVIRONMENTS = ("whole_path", "2021", "2022", "2023")
START, STOP = panels._ns("2021-01-01"), panels._ns("2024-01-01")
_SCHEMAS = {
    ORIGINAL_SCHEMA: ("PASS", "REVIEWED_EXPLORATORY_DEVELOPMENT"),
    RECOVERY_SCHEMA: (RECOVERY_STATUS, "DEVELOPMENT_REVIEWED_RETROSPECTIVE"),
}
_RAW_METRICS = {
    "net_return": "account.total_return", "drawdown": "drawdown.max_depth",
    "sharpe": "period.sharpe", "daily_mean_return": "period.mean_arithmetic",
    "return_step_pf": "period.profit_factor",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


@dataclass(frozen=True)
class ReaderCertification:
    reader_schema: str
    cell_identity: str
    alpha_source_digest: str
    economic_config_digest: str

    def __post_init__(self):
        _require(self.reader_schema in _SCHEMAS and all(_sha(v) for v in
                 (self.cell_identity, self.alpha_source_digest, self.economic_config_digest)),
                 "explicit reader, captured cell and approved source/economic identities required")


def reader_cell_identity(cell):
    """Capture the immutable reader output, not a financial execution certificate."""
    _require(type(cell) in (panels.VerifiedCell, RecoveryCell), "existing typed reader output required")
    return digest(dict(provenance=asdict(cell.provenance), contract=cell.contract.identity,
        observations=cell.observations.identity if cell.observations is not None else None,
        start=cell.start_ns, stop=cell.stop_ns, status=cell.compute_status, reason=cell.reason,
        buffers=[(b.name, b.dtype, b.shape, sha256(b.data).hexdigest()) for b in cell.buffers],
        campaigns=cell.campaigns_json, fills=cell.fills_json, original_metrics=cell.original_metrics_json,
        account_calls=_calls(cell)))


def _calls(cell):
    return ((cell.native_feedback_calls, cell.normal_native_calls, cell.python_oracle_calls)
            if type(cell) is RecoveryCell else None)


def _validate_cell(cell, certification, proposal, design, cutoff_ns):
    _require(type(cell) in (panels.VerifiedCell, RecoveryCell)
             and isinstance(certification, ReaderCertification), "source-admitted cell and certificate required")
    schema = RECOVERY_SCHEMA if type(cell) is RecoveryCell else ORIGINAL_SCHEMA
    _require(certification.reader_schema == schema
             and certification.cell_identity == reader_cell_identity(cell), "reader certification differs from subject")
    raw_status, role = _SCHEMAS[schema]
    p = cell.provenance
    _require(cell.compute_status == raw_status and cell.reason is None and cell.observations is not None,
             "full completed source account required, not a masked failure")
    _require(p.alpha_id == design["alpha"] and p.design_id == design["design_id"]
             and p.candidate_id == proposal["candidate_id"] and p.branch_id == proposal["direction"]
             and p.raw_params_digest == digest(proposal["requested"])
             and p.effective_params_digest == digest(proposal["effective"])
             and p.trial_refs == (proposal["row_id"],) and type(p.trial_refs[0]) is int,
             "original candidate/index/effective-parameter lineage differs")
    _require(p.data_role == role and bool(p.outcome_timing_disclosure) and bool(p.chronology_claim)
             and (cell.start_ns, cell.stop_ns) == (START, STOP)
             and p.warmup_start_ns == panels._ns("2020-01-01") and p.data_cutoff_ns == STOP
             and type(p.artifact_creation_cutoff_ns) is int and type(p.knowledge_cutoff_ns) is int
             and STOP <= p.artifact_creation_cutoff_ns <= p.knowledge_cutoff_ns <= cutoff_ns,
             "reviewed original development role/calendar/cutoff required")
    refs = dict(p.evidence_refs)
    _require(len(refs) == len(p.evidence_refs) and all(_sha(v) for v in refs.values()),
             "unique exact source/data/result digests required")
    required = {"paths", "design", "development_data"}
    required |= ({"cell", "request", "registration", "resources", "analysis", "execution_budget", "access",
                  "source.alpha_source", "source.finance_driver"} if schema == ORIGINAL_SCHEMA else
                 {"result", "worker_registration", "original_registration", "economic_config", "native_gate",
                  "campaigns", "fills"})
    _require(required <= refs.keys(), "reader source/economics/result lineage incomplete")
    if schema == RECOVERY_SCHEMA:
        approved = {v for k, v in refs.items() if k.startswith("approved_source_")}
        _require(certification.alpha_source_digest in approved
                 and refs["economic_config"] == certification.economic_config_digest,
                 "approved control alpha/economics differ")
        calls = _calls(cell)
        _require(all(type(n) is int for n in calls) and calls[0] >= 1 and calls[2] in (0, 1)
                 and calls[1] == 1 + calls[2], "recovery oracle/account-call coverage differs")
        _require(p.execution_id == refs["result"]
                 and p.actual_route == "incremental_actual_feedback_boundary_full_hash_v1",
                 "recovery result/route authority differs")
    else:
        _require(refs["source.alpha_source"] == certification.alpha_source_digest,
                 "original alpha source differs from approved lineage")
    contract = cell.contract
    expected = ReportingContractV1(scope="full", unit="account_period", currency=contract.currency,
        baseline_equity=contract.baseline_equity, baseline_time_ns=START-panels.HOUR_NS,
        scope_end_ns=STOP-panels.HOUR_NS, sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
    _require(contract == expected, "original continuous reporting/economic policy required")
    obs = cell.observations
    _require(obs.coverage.result_identity == refs["paths"]
             and np.array_equal(obs.times_ns, np.arange(START, STOP, panels.HOUR_NS))
             and np.isfinite(obs.equity).all(), "full reader-certified hourly account calendar required")
    obs.validate_contract(contract)
    if obs.returns is not None:
        _require(obs.returns.values.shape == (1095,) and np.isfinite(obs.returns.values).all()
                 and np.array_equal(obs.returns.end_times_ns, obs.times_ns[23::24])
                 and not np.any(obs.returns.partial_mask), "full unmasked original daily population required")
    else:
        _require(np.any(obs.equity <= 0), "defined daily population cannot be silently omitted")
    arrays = cell.arrays()
    _require(len(arrays) == len(cell.buffers) and "positions" in arrays
             and all(a.shape == (26280,) and np.isfinite(a).all() for a in arrays.values()),
             "aligned finite reader-certified account streams required")


def analysis_compute_pass(row):
    """Explicit new-schema admission predicate; no fallback or role normalization."""
    schema = row.get("source_reader_schema")
    return (row.get("panel_admission_schema") == PANEL_SCHEMA and schema in _SCHEMAS
            and row.get("analysis_compute_status") == "PASS"
            and row.get("compute_status") == _SCHEMAS[schema][0]
            and row.get("provenance", {}).get("data_role") == _SCHEMAS[schema][1]
            and _sha(row.get("reader_cell_identity")))


def validate_panel_row(row):
    """Validate the serialized shared row before diagnostic/selector consumption."""
    _require(analysis_compute_pass(row), "explicit source-reader analysis admission required")
    certification = ReaderCertification(row["source_reader_schema"], row["reader_cell_identity"],
        row["alpha_source_digest"], row["economic_config_digest"])
    _require(row["reader_certification_id"] == digest(asdict(certification)),
             "source/economic reader certification differs")
    refs = dict(row["provenance"]["evidence_refs"])
    if certification.reader_schema == RECOVERY_SCHEMA:
        _require(refs.get("economic_config") == certification.economic_config_digest
                 and certification.alpha_source_digest in
                    {v for k, v in refs.items() if k.startswith("approved_source_")}, "recovery source/economic lineage differs")
    else:
        _require(refs.get("source.alpha_source") == certification.alpha_source_digest,
                 "original source lineage differs")
    env = row["environment_id"]
    _require(env in ENVIRONMENTS and type(row["index"]) is int and 0 <= row["index"] < 128
             and row["clean_oos"] is False and row["estimand_id"] == "CONTINUOUS_PATH_ATTRIBUTION"
             and row["environment_family"] == ("continuous_account" if env == "whole_path" else "annual_anchor"),
             "original dependent development candidate/environment required")
    start = START if env == "whole_path" else panels._ns(env + "-01-01")
    stop = STOP if env == "whole_path" else panels._ns(str(int(env)+1) + "-01-01")
    days = 1095 if env == "whole_path" else 365
    _require((row["start_ns"], row["stop_ns"]) == (start, stop)
             and row["calendar_days"] == days and row["actual_bar_count"] == days*24,
             "complete original whole/annual scope required")
    _require(row["status"] in {"VALID_PROFITABLE", "VALID_UNPROFITABLE", "VALID_ZERO_RETURN", "VALID_NO_TRADE"}
             and row["reason"] is None, "failed source cannot masquerade as an economic outcome")
    metrics = [MetricValue(**m) for m in row["metrics"]]
    by_id = {m.metric_id: m for m in metrics}
    _require(len(by_id) == len(metrics) and {"mode5.panel."+k for k in
        (*_RAW_METRICS, "daily_loss_es", "economic_utility")} <= by_id.keys(), "complete unique metric contracts required")
    for name in (*_RAW_METRICS, "daily_loss_es", "economic_utility"):
        expected_unit = "ratio" if name in {"sharpe", "return_step_pf"} else "decimal_return"
        _require(by_id["mode5.panel."+name].unit == expected_unit, "original panel metric unit required")
    nulls = dict(row["null_reasons"])
    _require(len(nulls) == len(row["null_reasons"]), "unique null masks required")
    for m in metrics:
        key = m.metric_id.removeprefix("mode5.panel.")
        if m.value is None:
            _require(nulls.get(m.metric_id, nulls.get(key)) == m.reason, "undefined metric mask/reason differs")
        else:
            _require(m.metric_id not in nulls and key not in nulls, "defined value has a false null mask")
    raw = row["raw_account_metrics"]
    if raw is not None:
        original = {m["metric_id"]: m for m in raw["metrics"]}
        for name, source in _RAW_METRICS.items():
            m, authority = by_id["mode5.panel."+name], original["reporting."+source]
            _require(m.value == authority["value"] and m.status == authority["status"].upper()
                     and m.reason == authority["reason"] and m.sample_count == authority["sample_count"],
                     "raw reporting authority or undefined semantics masked")
    else:
        _require(all(by_id["mode5.panel."+k].value is None for k in _RAW_METRICS),
                 "unavailable raw authority cannot supply defined metrics")
    if row["source_reader_schema"] == ORIGINAL_SCHEMA:
        _require(row["oracle_coverage"] == ORIGINAL_ORACLE and row["recovery_account_calls"] is None,
                 "original reader does not supply recovery oracle coverage")
    else:
        calls = row["recovery_account_calls"]
        _require(isinstance(calls, list) and len(calls) == 3 and all(type(n) is int for n in calls)
                 and calls[0] >= 1 and calls[2] in (0, 1) and calls[1] == 1+calls[2]
                 and row["oracle_coverage"] == ("FRESH_ORIGINAL_PYTHON_CONTROL" if calls[2] else
                     "INHERITED_CONTROL_SOURCE_APPROVAL_NO_FRESH_PYTHON_ORACLE"), "recovery oracle coverage masked")
    return row


def admit_panel(cells, *, original_design, original_design_digest, certifications,
                alpha_source_digest, economic_config_digest, utility_policy, cutoff_ns):
    """Return exactly 512 shared rows in original admitted-candidate order.

    original_design_digest is the caller-approved canonical parsed-design digest,
    not a newly computed approval of the subject. Each certificate is captured
    after the matching existing source reader succeeds. Serialized outputs need
    the owner's usual external evidence seal before a later consumer reads them.
    """
    _require(_sha(original_design_digest) and digest(original_design) == original_design_digest,
             "externally approved original design differs")
    _require(_sha(alpha_source_digest) and _sha(economic_config_digest),
             "externally approved original alpha and economic config required")
    _require(isinstance(utility_policy, panels.UtilityPolicy) and type(cutoff_ns) is int and cutoff_ns >= STOP,
             "explicit utility policy and current analysis cutoff required")
    _require(np.isfinite([utility_policy.dd_weight, utility_policy.tail_weight]).all(), "finite frozen utility required")
    design_rows = original_design["rows"]
    _require(all(type(r["admitted"]) is bool and type(r["row_id"]) is int for r in design_rows)
             and len({r["row_id"] for r in design_rows}) == len(design_rows), "unique original proposal row IDs required")
    proposals = [r for r in design_rows if r["admitted"]]
    _require(len(proposals) == 128 and all(r["status"] == "READY" and r["role"] == "exploration"
             and r.get("duplicate_of") is None for r in proposals), "full original 128 admitted discovery roster required")
    ids = [r["candidate_id"] for r in proposals]
    _require(len(set(ids)) == 128 and len({digest(r["effective"]) for r in proposals}) == 128,
             "128 unique original candidate/effective identities required")
    cells = tuple(cells)
    _require(all(type(c) in (panels.VerifiedCell, RecoveryCell) for c in cells), "typed source-admitted cells required")
    indexed = {c.provenance.candidate_id: c for c in cells}
    _require(len(cells) == len(indexed) == 128 and set(indexed) == set(ids)
             and set(certifications) == set(ids), "missing/duplicate/orphan cells or reader certificates")
    for proposal in proposals:
        cid = proposal["candidate_id"]
        cert = certifications[cid]
        _require(isinstance(cert, ReaderCertification) and cert.alpha_source_digest == alpha_source_digest
                 and cert.economic_config_digest == economic_config_digest,
                 "mixed or changed alpha source/economics cannot form one panel")
        _validate_cell(indexed[cid], certifications[cid], proposal, original_design, cutoff_ns)
    _require(len({c.provenance.symbol for c in cells}) == 1
             and len({c.contract.identity for c in cells}) == 1
             and len({dict(c.provenance.evidence_refs)["design"] for c in cells}) == 1
             and len({dict(c.provenance.evidence_refs)["development_data"] for c in cells}) == 1,
             "one exact original design/market/economic account per panel required")
    rows = []
    for index, cid in enumerate(ids):
        cell, cert = indexed[cid], certifications[cid]
        views = panels.continuous_annual_rows(cell, utility_policy=utility_policy, backend="python")
        _require(tuple(r.environment_id for r in views) == ENVIRONMENTS, "four ordered whole/annual views required")
        for view in views:
            _require(view.provenance == cell.provenance and view.compute_status == cell.compute_status,
                     "annual producer changed source lineage/status")
            row = row_metadata(view) | dict(index=index, panel_admission_schema=PANEL_SCHEMA,
                analysis_compute_status="PASS", source_reader_schema=cert.reader_schema,
                reader_cell_identity=cert.cell_identity,
                reader_certification_id=digest(asdict(cert)), alpha_source_digest=cert.alpha_source_digest,
                economic_config_digest=cert.economic_config_digest,
                oracle_coverage=cell.oracle_coverage if type(cell) is RecoveryCell else ORIGINAL_ORACLE,
                recovery_account_calls=list(_calls(cell)) if type(cell) is RecoveryCell else None)
            rows.append(validate_panel_row(row))
    return json.loads(canonical(dict(schema=PANEL_SCHEMA, analysis_compute_status="PASS",
        original_design_digest=original_design_digest, cutoff_ns=cutoff_ns,
        alpha_source_digest=alpha_source_digest, economic_config_digest=economic_config_digest,
        candidate_ids=ids, candidate_environment_rows=rows, utility_policy=asdict(utility_policy),
        clean_oos=False, independent_environments=False, financial_executions=0)))
