"""In-memory DV05 oracles only: no private corpus, writes, fits or accounts."""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from statistics import mean

import pytest

from tools.meta_model_research import decision_quarterly as q


def observation(n, role, value):
    fold = q.FOLDS[n]
    start, end = ((fold.is_start, fold.is_end) if role == "is"
                  else (fold.oos_start, fold.oos_end))
    end -= timedelta(hours=1)
    return dict(status="VALID" if value is not None else "NO_VARIANCE", raw_sharpe=value,
        activity_count=2, sample_count=90, sample_std=.1 if value is not None else 0.,
        metric_contract_id="synthetic-raw-daily", economics_id="synthetic-reset-account",
        window_start=start.isoformat(), window_end=end.isoformat(), input_frontier=end.isoformat(),
        initial_capital=20000., initial_mark_equity=20000.,
        output_ref=f"synthetic-{n}-{role}-{value}", input_signature=f"market-{n}-{role}",
        verification="original_result")


class MemoryEvidence:
    def __init__(self, documents, public):
        self.documents, self.public, self.pins = documents, public, {}
        self.expected = {str(p): sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
                         for p, d in documents.items()}

    def read(self, path):
        _ = self.expected[str(path)]
        value = self.documents[path]
        raw = json.dumps(value, sort_keys=True).encode()
        if sha256(raw).hexdigest() != self.expected[str(path)]:
            raise ValueError("evidence hash/size mismatch")
        relative = str(path.relative_to(q.ROOT))
        self.pins[relative] = dict(path=relative, bytes=len(raw), sha256=self.expected[str(path)])
        return deepcopy(value)


def corpus(*, undefined=(), level_adjustments=None):
    """Independent raw-level oracle; all policies retain all nineteen slots."""
    documents, public, retained = {}, dict(schema="m51161.public-quarterly-summary.v1",
        scope=dict(quarters=19, IS_days=365, trials_per_fold=128,
                   research_variants_not_original_alpha_equivalence=True),
        cells={}, contrasts={}), dict(schema="m51161.private-study-readback.v1",
                                     calendar=list(q.QUARTERS), cells={}, contrasts={})
    levels = {}
    for group in q.GROUPS:
        for sampler in q.SAMPLERS:
            directory = q.FAST / "studies-v3" / group / sampler
            key = f"{group}/{sampler}"
            retained["cells"][key] = dict(input_issues=[])
            public["cells"][key] = dict(logical_proposals=19 * 128,
                relative_proposal_trials=0 if sampler == q.SAMPLERS[0] else 19 * 118,
                all_sealed_decisions={a: dict(fitted_quarters=6, first_fit="2025Q2",
                    actual_parameter_changes=0) for a in q.ANCHORS})
            pairs = []
            for n, fold in enumerate(q.FOLDS):
                target = directory / "folds" / f"{n:02d}"
                levels[group, sampler, n] = {}
                candidates, outcomes, families = [], [], []
                for anchor in q.ANCHORS:
                    i, o = {(q.SAMPLERS[0], "native"): (2., 1.),
                            (q.SAMPLERS[0], "floor"): (1., 1.5),
                            (q.SAMPLERS[1], "native"): (3., 2.),
                            (q.SAMPLERS[1], "floor"): (1.5, 2.75)}[sampler, anchor]
                    i, o = (level_adjustments or {}).get((sampler, anchor, n), (i, o))
                    if (sampler, anchor, n) in undefined:
                        o = None
                    levels[group, sampler, n][anchor] = i, o
                    is_obs, forward_obs = observation(n, "is", i), observation(n, "forward", o)
                    candidates.append(dict(evaluation_id=anchor, observation=is_obs,
                        objective=99999., effective_params={"private-canary": "not-for-export"}))
                    outcomes.append(dict(evaluation_id=anchor, observation=forward_obs))
                    family = dict(strategy_id="synthetic", parameter_schema_id="synthetic-space",
                        descriptor_schema_id="synthetic-descriptors", instrument_id="synthetic-market",
                        timeframe="1h", window_policy_id="quarterly365", metric_contract_id="synthetic-raw-daily",
                        economics_id="synthetic-reset-account", scorer_contract_id="original-objective",
                        anchor_policy_id=anchor, sampler_policy_id=sampler, account_policy_id="reset-account")
                    families.append(dict(anchor=anchor, selected=anchor, family=family,
                        decision=dict(model_id="fitted-model" if n >= 13 else None,
                                      status="META_MODEL_PROPOSAL" if n >= 13 else "META_SUPPORT_INSUFFICIENT")))
                    for mode in ("off", "active"):
                        pairs.append(dict(fold=n, quarter=fold.fold_id, anchor=anchor, mode=mode,
                            family_id=q.CompatibilityFamily(**family).family_id,
                            model_id=families[-1]["decision"]["model_id"],
                            fit_status=families[-1]["decision"]["status"], is_observation=deepcopy(is_obs),
                            forward_observation=deepcopy(forward_obs), native_is=deepcopy(is_obs),
                            native_forward=deepcopy(forward_obs)))
                documents[target / "sealed-selection.json.gz"] = dict(before_current_forward=True,
                    alternate_disposition="SELECTED", families=families,
                    base_task=dict(anchor_candidate_evaluation_id="native", candidates=candidates,
                        family=deepcopy(families[0]["family"])))
                documents[target / "forward.json.gz"] = dict(outcomes=outcomes)
                documents[target / "search.json.gz"] = dict(source_strategy_identity="synthetic-source",
                    native=dict(selection_metadata=dict(selector="fallback_best_is_temporal" if n == 0
                        else "medoid", reason="no_dense_train_plateau" if n == 0 else None),
                        objective=88888.),
                    sampler=dict(recipe=sampler, attempts=128, requested_trials=128,
                        seed=731 + n, rows=[dict(trial_id=j, state="COMPLETE",
                            relative_dimensions=["private-dimension"] if j >= 10 and sampler == q.SAMPLERS[1]
                            else []) for j in range(128)], states={"COMPLETE": 128},
                        relative_proposal_trials=0 if sampler == q.SAMPLERS[0] else 118,
                        independent_sample_calls={"private-dimension": 128 if sampler == q.SAMPLERS[0] else 10},
                        unique_effective_candidates=128, duplicate_attempts=0, feasible_complete=128,
                        warm_start_attempts=0, optimization_mode="mode_4_is_only_robust",
                        objective_scope="current_is_study_folds", optimization_schedule="per_fold_causal"))
            documents[directory / "pairs.json.gz"] = pairs
        public["contrasts"][group], retained["contrasts"][group] = {}, {}
        for name, (s0, a0, s1, a1) in {
            "sampler_only": (0, "native", 1, "native"), "primary": (0, "native", 1, "floor"),
            "selector_only/" + q.SAMPLERS[0]: (0, "native", 0, "floor"),
            "selector_only/" + q.SAMPLERS[1]: (1, "native", 1, "floor"),
        }.items():
            mask, metrics = [], []
            for n in range(19):
                ia, oa = levels[group, q.SAMPLERS[s0], n][a0]
                ib, ob = levels[group, q.SAMPLERS[s1], n][a1]
                valid = oa is not None and ob is not None
                mask.append(valid)
                if valid:
                    metrics.append(dict(R=(ia - oa) - (ib - ob), Q=ob - oa, IS_effect=ia - ib))
            summary = dict(paired_mask=mask, paired_quarters=sum(mask),
                available_pair_means_descriptive={k: mean(r[k] for r in metrics) if metrics else None
                                                  for k in q.METRICS})
            public["contrasts"][group][name] = deepcopy(summary)
            retained["contrasts"][group][name] = dict(summary=summary)
        documents[q.FAST / "studies-v3" / group / q.SAMPLERS[0] /
            "folds/00/prefix-diagnostics.json.gz"] = dict(
                source_cutoff=(q.FOLDS[0].is_end - timedelta(hours=1)).isoformat(),
                no_forward_outcomes_used=True, valid_raw=2, unique_effective=2,
                private_strategy="not-for-export")
    documents[q.FAST / "public-summary-v4.json"] = deepcopy(public)
    documents[q.FAST / "quarterly-readback-v3.json"] = retained
    for name in ("study-registration.json", "study-v2-registration.json", "continuation-v3-registration.json"):
        documents[q.FAST / name] = dict(source_identity="synthetic-source", source_scope="synthetic-source",
            created_at="2026-10-16", folds=19, train_days=365, attempts_per_fold=128, seed=731)
    return MemoryEvidence(documents, public)


def run(monkeypatch, evidence):
    monkeypatch.setattr(q, "_Evidence", lambda: evidence)
    return q.run_quarterly()


def test_raw_matched_baselines_and_interaction(monkeypatch):
    result = run(monkeypatch, corpus())
    tables = result["groups"][q.GROUPS[0]]["contrasts"]
    expected = {"sampler_only": (0., 1., -1.), "primary": (2.25, 1.75, .5),
        "selector_only/" + q.SAMPLERS[0]: (1.5, .5, 1.),
        "selector_only/" + q.SAMPLERS[1]: (2.25, .75, 1.5), "interaction": (.75, .25, .5)}
    for name, values in expected.items():
        table = tables[name]
        assert table["paired_quarters"] == 19
        assert table["all_quarter_means"] == dict(zip(q.METRICS, values))
        for row in table["quarters"]:
            assert row["metrics"]["R"] == pytest.approx(row["metrics"]["Q"] + row["metrics"]["IS_effect"])
    assert tables["selector_only/" + q.SAMPLERS[1]]["quarters"][0]["raw"]["reference_IS"] == 3.
    assert result["new_model_fits"] == result["new_optimizer_proposals"] == result["new_financial_calls"] == 0


def test_interaction_uses_four_arm_common_calendar_not_mean_subtraction(monkeypatch):
    evidence = corpus(undefined=[(q.SAMPLERS[0], "floor", 0), (q.SAMPLERS[1], "native", 1)],
                      level_adjustments={(q.SAMPLERS[1], "floor", 0): (1.5, 20.)})
    tables = run(monkeypatch, evidence)["groups"][q.GROUPS[0]]["contrasts"]
    assert tables["selector_only/" + q.SAMPLERS[0]]["paired_quarters"] == 18
    assert tables["selector_only/" + q.SAMPLERS[1]]["paired_quarters"] == 18
    interaction = tables["interaction"]
    assert interaction["paired_quarters"] == 17
    assert interaction["paired_mask"][:3] == [False, False, True]
    assert interaction["all_quarter_means"] is None
    assert interaction["quarters"][0]["metrics"] == dict.fromkeys(q.METRICS)
    assert interaction["available_pair_means_descriptive"]["Q"] == .25
    unequal_mask_difference = (tables["selector_only/" + q.SAMPLERS[1]]["available_pair_means_descriptive"]["Q"]
                              - tables["selector_only/" + q.SAMPLERS[0]]["available_pair_means_descriptive"]["Q"])
    assert unequal_mask_difference != pytest.approx(.25)


def test_undefined_same_action_is_never_imputed_zero(monkeypatch):
    evidence = corpus(undefined=[(q.SAMPLERS[0], "native", n) for n in range(19)])
    tables = run(monkeypatch, evidence)["groups"][q.GROUPS[0]]["contrasts"]
    assert tables["sampler_only"]["paired_quarters"] == 0
    assert tables["sampler_only"]["available_pair_means_descriptive"] == dict.fromkeys(q.METRICS)
    assert any("NO_VARIANCE" in reason for reason in tables["sampler_only"]["quarters"][0]["reasons"])


def test_counts_fallback_sampling_and_prefix_proof_are_separate(monkeypatch):
    row = run(monkeypatch, corpus())["groups"][q.GROUPS[0]]
    legacy, group = (row["support"][s] for s in q.SAMPLERS)
    assert legacy["totals"]["attempts"] == 2432
    assert legacy["native_fallback_quarters"] == 1
    assert legacy["meta_decisions_all_slots"]["native"]["fitted_quarters"] == 6
    assert legacy["meta_decisions_all_slots"]["native"]["fallback_quarters"] == 13
    assert group["totals"]["relative_proposal_trials"] == 2242
    assert group["totals"]["independent_parameter_calls"] == 190
    assert group["actual_sampler_fallback_count"] is None
    prefix = row["prefix_advice"]
    assert prefix["prefix_data_eligible"] is True
    assert prefix["legacy_first_search"].startswith("UNAVAILABLE")
    assert prefix["group_first_search"].startswith("NOT_PROVEN")
    assert prefix["later_searches"].startswith("NOT_PROVEN")
    assert len(prefix["study_availability"]) == 38
    assert prefix["validated_pre_search_router"] is False
    assert row["advisory"]["disposition"] == "NO_CLEAR_WINNER"


def test_json_allowlist_does_not_export_parameters_or_objective_scores(monkeypatch):
    result = run(monkeypatch, corpus())
    payload = json.dumps(result, allow_nan=False)
    for secret in ("private-canary", "not-for-export", "private-dimension", "private_strategy", "99999", "88888"):
        assert secret not in payload
    assert result["input_pins"]
    assert all(set(p) == {"path", "bytes", "sha256"} for p in result["input_pins"])


@pytest.mark.parametrize("value", [None, 0., 2.])
def test_same_action_raw_metric_support_is_required_even_for_zero_contrasts(value):
    arms = [dict(identity={"same": True}, observations={
        "is": q.observation_from_payload(observation(n, "is", value)),
        "forward": q.observation_from_payload(observation(n, "forward", value))}) for n in range(19)]
    table = q._contrast(q.GROUPS[0], "same-action", arms, arms)
    assert table["paired_quarters"] == (0 if value is None else 19)
    assert table["available_pair_means_descriptive"] == dict.fromkeys(q.METRICS, None if value is None else 0.)


def test_interaction_rejects_cross_sampler_incompatibility_even_with_valid_selectors():
    valid = q._summary([dict(quarter=quarter, status="PAIRED_VALID",
        metrics=dict(R=1., Q=.5, IS_effect=.5)) for quarter in q.QUARTERS])
    incompatible = q._summary([dict(quarter=quarter, status="INCOMPATIBLE",
        metrics=dict.fromkeys(q.METRICS)) for quarter in q.QUARTERS])
    result = q._interaction(valid, valid, incompatible)
    assert result["paired_quarters"] == 0
    assert result["available_pair_means_descriptive"] == dict.fromkeys(q.METRICS)


def test_native_and_floor_families_can_have_the_same_anchor_candidate(monkeypatch):
    evidence = corpus()
    directory = q.FAST / "studies-v3" / q.GROUPS[0] / q.SAMPLERS[0]
    target = directory / "folds/00"
    sealed = evidence.documents[target / "sealed-selection.json.gz"]
    sealed["families"][1]["anchor"] = sealed["families"][1]["selected"] = "native"
    for pair in evidence.documents[directory / "pairs.json.gz"]:
        if pair["fold"] == 0 and pair["anchor"] == "floor":
            for key in ("is_observation", "native_is"):
                pair[key] = deepcopy(sealed["base_task"]["candidates"][0]["observation"])
            for key in ("forward_observation", "native_forward"):
                pair[key] = deepcopy(evidence.documents[target / "forward.json.gz"]["outcomes"][0]["observation"])
    evidence = MemoryEvidence(evidence.documents, evidence.public)
    arms, support = q._cell(evidence, q.GROUPS[0], q.SAMPLERS[0])
    assert arms[0, "native"]["observations"] == arms[0, "floor"]["observations"]
    assert support["totals"]["attempts"] == 2432


@pytest.mark.parametrize("field", ["source_strategy_identity", "optimization_mode", "seed", "scorer_contract_id"])
def test_unmatched_source_budget_objective_or_seed_rejected(monkeypatch, field):
    evidence = corpus()
    directory = q.FAST / "studies-v3" / q.GROUPS[0] / q.SAMPLERS[1] / "folds/00"
    if field == "scorer_contract_id":
        evidence.documents[directory / "sealed-selection.json.gz"]["base_task"]["family"][field] = "foreign"
    else:
        search = evidence.documents[directory / "search.json.gz"]
        (search if field == "source_strategy_identity" else search["sampler"])[field] = "foreign"
    # Treat the modified fixture as newly sealed, so identity checks, not hashes, must reject it.
    evidence = MemoryEvidence(evidence.documents, evidence.public)
    with pytest.raises(ValueError, match="unmatched|objective or schedule"):
        run(monkeypatch, evidence)


@pytest.mark.parametrize("defect", ["duplicate", "missing", "pair_metric", "sampling", "public_mean", "late_prefix"])
def test_negative_custody_and_availability_controls(monkeypatch, defect):
    evidence = corpus()
    directory = q.FAST / "studies-v3" / q.GROUPS[0] / q.SAMPLERS[0]
    pairs = evidence.documents[directory / "pairs.json.gz"]
    if defect == "duplicate":
        pairs.append(deepcopy(pairs[0]))
    elif defect == "missing":
        pairs.pop()
    elif defect == "pair_metric":
        pairs[0]["is_observation"]["raw_sharpe"] = 999.
    elif defect == "sampling":
        evidence.documents[directory / "folds/00/search.json.gz"]["sampler"]["relative_proposal_trials"] = 2
    elif defect == "public_mean":
        evidence.public["contrasts"][q.GROUPS[0]]["sampler_only"]["available_pair_means_descriptive"]["R"] = 99.
        evidence.documents[q.FAST / "public-summary-v4.json"] = deepcopy(evidence.public)
    else:
        evidence.documents[directory / "folds/00/prefix-diagnostics.json.gz"]["source_cutoff"] = "2026-10-01T00:00:00+00:00"
    evidence = MemoryEvidence(evidence.documents, evidence.public)
    if defect == "late_prefix":
        row = run(monkeypatch, evidence)["groups"][q.GROUPS[0]]["prefix_advice"]
        assert row["prefix_data_eligible"] is False
        assert row["validated_pre_search_router"] is False
    else:
        with pytest.raises(ValueError):
            run(monkeypatch, evidence)


def test_changed_consumed_file_is_not_trusted(monkeypatch):
    evidence = corpus()
    path = q.FAST / "studies-v3" / q.GROUPS[0] / q.SAMPLERS[0] / "pairs.json.gz"
    evidence.documents[path][0]["quarter"] = "mutated-after-seal"
    with pytest.raises(ValueError, match="hash/size"):
        run(monkeypatch, evidence)


def test_real_custody_reader_requires_registered_members_and_records_verified_pins(monkeypatch):
    calls = []
    path = q.FAST / "synthetic.json"
    ref = dict(path=str(path), bytes=12, sha256="a" * 64)
    def read_verified(target, **kwargs):
        calls.append((target, kwargs))
        if target == q.PUBLIC:
            return {"synthetic": True}
        if target == q.MANIFEST:
            return [ref]
        assert kwargs["expected_sha256"] == ref["sha256"]
        assert kwargs["expected_bytes"] == ref["bytes"]
        return {"qualified": True}
    monkeypatch.setattr(q, "read_verified", read_verified)
    evidence = q._Evidence()
    assert evidence.read(path) == {"qualified": True}
    assert len(evidence.pins) == 3
    assert calls[0][1]["expected_sha256"] == q.PUBLIC_SHA256
    assert calls[1][1]["expected_sha256"] == q.MANIFEST_SHA256
    with pytest.raises(ValueError, match="custody member"):
        evidence.read(q.FAST / "foreign.json")
