"""Synthetic retained-byte ML-06 diagnostics; no fits or financial execution."""

from copy import deepcopy
from collections import Counter
from dataclasses import replace
import gzip
import json

import numpy as np
import pandas as pd
import pytest

from quantbt.diagnostics import AccessPolicy, AccessWitness, AlphaDiagnostics
from quantbt.optimization.meta_selection.common import canonical, digest, wire
from quantbt.optimization.meta_selection.descriptors import OriginBalancedStandardizer
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import (
    MetaModelArtifact, RidgeLearner, RidgeSettings, scaler_payload, schema_payload,
)
from quantbt.optimization.meta_selection.numerics import NumericLimits
from quantbt.optimization.meta_selection.persistence import dumps_revision
from quantbt.optimization.meta_selection.records import OutcomeStatus
from quantbt.optimization.meta_selection.selection import MetaSelectionDecision
from tests.meta_selection.test_qms03_history import make_task, revision_for as base_revision_for
from tools.meta_model_research.admission import Corpus, pin
from tools.meta_model_research import decision_diagnostics as module


def write_source(root, fold, name, value):
    path = root / "folds" / f"{fold:02d}" / (name + ".json.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(canonical(value).encode(), mtime=0))
    return pin(path)


def revision_for(task, schema):
    return base_revision_for(task, schema, status_by_id={
        c.evaluation_id: c.observation.status for c in task.candidates
        if c.observation.status != OutcomeStatus.VALID})


def saved_model(schema, snapshot, task):
    """A declared synthetic artifact with known coefficients, not a fitted model."""
    d = len(schema.feature_names)
    mean, scale = np.zeros(d), np.ones(d)
    constant, observed = np.zeros(d, dtype=bool), np.zeros(d, dtype=bool)
    observed[list(schema.numeric_columns)] = True
    j = schema.feature_names.index("threshold:numeric")
    constant[j] = True
    mean[j] = np.log(0.2 / 0.1) / np.log(10 / 0.1)
    scale[schema.feature_names.index("raw_is_sharpe")] = 2
    scale[schema.feature_names.index("log1p_is_activity")] = 3
    scaler = OriginBalancedStandardizer(schema.schema_id, snapshot.snapshot_id,
        schema.feature_names, schema.numeric_columns, mean, scale, constant, observed)
    beta = np.zeros(d)
    beta[0] = 0.05
    beta[schema.feature_names.index("raw_is_sharpe")] = -2
    beta[schema.feature_names.index("log1p_is_activity")] = 0.1
    gram = np.eye(d) * 10
    return MetaModelArtifact(
        snapshot.family_id, snapshot.snapshot_id, snapshot.information_as_of,
        task.search_completed_at, task.wall_generated_at, task.clock_mode,
        dict(corpora=snapshot.authorized_corpora, cohorts=snapshot.outcome_origins,
             exposures=snapshot.research_exposures, snapshot_order=snapshot.snapshot_order),
        tuple(sorted((r.task.task_id, r.revision_id, r.content_digest) for r in snapshot.revisions)),
        tuple((r.task_id, r.revision_id, r.candidate_evaluation_id, r.origin_weight)
              for r in snapshot.training_rows),
        snapshot.origin_count, schema_payload(schema), scaler_payload(scaler),
        RidgeSettings(), NumericLimits(), tuple(beta), tuple(map(tuple, gram)),
        tuple(gram @ beta), {}, {"selected": "synthetic_saved_artifact"})


def saved_decision(task, schema, model):
    anchor = task.anchor
    predictions, ties = [], ()
    selected = anchor
    if model is None:
        status = "META_SUPPORT_INSUFFICIENT"
    else:
        batch = schema.encode(task.candidates)
        scaled, unsupported = OriginBalancedStandardizer(**dict(model.scaler)).transform(batch)
        if (unsupported & batch.valid).any():
            status = "META_OOD_NATIVE_FALLBACK"
        else:
            status = "META_MODEL_PROPOSAL"
            coords = schema.parameter_geometry(task.candidates)
            for i, c in enumerate(task.candidates):
                y = float((scaled[i] - scaled[0]) @ np.asarray(model.coefficients)) if batch.valid[i] else None
                q = c.observation.raw_sharpe - anchor.observation.raw_sharpe - y if y is not None else None
                predictions.append(dict(evaluation_id=c.evaluation_id, candidate_id=c.candidate_id,
                    raw_is=c.observation.raw_sharpe, yhat=y, qhat=q,
                    distance=float(np.linalg.norm(coords[i] - coords[0])) if y is not None else None,
                    eligible=q is not None and q >= -0.1,
                    exclusion=None if q is not None and q >= -0.1 else c.observation.status.value))
            best = min(p["yhat"] for p in predictions if p["eligible"])
            tied = [p for p in predictions if p["eligible"] and p["yhat"] <= best + 1e-10]
            winner = min(tied, key=lambda p: (p["distance"], p["candidate_id"], p["evaluation_id"]))
            selected = next(c for c in task.candidates if c.evaluation_id == winner["evaluation_id"])
            ties = tuple(p["evaluation_id"] for p in tied)
    return MetaSelectionDecision(
        task.task_id, anchor.evaluation_id, selected.evaluation_id, selected.evaluation_id,
        dict(selected.effective_params), anchor.evaluation_id, model.model_id if model else None,
        model.training_snapshot_id if model else None, task.data_cutoff,
        model.fit_completed_at if model else None, task.decision_sealed_at,
        task.decision_sealed_at, task.clock_mode, "active", status, tuple(predictions), ties, (), {}, {})


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("monthly-retained")
    revisions, schema = [], None
    for fold in range(57):
        task, schema = make_task(n=6, year=1950 + fold, schema=schema)
        candidates = []
        for i, c in enumerate(task.candidates):
            params = dict(c.effective_params)
            if params["filter"]:
                params["threshold"] = 0.2
            m = c.observation
            if i == 3:
                m = replace(m, activity_count=0)
            if i == 4:
                m = replace(m, raw_sharpe=None, status=OutcomeStatus.NO_VARIANCE,
                            sample_std=None, sample_count=0, activity_count=None)
            if i == 5:
                params = dict(candidates[1].effective_params)
                m = replace(candidates[1].observation, output_ref=m.output_ref)
            candidates.append(replace(c, requested_params=params, effective_params=params, observation=m))
        task = replace(task, candidates=tuple(candidates), sampling_provenance=dict(
            budget=128, trial_counts=dict(attempted=128, completed=124, pruned=3, failed=1)))
        revisions.append(revision_for(task, schema))
    history = MetaHistory()
    for revision in revisions:
        history.append(revision)
    selections, pins = [], []
    for fold, revision in enumerate(revisions):
        task = revision.task
        snapshot = history.snapshot(family_id=task.family.family_id,
            authorized_corpora=(task.corpus_id,), outcome_origins=(task.outcome_origin,),
            research_exposures=(task.research_exposure,), information_as_of=task.data_cutoff)
        model = saved_model(schema, snapshot, task) if fold >= 15 else None
        decision = saved_decision(task, schema, model)
        chosen = next(c for c in task.candidates if c.evaluation_id == decision.actual_evaluation_id)
        saved = dict(task=wire(task), model=wire(model), snapshot=dict(
            family_id=snapshot.family_id, authorized_corpora=snapshot.authorized_corpora,
            outcome_origins=snapshot.outcome_origins, research_exposures=snapshot.research_exposures,
            information_as_of=snapshot.information_as_of, snapshot_id=snapshot.snapshot_id,
            revision_ids=[r.revision_id for r in snapshot.revisions]), record=dict(
                native_selected_evaluation_id=task.anchor_candidate_evaluation_id,
                native_selected_params=dict(task.anchor.effective_params),
                selected_evaluation_id=chosen.evaluation_id, selected_params=dict(chosen.effective_params),
                current_outer_oos_used_for_selection=False, information_as_of=task.data_cutoff,
                decision_sealed_at=task.decision_sealed_at, training_snapshot_id=snapshot.snapshot_id,
                final_selection_reason=decision.status, proposal=wire(decision),
                native_selection_reason=dict(neighbor_count=3, feasible_trials=124,
                    top_trials=12, seed_consensus_count=1, fallback_reasons=["no_candidate_met_neighbor_or_seed_consensus"],
                    param_names=["PRIVATE-AXIS"], params={"PRIVATE-COORDINATE": 987654321})))
        saved = wire(saved)
        selections.append(saved)
        pins.append(write_source(root, fold, "revision", json.loads(dumps_revision(revision))))
        pins.append(write_source(root, fold, "selection", saved))
    return Corpus("SYNTHETIC", tuple(revisions), tuple(selections), schema, history, tuple(pins))


def patched(corpus, root, fold, *, saved=None, revision=None):
    revisions, selections = list(corpus.revisions), list(corpus.selections)
    if revision is not None:
        revisions[fold] = revision
    selections[fold] = deepcopy(corpus.selections[fold]) if saved is None else saved
    refs = [p for p in corpus.pins if not p["path"].endswith(
        f"folds/{fold:02d}/selection.json.gz") and not p["path"].endswith(f"folds/{fold:02d}/revision.json.gz")]
    refs.append(write_source(root, fold, "selection", selections[fold]))
    refs.append(write_source(root, fold, "revision", json.loads(dumps_revision(revisions[fold]))))
    history = MetaHistory()
    for r in revisions:
        history.append(r)
    return replace(corpus, revisions=tuple(revisions), selections=tuple(selections), pins=tuple(refs), history=history)


@pytest.fixture(scope="module")
def result(corpus):
    return module.monthly_diagnostics(corpus)


def test_all57_and_actual_maturity_not_theoretical_threshold(result):
    assert result["folds"] == len(result["rows"]) == 57
    assert [r["fold"] for r in result["rows"]] == list(range(57))
    assert result["rows"][12]["matured_origins"] == 12
    assert result["first_actually_mature_fold"] == 15
    assert [r["fold"] for r in result["deep_checks"]] == [15, 40, 56]
    assert Counter(r["role"] for r in result["rows"]) == {"acquisition": 13, "development": 12, "evaluation": 32}
    assert result["model_fits"] == result["financial_calls"] == result["optimizer_proposals"] == result["new_features"] == 0


def test_shared_owner_coverage_activity_branches_and_adaptive_suppression(result):
    row = result["rows"][40]
    c = row["coverage"]
    assert c["evaluations"] == 6 and c["unique_effective_candidates"] == 5
    assert c["duplicate_effective_evaluations"] == 1
    assert c["missing_primary"] == 1 and c["measured_primary"] == 5
    assert c["nominal_dimensions"] == 4 and c["observed_varying_dimensions"] == 3
    assert c["conditional_dimensions"] == 1
    assert c["active_dimensions"] == dict(minimum=3, maximum=4)
    assert sum(b["evaluations"] for b in c["branches"]) == 6
    assert c["effective_dimension_estimate"]["status"] == "UNAVAILABLE"
    assert row["activity"]["zero_activity_evaluations"] == 1
    assert row["activity"]["missing_evaluations"] == 1
    assert row["associations"]["status"] == "NOT_ESTIMATED_ADAPTIVE_OR_REVIEWED_ROSTER"
    assert row["associations"]["result"] is None
    assert len(row["shared_report_id"]) == 64


def test_shared_api_called_once_per_pool(corpus, monkeypatch):
    seen = []
    original = AlphaDiagnostics.analyze

    def observed(self, rows, **kwargs):
        seen.append((self.access.cutoff_ns, len(rows), self.context.outcome_blind_roster))
        return original(self, rows, **kwargs)

    monkeypatch.setattr(AlphaDiagnostics, "analyze", observed)
    module.monthly_diagnostics(corpus)
    assert len(seen) == 57 and all(n == 6 and not blind for _, n, blind in seen)


def test_exact_scaled_contributions_and_is_q_algebra(corpus, result):
    row = result["rows"][40]
    task = corpus.revisions[40].task
    selected = next(c for c in task.candidates if c.evaluation_id == corpus.selections[40]["record"]["selected_evaluation_id"])
    anchor = task.anchor
    target = row["ridge"]["targets"]["selected"]
    delta = selected.observation.raw_sharpe - anchor.observation.raw_sharpe
    expected_is = -delta  # beta_IS=-2, historical scale_IS=2.
    expected_activity = 0.1 * (np.log1p(selected.observation.activity_count) - np.log1p(anchor.observation.activity_count)) / 3
    expected_param = 0.05 * (selected.effective_params["hma_length"] - anchor.effective_params["hma_length"]) / 98
    assert target["raw_is_yhat_contribution"] == pytest.approx(expected_is)
    assert target["activity_yhat_contribution"] == pytest.approx(expected_activity)
    assert target["yhat"] == pytest.approx(expected_is + expected_activity + expected_param)
    assert target["contribution_sum"] == pytest.approx(target["yhat"])
    assert sum(t["yhat_contribution"] for t in target["contributions"]) == pytest.approx(target["yhat"])
    assert target["qhat"] == pytest.approx(delta - target["yhat"])
    assert target["raw_is_qhat_contribution"] + target["other_qhat_contribution"] == pytest.approx(target["qhat"])
    anchor_target = row["ridge"]["targets"]["anchor"]
    assert anchor_target["yhat"] == anchor_target["qhat"] == 0
    assert all(t["yhat_contribution"] == 0 for t in anchor_target["contributions"])
    assert row["position"]["selector_anchor_distance"] > 0
    assert row["position"]["same_effective_params"] is False
    assert row["ridge"]["coefficient_stability"]["previous_fold"] == 39
    assert row["ridge"]["coefficient_stability"]["l2_change"] == 0


def test_native_and_absent_paths_are_explicit(result):
    native = result["rows"][40]["native"]
    assert native["cluster_counts"]["neighbor_count"] == 3
    assert native["fallback"]["occurred"] is True
    assert native["fallback"]["count"] == 1
    for deep in result["deep_checks"]:
        for name in ("local_probes", "continuous_is_environment", "episodes", "x2"):
            assert deep[name]["status"] == "UNAVAILABLE" and deep[name]["value"] is None
    assert any(f["historically_constant"] for f in result["rows"][40]["ridge"]["features"])
    assert result["rows"][40]["ridge"]["ood_valid_candidates"] == 0


def test_trial_counts_are_actual_source_counts_not_pool_size(result):
    trials = result["rows"][40]["coverage"]["trials"]
    assert {n: r["value"] for n, r in trials.items()} == dict(attempted=128, completed=124, pruned=3, failed=1)
    assert all(r["status"] == "SOURCE_BOUND" for r in trials.values())


def test_privacy_strict_json_and_detached_exports(corpus, result):
    encoded = json.dumps(result, allow_nan=False)
    for private in ("hma_length", "threshold", "smooth", "degree", "PRIVATE", "candidate-", "evaluation-", "/tmp/", '"effective_params":', '"coefficients":', "numeric_columns"):
        assert private not in encoded, f"Private field or value exported: {private}"
    assert "raw_is_sharpe" in encoded and "log1p_is_activity" in encoded
    assert result["rows"][40]["source"]["selection"]["sha256"] in {p["sha256"] for p in corpus.pins}
    assert len(result["rows"][40]["source"]["model_digest"]) == 64
    modified = deepcopy(result)
    modified["rows"][40]["coverage"]["axes"][0]["observed_values"] = 999
    assert result["rows"][40]["coverage"]["axes"][0]["observed_values"] != 999


def test_no_fit_optimizer_or_corpus_discovery(corpus, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("new execution is forbidden")

    from tools.meta_model_research import admission
    monkeypatch.setattr(RidgeLearner, "fit", forbidden)
    monkeypatch.setattr(OriginBalancedStandardizer, "fit", forbidden)
    monkeypatch.setattr(admission, "load_corpus", forbidden)
    assert module.monthly_diagnostics(corpus)["model_fits"] == 0


def test_decoded_model_or_selection_changes_cannot_bypass_saved_bytes(corpus):
    changed = deepcopy(corpus.selections)
    changed[40]["model"]["coefficients"][0] += 1
    with pytest.raises(ValueError, match="SELECTION_BYTES_CHANGED"):
        module.monthly_diagnostics(replace(corpus, selections=changed))


def test_missing_pin_and_file_tampering_fail_closed(corpus, tmp_path):
    with pytest.raises(ValueError, match="SOURCE_PIN_ROSTER"):
        module.monthly_diagnostics(replace(corpus, pins=corpus.pins[1:]))
    changed = patched(corpus, tmp_path, 0)
    ref = next(p for p in changed.pins if p["path"].startswith(str(tmp_path)) and p["path"].endswith("selection.json.gz"))
    from pathlib import Path
    path = Path(ref["path"])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash/size"):
        module.monthly_diagnostics(changed)


@pytest.mark.parametrize("checkpoint", [15, 40, 56])
def test_later_model_or_full_development_snapshot_cannot_authorize_prefix(corpus, monkeypatch, checkpoint):
    original = Corpus.snapshot

    def later(self, fold):
        snapshot = original(self, fold)
        return replace(snapshot, information_as_of=snapshot.information_as_of + pd.Timedelta(days=1)) if fold == checkpoint else snapshot

    monkeypatch.setattr(Corpus, "snapshot", later)
    with pytest.raises(ValueError, match="FUTURE_SNAPSHOT"):
        module.monthly_diagnostics(corpus)


def test_shared_witness_rejects_future_readiness(corpus, monkeypatch):
    original = module.AccessWitness

    def late(*args):
        witness = original(*args)
        return replace(witness, ready_ns=witness.ready_ns + pd.Timedelta(days=1).value)

    monkeypatch.setattr(module, "AccessWitness", late)
    with pytest.raises(PermissionError, match="future or immature"):
        module.monthly_diagnostics(corpus)


def test_shared_policy_rejects_full_development_witness_at_early_prefix():
    policy = AccessPolicy("early", ("diagnostic_development",), ("source",), 100, "diagnostic")
    with pytest.raises(PermissionError, match="future or immature"):
        policy.require(AccessWitness("source", "diagnostic_development", 1, 1000, 1000))


def test_future_outcome_and_late_revision_do_not_change_earlier_prefixes(corpus, result, tmp_path):
    revision = corpus.revisions[56]
    outcomes = tuple(replace(o, observation=replace(o.observation, raw_sharpe=123456)) for o in revision.outcomes)
    revision = replace(revision, outcomes=outcomes,
                       revision_available_at=revision.revision_available_at + pd.Timedelta(days=500))
    mutated = module.monthly_diagnostics(patched(corpus, tmp_path, 56, revision=revision))
    assert mutated["rows"][:56] == result["rows"][:56]
    assert mutated["rows"][56]["ridge"] == result["rows"][56]["ridge"]
    assert mutated["rows"][56]["coverage"] == result["rows"][56]["coverage"]


def test_model_prediction_mismatch_is_not_reported_as_exact(corpus, tmp_path):
    saved = deepcopy(corpus.selections[40])
    selected = saved["record"]["selected_evaluation_id"]
    prediction = next(p for p in saved["record"]["proposal"]["predictions"] if p["evaluation_id"] == selected)
    prediction["yhat"] -= 0.01
    prediction["qhat"] += 0.01
    with pytest.raises(ValueError, match="SERVED_PREDICTION_MISMATCH"):
        module.monthly_diagnostics(patched(corpus, tmp_path, 40, saved=saved))


def test_missing_authoritative_trial_counts_are_not_inferred(corpus, tmp_path):
    old = corpus.revisions[56]
    task = replace(old.task, sampling_provenance={"budget": 128})
    revision = revision_for(task, corpus.schema)
    snapshot = corpus.snapshot(56)
    model = saved_model(corpus.schema, snapshot, task)
    decision = saved_decision(task, corpus.schema, model)
    saved = deepcopy(corpus.selections[56])
    saved["task"], saved["model"] = wire(task), wire(model)
    saved["record"]["proposal"] = wire(decision)
    row = module.monthly_diagnostics(patched(corpus, tmp_path, 56, saved=saved, revision=revision))["rows"][56]
    assert row["coverage"]["requested_trial_budget"] == 128
    assert all(r["value"] is None and r["status"] == "UNAVAILABLE" for r in row["coverage"]["trials"].values())


def test_ood_is_whole_pool_fallback_not_served_anchor_contributions(corpus, tmp_path):
    old = corpus.revisions[56]
    candidates = list(old.task.candidates)
    c = candidates[1]
    params = dict(c.effective_params, threshold=0.3)
    candidates[1] = replace(c, requested_params=params, effective_params=params)
    task = replace(old.task, candidates=tuple(candidates))
    revision = revision_for(task, corpus.schema)
    model = saved_model(corpus.schema, corpus.snapshot(56), task)
    decision = saved_decision(task, corpus.schema, model)
    assert decision.status == "META_OOD_NATIVE_FALLBACK"
    saved = deepcopy(corpus.selections[56])
    saved["task"], saved["model"] = wire(task), wire(model)
    saved["record"].update(proposal=wire(decision), selected_evaluation_id=task.anchor.evaluation_id,
        selected_params=wire(task.anchor.effective_params), final_selection_reason=decision.status)
    row = module.monthly_diagnostics(patched(corpus, tmp_path, 56, saved=saved, revision=revision))["rows"][56]
    assert row["ridge"]["ood_valid_candidates"] == 1
    assert row["ridge"]["whole_pool_ood_fallback"] is True
    assert row["ridge"]["targets"]["anchor"]["status"] == "NOT_SERVED"
    assert row["ridge"]["targets"]["selected"]["contributions"] is None


def test_incomplete_roster_is_not_silently_truncated(corpus):
    with pytest.raises(ValueError, match="MONTHLY_57_ROSTER_REQUIRED"):
        module.monthly_diagnostics(replace(corpus, revisions=corpus.revisions[:-1]))


def replace_saved_model(corpus, root, fold, model):
    task = corpus.revisions[fold].task
    decision = saved_decision(task, corpus.schema, model)
    chosen = next(c for c in task.candidates if c.evaluation_id == decision.actual_evaluation_id)
    saved = deepcopy(corpus.selections[fold])
    saved["model"] = wire(model)
    saved["record"].update(proposal=wire(decision), selected_evaluation_id=chosen.evaluation_id,
        selected_params=wire(chosen.effective_params), final_selection_reason=decision.status)
    return patched(corpus, root, fold, saved=saved)


def test_first_mature_artifact_is_deep_checked_even_if_ood(corpus, tmp_path):
    task = corpus.revisions[15].task
    model = saved_model(corpus.schema, corpus.snapshot(15), task)
    scaler = wire(model.scaler)
    j = corpus.schema.feature_names.index("raw_is_sharpe")
    scaler["constant"][j] = True
    model = replace(model, scaler=scaler)
    result = module.monthly_diagnostics(replace_saved_model(corpus, tmp_path, 15, model))
    assert result["first_actually_mature_fold"] == 15
    assert result["deep_checks"][0]["fold"] == 15
    assert result["deep_checks"][0]["ridge"]["selection_status"] == "META_OOD_NATIVE_FALLBACK"
    assert result["rows"][16]["ridge"]["selection_status"] == "META_MODEL_PROPOSAL"


def test_permitted_retained_model_change_is_nonvacuous(corpus, result, tmp_path):
    task = corpus.revisions[40].task
    model = saved_model(corpus.schema, corpus.snapshot(40), task)
    beta = np.asarray(model.coefficients).copy()
    beta[corpus.schema.feature_names.index("raw_is_sharpe")] -= 0.5
    model = replace(model, coefficients=tuple(beta), reference_b=tuple(np.asarray(model.reference_gram) @ beta))
    modified = module.monthly_diagnostics(replace_saved_model(corpus, tmp_path, 40, model))
    assert modified["rows"][:40] == result["rows"][:40]
    before = result["rows"][40]["ridge"]["targets"]["selected"]
    after = modified["rows"][40]["ridge"]["targets"]["selected"]
    assert before["raw_is_yhat_contribution"] != after["raw_is_yhat_contribution"]
    assert before["qhat"] != after["qhat"]
    assert modified["rows"][40]["ridge"]["coefficient_stability"]["l2_change"] == pytest.approx(0.5)


def test_missing_native_metadata_does_not_become_a_no_fallback_claim(corpus, tmp_path):
    saved = deepcopy(corpus.selections[56])
    del saved["record"]["native_selection_reason"]
    row = module.monthly_diagnostics(patched(corpus, tmp_path, 56, saved=saved))["rows"][56]
    assert row["native"]["status"] == "UNAVAILABLE"
    assert row["native"]["value"] is None


def test_current_forward_permission_cannot_be_relabelled_as_diagnostics(corpus, tmp_path):
    saved = deepcopy(corpus.selections[0])
    saved["record"]["current_outer_oos_used_for_selection"] = True
    with pytest.raises(ValueError, match="CURRENT_FORWARD_RIGHTS"):
        module.monthly_diagnostics(patched(corpus, tmp_path, 0, saved=saved))


@pytest.mark.parametrize("selector,reason,size,occurred", [
    ("medoid", None, 7, False),
    ("fallback_best_is_temporal", "no_dense_train_plateau", 0, True),
])
def test_actual_native_shape_is_source_bound_and_private(selector, reason, size, occurred):
    source = dict(selector=selector, cluster_size=size,
                  params={"PRIVATE-AXIS": 987654321}, coordinates=["PRIVATE-COORDINATE"])
    if reason is not None:
        source["reason"] = reason
    before = deepcopy(source)
    native = module._native(dict(native_selection_reason=source))
    assert source == before
    assert native["cluster_counts"] == {"cluster_size": size}
    assert native["cluster_status"] == "RETAINED"
    assert native["selector"] == selector and native["reason"] == reason
    assert native["metadata_digest"] == digest(source)
    assert native["fallback"]["status"] == "SOURCE_BOUND"
    assert native["fallback"]["occurred"] is occurred
    assert native["fallback"]["known_reasons"] == ([reason] if reason else [])
    assert native["fallback"]["count"] == int(reason is not None)
    encoded = json.dumps(native, allow_nan=False)
    for private in ("PRIVATE", "987654321", '"params":', '"coordinates":'):
        assert private not in encoded, f"Private native metadata exported: {private}"


@pytest.mark.parametrize("selector,reason,occurred", [
    ("medoid", None, False),
    ("fallback_best_is_temporal", "no_dense_train_plateau", True),
])
def test_actual_native_shape_survives_monthly_export(corpus, tmp_path, selector, reason, occurred):
    saved = deepcopy(corpus.selections[56])
    source = dict(selector=selector, cluster_size=0 if occurred else 5,
                  params={"PRIVATE-PARAM": 987654321})
    if reason is not None:
        source["reason"] = reason
    saved["record"]["native_selection_reason"] = source
    report = module.monthly_diagnostics(patched(corpus, tmp_path, 56, saved=saved))
    native = report["rows"][56]["native"]
    assert native["cluster_counts"]["cluster_size"] == source["cluster_size"]
    assert native["fallback"]["occurred"] is occurred
    assert report["deep_checks"][-1]["native"] == native
    assert "PRIVATE" not in json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("source", [
    {"cluster_size": 0},
    {"cluster_size": 0, "selector": "PRIVATE-fallback", "reason": "PRIVATE-reason"},
])
def test_unknown_native_disposition_is_unavailable_not_inferred_from_cluster_size(source):
    native = module._native(dict(native_selection_reason=source))
    assert native["cluster_status"] == "RETAINED"
    assert native["fallback"]["status"] == "UNAVAILABLE"
    assert native["fallback"]["value"] is None
    assert native["selector"] is None and native["reason"] is None
    assert "PRIVATE" not in json.dumps(native)


def test_known_fallback_selector_does_not_require_a_reason_array():
    native = module._native(dict(native_selection_reason=dict(selector="fallback_best_is_temporal")))
    assert native["fallback"]["occurred"] is True
    assert native["fallback"]["known_reasons"] == []
    assert native["fallback"]["count"] == 0
    assert native["cluster_status"] == "UNAVAILABLE"


def test_known_native_reason_is_authoritative_without_a_selector():
    native = module._native(dict(native_selection_reason=dict(reason="no_dense_train_plateau")))
    assert native["fallback"]["occurred"] is True
    assert native["fallback"]["known_reasons"] == ["no_dense_train_plateau"]


@pytest.mark.parametrize("size", [-1, True, 2.5])
def test_native_cluster_size_requires_an_exact_nonnegative_count(size):
    with pytest.raises(ValueError, match="NATIVE_CLUSTER_COUNT"):
        module._native(dict(native_selection_reason=dict(selector="medoid", cluster_size=size)))


def test_conflicting_known_native_dispositions_fail_closed():
    with pytest.raises(ValueError, match="NATIVE_FALLBACK_CONFLICT"):
        module._native(dict(native_selection_reason=dict(
            selector="medoid", cluster_size=5, reason="no_dense_train_plateau")))


def test_shared_sampler_compatibility_retained_in_all_rows_and_deep_checks(corpus, result):
    _, _, shared = module._shared(corpus, corpus.revisions[0].task)
    expected = shared["sampler_compatibility"]
    assert {r["recipe_id"] for r in expected} == {"tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"}
    assert {r["compatible"] for r in expected} == {True, False}
    for row in result["rows"]:
        actual = row["sampler_compatibility"]
        assert len(actual) == len(expected)
        for retained, source in zip(actual, expected):
            for key in ("recipe_id", "compatible", "dependency_checked", "empirical_superiority"):
                assert retained[key] == source[key]
            assert retained["dependency_checked"] is False
            assert retained["empirical_superiority"] == "NOT_ASSESSED"
    for deep in result["deep_checks"]:
        assert deep["sampler_compatibility"] == result["rows"][deep["fold"]]["sampler_compatibility"]


def test_sampler_compatibility_reasons_cannot_export_private_geometry(corpus, result, monkeypatch):
    original = AlphaDiagnostics.sampler_compatibility

    def private_reasons(self):
        return [dict(row, reason="PRIVATE hma_length=97 threshold=0.2 /private/alpha.py")
                for row in original(self)]

    monkeypatch.setattr(AlphaDiagnostics, "sampler_compatibility", private_reasons)
    modified = module.monthly_diagnostics(corpus)
    for actual, baseline in zip(modified["rows"], result["rows"]):
        assert actual["sampler_compatibility"] == baseline["sampler_compatibility"]
    for actual, baseline in zip(modified["deep_checks"], result["deep_checks"]):
        assert actual["sampler_compatibility"] == baseline["sampler_compatibility"]
    encoded = json.dumps(modified, allow_nan=False)
    for private in ("PRIVATE", "hma_length", "threshold", "/private/"):
        assert private not in encoded, f"Private sampler reason exported: {private}"


@pytest.mark.parametrize("undefined_index", [0, 1, 2])
def test_legacy_no_variance_zero_is_undefined_in_shared_metrics_and_positions(corpus, undefined_index):
    task, _ = make_task(n=3, schema=corpus.schema)
    candidates = list(task.candidates)
    candidate = candidates[undefined_index]
    legacy = replace(candidate.observation, status=OutcomeStatus.NO_VARIANCE,
                     raw_sharpe=0.0, sample_count=0, sample_std=0.0)
    candidates[undefined_index] = replace(candidate, observation=legacy)
    task = replace(task, candidates=tuple(candidates))
    before = canonical(task)
    geometry, observations, shared = module._shared(corpus, task)
    row = next(r for r in observations if r.evaluation_id == candidate.evaluation_id)
    assert row.metrics.data["raw_is_sharpe"] is None
    assert row.source_ref == digest(legacy)
    assert shared["coverage"]["measured_primary"] == 2
    assert shared["coverage"]["missing_primary"] == 1
    positions = module._position(task, corpus.schema, geometry, observations,
                                 task.candidates[1].evaluation_id)["positions"]
    expected_higher = ((None, 1), (1, None), (1, 0))[undefined_index]
    for role, index in (("anchor", 0), ("selected", 1)):
        assert positions[role]["measured_pool"] == 2
        assert positions[role]["strictly_higher_is"] == expected_higher[index]
        if index == undefined_index:
            assert positions[role]["strictly_higher_is"] is None
            assert positions[role]["equal_is"] is None
        else:
            assert positions[role]["equal_is"] == 1
    if undefined_index != 0:
        anchor_row = next(r for r in observations if r.evaluation_id == task.anchor.evaluation_id)
        assert anchor_row.metrics.data["raw_is_sharpe"] == 0.0
    assert canonical(task) == before
    assert task.candidates[undefined_index].observation.raw_sharpe == 0.0
    assert task.candidates[undefined_index].observation.status == OutcomeStatus.NO_VARIANCE


def test_legacy_no_variance_zero_monthly_export_preserves_retained_observations(corpus, tmp_path):
    candidates = list(corpus.revisions[56].task.candidates)
    legacy = replace(candidates[4].observation, raw_sharpe=0.0)
    assert legacy.status == OutcomeStatus.NO_VARIANCE
    candidates[4] = replace(candidates[4], observation=legacy)
    task = replace(corpus.revisions[56].task, candidates=tuple(candidates))
    revision = revision_for(task, corpus.schema)
    model = saved_model(corpus.schema, corpus.snapshot(56), task)
    decision = saved_decision(task, corpus.schema, model)
    chosen = next(c for c in candidates if c.evaluation_id == decision.actual_evaluation_id)
    saved = deepcopy(corpus.selections[56])
    saved.update(task=wire(task), model=wire(model))
    saved["record"].update(proposal=wire(decision), selected_evaluation_id=chosen.evaluation_id,
        selected_params=wire(chosen.effective_params), final_selection_reason=decision.status)
    modified = patched(corpus, tmp_path, 56, saved=saved, revision=revision)
    before = canonical(modified.selections)
    pins_before = tuple(pin(ref["path"]) for ref in modified.pins)
    report = module.monthly_diagnostics(modified)
    row = report["rows"][56]
    assert row["coverage"]["measured_primary"] == 5
    assert row["coverage"]["missing_primary"] == 1
    assert row["coverage"]["metric_status_counts"]["NO_VARIANCE"] == 1
    assert row["position"]["positions"]["anchor"]["measured_pool"] == 5
    assert row["position"]["positions"]["anchor"]["equal_is"] == 1
    assert row["position"]["positions"]["selected"]["measured_pool"] == 5
    assert report["deep_checks"][-1]["coverage"]["missing_primary"] == 1
    assert modified.revisions[56].task.candidates[4].observation.raw_sharpe == 0.0
    assert modified.revisions[56].task.candidates[4].observation.status == OutcomeStatus.NO_VARIANCE
    assert canonical(modified.selections) == before
    assert tuple(pin(ref["path"]) for ref in modified.pins) == pins_before
