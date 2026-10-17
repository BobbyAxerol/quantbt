"""Independent raw-level synthetic oracles; never read the real quarterly corpus."""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from tools.meta_model_research import decision_quarterly as q
from tools.meta_model_research import forward_factorial as f


LEGACY, GROUP = q.SAMPLERS
GROUPS = q.GROUPS
LEVELS = {(LEGACY, "native"): (5., 2.), (LEGACY, "floor"): (3., 1.),
          (GROUP, "native"): (7., 3.), (GROUP, "floor"): (4., 1.5)}
DELTAS = {(LEGACY, "native"): (-1., .25), (LEGACY, "floor"): (-.5, .5),
          (GROUP, "native"): (-2., .75), (GROUP, "floor"): (-1., 2.)}


def observation(n, role, value):
    fold = q.FOLDS[n]
    start, end = (fold.is_start, fold.is_end) if role == "is" else (fold.oos_start, fold.oos_end)
    end -= timedelta(hours=1)
    return dict(status="VALID" if value is not None else "NO_VARIANCE", raw_sharpe=value,
        activity_count=2 if value is not None else 0, sample_count=90,
        sample_std=.1 if value is not None else 0., metric_contract_id="synthetic-daily-raw",
        economics_id="synthetic-reset", window_start=start.isoformat(), window_end=end.isoformat(),
        input_frontier=end.isoformat(), initial_capital=20000., initial_mark_equity=20000.,
        output_ref=f"private-output-{n}-{role}-{value}", input_signature=f"market-{n}-{role}",
        verification="original_result")


class MemoryEvidence:
    def __init__(self, documents, public, groups):
        self.documents, self.public, self.groups, self.pins = documents, public, groups, {}
        self.expected = {path: self.signature(value) for path, value in documents.items()}

    @staticmethod
    def signature(value):
        raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
        return len(raw), sha256(raw).hexdigest()

    def read(self, path):
        value = self.documents[path]
        size, signature = self.signature(value)
        if (size, signature) != self.expected[path]:
            raise ValueError("evidence hash/size mismatch")
        relative = str(path.relative_to(q.ROOT))
        self.pins[relative] = dict(path=relative, bytes=size, sha256=signature)
        return deepcopy(value)


def corpus(*, groups=(GROUPS[0],), kinds=None, undefined=(), levels=None):
    documents = {}
    public = dict(schema="m51161.public-quarterly-summary.v1", cells={},
        scope=dict(quarters=19, IS_days=365, trials_per_fold=128,
                   research_variants_not_original_alpha_equivalence=True))
    retained = dict(schema="m51161.private-study-readback.v1", calendar=list(q.QUARTERS), cells={})
    for group in groups:
        for sampler in q.SAMPLERS:
            directory = q.FAST / "studies-v3" / group / sampler
            pairs, counts = [], {a: dict(fitted_quarters=0, first_fit=None, actual_parameter_changes=0)
                                 for a in q.ANCHORS}
            for n, fold in enumerate(q.FOLDS):
                candidates, outcomes, families = [], [], []
                for anchor in q.ANCHORS:
                    kind = (kinds or {}).get((sampler, anchor, n), "learned" if n >= 13 else "cold")
                    fitted, learned = kind != "cold", kind.startswith("learned")
                    anchor_id, alternative = f"private-{anchor}", f"private-{anchor}-proposal"
                    selected = alternative if learned and kind != "learned_unchanged" else anchor_id
                    family = dict(strategy_id=group, parameter_schema_id="synthetic-space",
                        descriptor_schema_id="synthetic-descriptors", instrument_id="synthetic-market",
                        timeframe="1h", window_policy_id="quarterly365", metric_contract_id="synthetic-daily-raw",
                        economics_id="synthetic-reset", scorer_contract_id="original-objective",
                        anchor_policy_id=anchor, sampler_policy_id=sampler, account_policy_id="reset-account")
                    family_id = q.CompatibilityFamily(**family).family_id
                    snapshot = dict(snapshot_id=f"snapshot-{anchor}-{n}", origin_count=max(0, n - 1))
                    model = None if not fitted else dict(family_id=family_id, origin_count=n - 1,
                        training_snapshot_id=snapshot["snapshot_id"], private_coefficient="never-export")
                    model_id = None if model is None else q.digest(dict(schema="qms-ridge-model-v1", model=model))
                    status = "META_MODEL_PROPOSAL" if learned else (
                        "META_OOD_NATIVE_FALLBACK" if fitted else "META_SUPPORT_INSUFFICIENT")
                    families.append(dict(anchor=anchor_id, selected=selected, family=family,
                        task_id=f"task-{anchor}-{n}", snapshot=snapshot,
                        fit=dict(model=model, origin_count=max(0, n - 1)),
                        decision=dict(model_id=model_id, training_snapshot_id=snapshot["snapshot_id"],
                            status=status, task_id=f"task-{anchor}-{n}", mode="active",
                            anchor_evaluation_id=anchor_id, actual_evaluation_id=selected)))
                    changed = selected != anchor_id and kind != "learned_alias"
                    count = counts[anchor]
                    count["fitted_quarters"] += int(fitted)
                    count["actual_parameter_changes"] += int(changed)
                    if fitted and count["first_fit"] is None:
                        count["first_fit"] = fold.fold_id
                    raw = {}
                    for mode, eid in (("off", anchor_id), ("active", selected)):
                        if eid == anchor_id and mode == "active":
                            raw[mode] = raw["off"]
                            continue
                        i, o = LEVELS[sampler, anchor]
                        if mode == "active" and kind != "learned_alias":
                            di, do = DELTAS[sampler, anchor]
                            i, o = i + di, o + do
                        i, o = (levels or {}).get((sampler, anchor, mode, n), (i, o))
                        if (sampler, anchor, mode, n) in undefined:
                            o = None
                        is_obs, forward = observation(n, "is", i), observation(n, "forward", o)
                        raw[mode] = is_obs, forward
                        candidates.append(dict(evaluation_id=eid, observation=is_obs, objective=999999.,
                            effective_params={"private-canary": "never-export", "parameter": anchor + str(changed and mode == "active")}))
                        outcomes.append(dict(evaluation_id=eid, observation=forward))
                    for mode in f.MODES:
                        pairs.append(dict(fold=n, quarter=fold.fold_id, anchor=anchor, mode=mode,
                            family_id=family_id, model_id=model_id, fit_status=status,
                            matured_origins=snapshot["origin_count"], changed=mode == "active" and selected != anchor_id,
                            is_observation=deepcopy(raw[mode][0]), forward_observation=deepcopy(raw[mode][1]),
                            native_is=deepcopy(raw["off"][0]), native_forward=deepcopy(raw["off"][1])))
                target = directory / "folds" / f"{n:02d}"
                documents[target / "sealed-selection.json.gz"] = dict(before_current_forward=True,
                    alternate_disposition="SELECTED", families=families,
                    base_task=dict(family=deepcopy(families[0]["family"]), candidates=candidates,
                        anchor_candidate_evaluation_id="private-native"))
                documents[target / "forward.json.gz"] = dict(outcomes=outcomes)
                documents[target / "search.json.gz"] = dict(source_strategy_identity=f"source-{group}",
                    native=dict(selection_metadata=dict(selector="fallback_best_is_temporal" if n == 0 else "medoid",
                        reason="insufficient_cluster_points" if n == 0 else None)),
                    sampler=dict(recipe=sampler, attempts=128, requested_trials=128, seed=731 + n,
                        rows=[dict(trial_id=j, state="COMPLETE", relative_dimensions=[]) for j in range(128)],
                        states={"COMPLETE": 128}, relative_proposal_trials=0,
                        independent_sample_calls={"private-parameter": 128}, unique_effective_candidates=128,
                        duplicate_attempts=0, feasible_complete=128, warm_start_attempts=0,
                        optimization_mode="mode_4_is_only_robust", objective_scope="current_is_study_folds",
                        optimization_schedule="per_fold_causal"))
            documents[directory / "pairs.json.gz"] = pairs
            key = f"{group}/{sampler}"
            public["cells"][key] = dict(logical_proposals=2432, relative_proposal_trials=0, all_sealed_decisions=counts)
            retained["cells"][key] = dict(input_issues=[])
    documents[q.FAST / "public-summary-v4.json"] = deepcopy(public)
    documents[q.FAST / "quarterly-readback-v3.json"] = retained
    for name in ("study-registration.json", "study-v2-registration.json", "continuation-v3-registration.json"):
        documents[q.FAST / name] = dict(source_identity="source-scope", source_scope="source-scope",
            folds=19, train_days=365, attempts_per_fold=128, seed=731)
    return MemoryEvidence(documents, public, groups)


def run(monkeypatch, evidence):
    monkeypatch.setattr(f, "_Evidence", lambda: evidence)
    monkeypatch.setattr(q, "GROUPS", evidence.groups)
    return f.run_factorial()


def group_result(monkeypatch, evidence):
    return run(monkeypatch, evidence)["groups"][GROUPS[0]]


def cohort(table, name="all_calendar"):
    return table["cohorts"][name]


def mutate(evidence, path, change):
    change(evidence.documents[path])
    evidence.expected[path] = evidence.signature(evidence.documents[path])


def cell_path(sampler=LEGACY, name="sealed-selection.json.gz", n=13):
    return q.FAST / "studies-v3" / GROUPS[0] / sampler / "folds" / f"{n:02d}" / name


def test_complete_factorial_own_anchors_and_raw_io(monkeypatch, tmp_path):
    result = run(monkeypatch, corpus(groups=GROUPS))
    assert set(result["groups"]) == set(GROUPS)
    assert result["calendar"] == list(q.QUARTERS)
    for group in result["groups"].values():
        assert len(group["arms"]) == 8
        for (sampler, anchor), (di, do) in DELTAS.items():
            table = group["own_anchor_meta"][f"{sampler}/{anchor}"]
            learned = cohort(table, "actually_learned")
            expected = dict(R=-di + do, Q=do, IS_effect=-di)
            assert learned["available_pair_means_descriptive"] == expected
            assert learned["paired_quarter_ids"] == list(q.QUARTERS[13:])
            assert cohort(table)["available_pair_means_descriptive"] == pytest.approx(
                {k: v * 6 / 19 for k, v in expected.items()})
            assert table["support"]["minimum_met"] is True
        rows = group["arms"][f"{LEGACY}/floor/active"]["quarters"]
        assert rows[13]["raw"]["is"]["raw_sharpe"] == 2.5
        assert rows[13]["raw"]["forward"]["raw_sharpe"] == 1.5
        assert rows[13]["origin"] == rows[13]["raw"]["is"]["input_frontier"]
        assert rows[0]["fallback"] and not rows[0]["fitted"]
        assert rows[13]["actually_learned"] and rows[13]["changed"]
    assert result["new_model_fits"] == result["new_optimizer_proposals"] == result["new_financial_calls"] == 0
    assert tmp_path.is_dir()


def test_sampler_selector_and_meta_differences_in_differences(monkeypatch):
    group = group_result(monkeypatch, corpus())
    expected = {"sampler/native": (1.5, .5, 1.), "sampler/floor": (2., 1.5, .5),
        f"selector/{LEGACY}": (-.25, .25, -.5), f"selector/{GROUP}": (.25, 1.25, -1.),
        "sampler_selector": (.5, 1., -.5)}
    for name, values in expected.items():
        table = cohort(group["meta_interactions"][name], "actually_learned")
        assert table["available_pair_means_descriptive"] == dict(zip(q.METRICS, values))
        assert table["paired_quarters"] == 6
        for row in table["quarters"][13:]:
            assert row["metrics"]["R"] == row["metrics"]["Q"] + row["metrics"]["IS_effect"]
    assert cohort(group["contrasts"]["off"]["sampler_selector"])["all_quarter_means"] == dict(R=.5, Q=-.5, IS_effect=1.)


def test_exact_common_masks_not_subtracted_available_means(monkeypatch):
    evidence = corpus(undefined=[(LEGACY, "floor", "active", 13), (GROUP, "native", "off", 14)],
        levels={(GROUP, "floor", "active", 14): (3., 100.)})
    group = group_result(monkeypatch, evidence)
    triple = cohort(group["meta_interactions"]["sampler_selector"])
    assert triple["paired_mask"] == [True] * 13 + [False, False] + [True] * 4
    assert len(triple["quarters"]) == 19 and triple["all_quarter_means"] is None
    assert triple["quarters"][13]["metrics"] == dict.fromkeys(q.METRICS)
    learned = cohort(group["meta_interactions"]["sampler_selector"], "actually_learned")
    assert learned["available_pair_means_descriptive"]["Q"] == 1.
    assert learned["paired_quarters"] == 4
    assert group["meta_interactions"]["sampler_selector"]["support"]["minimum_met"] is False
    for name, matched in group["matched_off_active"].items():
        assert cohort(matched["off"])["paired_mask"] == cohort(matched["active"])["paired_mask"]
        assert cohort(matched["off"])["paired_mask"] == cohort(group["meta_interactions"][name])["paired_mask"]
    unequal = (cohort(group["contrasts"]["active"]["sampler_selector"], "actually_learned")["available_pair_means_descriptive"]["Q"]
               - cohort(group["contrasts"]["off"]["sampler_selector"], "actually_learned")["available_pair_means_descriptive"]["Q"])
    assert unequal != pytest.approx(1.)


def test_model_ready_is_not_actually_learned_or_changed(monkeypatch):
    evidence = corpus(kinds={(LEGACY, "native", 13): "fitted_fallback",
        (LEGACY, "native", 14): "learned_unchanged", (LEGACY, "native", 15): "learned_alias"})
    group = group_result(monkeypatch, evidence)
    table = group["own_anchor_meta"][f"{LEGACY}/native"]
    assert cohort(table, "fitted")["eligible_quarters"] == 6
    assert cohort(table, "actually_learned")["eligible_quarters"] == 5
    assert cohort(table, "fallback_involved")["eligible_quarters"] == 14
    assert cohort(table, "changed")["eligible_quarters"] == 3
    assert table["support"]["minimum_met"] is False
    rows = group["arms"][f"{LEGACY}/native/active"]["quarters"]
    assert rows[13]["fitted"] and rows[13]["fallback"] and not rows[13]["actually_learned"]
    assert rows[14]["actually_learned"] and not rows[14]["changed"]
    assert rows[15]["selected_ref"] != rows[15]["anchor_ref"] and not rows[15]["changed"]
    assert cohort(table)["quarters"][14]["metrics"] == dict.fromkeys(q.METRICS, 0.)


def test_undefined_same_action_flat_is_not_a_zero_effect(monkeypatch):
    group = group_result(monkeypatch, corpus(undefined=[(LEGACY, "native", "off", 0)]))
    table = cohort(group["own_anchor_meta"][f"{LEGACY}/native"])
    assert table["paired_mask"][:2] == [False, True]
    assert table["quarters"][0]["metrics"] == dict.fromkeys(q.METRICS)
    assert any("NO_VARIANCE" in r for r in table["quarters"][0]["reasons"])
    assert table["quarters"][1]["metrics"] == dict.fromkeys(q.METRICS, 0.)
    assert table["all_quarter_means"] is None


def test_entirely_undefined_support_has_null_not_zero_means(monkeypatch):
    group = group_result(monkeypatch, corpus(undefined=[(LEGACY, "native", "off", n) for n in range(19)]))
    table = group["own_anchor_meta"][f"{LEGACY}/native"]
    assert cohort(table)["available_pair_means_descriptive"] == dict.fromkeys(q.METRICS)
    assert cohort(table)["paired_quarters"] == 0
    assert cohort(table, "actually_learned")["eligible_quarters"] == 6
    assert table["support"]["minimum_met"] is False
    assert group["arms"][f"{LEGACY}/native/off"]["counts"]["valid_forward"] == 0


def test_market_input_mismatch_stays_in_calendar_with_null_metrics(monkeypatch):
    evidence = corpus()
    mutate(evidence, cell_path(name="forward.json.gz"), lambda d: next(
        o for o in d["outcomes"] if o["evaluation_id"] == "private-native-proposal"
    )["observation"].update(input_signature="different-market"))
    path = cell_path().parents[2] / "pairs.json.gz"
    def change(rows):
        next(r for r in rows if r["fold"] == 13 and r["anchor"] == "native" and r["mode"] == "active")["forward_observation"]["input_signature"] = "different-market"
    mutate(evidence, path, change)
    table = cohort(group_result(monkeypatch, evidence)["own_anchor_meta"][f"{LEGACY}/native"])
    assert len(table["quarters"]) == 19
    assert table["quarters"][13]["status"] == "INCOMPATIBLE"
    assert table["quarters"][13]["metrics"] == dict.fromkeys(q.METRICS)
    assert "forward:MARKET_INPUT_MISMATCH" in table["quarters"][13]["reasons"]


@pytest.mark.parametrize("field,value", [("quarter", "2021Q4"), ("family_id", "foreign-family"),
    ("model_id", "foreign-model"), ("matured_origins", 999), ("changed", False)])
def test_mismatched_pair_rejected(monkeypatch, field, value):
    evidence = corpus()
    path = cell_path().parents[2] / "pairs.json.gz"
    def change(rows):
        next(r for r in rows if r["fold"] == 13 and r["anchor"] == "native" and r["mode"] == "active")[field] = value
    mutate(evidence, path, change)
    with pytest.raises(ValueError):
        run(monkeypatch, evidence)


@pytest.mark.parametrize("field,value", [("source_strategy_identity", "foreign-source")])
def test_cross_sampler_source_identity_rejected(monkeypatch, field, value):
    evidence = corpus()
    mutate(evidence, cell_path(GROUP, "search.json.gz"), lambda d: d.update({field: value}))
    with pytest.raises(ValueError, match="unmatched source"):
        run(monkeypatch, evidence)


def test_active_observation_requires_original_verification(monkeypatch):
    evidence = corpus()
    eid = "private-native-proposal"
    mutate(evidence, cell_path(), lambda d: next(c for c in d["base_task"]["candidates"]
        if c["evaluation_id"] == eid)["observation"].update(verification="unverified"))
    path = cell_path().parents[2] / "pairs.json.gz"
    def change(rows):
        next(r for r in rows if r["fold"] == 13 and r["anchor"] == "native" and r["mode"] == "active")["is_observation"]["verification"] = "unverified"
    mutate(evidence, path, change)
    with pytest.raises(ValueError, match="authoritative"):
        run(monkeypatch, evidence)


def test_mismatched_active_raw_witness_rejected(monkeypatch):
    evidence = corpus()
    path = cell_path().parents[2] / "pairs.json.gz"
    def change(rows):
        next(r for r in rows if r["fold"] == 13 and r["anchor"] == "floor" and r["mode"] == "active")["native_is"] = deepcopy(rows[0]["native_is"])
    mutate(evidence, path, change)
    with pytest.raises(ValueError, match="raw pair"):
        run(monkeypatch, evidence)


def test_consumed_hash_mutation_rejected(monkeypatch):
    evidence = corpus()
    evidence.documents[cell_path()]["before_current_forward"] = False
    with pytest.raises(ValueError, match="hash/size"):
        run(monkeypatch, evidence)


@pytest.mark.parametrize("kind", ["readiness", "history", "activation", "physical_family"])
def test_model_history_activation_and_family_crossbinds(monkeypatch, kind):
    evidence = corpus()
    def change(d):
        family = d["families"][0]
        if kind == "readiness":
            family["fit"]["model"] = None
        elif kind == "history":
            family["snapshot"]["origin_count"] = 11
        elif kind == "activation":
            family["decision"]["actual_evaluation_id"] = "private-floor"
        else:
            family["family"]["economics_id"] = "foreign-economics"
    mutate(evidence, cell_path(), change)
    with pytest.raises(ValueError):
        run(monkeypatch, evidence)


def test_json_sanitization_source_pins_and_no_side_effects(monkeypatch):
    evidence = corpus()
    before = deepcopy(evidence.documents)
    result = run(monkeypatch, evidence)
    serialized = json.dumps(result, allow_nan=False)
    for private in ("private-canary", "never-export", "private-output", "private-native", "private_coefficient"):
        assert private not in serialized
    assert evidence.documents == before
    assert result["input_pins"] == [evidence.pins[k] for k in sorted(evidence.pins)]
    assert len(result["source_identity_refs"]) == 2
    assert len(result["input_pins"]) == 5 + 2 * (1 + 19 * 3)
    assert f._Evidence is not q._Evidence  # This test's reader is a synthetic replacement.


def test_real_custody_owner_used_without_opening_corpus(monkeypatch):
    calls = []
    path = q.FAST / "synthetic-member.json"
    ref = dict(path=str(path), bytes=12, sha256="a" * 64)
    def verified(target, **kwargs):
        calls.append((target, kwargs))
        if target == q.PUBLIC:
            return {"synthetic": True}
        if target == q.MANIFEST:
            return [ref]
        assert kwargs["expected_sha256"] == ref["sha256"]
        assert kwargs["expected_bytes"] == ref["bytes"]
        return {"qualified": True}
    assert f._Evidence is q._Evidence
    monkeypatch.setattr(q, "read_verified", verified)
    evidence = f._Evidence()
    assert evidence.read(path) == {"qualified": True}
    assert calls[0][1]["expected_sha256"] == q.PUBLIC_SHA256
    assert calls[1][1]["expected_sha256"] == q.MANIFEST_SHA256
    assert len(evidence.pins) == 3
    with pytest.raises(ValueError, match="custody member"):
        evidence.read(q.FAST / "unregistered.json")
