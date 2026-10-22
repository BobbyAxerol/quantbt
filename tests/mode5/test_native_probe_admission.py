"""Software-only cold probe fixtures; no private alpha or account execution."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import numpy as np
import pytest

from quantbt.mode5.artifacts import file_identity
from quantbt.mode5.dossier.records import Record
from tools.mode5_diagnostics.identity import canonical, digest
from tools.mode5_research import native_diagnostics as diagnostic, native_probe_admission as admission
from tools.mode5_research import recovery_cells, selector_checkpoint
from tools.mode5_research.panels import UtilityPolicy, VerifiedCell, continuous_annual_rows

from test_native_diagnostics import Fixture as DiagnosticFixture
from test_recovery_cells import SyntheticRecovery


class ProbeFixture:
    def __init__(self, root, *, role="selection_probe", control=False, empty=False, sparse_ids=False):
        self.source = SyntheticRecovery(root, control=control, empty=empty)
        s = self.source
        self._symbol(s, "BTCUSDT")
        # Reuse only public synthetic metadata and fixed-fill arithmetic fixtures.
        directory = root / "diagnostic"
        directory.mkdir()
        d = self.diagnostic = DiagnosticFixture(directory)
        if sparse_ids:
            for i, row in enumerate(d.design["rows"]):
                row["row_id"] = 2*i+1
                d.requests[i]["proposal_row"] = row["row_id"]
            d.panel["original_design_digest"] = digest(d.design)
        for row in d.panel["candidate_environment_rows"]:
            row["provenance"]["symbol"] = "BTCUSDT"
            refs = dict(row["provenance"]["evidence_refs"])
            refs["development_data"] = s.documents["worker_registration"]["pins"][-1]["sha256"]
            row["provenance"]["evidence_refs"] = list(refs.items())
        d.access["witness"]["sha256"] = refs["development_data"]
        self.plan = d.seal()
        s.write("design", root / "design.json", d.design)
        s.revise("original_registration", lambda v: v.update(symbols={"A-HMA": "BTCUSDT"}))
        self.entry_index = next(e["index"] for e in self.plan.data["executions"] if e["request"]["role"] == role)
        self.entry = self.plan.data["executions"][self.entry_index]
        s.request = deepcopy(self.entry["request"])
        s.revise("worker_registration", lambda v: v.update(request=s.request))
        s.revise("result", lambda v: v.update(request=s.request))
        adapter, preparation = root / "probe_adapter.py", root / "original_preparation.py"
        adapter.write_text("# Inert externally approved adapter fixture.\n", encoding="ascii")
        preparation.write_text("# Inert original preparation fixture.\n", encoding="ascii")
        s.approvals["probe_adapter"] = file_identity(adapter)
        s.approvals["original_preparation"] = file_identity(preparation)
        worker = s.documents["worker_registration"]
        worker["pins"].append(s.approvals["original_preparation"])
        self.refresh_snapshots()
        self.plan_ref = d.put("frozen_plan", self.plan.data)
        self.completion_ref = d.put("parent_completion", dict(status="PASS_SOURCE_ADMITTED_NATIVE384_PANELS",
            all_owned_children_reaped=True, proof=dict(sha256=d.refs["admission"]["sha256"])))
        self.auth = dict(schema="mode5.native_probe_launch_authorization.v1", approved_by="owner",
            launch_authorized=True, plan_identity=self.plan.identity, plan_ref=self.plan_ref,
            request_sha256=self.entry["request_sha256"], output=str(s.worker), numeric_threads=1,
            financial_workers=1, thread_variables=sorted(admission._THREADS), cap_seconds=900.,
            reserve_bytes=5*1024**3, retained_limit_bytes=32*1024**2, python_control=control,
            runner_pin=s.approvals["recovery_driver"], adapter_pin=s.approvals["probe_adapter"],
            admission_completion_ref=self.completion_ref,
            runtime_source_pins=[s.approvals["original_preparation"]])
        self.auth_ref = d.put("launch_authorization", self.auth)
        wrapper = dict(schema="mode5.native_probe_adapter_registration.v1", plan_identity=self.plan.identity,
            exact_entry=self.entry, authorization_ref=self.auth_ref, authorization=self.auth,
            catalog=d.catalog().manifest.data, runner_pin=self.auth["runner_pin"], adapter_pin=self.auth["adapter_pin"],
            parent_request=d.catalog().require_ref(self.entry["parent_request_ref"]), cap_seconds=900.,
            original_preparation_source=s.approvals["original_preparation"],
            expected_final_native_calls=2 if control else 1, expected_python_oracle_calls=int(control),
            financial_executions=0, recipe_approval=False, same_original_preload_scoring=True)
        s.write("adapter_registration", root / "worker-adapter-registration.json", wrapper)
        s.write("cleanup", s.worker / "cleanup.json", dict(status="NO_SCRATCH_CREATED", deleted=[],
            preserved_evidence=True, free_bytes=6*1024**3))
        s.write("authorization", root / "authorization.json", self.auth)
        s.write("worker_config", root / "worker-config.json", dict(
            sources=wrapper["catalog"]["sources"], access=wrapper["catalog"]["access"],
            entry_index=self.entry_index, authorization_ref=self.auth_ref, launch_authorized=True))
        self.close()

    def _symbol(self, s, symbol):
        import pandas as pd
        witness = s.documents["worker_registration"]["pins"][-1]
        path = Path(witness["path"])
        market = pd.read_csv(path)
        market["symbol"] = symbol
        market.to_csv(path, index=False, compression="gzip")
        new = file_identity(path)
        s.documents["worker_registration"]["pins"][-1] = new
        metadata = Path(s.approvals["market_metadata"]["path"])
        metadata.write_text(canonical(dict(development=new)), encoding="ascii")
        s.approvals["market_metadata"] = file_identity(metadata)
        s.revise("fills", lambda rows: [row.update(symbol=symbol) for row in rows])

    def refresh_snapshots(self):
        s = self.source
        worker = s.documents["worker_registration"]
        native = json.loads(Path(s.pins["native_gate"]["path"]).read_text())["artifact"]
        witness = json.loads(Path(s.approvals["market_metadata"]["path"]).read_text())["development"]
        sources = [s.approvals[k] for k in ("alpha_source", "finance_driver", "recovery_driver", "market_metadata")]
        sources += [s.pins[k] for k in ("original_registration", "design", "economic_config")]
        sources += [s.approvals["original_preparation"]]
        shutil.rmtree(s.worker / "sources")
        (s.worker / "sources").mkdir()
        snapshots = []
        for i, pin in enumerate(sources):
            target = s.worker / "sources" / str(i)
            target.write_bytes(Path(pin["path"]).read_bytes())
            snapshots.append(dict(original=pin, retained=file_identity(target)))
        s.revise("worker_registration", lambda v: v.update(pins=sources+[native, witness], source_snapshots=snapshots))

    def close(self):
        s = self.source
        retained = sum(p.stat().st_size for p in s.worker.rglob("*") if p.is_file())
        controller = dict(status="PASS_OWNER_ACCOUNT", reason=None, returncode=0, all_owned_children_reaped=True,
            original_result=s.pins["result"], entry=dict(authorization=s.pins["authorization"],
                config=s.pins["worker_config"], output=str(s.worker), request_sha256=self.entry["request_sha256"],
                entry_index=self.entry_index))
        s.write("controller_result", s.root / "controller-result.json", controller)
        s.write("tranche_result", s.root / "tranche-result.json", dict(status="PASS_PROBE_TRANCHE", stop_reason=None,
            pending=[], protected_inputs_unchanged=True, all_owned_children_reaped=True,
            completed=[controller | dict(receipt=s.pins["controller_result"])]))
        s.write("tranche_cleanup", s.root / "tranche-cleanup.json", dict(status="PASS", result=s.pins["tranche_result"],
            protected_inputs_unchanged=True, all_owned_children_reaped=True,
            resources_after=dict(free_bytes=6*1024**3, free_inodes=100)))
        s.write("closure", s.root / "closure.json", dict(schema=admission.CLOSURE_SCHEMA, status="PASS",
            result=s.pins["result"], cleanup=s.pins["cleanup"], adapter_registration=s.pins["adapter_registration"],
            request_sha256=self.entry["request_sha256"], returncode=0, all_owned_children_reaped=True,
            retained_bytes=retained+s.pins["adapter_registration"]["bytes"], free_bytes=6*1024**3, free_inodes=100,
            **{k: s.pins[k] for k in ("controller_result", "tranche_result", "tranche_cleanup", "worker_config", "authorization")}))

    def load(self, **changes):
        s = self.source
        return admission.load_native_probe_cell(s.pins["result"]["path"], **(dict(artifact_pins=s.pins,
            approved_source_pins=s.approvals, plan=self.plan, catalog=self.diagnostic.catalog(),
            entry_index=self.entry_index, contract=s.contract, cutoff_ns=s.cutoff,
            study_id="synthetic_study", diagnostic_revision="cold_01") | changes))


@pytest.fixture
def probe(tmp_path):
    value = ProbeFixture(tmp_path)
    yield value
    shutil.rmtree(tmp_path)


@pytest.mark.parametrize("role,control,sparse_ids", [("selection_probe", False, False), ("local_validation", False, False),
    ("selection_probe", True, False), ("local_validation", True, False), ("selection_probe", False, True)])
def test_exact_qualified_probe_preserves_original_authority_and_coverage(tmp_path, role, control, sparse_ids):
    f = ProbeFixture(tmp_path, role=role, control=control, sparse_ids=sparse_ids)
    s = f.source
    before = {key: file_identity(pin["path"]) for key, pin in s.pins.items()}
    with patch.object(recovery_cells, "load_recovery_cell", side_effect=AssertionError("neutral loader prohibited")), \
            patch.object(diagnostic, "execute_sealed_probe", side_effect=AssertionError("financial execution prohibited")), \
            patch("pickle.load", side_effect=AssertionError("unpickle prohibited")):
        cell = f.load()
    assert isinstance(cell, VerifiedCell) and type(cell) is admission.NativeProbeCell
    assert cell.provenance.data_role == role and cell.rights == admission._RIGHTS[role]
    assert cell.compute_status == recovery_cells.RECOVERY_STATUS and cell.reader_schema == admission.READER_SCHEMA
    assert cell.original_result_schema is None
    if sparse_ids:
        assert f.entry["request"]["parent_panel_index"] != f.source.documents["adapter_registration"]["parent_request"]["proposal_row"]
    assert cell.python_oracle_calls == int(control) and cell.normal_native_calls == (2 if control else 1)
    assert cell.actual_execution_calls == (10 if control else 8)
    assert cell.visited_bars == cell.actual_execution_calls * 26280
    assert ("NO_FRESH_PYTHON_ORACLE" in cell.oracle_coverage) is not control
    assert all(file_identity(pin["path"]) == before[key] for key, pin in s.pins.items())
    with pytest.raises(FrozenInstanceError):
        cell.rights = "selection"
    with pytest.raises(ValueError):
        s.load()
    shutil.rmtree(tmp_path)


def test_admitted_four_views_feed_real_normalized_rows_without_panel_counterfeit(probe):
    cell = probe.load()
    utility = UtilityPolicy("synthetic_preference", 1., 1.)
    envelope = admission.admit_probe_views([cell], plan=probe.plan, utility_policy=utility)
    rows = envelope.data["rows"]
    direct = continuous_annual_rows(cell, utility_policy=utility)
    assert [r["environment_id"] for r in rows] == list(diagnostic.ENVIRONMENTS)
    assert [r["value"]["money_pnl"] for r in rows] == [r.money_pnl for r in direct]
    assert np.isclose(sum(r["value"]["money_pnl"] for r in rows[1:]), rows[0]["value"]["money_pnl"])
    assert all(admission.analysis_compute_pass(r["value"]) for r in rows)
    assert all(not selector_checkpoint.compute_pass(r["value"]) for r in rows)
    assert all("panel_admission_schema" not in r["value"] and r["value"]["compute_status"] != "PASS" for r in rows)
    ref = probe.diagnostic.put("admitted_probe_views", envelope.data)
    normalized = diagnostic.normalized_rows(probe.plan, probe.diagnostic.catalog(), probe_views_ref=ref).data
    observed = [r for r in normalized["values"]["center_neighbor_environment"]
                if r["operation"] == "probe" and r["status"] == "OBSERVED"]
    assert len(observed) == 4 and all(not r["annual_local_authorized"] and not r["independent_oos"] for r in observed)
    assert all(r["value"]["provenance"]["data_role"] == "selection_probe" for r in observed)


def test_no_trade_is_valid_with_null_sharpe_not_failed_or_alpha_quality(tmp_path):
    f = ProbeFixture(tmp_path, empty=True, role="local_validation")
    envelope = admission.admit_probe_views([f.load()], plan=f.plan, utility_policy=UtilityPolicy("synthetic", 1., 1.))
    for row in envelope.data["rows"]:
        assert row["value"]["status"] == "VALID_NO_TRADE"
        sharpe = next(m for m in row["value"]["metrics"] if m["metric_id"] == "mode5.panel.sharpe")
        assert sharpe["value"] is None and sharpe["reason"]
        assert row["role"] == "local_validation" and row["value"]["rights"] == "post_decision_reporting_only"
    shutil.rmtree(tmp_path)


@pytest.mark.parametrize("key,value", [("status", "PASS"), ("original_compiler_parity", False),
    ("typed_lifecycle_terminal_parity", False), ("future_tape_opened", True), ("clean_oos", True),
    ("panel_complete", True), ("bar_steps", 26279), ("bar_retries", 1), ("bar_retries", False),
    ("native_feedback_calls", 0), ("native_feedback_calls", True), ("final_native_calls", 2),
    ("python_oracle_calls", 1), ("wall_seconds", 901.), ("peak_rss_mib", 2049.),
    ("accounting_residual", 1e-7), ("fills", 0), ("closed_campaigns", 0), ("open_campaigns", 0)])
def test_original_result_mutations_fail_closed(probe, key, value):
    probe.source.revise("result", lambda v: v.update({key: value}))
    probe.close()
    with pytest.raises(ValueError):
        probe.load()


@pytest.mark.parametrize("key,value", [("params", {"low": .123, "high": 1.5}), ("role", "NEUTRAL_BROAD_DISCOVERY"),
    ("role", "local_validation"), ("start", "2022-01-01"), ("stop", "2023-01-01"),
    ("candidate_id", digest("forged")), ("design_id", digest("forged")), ("parent_panel_index", 0),
    ("probe_seed", 733), ("probe_radius", .12), ("probe_direction", "forged"), ("proposal_row", 9999)])
def test_result_request_cannot_change_role_geometry_calendar_or_candidate(probe, key, value):
    probe.source.revise("result", lambda v: v["request"].update({key: value}))
    probe.close()
    with pytest.raises(ValueError):
        probe.load()


@pytest.mark.parametrize("name,key,value", [
    ("worker_registration", "methodology_changed", True), ("worker_registration", "control", True),
    ("worker_registration", "dense_owner_retained", True), ("worker_registration", "python_oracle_calls_planned", 1),
    ("worker_registration", "reserve_bytes", 0), ("worker_registration", "guard_policy", "forged"),
    ("adapter_registration", "plan_identity", digest("forged")), ("adapter_registration", "same_original_preload_scoring", False),
    ("cleanup", "free_bytes", 1), ("cleanup", "preserved_evidence", False),
    ("closure", "status", "CENSORED"), ("closure", "all_owned_children_reaped", False),
    ("closure", "returncode", 1), ("closure", "free_inodes", 0), ("closure", "free_bytes", 1),
    ("closure", "retained_bytes", 33*1024**2), ("closure", "request_sha256", digest("forged"))])
def test_separate_registration_cleanup_and_closed_worker_are_mandatory(probe, name, key, value):
    if name == "closure":
        probe.source.revise(name, lambda v: v.update({key: value}))
    else:
        probe.source.revise(name, lambda v: v.update({key: value}))
        probe.close()
    with pytest.raises(ValueError):
        probe.load()


@pytest.mark.parametrize("mutation", ["result_bytes", "snapshot_bytes", "missing_approval", "wrong_adapter",
    "future_cutoff", "failure", "censored", "short_calendar", "wrong_daily", "wrong_metric", "wrong_campaign",
    "missing_closure", "different_design", "different_plan", "different_entry"])
def test_external_seals_sources_account_and_plan_mutations_are_rejected(probe, mutation):
    s, changes = probe.source, {}
    if mutation == "result_bytes":
        Path(s.pins["result"]["path"]).write_bytes(b"{}")
    elif mutation == "snapshot_bytes":
        path = s.documents["worker_registration"]["source_snapshots"][0]["retained"]["path"]
        Path(path).write_bytes(b"altered snapshot")
    elif mutation in {"missing_approval", "wrong_adapter"}:
        approvals = deepcopy(s.approvals)
        if mutation == "missing_approval":
            approvals.pop("alpha_source")
        else:
            approvals["probe_adapter"] = approvals["recovery_driver"]
        changes["approved_source_pins"] = approvals
    elif mutation == "future_cutoff":
        changes["cutoff_ns"] = 1
    elif mutation in {"failure", "censored"}:
        (s.worker / (mutation+".json")).write_text("{}", encoding="ascii")
    elif mutation in {"short_calendar", "wrong_daily"}:
        if mutation == "short_calendar":
            s.arrays["times_ns"] = s.arrays["times_ns"][:-1]
        else:
            s.arrays["daily_returns"] = s.arrays["daily_returns"].copy()
            s.arrays["daily_returns"][0] = .9
        s.paths()
        probe.close()
    elif mutation == "wrong_metric":
        s.revise("result", lambda v: v["metrics"].update(total_return=.9))
        probe.close()
    elif mutation == "wrong_campaign":
        s.revise("campaigns", lambda v: v["closed"][0].update(net_pnl=1000.))
        probe.close()
    elif mutation == "missing_closure":
        changes["artifact_pins"] = {k: v for k, v in s.pins.items() if k != "closure"}
    elif mutation == "different_design":
        s.revise("design", lambda v: v["rows"][0]["effective"].update(low=.9))
    elif mutation == "different_plan":
        plan = probe.plan.data
        plan["executions"][probe.entry_index]["request"]["role"] = "local_validation"
        changes["plan"] = Record.of(plan)
    else:
        changes["entry_index"] = probe.entry_index+1
    with pytest.raises((ValueError, PermissionError)):
        probe.load(**changes)


@pytest.mark.parametrize("key,value", [("approved_by", "subject"), ("launch_authorized", False),
    ("numeric_threads", 2), ("financial_workers", 2), ("cap_seconds", 1801.), ("reserve_bytes", 0),
    ("retained_limit_bytes", 33*1024**2), ("request_sha256", digest("forged")), ("python_control", True)])
def test_subject_cannot_self_approve_or_expand_external_launch_rights(probe, key, value):
    # Change both adapter-embedded auth and real external auth, not just one copy.
    auth = deepcopy(probe.auth)
    auth[key] = value
    ref = probe.diagnostic.put("amended_authorization", auth)
    s = probe.source
    s.revise("adapter_registration", lambda v: v.update(authorization=auth, authorization_ref=ref,
        catalog=probe.diagnostic.catalog().manifest.data))
    probe.close()
    with pytest.raises(ValueError):
        probe.load()


def test_view_gate_rejects_neutral_counterfeit_and_held_selection_rights(probe):
    cell = probe.load()
    utility = UtilityPolicy("synthetic", 1., 1.)
    row = admission.admit_probe_views([cell], plan=probe.plan, utility_policy=utility).data["rows"][0]["value"]
    for mutate in (lambda r: r.update(panel_admission_schema="source_admitted_continuous_panel_v1"),
                   lambda r: r["provenance"].update(data_role="NEUTRAL_BROAD_DISCOVERY"),
                   lambda r: r.update(compute_status="PASS"), lambda r: r.update(annual_local_authorized=True),
                   lambda r: r.update(rights="post_decision_reporting_only")):
        bad = deepcopy(row)
        mutate(bad)
        assert not admission.analysis_compute_pass(bad)
    with pytest.raises(ValueError):
        admission.admit_probe_views([cell, cell], plan=probe.plan, utility_policy=utility)
    with pytest.raises(ValueError):
        admission.admit_probe_views([replace(cell, rights="post_decision_reporting_only")], plan=probe.plan, utility_policy=utility)


@pytest.mark.parametrize("name,key,value", [("controller_result", "all_owned_children_reaped", False),
    ("controller_result", "status", "FAIL_PRESERVED"), ("controller_result", "reason", "worker failure"),
    ("tranche_result", "protected_inputs_unchanged", False), ("tranche_cleanup", "status", "FAIL"),
    ("worker_config", "entry_index", 9999)])
def test_closure_is_bound_to_real_controller_custody_not_subject_success(probe, name, key, value):
    s = probe.source
    s.revise(name, lambda v: v.update({key: value}))
    s.revise("closure", lambda v: v.update({name: s.pins[name]}))
    with pytest.raises(ValueError):
        probe.load()
