"""Synthetic metadata fixtures only; no financial imports, accounts or tapes."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.evidence import EvidenceCatalog, KINDS, Source
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.geometry.schema import EffectiveGeometry, OrderedConstraint
from quantbt.mode5.statistics.contracts import MetricValue
from tools.mode5_geometry.neighborhoods import active_neighbors
from tools.mode5_research import native_diagnostics as n, panel_admission as a
from tools.mode5_research import selector_checkpoint as selector


CUTOFF = 1791763200000000000
ALPHA_SOURCE, ECONOMICS, MARKET = (digest("public_synthetic_"+s) for s in ("alpha", "economics", "market"))


def synthetic_row(index, cid, design_id, env):
    start = a.START if env == "whole_path" else a.panels._ns(env+"-01-01")
    stop = a.STOP if env == "whole_path" else a.panels._ns(str(int(env)+1)+"-01-01")
    days = 1095 if env == "whole_path" else 365
    metrics = [asdict(MetricValue("mode5.panel."+key, "ratio" if key in {"sharpe", "return_step_pf"}
        else "decimal_return", days, value)) for key, value in
        (("economic_utility", index/1000.), ("drawdown", .1), ("daily_loss_es", .01),
         ("net_return", .2), ("sharpe", 1.), ("daily_mean_return", .001), ("return_step_pf", 2.))]
    refs = {"source.alpha_source": ALPHA_SOURCE, "development_data": MARKET, "paths": digest("path"+str(index))}
    p = dict(candidate_id=cid, design_id=design_id, symbol="BTCUSDT", execution_id=digest("execution"+str(index)),
        data_role="REVIEWED_EXPLORATORY_DEVELOPMENT", warmup_start_ns=1577836800000000000,
        data_cutoff_ns=a.STOP, evidence_refs=list(refs.items()))
    cert = a.ReaderCertification(a.ORIGINAL_SCHEMA, digest("synthetic_cell"+str(index)), ALPHA_SOURCE, ECONOMICS)
    raw = [dict(metric_id="reporting."+a._RAW_METRICS[m["metric_id"].removeprefix("mode5.panel.")],
                value=m["value"], status=m["status"].lower(), reason=m["reason"], sample_count=m["sample_count"])
           for m in metrics if m["metric_id"].removeprefix("mode5.panel.") in a._RAW_METRICS]
    return dict(index=index, panel_admission_schema=a.PANEL_SCHEMA, source_reader_schema=a.ORIGINAL_SCHEMA,
        analysis_compute_status="PASS", compute_status="PASS", reader_cell_identity=cert.cell_identity,
        alpha_source_digest=ALPHA_SOURCE, economic_config_digest=ECONOMICS, reader_certification_id=digest(asdict(cert)),
        provenance=p, environment_id=env, environment_family="continuous_account" if env == "whole_path" else "annual_anchor",
        start_ns=start, stop_ns=stop, calendar_days=days, actual_bar_count=24*days,
        clean_oos=False, estimand_id="CONTINUOUS_PATH_ATTRIBUTION", status="VALID_PROFITABLE", reason=None,
        metrics=metrics, null_reasons=[], raw_account_metrics=dict(metrics=raw), fills=30, closed_campaigns=20,
        oracle_coverage=a.ORIGINAL_ORACLE, recovery_account_calls=None)


class Fixture:
    def __init__(self, path):
        self.path, self.sources = path, []
        self.policy = AccessPolicy("public_synthetic", ("synthetic",), ("synthetic",), CUTOFF, "diagnostic")
        self.witness = AccessWitness("synthetic", "synthetic", a.START, a.STOP, CUTOFF)
        self.geometry = EffectiveGeometry.from_ranges({"low": (0., 1.), "high": (1., 2.)},
            constraints=(OrderedConstraint(("low", "high")),))
        params = [dict(low=(i % 16 + .2)/16, high=1+(i//16+.2)/8) for i in range(128)]
        points = [self.geometry.resolve(p) for p in params]
        self.design = dict(alpha="A-HMA", design_id=digest("public_synthetic_design"), schema_id=self.geometry.identity,
            rows=[dict(row_id=i, admitted=True, status="READY", role="exploration", effective=p.params,
                requested=p.params, candidate_id=p.identity, duplicate_of=None) for i, p in enumerate(points)])
        self.panel = dict(schema=a.PANEL_SCHEMA, original_design_digest=digest(self.design), cutoff_ns=CUTOFF,
            candidate_ids=[p.identity for p in points], candidate_environment_rows=[
                synthetic_row(i, p.identity, self.design["design_id"], env) for i, p in enumerate(points) for env in n.ENVIRONMENTS])
        self.analysis = dict(schema="mode5_broad_analysis_v1", role="REVIEWED_EXPLORATORY_DEVELOPMENT",
            forward_snapshot_allowed=False, clean_independent_claim=False,
            center_policy=n.CENTER_POLICY | dict(fallback="deterministic geometric controls with QUALITY_FAIL/INSUFFICIENT_SUPPORT, never promoted as good basin"),
            neighbors=n.NEIGHBOR_POLICY | dict(no_reuse_of_selection_probes_as_independent_confirmation=True),
            batteries={k: "PUBLIC_SYNTHETIC_REGISTERED_NOT_RUN" for k in n.BATTERIES})
        self.requests = [n.BASE | dict(alpha="A-HMA", symbol="BTCUSDT", params=p.params, candidate_id=p.identity,
            design_id=self.design["design_id"], proposal_row=i, role="NEUTRAL_BROAD_DISCOVERY") for i, p in enumerate(points)]
        self.access = dict(witness=dict(sha256=MARKET), allowed_stop=n.BASE["stop"], future_tape_opened=False,
            original_contract_preserved=True)

    def put(self, name, value):
        path = self.path / (name+".json")
        write_json(path, value)
        pin = file_identity(path)
        self.sources.append(Source(name, pin["path"], pin["sha256"], pin["bytes"], self.witness))
        return self.catalog().ref(name)

    def catalog(self):
        return EvidenceCatalog(self.sources, self.policy)

    def seal(self):
        refs = {k: self.put(k, getattr(self, k)) for k in ("analysis", "design", "panel")}
        rr, ar = self.put("requests", self.requests), self.put("access", self.access)
        parents = [dict(index=i, request_ref=dict(rr, pointer=f"/{i}"), access_ref=ar,
                        access_schema="original_development_access_v1") for i in range(128)]
        refs["parents"] = self.put("parents", parents)
        refs["admission"] = self.put("admission", dict(status="PASS_SOURCE_ADMITTED_NATIVE384_PANELS", actual_cells=384,
            views=1536, financial_executions=0, independent_oos=False, panels={"A-HMA": dict(sha256=refs["panel"]["sha256"])},
            limitations=["PUBLIC_SYNTHETIC_METADATA_NOT_FINANCIAL_PROOF"]))
        self.refs = refs
        return n.plan_native(self.catalog(), refs, self.geometry)

    def set_metric(self, name, value, *, indexes=range(128)):
        for row in self.panel["candidate_environment_rows"]:
            if row["index"] not in indexes:
                continue
            m = next(m for m in row["metrics"] if m["metric_id"] == "mode5.panel."+name)
            m["value"] = value
            if name in a._RAW_METRICS:
                raw = next(m for m in row["raw_account_metrics"]["metrics"] if m["metric_id"] == "reporting."+a._RAW_METRICS[name])
                raw["value"] = value


@pytest.fixture
def f(tmp_path):
    return Fixture(tmp_path)


def test_full_inventory_preserves_every_admitted_candidate_and_null_masks(f):
    plan = f.seal()
    p = plan.data
    assert p["counts"]["candidates"] == 128 and p["counts"]["candidate_environment_rows"] == 512
    assert set(p["inventory"]) == set(KINDS) and set(p["batteries"]) == set(n.BATTERIES)
    assert not p["launch_authorized"] and not p["recipe_approval"] and p["financial_executions"] == 0
    rows = n.normalized_rows(plan, f.catalog()).data
    assert sum(r["status"] == "OBSERVED" for r in rows["values"]["candidate_environment"]) == 512
    untested = [r for kind in ("environment_environment", "recipe_split_seed") for r in rows["values"][kind]]
    assert all(r["value"] is None and r["reason"] and r["metric_masks"] for r in untested)
    assert all(r["status"] == "NOT_TESTED" for r in rows["values"]["execution_stress"] if r["coordinates"]["scenario"] == "fee_x2")
    assert not rows["scientific_complete"]


def test_exact_top_quarter_two_center_rule_and_utility_ties(f):
    f.set_metric("economic_utility", .1)
    plan = f.seal()
    points = [f.geometry.resolve(r["effective"]) for r in f.design["rows"]]
    order = sorted(points, key=lambda p: p.identity)
    first = order[0]
    second = min(order[1:32], key=lambda p: (-f.geometry.distance(first, p), p.identity))
    assert [c["candidate_id"] for c in plan.data["centers"]] == [first.identity, second.identity]
    assert len(plan.data["center_disposition"]["top_ids"]) == 32


@pytest.mark.parametrize("utility,drawdown,fills,campaigns,eligible", [
    (0., .5, 30, 20, True), (-.001, .5, 30, 20, False), (0., .501, 30, 20, False),
    (0., .5, 29, 20, False), (0., .5, 30, 19, False), (0., .5, None, None, True)])
def test_original_quality_and_if_available_support_gates(f, utility, drawdown, fills, campaigns, eligible):
    row = f.panel["candidate_environment_rows"][0]
    f.set_metric("economic_utility", utility, indexes=[0])
    f.set_metric("drawdown", drawdown, indexes=[0])
    row.update(fills=fills, closed_campaigns=campaigns)
    q = n.quality(row)
    assert q["eligible"] == eligible
    if fills is None:
        assert q["quality_issue"] == "INSUFFICIENT_SUPPORT" and q["support"]["fills"] is None


def test_sparse_quality_uses_only_original_nonquality_controls(f):
    f.set_metric("economic_utility", -.01)
    f.set_metric("economic_utility", 1., indexes=[0])
    p = f.seal().data
    assert p["center_disposition"]["eligible_count"] == 1
    assert p["center_disposition"]["quality_issue"] == "FEWER_THAN_TWO_QUALITY_CENTERS"
    assert all(not c["quality_center"] for c in p["centers"])
    assert all(h["covariance_status"] in {"SCHEMA_ONLY_NO_CLOUD", "SCHEMA_ONLY_SPARSE_CLOUD"} for h in p["neighborhoods"])


def test_proposals_are_exact_existing_owner_schema_joint_covariance_union(f):
    p = f.seal().data
    points = [f.geometry.resolve(r["effective"]) for r in f.design["rows"]]
    by_id = {p.identity: p for p in points}
    for hood in p["neighborhoods"]:
        center = p["centers"][hood["center"]]
        expected = active_neighbors(f.geometry, by_id[center["candidate_id"]], radius=hood["radius"], seed=hood["seed"],
            role=hood["role"], minimum_radius=.05, joint_groups=(("low", "high"),), cloud=tuple(by_id[x] for x in center["cloud_ids"]),
            rho=.2, tau=.001, minimum_cloud=5, cloud_radius=.25)
        assert [(r["status"], r["direction"], r["effective"]) for r in hood["rows"]] == [
            (r.status, r.direction, r.point.params if r.point else None) for r in expected.rows]
        assert any(r["direction"].startswith("joint:") for r in hood["rows"])
        assert set(hood["comparison_sets"]["schema"]) | set(hood["comparison_sets"]["covariance"]) == set(hood["comparison_sets"]["union"])
        assert not hood["covariance_alone_replaces_schema"]
    assert any(h["covariance_status"] == "REGULARIZED_PROPOSALS_NOT_HESSIAN" for h in p["neighborhoods"])


def test_selection_held_overlap_is_retained_not_independent(f):
    plan = f.seal()
    p = plan.data
    assert {e["request"]["role"] for e in p["executions"]} == {"selection_probe", "local_validation"}
    assert all(c["held_support"]["shared_directions_are_not_independent"] and not c["held_support"]["independent_oos"] for c in p["centers"])
    assert all(e["rights"] == "post_decision_reporting_only" for e in p["executions"] if e["request"]["role"] == "local_validation")
    assert all(e["request_sha256"] == digest(e["request"]) for e in p["executions"])
    assert n.missing_roster(plan, f.catalog()) == tuple(p["executions"])


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "raw_role", "wrong_calendar", "source_status", "metric_unit"])
def test_reject_malformed_or_unadmitted_full_panel(f, mutation):
    rows = f.panel["candidate_environment_rows"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif mutation == "raw_role":
        rows[0]["provenance"]["data_role"] = "holdout"
    elif mutation == "wrong_calendar":
        rows[0]["calendar_days"] = 365
    elif mutation == "source_status":
        rows[0]["compute_status"] = "CENSORED"
    else:
        rows[0]["metrics"][0]["unit"] = "percent"
    with pytest.raises((ValueError, PermissionError)):
        f.seal()


@pytest.mark.parametrize("key,value", [("count", 1), ("quality_floor", -.1), ("minimum_days", 30), ("top_fraction", .5)])
def test_no_scientific_policy_amendment(f, key, value):
    f.analysis["center_policy"][key] = value
    with pytest.raises(ValueError, match="policy changed"):
        f.seal()


@pytest.mark.parametrize("key,value", [("start", "2022-01-01"), ("role", "holdout"), ("symbol", "ETHUSDT"), ("candidate_id", "made_up")])
def test_actual_original_parent_request_is_authority(f, key, value):
    f.requests[0][key] = value
    with pytest.raises(ValueError, match="parent request differs"):
        f.seal()


def test_source_tamper_and_maturity_do_not_grant_access(f):
    plan = f.seal()
    source = f.path / "panel.json"
    source.write_bytes(source.read_bytes()+b" ")
    with pytest.raises(ValueError, match="content changed"):
        f.catalog()
    with pytest.raises(PermissionError):
        EvidenceCatalog(f.sources, AccessPolicy("too_early", ("synthetic",), ("synthetic",), a.STOP, "diagnostic"))


def test_no_future_source_role_even_with_matching_content(f):
    f.seal()
    source = f.sources[0]
    bad = Source(source.source_id, source.path, source.sha256, source.bytes,
                 AccessWitness("synthetic", "holdout", a.START, a.STOP, CUTOFF))
    with pytest.raises(PermissionError):
        EvidenceCatalog([bad], f.policy)


def test_matrix_assembly_reconciles_independent_roster_and_rejects_omissions(f):
    plan = f.seal()
    plan_ref = f.put("plan", plan.data)
    rows = n.normalized_rows(plan, f.catalog())
    rows_ref = f.put("normalized", rows.data)
    matrices, rosters, inventory = n.assemble_matrices(plan, f.catalog(), plan_ref=plan_ref, normalized_ref=rows_ref)
    assert len(matrices) == 6 and inventory.data == plan.data["inventory"]
    for m, r in zip(matrices, rosters):
        m.verify(r, f.catalog())
    advice = n.advisory(plan, f.catalog(), plan_ref=plan_ref)
    assert advice["status"] == "NO_CLEAR_WINNER" and not advice["automatic_routing"]
    bad = rows.data
    bad["values"]["execution_stress"].pop()
    bad_ref = f.put("omitted", bad)
    with pytest.raises(ValueError, match="altered/omitted/reordered"):
        n.assemble_matrices(plan, f.catalog(), plan_ref=plan_ref, normalized_ref=bad_ref)


def test_qualified_recovery_limits_and_original_oracle_status_not_rewritten(f):
    from tools.mode5_research.recovery_cells import RECOVERY_SCHEMA, RECOVERY_STATUS
    for row in f.panel["candidate_environment_rows"][:4]:
        row.update(source_reader_schema=RECOVERY_SCHEMA, compute_status=RECOVERY_STATUS,
            oracle_coverage="INHERITED_CONTROL_SOURCE_APPROVAL_NO_FRESH_PYTHON_ORACLE", recovery_account_calls=[3, 1, 0])
        row["provenance"]["data_role"] = "DEVELOPMENT_REVIEWED_RETROSPECTIVE"
        row["provenance"]["evidence_refs"] += [["economic_config", ECONOMICS], ["approved_source_0", ALPHA_SOURCE]]
        row["reader_certification_id"] = digest(asdict(a.ReaderCertification(RECOVERY_SCHEMA,
            row["reader_cell_identity"], ALPHA_SOURCE, ECONOMICS)))
    plan = f.seal()
    rows = n.normalized_rows(plan, f.catalog()).data["values"]["candidate_environment"]
    projected = rows[0]["value"]
    assert f.catalog().require_ref(projected["raw_account_metrics_ref"]) == Record.of(f.panel["candidate_environment_rows"][0]["raw_account_metrics"]).data
    assert Record.of({k: v for k, v in projected.items() if k != "raw_account_metrics_ref"}) == Record.of({
        k: v for k, v in f.panel["candidate_environment_rows"][0].items() if k != "raw_account_metrics"})
    assert rows[0]["value"]["compute_status"] == RECOVERY_STATUS
    assert rows[4]["value"]["oracle_coverage"] == a.ORIGINAL_ORACLE


def test_exact_completed_request_only_removed_and_never_relabeled(f):
    plan = f.seal()
    entry = plan.data["executions"][0]
    completion = dict(request_sha256=entry["request_sha256"], request=entry["request"],
        status="PASS_FINAL_COMPILER_AND_ACCOUNTING", original_compiler_parity=True,
        typed_lifecycle_terminal_parity=True, clean_oos=False, future_tape_opened=False)
    ref = f.put("completed_synthetic", completion)
    missing = n.missing_roster(plan, f.catalog(), [ref])
    assert len(missing) == len(plan.data["executions"])-1
    bad = deepcopy(completion)
    bad["request"]["role"] = "local_validation"
    bad_ref = f.put("relabeled", bad)
    with pytest.raises(ValueError):
        n.missing_roster(plan, f.catalog(), [bad_ref])


def fake_prepared(parent):
    class Original:
        def __init__(self, alias):
            self.registration = dict(protocol=dict(preload_start="2020-01-01", development_start=n.BASE["start"], development_stop=n.BASE["stop"]))
            self.history = SimpleNamespace(index=["2020-01-01"])
            self.scored = SimpleNamespace(index=["2021-01-01"]+["synthetic"]*26278+["2023-12-31"])
            self.data_hash = "public_synthetic_data"

        def request(self, index):
            return deepcopy(parent)

        def signature(self):
            return self.data_hash

    # The adapter uses the original scored-frame length, not an invented buffer.
    class Scored:
        index = ["2021-01-01"]+["synthetic"]*26278+["2023-12-31"]

        def __len__(self):
            return 26280

    class Prepared(Original):
        def __init__(self, alias):
            super().__init__(alias)
            self.scored = Scored()

    return Prepared


def test_request_aware_subclass_preserves_original_source_and_isolation(f):
    plan = f.seal()
    entry = plan.data["executions"][0]
    parent = f.requests[entry["request"]["parent_panel_index"]]
    base = fake_prepared(parent)
    adapter = n.prepared_probe_class(base, entry, parent)
    context = adapter("A-HMA")
    assert context.request(entry["request"]["parent_panel_index"]) == entry["request"]
    changed = context.request(entry["request"]["parent_panel_index"])
    changed["params"].clear()
    assert context.request(entry["request"]["parent_panel_index"])["params"]
    assert base("A-HMA").request(0) == parent
    with pytest.raises(ValueError):
        context.request(-1)
    with pytest.raises(ValueError):
        adapter("A-HASH")


@pytest.mark.parametrize("failure,control,cap", [(False, False, 1800), (False, True, 900), (True, False, 30)])
def test_gated_adapter_restores_module_namespace_on_return_or_failure(f, monkeypatch, failure, control, cap):
    plan = f.seal()
    plan_ref = f.put("plan", plan.data)
    entry = plan.data["executions"][0]
    parent = f.requests[entry["request"]["parent_panel_index"]]
    prepared = SimpleNamespace(PreparedResearch=fake_prepared(parent), finance="PUBLIC_SYNTHETIC", __file__=__file__)
    output = f.path / "one_probe"
    runner = SimpleNamespace(prepared=prepared, __file__=__file__)

    def run(alpha, index, target, cap, *, control):
        assert runner.prepared.finance == prepared.finance
        request = runner.prepared.PreparedResearch(alpha).request(index)
        if failure:
            raise RuntimeError("PUBLIC_SYNTHETIC_OWNER_FAILURE")
        target.mkdir()
        write_json(target / "result.json", dict(request=request, status="PASS_FINAL_COMPILER_AND_ACCOUNTING",
            final_native_calls=2 if control else 1, python_oracle_calls=int(control), native_feedback_calls=5,
            original_compiler_parity=True, typed_lifecycle_terminal_parity=True, future_tape_opened=False, clean_oos=False))

    runner.run = run
    threads = ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
               "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS", "RAYON_NUM_THREADS"]
    for key in threads:
        monkeypatch.setenv(key, "1")
    auth = dict(schema="mode5.native_probe_launch_authorization.v1", approved_by="owner", launch_authorized=True,
        plan_identity=plan.identity, plan_ref=plan_ref, request_sha256=entry["request_sha256"], numeric_threads=1,
        financial_workers=1, cap_seconds=cap, output=str(output), reserve_bytes=5*1024**3,
        runner_pin=file_identity(__file__), adapter_pin=file_identity(n.__file__), thread_variables=threads,
        retained_limit_bytes=32*1024**2, python_control=control)
    auth["admission_completion_ref"] = f.put("admission_completion", dict(status="PASS_SOURCE_ADMITTED_NATIVE384_PANELS",
        all_owned_children_reaped=True, proof=dict(sha256=plan.data["refs"]["admission"]["sha256"])))
    auth_ref = f.put("synthetic_authorization", auth)
    if failure:
        with pytest.raises(RuntimeError, match="OWNER_FAILURE"):
            n.execute_sealed_probe(plan, f.catalog(), entry_index=0, runner=runner, output=output, cap=cap, authorization_ref=auth_ref)
    else:
        result = n.execute_sealed_probe(plan, f.catalog(), entry_index=0, runner=runner, output=output, cap=cap, authorization_ref=auth_ref)
        assert result["request"] == entry["request"]
    assert runner.prepared is prepared
    assert (f.path / "one_probe-adapter-registration.json").is_file()


def test_recovery_authority_uses_actual_registration_market_worker_not_fake_access(f):
    plan = f.seal()
    parent = plan.data["executions"][0]["parent_authority"]
    request = f.catalog().require_ref(parent["request_ref"])
    original = dict(protocol=dict(preload_start="2020-01-01", development_start=n.BASE["start"],
        development_stop=n.BASE["stop"], continuous_within_scope=True, data_role="DEVELOPMENT_REVIEWED_RETROSPECTIVE"),
        symbols={"A-HMA": "BTCUSDT"})
    reg_ref = f.put("original_registration", original)
    witness = dict(path="public_synthetic_no_market_opened", sha256=MARKET, bytes=1)
    market_ref = f.put("market", dict(development=witness))
    worker_ref = f.put("worker_registration", dict(request=request, pins=[dict(sha256=reg_ref["sha256"]), witness]))
    authority = dict(access_schema="registered_recovery_development_v1", original_registration_ref=reg_ref,
        market_ref=market_ref, worker_registration_ref=worker_ref)
    assert n._parent_access(f.catalog(), authority, request) == MARKET
    request["role"] = "local_validation"
    with pytest.raises(ValueError, match="actual recovery worker/request"):
        n._parent_access(f.catalog(), authority, request)


def test_original_limited_access_remains_analysis_only_without_fabricated_finance_driver(f):
    plan = f.seal()
    assert "finance_driver" not in f.access
    assert all(e["parent_authority"]["access_schema"] == "original_development_access_v1" for e in plan.data["executions"])
    assert all(e["launch_authorized"] is False for e in plan.data["executions"])
    rows = n.normalized_rows(plan, f.catalog()).data["values"]["candidate_environment"]
    assert all(r["value"]["oracle_coverage"] == a.ORIGINAL_ORACLE for r in rows)


@pytest.mark.parametrize("mutation", [None, "role", "duplicate"])
def test_probe_view_rows_bind_requests_roles_and_keep_missing_masks(f, mutation):
    plan = f.seal()
    entry = plan.data["executions"][0]
    value = deepcopy(f.panel["candidate_environment_rows"][0])
    value["provenance"]["candidate_id"] = entry["request"]["candidate_id"]
    row = dict(execution_index=0, environment_id="whole_path", request=entry["request"],
        request_sha256=entry["request_sha256"], role=entry["request"]["role"], annual_local_authorized=False,
        clean_oos=False, analysis_compute_status="PASS", value=value)
    rows = [row]
    if mutation == "role":
        row["role"] = "local_validation"
    elif mutation == "duplicate":
        rows.append(deepcopy(row))
    ref = f.put("synthetic_probe_views", dict(schema=n.PROBE_SCHEMA, plan_identity=plan.identity, rows=rows))
    if mutation:
        with pytest.raises(ValueError):
            n.normalized_rows(plan, f.catalog(), probe_views_ref=ref)
    else:
        result = n.normalized_rows(plan, f.catalog(), probe_views_ref=ref).data
        observed = [r for r in result["values"]["center_neighbor_environment"]
                    if r["operation"] == "probe" and r["status"] == "OBSERVED"]
        assert len(observed) == 1 and observed[0]["source_refs"][0]["source"] == "synthetic_probe_views"
        assert any(r["status"] == "MISSING" for r in result["values"]["center_neighbor_environment"])
        assert not observed[0]["annual_local_authorized"] and not observed[0]["independent_oos"]


def test_unauthorized_launch_never_calls_financial_owner(f):
    plan = f.seal()
    ref = f.put("not_authorized", dict(schema="not_a_launch_authorization"))
    with pytest.raises((ValueError, KeyError)):
        n.execute_sealed_probe(plan, f.catalog(), entry_index=0, runner=None, output=f.path/"never_created", cap=30, authorization_ref=ref)
    assert not (f.path/"never_created").exists()


def artifact(f, name, value):
    ref = f.put(name, value)
    pin = file_identity(f.path / (name+".json"))
    f.sources.append(Source("artifact:"+digest(pin), pin["path"], pin["sha256"], pin["bytes"], f.witness))
    return pin, ref


@pytest.mark.parametrize("schema,mutation", [("snapshot_recovery_v1", None),
    ("early_owner_registered_sources_limited_v1", None), ("snapshot_recovery_v1", "request"),
    ("snapshot_recovery_v1", "witness"), ("snapshot_recovery_v1", "snapshot"),
    ("early_owner_registered_sources_limited_v1", "limitations")])
def test_actual_handoff_recovery_and_early_authorities_are_not_legacy_access(f, schema, mutation):
    request = f.requests[0]
    witness = dict(path="public_synthetic_no_finance", sha256=MARKET, bytes=1)
    market, _ = artifact(f, "metadata", dict(development=witness))
    registration, _ = artifact(f, "original_registration", dict(protocol=dict(preload_start="2020-01-01",
        development_start=n.BASE["start"], development_stop=n.BASE["stop"], continuous_within_scope=True,
        data_role="DEVELOPMENT_REVIEWED_RETROSPECTIVE"), symbols={"A-HMA": "BTCUSDT"}))
    snapshots = [dict(original=market, retained=market)] if schema == "snapshot_recovery_v1" else []
    raw, _ = artifact(f, "original_result", dict(request=request, status="PUBLIC_SYNTHETIC_SOURCE_STATUS",
        future_tape_opened=False, clean_oos=False))
    worker, _ = artifact(f, "original_worker", dict(request=request, pins=[registration, market], source_snapshots=snapshots))
    request_file, _ = artifact(f, "cold_projection", request | (dict(role="local_validation") if mutation == "request" else {}))
    access_refs = dict(schema=schema, access_file=None, actual_result_claims=dict(artifact=raw, pointer=""),
        market_metadata=dict(artifact=market, pointer="/development"), development_witness=witness,
        future_tape_opened=False, clean_oos=False)
    if schema == "snapshot_recovery_v1":
        access_refs["source_snapshot_roster"] = dict(artifact=worker, pointer="/source_snapshots")
    else:
        access_refs.update(original_worker_source_roster=dict(artifact=worker, pointer="/pins"), limitation="SYNTHETIC_LIMITED")
    actual = dict(request_file=request_file, request=request_file, request_file_origin="CURRENT_KNOWLEDGE_EXACT_COPY_OF_SEALED_REQUEST",
        original_request_refs=[dict(artifact=p, pointer="/request") for p in (raw, worker)], access=None,
        access_refs=access_refs, original_artifact_refs=dict(original_registration=registration),
        external_recovery_registration=worker, source_compute_status="PUBLIC_SYNTHETIC_SOURCE_STATUS",
        original_source_snapshots=snapshots, approved_source_refs=dict(market_metadata=market),
        early_source_limitations=["SYNTHETIC_LIMITED"] if schema.startswith("early") else None)
    if mutation == "witness":
        actual["access_refs"]["development_witness"] = witness | dict(sha256=digest("wrong"))
    if mutation == "snapshot":
        actual["original_source_snapshots"] = []
    if mutation == "limitations":
        actual["early_source_limitations"] = None
    ref = f.put("actual_parent", actual)
    parent = dict(authority_ref=ref)
    projected = f.catalog().require_ref(n.artifact_ref(f.catalog(), request_file))
    if mutation:
        with pytest.raises(ValueError):
            n._parent_access(f.catalog(), parent, projected)
    else:
        assert n._parent_access(f.catalog(), parent, projected) == MARKET
        assert f.catalog().require_ref(ref)["access"] is None


def test_actual_consumer_parent_roster_uses_refs_without_fabricated_access(f):
    f.seal()
    request_pins = [artifact(f, f"cold_request_{i}", r)[0] for i, r in enumerate(f.requests)]
    original_requests, _ = artifact(f, "original_request_array", f.requests)
    access, _ = artifact(f, "unchanged_legacy_access", f.access)
    cells = []
    for alpha in n.ALPHAS:
        for i in range(128):
            row = f.panel["candidate_environment_rows"][4*i]
            cells.append(dict(alpha=alpha, index=i, request=request_pins[i], request_file=request_pins[i],
                request_file_origin="CURRENT_KNOWLEDGE_EXACT_COPY_OF_SEALED_REQUEST",
                original_request_file=request_pins[i], original_request_refs=[
                    dict(artifact=original_requests, pointer=f"/{i}"), dict(artifact=request_pins[i], pointer="")],
                access=access, access_refs=dict(schema="original_development_access_v1",
                    access=dict(artifact=access, pointer=""), finance_driver_mapping=None, original_access_file_unchanged=True),
                source_reader_schema=row["source_reader_schema"], source_compute_status=row["compute_status"],
                source_data_role=row["provenance"]["data_role"], reader_certification=dict(cell_identity=row["reader_cell_identity"]),
                oracle_coverage=row["oracle_coverage"], original_alias_coverage="LIMITED_ORIGINAL_SCHEMA",
                original_terminal_limitations=dict(financial_scope="SYNTHETIC_ORIGINAL_LIMITED"), early_source_limitations=None))
    panels = {"A-HMA": dict(sha256=f.refs["panel"]["sha256"])}
    reader, _ = artifact(f, "actual_reader", dict(status="PASS_ACTUAL_COLD_NATIVE384_PANELS", actual_cells=384,
        views=1536, panels=panels, financial_executions=0, independent_oos=False, no_terminal_or_oracle_promotion=True))
    cleanup, _ = artifact(f, "actual_cleanup", dict(status="PASS", retained_inputs_unchanged=True, protected_source_unchanged=True))
    completion, _ = artifact(f, "actual_closed", dict(status="PASS_ACTUAL_COLD_NATIVE384_PANELS",
        proof=reader, cleanup=cleanup, financial_executions=0, all_owned_children_reaped=True))
    pp, parent_ref = artifact(f, "consumer_parents", dict(status="PASS_ACTUAL_PARENT_REFS", cells=cells,
        actual_cells=384, request_files=384, original_request_files=384, fabricated_legacy_access_files=0,
        financial_executions=0, independent_oos=False, new_request_files_are_explicit_cold_projections=True, original_proof=reader))
    proof = f.put("consumer_proof", dict(status="PASS_SOURCE_ADMITTED_NATIVE384_PANELS", actual_cells=384,
        views=1536, financial_executions=0, independent_oos=False, panels=panels, source_parent_refs=pp,
        actual_reader_proof=reader, completed_controller_result=completion,
        no_fabricated_legacy_access=True, source_status_or_coverage_not_promoted=True))
    refs = f.refs | dict(parents=parent_ref, admission=proof)
    plan = n.plan_native(f.catalog(), refs, f.geometry)
    assert all(e["parent_authority"]["original_alias_coverage"] == "LIMITED_ORIGINAL_SCHEMA" for e in plan.data["executions"])
    assert all("authority_ref" in e["parent_authority"] and not e["launch_authorized"] for e in plan.data["executions"])
    assert all(f.catalog().require_ref(e["parent_authority"]["authority_ref"])["access_refs"]["finance_driver_mapping"] is None
               for e in plan.data["executions"])


def test_later_auth_frontier_does_not_backdate_or_change_frozen_probe_plan(f):
    plan = f.seal()
    witness = AccessWitness("synthetic", "synthetic", a.START, a.STOP, CUTOFF+100)
    path = f.path / "later_authorization.json"
    write_json(path, dict(status="PUBLIC_SYNTHETIC_NOT_A_FINANCIAL_AUTH"))
    p = file_identity(path)
    source = Source("later", p["path"], p["sha256"], p["bytes"], witness)
    policy = AccessPolicy("later-frontier", ("synthetic",), ("synthetic",), CUTOFF+100, "diagnostic")
    catalog = EvidenceCatalog([*f.sources, source], policy)
    assert n.regenerate_plan(plan, catalog) == plan
    assert catalog.require_ref(catalog.ref("later"))["status"] == "PUBLIC_SYNTHETIC_NOT_A_FINANCIAL_AUTH"
