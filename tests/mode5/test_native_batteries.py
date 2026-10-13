"""Public synthetic cold metadata, never financial evidence or execution."""

from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.records import Record
from tools.mode5_research import native_batteries as b
from tools.mode5_research import native_diagnostics as n, native_probe_admission as admission
from tools.mode5_research.probe_views import UTILITY


spec = importlib.util.spec_from_file_location("native_battery_public_fixture",
    Path(__file__).with_name("test_native_diagnostics.py"))
fixture_owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_owner)

PREFERENCES = dict(formulas=list(b.FORMULAS), activity_penalty=0., risk_drawdown_max=.5,
    quality_utility_strictly_greater_than=0., minimum_daily_count=365,
    environment_weights="equal positive 1.0 per annual environment; whole path not stacked into annual selectors",
    floor_reference=.25, near_optimal_tolerance_decimal=.01,
    pareto=dict(ideal=.25, worst=-.25, weights=1., directions=1, extrapolation="allow_and_report_v1"),
    minimum_improvement=0., incumbent=None, tie_break="candidate_id_lexicographic_v1")


class Fixture(fixture_owner.Fixture):
    def __init__(self, path):
        super().__init__(path)
        for row in self.panel["candidate_environment_rows"]:
            row["metrics"][0]["components"] = list(UTILITY.items())

    def metric(self, index, env, name, value):
        row = next(r for r in self.panel["candidate_environment_rows"] if r["index"] == index and r["environment_id"] == env)
        metric = next(m for m in row["metrics"] if m["metric_id"] == "mode5.panel."+name)
        metric.update(value=value, status="VALID" if value is not None else "UNDEFINED",
                      reason=None if value is not None else "PUBLIC_SYNTHETIC_MISSING_METRIC")
        row["null_reasons"] = [pair for pair in row["null_reasons"] if pair[0] != metric["metric_id"]]
        if value is None:
            row["null_reasons"].append((metric["metric_id"], metric["reason"]))
        raw_name = fixture_owner.a._RAW_METRICS.get(name)
        if raw_name:
            raw = next(m for m in row["raw_account_metrics"]["metrics"] if m["metric_id"] == "reporting."+raw_name)
            raw.update(value=value, status=metric["status"].lower(), reason=metric["reason"])

    def freeze(self):
        self.plan = self.seal()
        self.plan_ref = self.put("frozen-plan", self.plan.data)
        self.preferences_ref = self.put("preferences", deepcopy(PREFERENCES))

    def envelope(self):
        rows = []
        for execution in self.plan.data["executions"]:
            request = execution["request"]
            for env in b.ENVIRONMENTS:
                value = deepcopy(next(r for r in self.panel["candidate_environment_rows"] if r["environment_id"] == env))
                value.pop("panel_admission_schema")
                value.update(probe_admission_schema=n.PROBE_SCHEMA, source_reader_schema=admission.READER_SCHEMA,
                    compute_status="PASS_FINAL_COMPILER_AND_ACCOUNTING", analysis_compute_status="PASS",
                    rights="selection" if request["role"] == "selection_probe" else "post_decision_reporting_only",
                    annual_local_authorized=False, actual_account_calls=[1, 1, 0],
                    oracle_coverage="PUBLIC_SYNTHETIC_NO_FINANCIAL_CONTROL", parent_coverage="SYNTHETIC_ONLY",
                    source_limitations=["PUBLIC_SYNTHETIC_METADATA_NOT_FINANCIAL_PROOF"])
                value["provenance"].update(candidate_id=request["candidate_id"], design_id=request["design_id"],
                    execution_id=digest("public_synthetic_probe_"+str(execution["index"])), data_role=request["role"])
                value["metrics"][0].update(value=.08)
                for metric in value["metrics"]:
                    if metric["metric_id"] in ("mode5.panel.economic_utility", "mode5.panel.net_return",
                                               "mode5.panel.drawdown"):
                        metric["sample_count"] = value["actual_bar_count"]
                for metric in value["raw_account_metrics"]["metrics"]:
                    if metric["metric_id"] in ("reporting.account.total_return",
                                               "reporting.drawdown.max_depth"):
                        metric["sample_count"] = value["actual_bar_count"]
                rows.append(dict(execution_index=execution["index"], environment_id=env,
                    request=request, request_sha256=execution["request_sha256"], role=request["role"], value=value,
                    annual_local_authorized=False, clean_oos=False, analysis_compute_status="PASS"))
        return dict(schema=n.PROBE_SCHEMA, plan_identity=self.plan.identity, rows=rows,
                    utility_policy=UTILITY, financial_executions=0, annual_local_authorized=False, clean_oos=False)

    def reduce(self, envelope=None):
        ref = None if envelope is None else self.put("probes-"+str(len(self.sources)), envelope)
        return b.reduce_batteries(self.catalog(), plan_ref=self.plan_ref,
            preferences_ref=self.preferences_ref, probe_views_ref=ref)


@pytest.fixture
def f(tmp_path):
    return Fixture(tmp_path)


def test_canonical_scores_match_independent_scalar_oracles(f):
    for env, value in zip(b.ANNUAL, (.11, .07, .19)):
        f.metric(127, env, "economic_utility", value)
    f.freeze()
    reduction = f.reduce()
    report = reduction.report.data
    cid = f.panel["candidate_ids"][127]
    floor = next(r for r in report["batteries"]["B1"]["decisions"]["environment_floor_mean_v1"]["component_rows"] if r["candidate_id"] == cid)
    tail = next(r for r in report["batteries"]["B1"]["decisions"]["environment_lower_tail_v2"]["component_rows"] if r["candidate_id"] == cid)
    values = [.11, .07, .19]
    mean = sum(values)/3
    median = sorted(values)[1]
    mad = sorted(abs(v-median) for v in values)[1]
    assert floor["score"] == pytest.approx(min(values)+.25*mean)
    assert tail["score"] == pytest.approx(1.5*min(values)-.2*mad)
    assert tail["components"]["floor_tail_redundancy"]
    pareto = next(r for r in report["batteries"]["B3"]["decision"]["component_rows"] if r["candidate_id"] == cid)
    gaps = [(.25-v)/.5 for v in values]
    assert pareto["score"] == pytest.approx(-(max(gaps)+.01*sum(gaps)))
    assert set(report["batteries"]["B3"]["same_front"]["front_ids"]) == set(report["batteries"]["B3"]["decision"]["pareto_candidate_ids"])
    assert not report["phase_complete"] and not report["recipe_approval"]


def test_actual_recipe_ids_support_readiness_not_clear_winner(f):
    f.freeze()
    reduction = f.reduce()
    rows = reduction.assessment.data["recipes"]
    assert {r["recipe_id"] for r in rows} == {s["selector"]+":"+s["version"] for s in b.FORMULAS} | {"full_sam_basin:local_downside_v1"}
    assert all(r["status"] == "CONSIDER_FINITE_PANEL" for r in rows[:3])
    assert all(r["selected_decisions"] == 4 and not r["whole_procedure_qualified"] for r in rows[:3])
    assert rows[-1]["status"] == "INSUFFICIENT_COVERAGE"
    advice = reduction.assessment.data["ordered_advice"]
    assert advice["status"] == "NO_CLEAR_WINNER" and not advice["whole_procedure_qualified"]
    assert len([r for r in advice["recipes"] if r["status"] == "CONSIDER_FINITE_PANEL"]) == 3


def test_raw_whole_sharpe_control_does_not_apply_annual_eligibility(f):
    f.metric(0, "whole_path", "sharpe", 100.)
    f.metric(0, "2021", "economic_utility", -.1)
    f.freeze()
    report = f.reduce().report.data
    raw = report["raw_whole_sharpe_control"]
    assert raw["chosen_candidate"] == f.panel["candidate_ids"][0]
    assert not raw["common_annual_eligibility_applied"]
    for decision in report["batteries"]["B1"]["decisions"].values():
        assert decision["chosen_candidate"] != raw["chosen_candidate"]
        row = next(r for r in decision["component_rows"] if r["candidate_id"] == raw["chosen_candidate"])
        assert not row["eligible"] and row["score"] is not None


def test_held_annual_gate_excluded_from_leave_out_choice(f):
    for env, value in zip(b.ANNUAL, (.9, .8, -.3)):
        f.metric(0, env, "economic_utility", value)
    f.freeze()
    report = f.reduce().report.data
    leave = {**report["batteries"]["B1"]["leave_out"], "pareto_chebyshev_v1": report["batteries"]["B3"]["leave_out"]}
    for rows in leave.values():
        omitted = next(r for r in rows if r["omitted_environment"] == "2023")
        assert omitted["chosen_candidate"] == f.panel["candidate_ids"][0]
        assert omitted["held_metric"]["value"] == -.3 and not omitted["held_gate_flags"][1]
        assert omitted["held_gate_information_excluded"] and not omitted["independent_oos"]


def test_all_negative_no_selection_keeps_negative_benchmarks(f):
    f.set_metric("economic_utility", -.1)
    f.freeze()
    reduction = f.reduce()
    report = reduction.report.data
    assert all(d["chosen_candidate"] is None for d in report["batteries"]["B1"]["decisions"].values())
    assert report["batteries"]["B3"]["decision"]["chosen_candidate"] is None
    assert report["batteries"]["B3"]["same_front"]["front_ids"] == []
    envs = report["batteries"]["B3"]["environment_matrix"]
    assert envs["near_optimal_sets"]["2021"]["finite_valid_benchmark"] == -.1
    assert envs["near_optimal_sets"]["2021"]["members"] == []
    assert all(p["common_count"] == 128 and p["spearman"] is None and p["spearman_reason"] for p in envs["pairs"])
    assert all(r["status"] == "NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL" for r in reduction.assessment.data["recipes"][:3])
    assert report["raw_whole_sharpe_control"]["chosen_candidate"] is not None


def test_correlations_and_near_benchmarks_include_risk_failing_negative_candidates(f):
    f.metric(0, "2021", "economic_utility", -.4)
    f.metric(127, "2021", "economic_utility", 3.)
    f.metric(127, "2021", "drawdown", .6)
    f.freeze()
    report = f.reduce().report.data
    envs = report["batteries"]["B3"]["environment_matrix"]
    pair = next(p for p in envs["pairs"] if (p["left"], p["right"]) == ("2021", "2022"))
    assert pair["common_count"] == 128 and all(pair["common_mask"])
    assert pair["spearman"] is not None and pair["p_value"] is None
    assert envs["near_optimal_sets"]["2021"]["finite_valid_benchmark"] == 3.
    assert envs["near_optimal_sets"]["2021"]["members"] == []
    row = next(r for r in envs["finite_panel_regrets"] if r["candidate_id"] == f.panel["candidate_ids"][0])
    assert row["per_environment"]["2021"] == pytest.approx(3.4)
    assert envs["finite_benchmark_includes_negative_and_risk_failing"]


def test_missing_metric_masks_not_zero_or_survivor_average(f):
    f.metric(127, "2021", "economic_utility", None)
    f.freeze()
    reduction = f.reduce()
    report = reduction.report.data
    envs = report["batteries"]["B3"]["environment_matrix"]
    pair = next(p for p in envs["pairs"] if (p["left"], p["right"]) == ("2021", "2022"))
    assert pair["common_count"] == 127 and not pair["left_valid_mask"][127]
    regret = envs["finite_panel_regrets"][-1]
    assert regret["canonical"]["annual"]["value"] is None
    assert regret["canonical"]["annual"]["reason"]
    assert all(r["status"] == "INSUFFICIENT_COVERAGE" for r in reduction.assessment.data["recipes"][:3])


def test_complete_bounded_local_cannot_grant_annual_or_whole_panel_rights(f):
    f.freeze()
    reduction = f.reduce(f.envelope())
    b2 = reduction.report.data["batteries"]["B2"]
    assert b2["status"] == "MEASURED_BOUNDED_LOCAL"
    assert b2["expected_executions"] == b2["admitted_executions"]
    assert b2["whole128_local"] == "NOT_EVALUABLE" and b2["annual_local"] == "NOT_AUTHORIZED"
    local = b2["local"]
    assert local["chosen_candidate"] in [c["candidate_id"] for c in f.plan.data["centers"]]
    assert all(r["components"]["empirical_worst_utility"] == pytest.approx(.08) for r in local["component_rows"])
    assert all(not r["independent_overlaps"] and not r["temporal_oos"] for r in local["overlap"])
    assessment = reduction.assessment.data["recipes"][-1]
    assert assessment["status"] == "CONSIDER_FINITE_PANEL" and not assessment["annual_local_authorized"]
    assert not assessment["whole_procedure_qualified"]


def test_held_negative_probes_are_reporting_only_and_retained(f):
    f.freeze()
    envelope = f.envelope()
    first = f.reduce(envelope).report.data["batteries"]["B2"]["local"]
    for row in envelope["rows"]:
        if row["role"] == "local_validation":
            row["value"]["metrics"][0]["value"] = -.4
    second = f.reduce(envelope).report.data["batteries"]["B2"]["local"]
    assert first["chosen_candidate"] == second["chosen_candidate"]
    fields = ("candidate_id", "components", "score", "eligible", "reasons", "evidence_complete", "missing", "failed")
    assert [{k: r[k] for k in fields} for r in first["component_rows"]] == [
        {k: r[k] for k in fields} for r in second["component_rows"]]
    assert all(not r["eligible"] and r["score"] == -.4 for r in second["validation_post_decision"])


def test_missing_whole_execution_cannot_reuse_held_for_selection(f):
    f.freeze()
    envelope = f.envelope()
    index = next(e["index"] for e in f.plan.data["executions"] if e["request"]["role"] == "selection_probe")
    envelope["rows"] = [r for r in envelope["rows"] if r["execution_index"] != index]
    reduction = f.reduce(envelope)
    local = reduction.report.data["batteries"]["B2"]["local"]
    assert local["chosen_candidate"] is None and not local["evidence_complete"]
    assert any(index in r["missing"] for r in local["component_rows"])
    assert all(r["evidence_complete"] for r in local["validation_post_decision"])
    assert reduction.assessment.data["recipes"][-1]["status"] == "INSUFFICIENT_COVERAGE"


def test_nonquality_geometric_controls_never_promoted(f):
    f.set_metric("economic_utility", -.1)
    f.freeze()
    reduction = f.reduce(f.envelope())
    local = reduction.report.data["batteries"]["B2"]["local"]
    assert local["evidence_complete"] and local["chosen_candidate"] is None
    assert all(not r["eligible"] and r["status"] == "NONQUALITY_CONTROL_NOT_PROMOTED" for r in local["component_rows"])
    assert reduction.assessment.data["recipes"][-1]["status"] == "NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL"


@pytest.mark.parametrize("mutation", ["role", "request", "reader", "rights", "partial", "duplicate", "utility", "calendar", "annual_rights", "lineage"])
def test_probe_envelope_tamper_or_role_laundering_rejected(f, mutation):
    f.freeze()
    envelope = f.envelope()
    row = envelope["rows"][0]
    if mutation == "role":
        row["role"] = "local_validation"
    elif mutation == "request":
        row["request"] = row["request"] | {"probe_seed": 999}
    elif mutation == "reader":
        row["value"]["source_reader_schema"] = "old_discovery_reader"
    elif mutation == "rights":
        row["value"]["rights"] = "post_decision_reporting_only"
    elif mutation == "partial":
        envelope["rows"].pop()
    elif mutation == "duplicate":
        envelope["rows"].append(deepcopy(row))
    elif mutation == "utility":
        row["value"]["metrics"][0]["components"] = list((UTILITY | dict(dd_weight=0.)).items())
    elif mutation == "calendar":
        row["value"]["calendar_days"] = 365
    elif mutation == "annual_rights":
        row["value"]["annual_local_authorized"] = True
    else:
        row["value"]["provenance"]["execution_id"] = digest("different_continuous_account")
    with pytest.raises((ValueError, PermissionError)):
        f.reduce(envelope)


@pytest.mark.parametrize("key,value", [("floor_reference", .5), ("risk_drawdown_max", .6),
    ("near_optimal_tolerance_decimal", .02), ("quality_utility_strictly_greater_than", -.1)])
def test_original_preferences_cannot_relax_scientific_gates(f, key, value):
    f.freeze()
    preferences = deepcopy(PREFERENCES) | {key: value}
    ref = f.put("changed-preferences", preferences)
    with pytest.raises(ValueError, match="original annual"):
        b.reduce_batteries(f.catalog(), plan_ref=f.plan_ref, preferences_ref=ref)


def test_source_content_tamper_detected_after_reduction(f):
    f.freeze()
    catalog = f.catalog()
    reduction = f.reduce()
    path = f.path / "panel.json"
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError, match="content changed"):
        reduction.verify(catalog)


def test_all_six_matrices_reconcile_actual_inventory_and_keep_masks(f):
    f.freeze()
    reduction = f.reduce(f.envelope())
    f.policy = replace(f.policy, cutoff_ns=f.policy.cutoff_ns+1)
    f.witness = replace(f.witness, ready_ns=f.policy.cutoff_ns)
    rows_ref = f.put("battery-rows", reduction.rows.data)
    report_ref = f.put("battery-report", reduction.report.data)
    matrices, rosters, inventory_ref = b.assemble_matrices(reduction, f.catalog(), rows_ref=rows_ref, report_ref=report_ref)
    assert len(matrices) == 6 and {m.record.data["kind"] for m in matrices} == set(fixture_owner.KINDS)
    assert f.catalog().require_ref(inventory_ref) == f.plan.data["inventory"]
    for matrix, roster in zip(matrices, rosters):
        matrix.verify(roster, f.catalog())
    values = reduction.rows.data["values"]
    assert len(values["candidate_environment"]) == 512 and len(values["environment_environment"]) == 16
    assert all(r["status"] == "NOT_TESTED" and r["value"] is None and r["metric_masks"]
               for r in values["execution_stress"] if r["coordinates"]["scenario"] == "fee_x2")
    assert all(r["status"] == "NOT_RUN" and r["value"] is None and r["metric_masks"]
               for r in values["recipe_split_seed"] if r["coordinates"].get("battery"))
    observed = next(r for r in values["center_neighbor_environment"] if r["operation"] == "probe" and r["status"] == "OBSERVED")
    projection = observed["value"]
    assert projection["original_view_ref"]["pointer"].endswith("/value")
    source = f.catalog().require_ref(projection["original_view_ref"])
    assert source["metrics"] == projection["metrics"]
    assert projection["compute_status"] == "PASS_FINAL_COMPILER_AND_ACCOUNTING"
    assert not reduction.rows.data["scientific_complete"]


def test_altered_reduction_or_sealed_report_rejected(f):
    f.freeze()
    reduction = f.reduce()
    rows = reduction.rows.data
    rows["values"]["environment_environment"][0]["value"]["spearman"] = 0.
    with pytest.raises(ValueError, match="altered source-bound"):
        replace(reduction, rows=Record.of(rows)).verify(f.catalog())
    rows_ref = f.put("rows", reduction.rows.data)
    report = reduction.report.data
    report["phase_complete"] = True
    report_ref = f.put("altered-report", report)
    with pytest.raises(ValueError, match="frozen battery rows/report differ"):
        b.assemble_matrices(reduction, f.catalog(), rows_ref=rows_ref, report_ref=report_ref)


def test_b4_b5_and_no_financial_runtime_imports(f):
    import sys
    f.freeze()
    report = f.reduce().report.data
    assert report["batteries"]["B4"]["status"] == report["batteries"]["B5"]["status"] == "NOT_RUN"
    assert report["financial_executions"] == 0
    assert not any(k.startswith(("_quantbt_native", "numba", "optuna")) or k in
        {"finance", "fast_native", "prepared", "private_inputs", "private_support", "static_binding"} for k in sys.modules)
