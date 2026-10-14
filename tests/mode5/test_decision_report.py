"""Synthetic public-runtime shapes only; no market evidence or disk fixtures."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import pickle

import pandas as pd
import pytest

from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.selection.pareto import ParetoPreference
from quantbt.mode5.selection.selectors import select
from quantbt.mode5.selection.contracts import Channel, LocalEvidence, Probe
from selection_fixtures import panel, plan


SECRET = "PRIVATE-PARAM-<script>|recipe"


@pytest.mark.parametrize("stamp", [pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2023-01-01"),
                                    pd.Timestamp("2023-01-01", tz="Asia/Ho_Chi_Minh")])
def test_actual_sampler_timestamp_is_losslessly_portable_without_timezone_guess(stamp):
    metadata, params = runtime_metadata()
    metadata["sampler"].update(is_cutoff=stamp, warm_start_cutoff=stamp)
    report = DecisionReport.read(metadata, selected_params=params)
    observed = report.to_dict(private=True)["runtime"]["sampler"]
    assert observed["is_cutoff"] == observed["warm_start_cutoff"] == stamp.isoformat()
    assert metadata["sampler"]["is_cutoff"] is stamp
    assert DecisionReport.from_json(report.to_json(private=True)) == report


def test_invalid_sampler_clock_is_not_stringified_into_a_valid_report():
    metadata, params = runtime_metadata()
    metadata["sampler"]["is_cutoff"] = pd.NaT
    with pytest.raises(ValueError):
        DecisionReport.read(metadata, selected_params=params)


def test_readable_markdown_keeps_each_trial_and_component_in_separate_rows():
    metadata, params = runtime_metadata()
    report = DecisionReport.read(metadata, selected_params=params)
    text = report.to_markdown()
    assert "## Trials" in text and "## Candidate Components" in text
    assert "## Environment Observations" in text
    assert "| Trial | State | Candidate | Objective | Raw Sharpe | Reason |" in text
    for row in metadata["trial_ledger"]:
        assert "| " + str(row["trial_id"]) + " | &quot;" + row["state"] + "&quot; |" in text
    assert SECRET not in text


def runtime_metadata(*, continuous=False, no_selection=False, incumbent=False, pareto=False, local=False, tail=False):
    params = [{SECRET: n, "branch": SECRET} for n in (11, 22, 33, 44)]
    p = panel(((-.3, .5), (.05, .15), (.8, .9), (None, None)),
              channel=Channel("ECONOMIC_UTILITY_V1", "mode5.private-metric-" + SECRET, "decimal_return"))
    p = replace(p, candidates=tuple(replace(c, candidate_id=digest(params[i]), params_digest=digest(params[i]),
        risk_pass=not no_selection and i != 2, support_pass=i != 3) for i, c in enumerate(p.candidates)),
        revision="formal_search_v1", generation="fixed_panel")
    kwargs = {}
    if incumbent:
        kwargs.update(incumbent_id=p.candidates[0].candidate_id)
    preference = None
    if pareto:
        preference = ParetoPreference("private-preference", p.reference.environment_ids,
            p.channel.identity, (1., 1.), (-1., -1.), (1, 1), (1., 1.), "allow_and_report_v1")
        kwargs["pareto_preference_identity"] = preference.identity
    locals_by_id = {}
    if local:
        kwargs.update(local_reference_id="private-local-reference", local_reference_scale=1.)
        s = plan(p, "local_downside_v1", (("gamma", 1.),), "full_sam_basin", **kwargs)
        for c in p.candidates:
            locals_by_id[c.candidate_id] = LocalEvidence(c.candidate_id, p.channel, "private-local-reference", 1.,
                "weighted_environment_mean_v1", ("probe-1",),
                (Probe("probe-1", -.8 if c == p.candidates[0] else .1, "COMPLETE", c.analyses[0], c.witnesses[0]),),
                "OBSERVED_REQUIRED_RADII", "SCHEMA_ONLY_REGISTERED", "private-probe-design", "private-validation")
    elif tail:
        s = plan(p, "environment_lower_tail_v2", (("alpha", .25), ("floor", 1.), ("tail", .5), ("dispersion", .2)))
    elif pareto:
        s = plan(p, "pareto_chebyshev_v1", (("rho", .01),), "full_pareto_chebyshev", **kwargs)
    else:
        s = plan(p, **kwargs)
    if incumbent:
        s = replace(s, minimum_improvement=1.)
    s = replace(s, stage_id="formal_search_v1")
    choice = select(p, s, pareto_preference=preference, local_evidence=tuple(locals_by_id.values()))
    rows = []
    for i, c in enumerate(p.candidates):
        point = select(replace(p, candidates=(c,)), replace(s, incumbent_id=None), pareto_preference=preference,
                       local_evidence=(locals_by_id[c.candidate_id],) if local else ())
        part = point.metadata["component_rows"][0]
        observations = []
        for j, metric in enumerate(c.metrics):
            observations.append(dict(schema="quantbt.mode5.observation.v1", environment_id=f"private-env-{j}",
                finance={"equity": f"account-{i}-{j}"}, raw_sharpe=(9. if i == 0 else -.7) if i != 3 else None,
                utility=metric.to_metadata(), psr=dict(value=None, status="UNDEFINED", reason=SECRET),
                net_return=metric.value, max_drawdown=.2, daily_loss_es=.05, daily_count=100,
                support_pass=c.support_pass, risk_pass=c.risk_pass, quality_pass=c.quality_pass,
                daily_returns=[0.] * 2000, final_equity=80.))
        row = dict(trial_id=i, state="COMPLETE" if part["score"] is not None else "PRUNED",
            candidate_id=c.candidate_id, requested_params=params[i], effective_params=params[i],
            evaluation_ref=digest(observations), observations=observations, components=part,
            objective=part["score"], raw_sharpe=observations[0]["raw_sharpe"] or 0.)
        if part["score"] is None:
            row["reason"] = "UNDEFINED_OBJECTIVE"
        if continuous:
            whole = deepcopy(observations[0])
            whole["raw_sharpe"] = None if i == 3 else -1.2 + i * .1
            row.update(whole_observation=whole, raw_sharpe=whole["raw_sharpe"], raw_whole_sharpe=whole["raw_sharpe"],
                annual_mean_raw_sharpe=observations[0]["raw_sharpe"])
        rows.append(row)
    rows.append(dict(trial_id=4, state="PRUNED", candidate_id=rows[1]["candidate_id"],
        requested_params=params[1], effective_params=params[1], evaluation_ref=rows[1]["evaluation_ref"],
        reason="DUPLICATE_EFFECTIVE_PARAMS"))
    rows.append(dict(trial_id=5, state="FAILED", candidate_id=None, requested_params={SECRET: 99},
        effective_params=None, evaluation_ref=None, reason="NOT_EVALUATED", error_type="RuntimeError"))
    telemetry = [dict(trial_id=r["trial_id"], state="FAIL" if r["state"] == "FAILED" else r["state"],
        candidate_id="sampler-proposal-" + r["candidate_id"] if r["candidate_id"] else None,
        requested_params=r["requested_params"],
        effective_params=r["effective_params"] or {}, source="warm_start" if r["trial_id"] == 0 else "sampled",
        objective=[r["objective"]] if r["state"] == "COMPLETE" else None,
        reason=r.get("reason"), constraints=[], relative_dimensions=[SECRET] if r["trial_id"] > 0 else []) for r in rows]
    m = dict(schema="quantbt.mode5.public_run.continuous.v1" if continuous else "quantbt.mode5.public_run.v1",
        status="FAILED_CLOSED" if no_selection else "SELECTED_REPLAY_VERIFIED",
        dossier_id="private-dossier", calibration_plan_id="private-plan", runtime_binding_identity="private-binding",
        validation_claim="none_full_sample_calibration", meta_learning_activated=False,
        automatic_routing=False, deployment_authorized=False, advisory_shortlist=[{"reason": SECRET}],
        decision=choice.metadata, selection_decision_id=choice.identity, trial_ledger=rows,
        sampler=dict(schema="quantbt-wfo-sampler-study-v1", recipe="cmaes", sampler_class="CmaEsSampler",
            optuna_version="4.8.0", kwargs={"seed": 123, "private-knob": SECRET}, seed=123, stage="public-study-0",
            objective_scope="current_is_study_folds", constraint_mode="post_filter", mixed_space_policy="explicit_independent",
            attempts=6, requested_trials=6, unique_effective_candidates=4, duplicate_attempts=1,
            states={"COMPLETE": 3, "PRUNED": 2, "FAIL": 1}, warm_start_attempts=1,
            independent_sample_calls={SECRET: 6}, relative_proposal_trials=5, startup_policy=1,
            resume="owned_in_process_study_only", rows=telemetry, space={SECRET: [1, 2]}),
        optimizer_schedule="sequential_exact", batch_size=1, candidate_sequence_equivalent_to_sequential=True,
        trial_reports="one completed full candidate at step 0; NopPruner",
        compute_bill={"query_attempts": 6, "effective_candidates": 4, "elapsed_seconds": .01},
        environment_account_policy="CONTINUOUS_PATH_ATTRIBUTION" if continuous else "independent_reset_flat_v1",
        final_account_policy="original_endpoint_full_development_v1",
        chronology={"diagnostic_id": SECRET, "plan_sealed_at_ns": 1, "search_started_at_ns": 2})
    selected_params = None
    if no_selection:
        m["error_type"] = "Mode5NoSelectionError"
    else:
        cid = choice.metadata["chosen_candidate"]
        selected = next(r for r in rows if r["candidate_id"] == cid)
        selected_params = deepcopy(selected["effective_params"])
        m.update(selected_params_digest=cid, selected_audit=deepcopy(selected["observations"]))
    if continuous:
        m.update(annual_account_resets=0, financial_scope="one_original_scorer_account_per_effective_query",
            account_scope=dict(schema="quantbt.mode5.continuous_account_scope.v1", identity="private-scope",
                scored_start_ns=10, scored_stop_ns=20, full_bars=12, preload_bars=2, scored_bars=10,
                scored_positions=[2, 12], account_policy="CONTINUOUS_PATH_ATTRIBUTION",
                annual_account_resets=0, preload_account_execution=False))
    return m, selected_params


@pytest.mark.parametrize("continuous", [False, True])
def test_actual_dictionary_objective_raw_sharpe_and_bounded_snapshot(continuous):
    m, params = runtime_metadata(continuous=continuous)
    report = DecisionReport.read(m, selected_params=params)
    d = report.to_dict(private=True)
    assert d["selected_params"] == params
    assert d["summary"]["chosen_candidate"] == digest(params)
    assert d["summary"]["runner_up_candidate"] == m["trial_ledger"][0]["candidate_id"]
    assert d["summary"]["trial_states"] == {"COMPLETE": 3, "PRUNED": 2, "FAILED": 1}
    assert d["summary"]["duplicate_attempts"] == 1
    assert d["summary"]["unique_evaluated_candidates"] == 4
    row = d["runtime"]["trial_ledger"][1]
    assert row["objective"] > 0 and row["raw_sharpe"] < 0
    assert row["objective"] != row["raw_sharpe"]
    assert "daily_returns" not in row["observations"][0]
    assert "space" not in d["runtime"]["sampler"]
    assert len(report.to_json(private=True)) < 30_000
    if continuous:
        assert row["raw_sharpe"] == pytest.approx(-1.1)
        assert row["annual_mean_raw_sharpe"] == -.7
        assert "dependent attribution" in d["summary"]["account_semantics"]
    else:
        assert "reset-flat" in d["summary"]["account_semantics"]
    assert "not raw Sharpe" in d["summary"]["objective_semantics"]


@pytest.mark.parametrize("continuous", [False, True])
def test_no_selection_retains_nulls_gates_and_adverse_results(continuous):
    m, _ = runtime_metadata(continuous=continuous, no_selection=True)
    report = DecisionReport.read(m)
    d = report.to_dict(private=True)
    assert d["summary"]["selection_status"] == "NO_SELECTION"
    assert d["summary"]["runner_up_candidate"] is None and d["selected_params"] is None
    assert len(d["summary"]["gate_excluded_candidates"]) == 4
    rows = d["runtime"]["decision"]["component_rows"]
    assert rows[0]["components"]["floor"] == -.3
    assert rows[-1]["score"] is None and rows[-1]["components"] is None
    assert "RISK_FAIL" in report.to_json()
    assert "NO\\_SELECTION" in report.to_markdown()
    public = report.to_dict()["runtime"]["trial_ledger"]
    assert public[0]["observations"][0]["utility"]["value"] == -.3
    assert public[-3]["observations"][0]["utility"]["value"] is None
    with pytest.raises(ValueError, match="NO_SELECTION"):
        DecisionReport.read(m, selected_params={SECRET: 11})


def test_hourly_metric_sample_count_does_not_replace_annual_day_support():
    m, _ = runtime_metadata(continuous=True, no_selection=True)
    for row in m["trial_ledger"]:
        for observation in row.get("observations", ()):
            observation["utility"]["sample_count"] = 8760
            observation["daily_count"] = 2 if not observation["support_pass"] else 365
    for evidence in m["decision"]["evidence_refs"]:
        evidence["environment_sample_counts"] = [8760, 8760]
    m["selection_decision_id"] = digest(m["decision"])
    report = DecisionReport.read(m)
    assert report.to_dict(private=True)["runtime"]["decision"] == m["decision"]
    weak = report.to_dict()["runtime"]["trial_ledger"][3]["observations"][0]
    assert weak["utility"]["sample_count"] == 8760
    assert weak["daily_count"] == 2 and weak["support_pass"] is False
    assert "INSUFFICIENT_SUPPORT" in report.to_dict()["runtime"]["decision"]["component_rows"][3]["reasons"]
    assert DecisionReport.from_json(report.to_json(private=True)) == report


def test_empty_predecision_failure_is_not_a_fabricated_decision():
    m, _ = runtime_metadata(no_selection=True)
    m.pop("decision")
    m.pop("selection_decision_id")
    m["trial_ledger"] = []
    m["sampler"].update(rows=[], attempts=0, states={}, duplicate_attempts=0)
    report = DecisionReport.read(m)
    assert report.to_dict()["summary"]["selection_status"] is None
    assert "No decision sealed" in report.to_markdown()
    assert report.to_dict(private=True)["runtime"]["error_type"] == "Mode5NoSelectionError"


def test_sampler_provenance_does_not_relabel_independent_calls_as_joint():
    m, params = runtime_metadata()
    report = DecisionReport.read(m, selected_params=params)
    actual = report.to_dict(private=True)["runtime"]["sampler"]
    assert actual["recipe"] == "cmaes" and actual["sampler_class"] == "CmaEsSampler"
    assert actual["mixed_space_policy"] == "explicit_independent"
    assert actual["startup_policy"] == 1 and actual["kwargs"] == m["sampler"]["kwargs"]
    assert actual["independent_sample_calls"] == {SECRET: 6}
    assert actual["rows"][0]["relative_dimensions"] == []
    assert actual["rows"][1]["relative_dimensions"] == [SECRET]
    assert actual["resume"] == "owned_in_process_study_only"


def test_incumbent_tradeoff_keeps_actual_post_guard_dictionary():
    m, params = runtime_metadata(incumbent=True)
    report = DecisionReport.read(m, selected_params=params)
    d = report.to_dict(private=True)
    choice = d["runtime"]["decision"]
    assert choice["incumbent_guard"] == "INCUMBENT_RETAINED_BY_DECLARED_MARGIN"
    assert choice["pre_incumbent_candidate"] != choice["chosen_candidate"]
    assert d["summary"]["runner_up_candidate"] == choice["pre_incumbent_candidate"]
    assert d["selected_params"][SECRET] == 11
    assert "INCUMBENT\\_RETAINED\\_BY\\_DECLARED\\_MARGIN" in report.to_markdown()


def test_pareto_front_and_normalized_components_are_preserved():
    m, params = runtime_metadata(pareto=True)
    report = DecisionReport.read(m, selected_params=params)
    d = report.to_dict(private=True)["runtime"]["decision"]
    assert d["selector_algorithm"] == "pareto_post_selection_chebyshev"
    assert d["front_metric_claim"] == "not_selected_point_performance"
    assert any(r["pareto_front"] for r in d["component_rows"])
    assert "normalized_gaps" in report.to_json()


@pytest.mark.parametrize("slot", ["local", "tail"])
def test_local_and_tail_formula_components_remain_frozen(slot):
    m, params = runtime_metadata(**{slot: True})
    report = DecisionReport.read(m, selected_params=params)
    d = report.to_dict(private=True)["runtime"]["decision"]
    assert d == m["decision"]
    public = report.to_dict()["runtime"]["decision"]["component_rows"]
    if slot == "local":
        assert d["formula_version"] == "local_downside_v1"
        assert public[0]["components"]["fragility"] > 0
        assert "private-local-reference" not in report.to_json()
    else:
        assert d["formula_version"] == "environment_lower_tail_v2"
        assert public[0]["components"]["floor_tail_redundancy"] is True
        assert public[0]["components"]["tail"] == public[0]["components"]["floor"]


def test_default_privacy_all_views_and_explicit_private_serialization():
    m, params = runtime_metadata()
    report = DecisionReport.read(m, selected_params=params)
    for public in (str(report.to_dict()), report.to_json(), report.to_markdown()):
        assert SECRET not in public
        assert "private-env" not in public and "private-metric" not in public
        assert digest(params) not in public
        assert "private-dossier" not in public and "private-knob" not in public
    assert SECRET not in repr(report)
    assert report.to_dict()["selected_params"] == "REDACTED"
    assert report.to_dict(private=True)["selected_params"] == params
    assert SECRET in report.to_json(private=True)
    markdown = report.to_markdown(private=True)
    assert "<script>" not in markdown and "&lt;script&gt;" in markdown
    assert DecisionReport.from_json(report.to_json(private=True)) == report
    with pytest.raises(ValueError, match="private decision report"):
        DecisionReport.from_json(report.to_json())


def test_record_mutation_copy_pickle_and_input_ownership():
    m, params = runtime_metadata()
    report = DecisionReport.read(m, selected_params=params)
    original = report.to_json(private=True)
    m["trial_ledger"][0]["effective_params"][SECRET] = -999
    params[SECRET] = -999
    with pytest.raises(FrozenInstanceError):
        report.record = Record.of({})
    for copied in (deepcopy(report), pickle.loads(pickle.dumps(report))):
        copied.record.data["runtime"]["trial_ledger"].clear()
        copied.to_dict(private=True)["selected_params"].clear()
        copied.to_dict()["summary"].clear()
        assert copied.to_json(private=True) == original


@pytest.mark.parametrize("mutation", ["missing_decision", "missing_params", "wrong_params", "digest",
    "decision_hash", "component_hash", "component_score", "formula", "audit", "audit_length", "ledger_params",
    "sampler_params", "sampler_count", "sampler_state", "duplicate_ref", "duplicate_id", "running", "missing_observations",
    "reference", "evidence"])
def test_inconsistent_runtime_metadata_rejected(mutation):
    m, params = runtime_metadata()
    if mutation == "missing_decision":
        m.pop("decision")
    elif mutation == "missing_params":
        params = None
    elif mutation == "wrong_params":
        params[SECRET] = 55
    elif mutation == "digest":
        m["selected_params_digest"] = "wrong"
    elif mutation == "decision_hash":
        m["selection_decision_id"] = "wrong"
    elif mutation in {"component_hash", "component_score", "formula", "reference", "evidence"}:
        d = m["decision"]
        if mutation == "component_hash":
            d["component_hash"] = "wrong"
        elif mutation == "component_score":
            d["component_rows"][0]["score"] = 99
            d["component_hash"] = digest(d["component_rows"])
        elif mutation == "formula":
            d["formula_coefficients"] = [["mean", .99]]
        elif mutation == "reference":
            d["reference"]["weights"][0] = 10.
        else:
            d["evidence_refs"][0]["environment_values"][0] = 99.
        m["selection_decision_id"] = digest(d)
    elif mutation == "audit":
        m["selected_audit"][0]["finance"]["equity"] = "wrong"
    elif mutation == "audit_length":
        m["selected_audit"].pop()
    elif mutation == "ledger_params":
        m["trial_ledger"][1]["effective_params"] = {SECRET: -9}
    elif mutation == "sampler_params":
        m["sampler"]["rows"][1]["effective_params"] = {SECRET: -9}
    elif mutation == "sampler_count":
        m["sampler"]["attempts"] = 7
    elif mutation == "sampler_state":
        m["sampler"]["rows"][0]["state"] = "PRUNED"
    elif mutation == "duplicate_ref":
        m["trial_ledger"][4]["evaluation_ref"] = "wrong"
    elif mutation == "duplicate_id":
        m["trial_ledger"][5]["trial_id"] = 0
    elif mutation == "running":
        m["trial_ledger"][0]["state"] = "RUNNING"
    elif mutation == "missing_observations":
        m["trial_ledger"][0].pop("observations")
    with pytest.raises(ValueError):
        DecisionReport.read(m, selected_params=params)


@pytest.mark.parametrize("mutation", ["reset_policy", "scope_reset", "missing_scope", "preload", "whole_sharpe",
                                      "scope_policy", "scope_bars", "missing_whole"])
def test_continuous_scope_and_raw_sharpe_mismatch_reject(mutation):
    m, params = runtime_metadata(continuous=True)
    if mutation == "reset_policy":
        m["environment_account_policy"] = "independent_reset_flat_v1"
    elif mutation == "scope_reset":
        m["account_scope"]["annual_account_resets"] = 1
    elif mutation == "missing_scope":
        m.pop("account_scope")
    elif mutation == "preload":
        m["account_scope"]["preload_account_execution"] = True
    elif mutation == "scope_policy":
        m["account_scope"]["account_policy"] = "independent_reset_flat_v1"
    elif mutation == "scope_bars":
        m["account_scope"]["scored_bars"] = 11
    elif mutation == "missing_whole":
        m["trial_ledger"][1].pop("whole_observation")
    else:
        m["trial_ledger"][1]["raw_sharpe"] = 99
    with pytest.raises(ValueError):
        DecisionReport.read(m, selected_params=params)


def test_altered_cold_summary_is_rejected():
    m, params = runtime_metadata()
    d = DecisionReport.read(m, selected_params=params).to_dict(private=True)
    d["summary"]["chosen_candidate"] = "invented"
    with pytest.raises(ValueError, match="summary"):
        DecisionReport.from_json(json.dumps(d))


def test_cold_reload_cannot_insert_large_account_arrays():
    m, params = runtime_metadata()
    d = DecisionReport.read(m, selected_params=params).to_dict(private=True)
    d["runtime"]["trial_ledger"][0]["observations"][0]["daily_returns"] = [0.] * 100
    with pytest.raises(ValueError, match="bounded"):
        DecisionReport.from_json(json.dumps(d))


def test_missing_required_runtime_metadata_rejects_without_guessing():
    m, params = runtime_metadata()
    for field in ("trial_ledger", "sampler", "schema", "selection_decision_id"):
        broken = deepcopy(m)
        broken.pop(field)
        with pytest.raises(ValueError):
            DecisionReport.read(broken, selected_params=params)


def test_private_disclosure_requires_boolean_and_no_selection_stays_absent():
    m, _ = runtime_metadata(no_selection=True)
    report = DecisionReport.read(m)
    assert report.to_dict()["selected_params"] is None
    assert report.to_dict()["runtime"]["selected_audit"] is None
    for renderer in (report.to_dict, report.to_json, report.to_markdown):
        with pytest.raises(ValueError, match="explicit boolean"):
            renderer(private="false")


def test_private_strings_in_numeric_slots_do_not_escape_public_allowlist():
    m, params = runtime_metadata()
    m["sampler"]["requested_trials"] = SECRET
    m["sampler"]["independent_sample_calls"][SECRET] = SECRET
    m["trial_ledger"][0]["raw_sharpe"] = SECRET
    report = DecisionReport.read(m, selected_params=params)
    assert SECRET not in report.to_json() and SECRET not in report.to_markdown()
    assert SECRET in report.to_json(private=True)


def test_read_and_render_never_call_execution_search_reduction_or_rng(monkeypatch):
    import random
    import numpy as np
    from quantbt.mode5 import runtime
    from quantbt.mode5.selection import selectors, objectives

    m, params = runtime_metadata()

    def forbidden(*args, **kwargs):
        raise AssertionError("report is cold")

    monkeypatch.setattr(runtime.PublicMode5Runtime, "optimize", forbidden)
    monkeypatch.setattr(runtime.PublicMode5Runtime, "_observe_point", forbidden)
    monkeypatch.setattr(runtime, "run_ordered_study", forbidden)
    monkeypatch.setattr(selectors, "select", forbidden)
    monkeypatch.setattr(objectives, "evaluate", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(np.random, "random", forbidden)
    state = pickle.dumps((random.getstate(), np.random.get_state()))
    report = DecisionReport.read(m, selected_params=params)
    report.to_json()
    report.to_markdown()
    reloaded = DecisionReport.from_json(report.to_json(private=True))
    assert reloaded == report
    assert pickle.dumps((random.getstate(), np.random.get_state())) == state
