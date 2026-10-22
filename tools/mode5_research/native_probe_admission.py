"""Cold admission of exact native diagnostic probes, never financial execution.

Caller seals include the unchanged broad design/worker authority and the separate
adapter registration, launch authorization and reaped-worker closure. Source
approval must come from qualified controls, not from the subject's success flag.
"""

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path

import numpy as np

from quantbt.metrics.report_contracts import ReportingContractV1
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_diagnostics.evidence import FrozenBuffer
from tools.mode5_diagnostics.identity import canonical, digest

from . import native_diagnostics as diagnostic, panels, recovery_cells as recovery
from .protocol import ResearchProtocol

READER_SCHEMA = "mode5.native_probe_cold_reader.v1"
CLOSURE_SCHEMA = "mode5.native_probe_closure.v1"
_REQUIRED = recovery._REQUIRED | {"adapter_registration", "cleanup", "closure"}
_RIGHTS = {"selection_probe": "selection", "local_validation": "post_decision_reporting_only"}
_THREADS = {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
            "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS", "RAYON_NUM_THREADS"}
_LIMITATIONS = (
    "Current-knowledge reviewed development, not historical calibration or independent OOS.",
    "Annual/full views share the original continuous account; no annual-local authorization.",
    "Compiler/lifecycle/terminal qualification is retained from the sealed original owner, not rerun.",
    "Control source approval is inherited; fresh Python-oracle coverage is disclosed separately.",
    "Bounded registered neighbors do not certify whole-panel local robustness or alpha quality.",
)
_require = recovery._require


@dataclass(frozen=True)
class NativeProbeCell(panels.VerifiedCell):
    native_feedback_calls: int
    normal_native_calls: int
    python_oracle_calls: int
    execution_index: int
    plan_identity: str
    request_json: str
    rights: str
    original_result_schema: str | None
    parent_coverage_json: str
    source_limitations: tuple[str, ...] = _LIMITATIONS

    @property
    def reader_schema(self):
        return READER_SCHEMA

    @property
    def actual_execution_calls(self):
        return self.native_feedback_calls + self.normal_native_calls + self.python_oracle_calls

    @property
    def visited_bars(self):
        return self.actual_execution_calls * ((self.stop_ns - self.start_ns) // panels.HOUR_NS)

    @property
    def oracle_coverage(self):
        return ("FRESH_ORIGINAL_PYTHON_CONTROL" if self.python_oracle_calls else
                "INHERITED_CONTROL_SOURCE_APPROVAL_NO_FRESH_PYTHON_ORACLE")


def _launch_lineage(plan, catalog, entry_index, pins, approvals, cutoff, parent):
    _require(isinstance(plan, Record) and isinstance(catalog, EvidenceCatalog)
             and plan.data["schema"] == diagnostic.SCHEMA, "sealed typed native diagnostic plan required")
    p = plan.data
    _require(type(entry_index) is int and 0 <= entry_index < len(p["executions"]), "exact planned entry required")
    entry = p["executions"][entry_index]
    wrapper = recovery._json(pins["adapter_registration"], cutoff)
    auth_ref = wrapper["authorization_ref"]
    auth = catalog.require_ref(auth_ref)
    _require(wrapper["schema"] == "mode5.native_probe_adapter_registration.v1"
             and wrapper["plan_identity"] == plan.identity and wrapper["exact_entry"] == entry
             and wrapper["authorization"] == auth and wrapper["financial_executions"] == 0
             and wrapper["recipe_approval"] is False and wrapper["same_original_preload_scoring"] is True,
             "externally sealed adapter lineage differs")
    _require(auth["schema"] == "mode5.native_probe_launch_authorization.v1"
             and auth["approved_by"] == "owner" and auth["launch_authorized"] is True
             and auth["plan_identity"] == plan.identity
             and catalog.require_ref(auth["plan_ref"]) == p
             and auth["request_sha256"] == entry["request_sha256"] == digest(entry["request"])
             and auth["output"] == str(parent) and type(auth["python_control"]) is bool
             and type(auth["numeric_threads"]) is int and auth["numeric_threads"] == 1
             and type(auth["financial_workers"]) is int and auth["financial_workers"] == 1
             and set(auth["thread_variables"]) == _THREADS
             and len(auth["thread_variables"]) == len(_THREADS), "exact external probe launch rights required")
    _require(type(auth["cap_seconds"]) in (int, float) and np.isfinite(auth["cap_seconds"])
             and 0 < auth["cap_seconds"] <= 1800 and wrapper["cap_seconds"] == auth["cap_seconds"]
             and recovery._count(auth["reserve_bytes"]) >= 5*1024**3
             and 0 < recovery._count(auth["retained_limit_bytes"]) <= 32*1024**2,
             "bounded original probe resources required")
    for key, role in (("runner_pin", "recovery_driver"), ("adapter_pin", "probe_adapter")):
        _require(role in approvals and auth[key] == wrapper[key] == approvals[role],
                 "externally approved owner/adapter identity required")
    recovery._sealed(auth["adapter_pin"], cutoff)
    approved = {recovery._pin(pin) for pin in approvals.values()}
    _require(recovery._pin(wrapper["original_preparation_source"]) in approved,
             "original preparation source lacks external approval")
    for pin in auth.get("runtime_source_pins", []):
        _require(recovery._pin(pin) in approved, "runtime dependency lacks external control approval")

    # Reconstruct the real launch access snapshot; later output sources do not
    # acquire retroactive availability or change the plan's input frontier.
    manifest = wrapper["catalog"]
    access = manifest["access"]
    policy = AccessPolicy(access["policy_id"], tuple(access["roles"]), tuple(access["manifests"]),
                          access["cutoff_ns"], access["purpose"])
    _require(policy.cutoff_ns <= cutoff and p["access"]["cutoff_ns"] <= policy.cutoff_ns,
             "future launch/plan access snapshot")
    sources = []
    for value in manifest["sources"]:
        source = Source(value["source_id"], value["path"], value["sha256"], value["bytes"],
                        AccessWitness(**value["witness"]))
        _require(catalog._sources.get(source.source_id) == source, "caller/launch access source differs")
        sources.append(source)
    launch = EvidenceCatalog(sources, policy)
    _require(launch.require_ref(auth_ref) == auth and launch.require_ref(auth["plan_ref"]) == p
             and diagnostic.regenerate_plan(plan, launch) == plan,
             "original source/access cannot regenerate sealed probe plan")
    completion = launch.require_ref(auth["admission_completion_ref"])
    admission = launch.require_ref(p["refs"]["admission"])
    proof = admission.get("actual_reader_proof", p["refs"]["admission"])
    _require(completion["status"] in {"PASS_SOURCE_ADMITTED_NATIVE384_PANELS", "PASS_ACTUAL_COLD_NATIVE384_PANELS"}
             and completion["all_owned_children_reaped"] is True
             and completion["proof"]["sha256"] == proof["sha256"], "closed original parent admission required")
    parent_request = launch.require_ref(entry["parent_request_ref"])
    _require(wrapper["parent_request"] == parent_request, "actual original parent request differs")
    return entry, wrapper, auth, diagnostic._parent_access(launch, entry["parent_authority"], parent_request)


def _original_request(entry, parent_request, worker, original, design, config, contract, cutoff):
    request = entry["request"]
    role = request["role"]
    _require(role in _RIGHTS and entry["rights"] == _RIGHTS[role]
             and entry["clean_oos"] is False and entry["annual_local_authorized"] is False
             and canonical(worker["request"]) == canonical(request), "original exact probe request/role required")
    protocol = ResearchProtocol(**original["protocol"])
    _require(original["protocol_id"] == protocol.identity
             and original["financial_outcomes_used_to_choose_design"] is False
             and original["forward_selection"] is False and panels._ns(original["created_at"]) <= cutoff
             and (protocol.preload_start, protocol.development_start, protocol.development_stop)
                 == ("2020-01-01", "2021-01-01", "2024-01-01")
             and protocol.data_role == "DEVELOPMENT_REVIEWED_RETROSPECTIVE"
             and all(request[k] == v for k, v in diagnostic.BASE.items())
             and type(request["max_feedback_runs"]) is int
             and design["alpha"] == request["alpha"]
             and request["parent_design_id"] == design["design_id"]
             and original["symbols"][request["alpha"]] == request["symbol"], "original broad authority/calendar changed")
    recovery._count(request["parent_panel_index"])
    row_id = recovery._count(parent_request["proposal_row"])
    proposals = [row for row in design["rows"] if type(row["row_id"]) is int and row["row_id"] == row_id]
    _require(len(proposals) == 1, "unique original parent proposal required")
    proposal = proposals[0]
    _require(proposal["admitted"] is True and proposal["status"] == "READY"
             and proposal["role"] == "exploration" and proposal.get("duplicate_of") is None
             and proposal["candidate_id"] == parent_request["candidate_id"] == request["parent_candidate_id"]
             and canonical(proposal["effective"]) == canonical(parent_request["params"]), "original broad parent changed")
    for key in ("alpha", "candidate_id", "design_id", "symbol"):
        recovery._public_id(request[key])
    start, stop = panels._ns(request["start"]), panels._ns(request["stop"])
    expected = ReportingContractV1(scope="full", unit="account_period", currency=contract.currency,
        baseline_equity=config["account"]["initial_capital"], baseline_time_ns=start-panels.HOUR_NS,
        scope_end_ns=stop-panels.HOUR_NS, sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
    _require(contract == expected and config["timeframe"] == "1h"
             and config["execution_contract"] == "event_lifecycle_v3_next_open"
             and config["terminal_policy"] == "mark_only_no_hidden_flatten"
             and config["account"]["use_funding"] is False, "original report/economic contract changed")
    return protocol, start, stop


def _completed_result(result, worker, wrapper, auth, pins, parent, cutoff):
    _require(result["status"] == recovery.RECOVERY_STATUS
             and result["typed_lifecycle_terminal_parity"] is True and result["original_compiler_parity"] is True
             and result["future_tape_opened"] is False and result["clean_oos"] is False
             and result["panel_complete"] is False, "completed original compiler/lifecycle/terminal result required")
    for key, name in (("registration", "worker_registration"), ("paths", "paths"),
                      ("campaigns_ledger", "campaigns"), ("fills_ledger", "fills")):
        _require(result[key] == pins[name], "original result/caller seal differs")
    control = auth["python_control"]
    _require(worker["native_gate"] == pins["native_gate"] and worker["methodology_changed"] is False
             and worker["guard_policy"] == "boundary_full_hash_v1" and worker["control"] is control
             and worker["dense_owner_retained"] is control
             and type(worker["python_oracle_calls_planned"]) is int
             and worker["python_oracle_calls_planned"] == int(control)
             and worker["cap_seconds"] == auth["cap_seconds"]
             and recovery._count(worker["reserve_bytes"]) >= auth["reserve_bytes"]
             and recovery._count(worker["retained_limit_bytes"], 1) <= 256*1024**2 and worker["scratch"] == [],
             "unchanged original worker registration required")
    feedback, normal, python = (recovery._count(result[k], minimum) for k, minimum in
        (("native_feedback_calls", 1), ("final_native_calls", 1), ("python_oracle_calls", 0)))
    _require(normal == wrapper["expected_final_native_calls"] == (2 if control else 1)
             and python == wrapper["expected_python_oracle_calls"] == int(control)
             and (result["owner"] is not None) == control, "actual registered control/account call coverage differs")
    if control:
        _require(Path(result["owner"]["path"]) == parent / "actual_owner.pkl", "orphan original control owner")
        recovery._sealed(result["owner"], cutoff)
    _require(recovery._count(result["bar_steps"]) - recovery._count(result["bar_retries"]) == 26280,
             "full committed original decision calendar required")
    for key, cap in (("wall_seconds", auth["cap_seconds"]), ("peak_rss_mib", 2048.), ("accounting_residual", 1e-8)):
        _require(type(result[key]) in (int, float) and np.isfinite(result[key]) and 0 <= result[key] <= cap,
                 "actual original qualification/resource bound failed")
    cleanup, closure = (recovery._json(pins[k], cutoff) for k in ("cleanup", "closure"))
    _require(cleanup["status"] == "NO_SCRATCH_CREATED" and cleanup["deleted"] == []
             and cleanup["preserved_evidence"] is True
             and recovery._count(cleanup["free_bytes"]) >= auth["reserve_bytes"], "original owner cleanup/reserve failed")
    _require(closure["schema"] == CLOSURE_SCHEMA and closure["status"] == "PASS"
             and closure["result"] == pins["result"] and closure["cleanup"] == pins["cleanup"]
             and closure["adapter_registration"] == pins["adapter_registration"]
             and closure["request_sha256"] == auth["request_sha256"]
             and type(closure["returncode"]) is int and closure["returncode"] == 0
             and closure["all_owned_children_reaped"] is True
             and recovery._count(closure["free_bytes"]) >= auth["reserve_bytes"]
             and recovery._count(closure["free_inodes"], 1), "externally sealed reaped-worker closure required")
    controller, tranche, tranche_cleanup, config, authorization = (
        recovery._json(closure[k], cutoff) for k in
        ("controller_result", "tranche_result", "tranche_cleanup", "worker_config", "authorization"))
    actual = controller["entry"]
    _require(controller["status"] == "PASS_OWNER_ACCOUNT" and controller["reason"] is None
             and type(controller["returncode"]) is int and controller["returncode"] == 0
             and controller["all_owned_children_reaped"] is True
             and controller["original_result"] == pins["result"]
             and actual["authorization"] == closure["authorization"] and authorization == auth
             and actual["config"] == closure["worker_config"] and actual["output"] == str(parent)
             and actual["request_sha256"] == auth["request_sha256"]
             and config["entry_index"] == actual["entry_index"] == wrapper["exact_entry"]["index"]
             and config["authorization_ref"] == wrapper["authorization_ref"] and config["launch_authorized"] is True
             and canonical({k: config[k] for k in ("sources", "access")}) == canonical(wrapper["catalog"]),
             "actual controller/config/authorization closure differs")
    completed = [c for c in tranche["completed"] if c["receipt"] == closure["controller_result"]]
    _require(tranche["status"] == "PASS_PROBE_TRANCHE" and tranche["stop_reason"] is None
             and tranche["pending"] == [] and tranche["protected_inputs_unchanged"] is True
             and tranche["all_owned_children_reaped"] is True and len(completed) == 1
             and {k: v for k, v in completed[0].items() if k != "receipt"} == controller
             and tranche_cleanup["status"] == "PASS" and tranche_cleanup["result"] == closure["tranche_result"]
             and tranche_cleanup["protected_inputs_unchanged"] is True
             and tranche_cleanup["all_owned_children_reaped"] is True
             and tranche_cleanup["resources_after"]["free_bytes"] == closure["free_bytes"]
             and tranche_cleanup["resources_after"]["free_inodes"] == closure["free_inodes"],
             "actual completed tranche cleanup/custody differs")
    retained = sum(p.stat().st_size for p in parent.rglob("*") if p.is_file())
    _require(not any(p.is_symlink() for p in parent.rglob("*"))
             and recovery._count(closure["retained_bytes"]) >= retained
             and retained + pins["adapter_registration"]["bytes"] <= auth["retained_limit_bytes"]
             and closure["retained_bytes"] <= auth["retained_limit_bytes"], "actual separate probe retained cap failed")
    return feedback, normal, python


def load_native_probe_cell(result_path, *, artifact_pins, approved_source_pins, plan, catalog,
                           entry_index, contract, cutoff_ns, study_id, diagnostic_revision,
                           data_cutoff_ns=None):
    """Read one completed probe using independent external seals, never an engine.

    artifact_pins adds adapter_registration, cleanup and closure to the original
    recovery inventory. The sibling adapter-registration is unchanged. Closure
    is a separate caller-sealed mode5.native_probe_closure.v1 receipt with PASS,
    result/cleanup/adapter_registration pins, request_sha256, returncode=0,
    all_owned_children_reaped=True, retained_bytes, free_bytes and free_inodes,
    plus controller_result, tranche_result, tranche_cleanup, worker_config and
    authorization pins linking the real closed supervisor evidence.
    It is not written or inferred here. approved_source_pins also needs the exact
    probe_adapter identity and original preparation/runtime source identities.
    """
    _require(_REQUIRED <= artifact_pins.keys(), "complete external probe artifact inventory required")
    _require(type(cutoff_ns) is int and cutoff_ns > 0 and isinstance(contract, ReportingContractV1),
             "typed original contract and exact retrospective cutoff required")
    recovery._public_id(study_id)
    recovery._public_id(diagnostic_revision)
    pins = {k: dict(artifact_pins[k]) for k in _REQUIRED}
    approvals = {k: dict(v) for k, v in approved_source_pins.items()}
    path = Path(result_path)
    parent = path.resolve().parent
    _require(path.is_absolute() and path == path.resolve(), "canonical original result path required")
    for name, filename in (("result", "result.json"), ("worker_registration", "registration.json"),
                           ("paths", "paths.npz"), ("campaigns", "campaigns.json"),
                           ("fills", "fills.json"), ("cleanup", "cleanup.json")):
        _require(Path(pins[name]["path"]) == parent / filename, "orphan original probe artifact")
    _require(Path(pins["adapter_registration"]["path"]) == parent.with_name(parent.name+"-adapter-registration.json"),
             "orphan original adapter registration")
    _require(not any((parent / name).exists() for name in ("failure.json", "FAIL.json", "censored.json")),
             "failed/censored probe cannot be admitted")
    result, worker, original, design, config = (recovery._json(pins[k], cutoff_ns) for k in
        ("result", "worker_registration", "original_registration", "design", "economic_config"))
    entry, wrapper, auth, parent_market = _launch_lineage(
        plan, catalog, entry_index, pins, approvals, cutoff_ns, parent)
    _require(canonical(design) == canonical(catalog.require_ref(plan.data["refs"]["design"])),
             "original worker broad design differs from plan authority")
    _require(canonical(result["request"]) == canonical(entry["request"]), "actual result differs from exact planned request")
    protocol, start, stop = _original_request(entry, wrapper["parent_request"], worker, original, design, config, contract, cutoff_ns)
    calls = _completed_result(result, worker, wrapper, auth, pins, parent, cutoff_ns)
    data_cutoff_ns = stop if data_cutoff_ns is None else data_cutoff_ns
    _require(type(data_cutoff_ns) is int and stop <= data_cutoff_ns <= cutoff_ns, "immature/future development scope")
    witness = recovery._sources(worker, pins, approvals, parent, cutoff_ns)
    _require(witness["sha256"] == parent_market, "original parent/probe development access differs")
    arrays, observations, report, campaigns, fills = recovery._account(
        pins, witness, entry["request"], protocol, config, contract, cutoff_ns)
    for key, count in (("fills", len(fills)), ("closed_campaigns", len(campaigns["closed"])),
                       ("open_campaigns", len(campaigns["open"]))):
        _require(recovery._count(result[key]) == count, "actual retained support count differs")
    metrics = recovery._public_metrics(result["metrics"])
    for source, target in (("account.total_return", "total_return"), ("drawdown.max_depth", "max_drawdown"),
                           ("period.sharpe", "sharpe")):
        expected, retained = report.metric(source).value, metrics[target]
        _require((expected is None and retained is None) or (expected is not None and type(retained) in (int, float)
                 and np.isclose(expected, retained, rtol=0, atol=1e-10)), "original metric authority differs")
    _require(type(metrics["daily_count"]) is int and metrics["daily_count"] == 1095
             and metrics["account_mode"] == entry["request"]["account_mode"], "original retained metric scope differs")
    request = entry["request"]
    hood = next(h for h in plan.data["neighborhoods"] if h["neighborhood_id"] == request["design_id"])
    proposal = next(r for r in hood["rows"] if r["execution_index"] == entry_index)
    refs = {k: pin["sha256"] for k, pin in pins.items()}
    refs.update({"source."+k: pin["sha256"] for k, pin in approvals.items()})
    refs.update(development_data=witness["sha256"], plan=plan.identity, request=entry["request_sha256"],
                authorization=wrapper["authorization_ref"]["sha256"])
    provenance = panels.CandidateProvenance(study_id, diagnostic_revision, request["alpha"], request["candidate_id"],
        digest(proposal["requested"]), digest(request["params"]), request["probe_direction"], (request["proposal_row"],),
        pins["result"]["sha256"], request["design_id"], request["symbol"], request["role"], _LIMITATIONS[0],
        panels._ns(protocol.preload_start), data_cutoff_ns, cutoff_ns, cutoff_ns,
        "unchanged_fast_native_exact_registered_probe", tuple(sorted(refs.items())))
    buffers = tuple(FrozenBuffer.from_array(k, arrays[k]) for k in ("positions", "fees", "funding", "turnover"))
    schema = result.get("schema")
    if schema is not None:
        recovery._public_id(schema)
    coverage = {k: v for k, v in entry["parent_authority"].items() if k in {
        "source_reader_schema", "source_compute_status", "source_data_role", "oracle_coverage",
        "original_alias_coverage", "original_terminal_limitations", "early_source_limitations"}}
    for pin in (*pins.values(), witness, *(s["retained"] for s in worker["source_snapshots"])):
        recovery._sealed(pin, cutoff_ns)
    catalog.verify_current()
    return NativeProbeCell(provenance, start, stop, contract, observations, buffers, canonical(campaigns),
        canonical(fills), canonical(metrics), result["status"], None, *calls, entry_index, plan.identity,
        canonical(request), entry["rights"], schema, canonical(coverage))


def analysis_compute_pass(row):
    """Explicit probe gate; never counterfeit a neutral panel admission/status."""
    return (row.get("probe_admission_schema") == diagnostic.PROBE_SCHEMA
            and row.get("source_reader_schema") == READER_SCHEMA
            and row.get("analysis_compute_status") == "PASS"
            and row.get("compute_status") == recovery.RECOVERY_STATUS
            and row.get("provenance", {}).get("data_role") in _RIGHTS
            and row.get("rights") == _RIGHTS.get(row.get("provenance", {}).get("data_role"))
            and row.get("annual_local_authorized") is False and row.get("clean_oos") is False
            and "panel_admission_schema" not in row)


def admit_probe_views(cells, *, plan, utility_policy):
    """Four dependent rows per verified probe, shaped for normalized_rows."""
    _require(isinstance(plan, Record) and isinstance(utility_policy, panels.UtilityPolicy), "typed plan/utility required")
    rows, seen = [], set()
    for cell in cells:
        _require(type(cell) is NativeProbeCell and cell.plan_identity == plan.identity
                 and cell.execution_index not in seen, "distinct typed reader outputs bound to this plan required")
        seen.add(cell.execution_index)
        entry = plan.data["executions"][cell.execution_index]
        _require(canonical(entry["request"]) == cell.request_json and entry["rights"] == cell.rights
                 and cell.provenance.data_role == entry["request"]["role"]
                 and cell.compute_status == recovery.RECOVERY_STATUS and cell.observations is not None,
                 "probe reader lineage/status changed")
        views = panels.continuous_annual_rows(cell, utility_policy=utility_policy, backend="python")
        _require(tuple(v.environment_id for v in views) == diagnostic.ENVIRONMENTS, "four complete dependent views required")
        for view in views:
            value = {f.name: getattr(view, f.name) for f in fields(view)
                     if f.name not in {"provenance", "metrics", "raw_account_metrics", "environment_baseline", "carried_watermark"}}
            value.update(provenance=asdict(view.provenance), metrics=[asdict(m) for m in view.metrics],
                raw_account_metrics=view.raw_account_metrics.to_metadata() if view.raw_account_metrics is not None else None,
                environment_baseline=view.environment_baseline.to_metadata(), carried_watermark=view.carried_watermark.to_metadata(),
                probe_admission_schema=diagnostic.PROBE_SCHEMA, source_reader_schema=READER_SCHEMA,
                analysis_compute_status="PASS", rights=cell.rights, annual_local_authorized=False,
                original_result_schema=cell.original_result_schema, oracle_coverage=cell.oracle_coverage,
                actual_account_calls=[cell.native_feedback_calls, cell.normal_native_calls, cell.python_oracle_calls],
                parent_coverage=json.loads(cell.parent_coverage_json), source_limitations=list(cell.source_limitations))
            _require(analysis_compute_pass(value), "versioned native probe admission failed")
            rows.append(dict(execution_index=cell.execution_index, environment_id=view.environment_id,
                request_sha256=entry["request_sha256"], request=entry["request"], role=entry["request"]["role"],
                value=value, analysis_compute_status="PASS", annual_local_authorized=False, clean_oos=False))
    return Record.of(dict(schema=diagnostic.PROBE_SCHEMA, plan_identity=plan.identity, rows=rows,
        utility_policy=asdict(utility_policy), financial_executions=0, annual_local_authorized=False, clean_oos=False))
