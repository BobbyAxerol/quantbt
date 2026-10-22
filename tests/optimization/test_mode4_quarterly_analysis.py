"""Known-scalar quarterly inference fixtures; never financial/optimizer runs."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from arch.bootstrap import MovingBlockBootstrap

from quantbt.optimization.meta_selection.observer import canonical_metric_contract
from quantbt.optimization.meta_selection.records import MetricObservation, OutcomeStatus
from tools.mode4_quarterly.analysis import (
    BOOTSTRAP_DRAWS, BOOTSTRAP_SEED, COORDINATES, FAMILY_CONFIDENCE,
    MARGINAL_CONFIDENCE, PRIMARY_ALPHAS, ContrastScope, infer_primary_family,
    measure_quarter, summarize_quarters,
)
from tools.mode4_quarterly.contracts import quarterly_calendar


FOLDS = quarterly_calendar()
HOUR = pd.Timedelta(hours=1)
METRIC_ID = canonical_metric_contract().metric_id
NAMES = ("reference_is", "reference_forward", "policy_is", "policy_forward")


def scope(alpha="A-SC", *, kind="legacy_reference", role="primary_recipe"):
    return ContrastScope("registered-quarterly-recipe", kind,
        f"{alpha}:legacy-native" if kind == "legacy_reference" else f"{alpha}:recipe-native",
        f"{alpha}:recipe-policy", role)


def observation(fold, role, value):
    start, end = ((fold.is_start, fold.is_end) if role == "is"
                  else (fold.oos_start, fold.oos_end))
    return MetricObservation(OutcomeStatus.VALID, float(value), 20,
        (end - start).days - 1, .1, METRIC_ID, "synthetic-common-account-v1",
        pd.Timestamp(start), pd.Timestamp(end) - HOUR, pd.Timestamp(end) - HOUR,
        20_000., 20_000., f"synthetic-qualified-{fold.fold_id}-{role}-{value}",
        f"synthetic-market-{fold.fold_id}-{role}", "reviewed_import")


def observations(fold, values=(4., 1., 3.5, 1.2)):
    return {name: observation(fold, "is" if name.endswith("_is") else "forward", value)
            for name, value in zip(NAMES, values, strict=True)}


def quarter(alpha="A-SC", index=0, *, values=(4., 1., 3.5, 1.2),
            comparison=None, **kwargs):
    fold = FOLDS[index]
    return measure_quarter(alpha, fold.fold_id, observations(fold, values),
                           scope=comparison or scope(alpha), **kwargs)


def family(*, r=None, q=None):
    result, matrix = {}, np.empty((19, 8))
    for column, alpha in enumerate(PRIMARY_ALPHAS):
        rows = []
        for i in range(19):
            effect = .25 + .04 * column
            forward = .2 + .03 * column + .005 * i
            if q is not None:
                forward = q
            if r is not None:
                effect = r - forward
            rows.append(quarter(alpha, i, values=(4., 1., 4. - effect, 1. + forward)))
            matrix[i, column * 2:column * 2 + 2] = effect + forward, forward
        result[alpha] = rows
    return result, matrix


def forbid_bootstrap(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("an unsupported/missing family must not be bootstrapped")
    monkeypatch.setattr("arch.bootstrap.MovingBlockBootstrap", forbidden)


def test_exact_quarter_decomposition_labels_and_preserved_original_observations():
    fold = FOLDS[0]
    source = observations(fold, (4., 1., 3., 1.5))
    row = measure_quarter("A-SC", fold.fold_id, source, scope=scope())
    assert row.status == "PAIRED_VALID"
    assert dict(row.metrics) == dict(D_reference=3., D_policy=1.5,
        IS_effect=1., R=1.5, Q=.5, identity_residual=0.)
    assert dict(row.contrast_labels) == {"R": "R_ref", "Q": "Q_ref"}
    assert row.flags == ("LOWER_IS_CONTRIBUTION",)
    assert row.fold_identity == fold.identity
    assert all(row.observations[name] is source[name] for name in NAMES)
    own = measure_quarter("A-SC", fold.fold_id, source,
                          scope=scope(kind="own_anchor", role="descriptive"))
    assert dict(own.contrast_labels) == {"R": "R_meta", "Q": "Q_meta"}
    assert own.metrics == row.metrics and own.scope != row.scope
    with pytest.raises(TypeError):
        row.observations["reference_is"] = None
    with pytest.raises(TypeError):
        row.metrics["Q"] = 123.


@pytest.mark.parametrize(("values", "flag"), [
    ((4., 1., 3., 1.), "LOWER_IS_ONLY"),
    ((4., 1., 2., .5), "LOWER_IS_DESPITE_WORSE_FORWARD"),
])
def test_positive_r_from_lower_is_is_not_a_forward_win(values, flag):
    row = quarter(values=values)
    assert row.metrics["R"] > 0 and row.metrics["Q"] <= 0
    assert flag in row.flags and "LOWER_IS_CONTRIBUTION" in row.flags
    assert row.metrics["R"] == row.metrics["IS_effect"] + row.metrics["Q"]


@pytest.mark.parametrize("status", [s for s in OutcomeStatus if s != OutcomeStatus.VALID])
def test_nonvalid_qualified_dispositions_are_retained_not_zeroed(status):
    source = observations(FOLDS[0])
    failed = replace(source["policy_forward"], status=status, raw_sharpe=None,
                     sample_std=None, sample_count=0)
    source["policy_forward"] = failed
    row = measure_quarter("A-SC", FOLDS[0].fold_id, source, scope=scope())
    assert row.status == "UNSUPPORTED"
    assert f"policy_forward:{status.value}" in row.reasons
    assert row.observations["policy_forward"] is failed
    assert all(value is None for value in row.metrics.values())
    summary = summarize_quarters("A-SC", [row])
    assert len(summary["rows"]) == 19 and summary["rows"][0] is row
    assert summary["slot_status"] == ("UNSUPPORTED",) + ("MISSING",) * 18
    assert summary["paired_quarters"] == 0


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("metric_contract_id", "other-metric", "INCOMPATIBLE_METRIC_CONTRACT_ID"),
    ("economics_id", "other-economics", "INCOMPATIBLE_ECONOMICS_ID"),
    ("initial_capital", 1000., "INCOMPATIBLE_INITIAL_CAPITAL"),
    ("input_signature", "different-market", "is:MARKET_INPUT_MISMATCH"),
    ("window_start", pd.Timestamp(FOLDS[0].is_start) + HOUR, "reference_is:WINDOW_OR_FRONTIER_MISMATCH"),
    ("window_end", pd.Timestamp(FOLDS[0].is_end), "reference_is:WINDOW_OR_FRONTIER_MISMATCH"),
    ("input_frontier", pd.Timestamp(FOLDS[0].is_end) - 2 * HOUR, "reference_is:WINDOW_OR_FRONTIER_MISMATCH"),
])
def test_metric_economics_market_and_exact_window_identity_mismatches(field, value, reason):
    source = observations(FOLDS[0])
    source["reference_is"] = replace(source["reference_is"], **{field: value})
    row = measure_quarter("A-SC", FOLDS[0].fold_id, source, scope=scope())
    assert row.status == "INCOMPATIBLE" and reason in row.reasons
    assert all(value is None for value in row.metrics.values())


def test_missing_observations_remain_missing_with_their_slot_and_present_identity():
    source = observations(FOLDS[7])
    original = source.pop("policy_forward")
    row = measure_quarter("A-SC", FOLDS[7].fold_id, source, scope=scope())
    assert row.status == "MISSING" and row.reasons == ("policy_forward:MISSING",)
    assert row.observations["policy_forward"] is None
    assert row.observations["reference_forward"].economics_id == original.economics_id
    report = summarize_quarters("A-SC", [row])
    assert report["rows"][7] is row and report["slot_status"][7] == "MISSING"
    assert report["slots"] == tuple(f.fold_id for f in FOLDS)
    assert report["windows"] == FOLDS


def test_primary_reuses_one_joint_arch_bootstrap_with_registered_constants(monkeypatch):
    source, expected_matrix = family()
    calls = []

    class Capture:
        def __init__(self, block, values, *, seed):
            calls.append((block, values.copy(), seed))
            self.owner = MovingBlockBootstrap(block, values, seed=seed)

        def conf_int(self, function, **kwargs):
            calls.append(kwargs)
            return self.owner.conf_int(function, **kwargs)

    monkeypatch.setattr("arch.bootstrap.MovingBlockBootstrap", Capture)
    report = infer_primary_family(source)
    assert report["status"] == "INTERVALS_COMPUTED" and not report["reasons"]
    assert len(calls) == 2
    assert calls[0][0] == 2 and calls[0][2] == 731
    np.testing.assert_allclose(calls[0][1], expected_matrix, rtol=0., atol=1e-15)
    assert calls[1] == dict(reps=16_384, method="percentile", size=.99375, tail="two")
    # Independent call to the numerical owner, with the actual scalar inputs.
    expected_bounds = MovingBlockBootstrap(2, calls[0][1], seed=731).conf_int(
        lambda a: a.mean(axis=0), reps=16_384, method="percentile", size=.99375, tail="two")
    np.testing.assert_array_equal([[r["lower"] for r in report["coordinates"]],
                                   [r["upper"] for r in report["coordinates"]]], expected_bounds)
    np.testing.assert_allclose([r["mean"] for r in report["coordinates"]],
                              expected_matrix.mean(axis=0), rtol=0., atol=1e-15)
    weights = np.array([(f.oos_end - f.oos_start).days for f in FOLDS])
    assert not np.isclose(report["coordinates"][1]["mean"],
                          np.average(expected_matrix[:, 1], weights=weights), rtol=0., atol=1e-6)
    assert all(a["paired_calendar_days"] == 1734 for a in report["alphas"].values())
    assert report["registration"]["coordinates"] == COORDINATES
    assert all(report["directional_gates"].values())
    assert report["economic_promotion"] is False and report["mature_meta_promotion"] is False


@pytest.mark.parametrize(("r", "q", "passed"), [(1., 0., True), (0., 0., False),
                                                     (1., -.125, False), (-1., .5, False)])
def test_joint_directional_gate_uses_strict_r_and_nonstrict_q_lower_bounds(r, q, passed):
    source, _ = family(r=r, q=q)
    report = infer_primary_family(source)
    assert report["status"] == "INTERVALS_COMPUTED"
    for alpha in PRIMARY_ALPHAS:
        assert report["directional_gates"][alpha] is passed
    for item in report["coordinates"]:
        expected = r if item["metric"] == "R" else q
        assert item["mean"] == item["lower"] == item["upper"] == expected
    assert report["economic_promotion"] is False


@pytest.mark.parametrize("pattern", ("one_gap", "shared_gaps", "different_gaps", "entire_alpha"))
def test_missing_patterns_never_compress_quarters_or_drop_family_coordinates(monkeypatch, pattern):
    source, _ = family()
    if pattern == "entire_alpha":
        del source[PRIMARY_ALPHAS[0]]
    else:
        for number, alpha in enumerate(PRIMARY_ALPHAS):
            drop = ({7} if number == 0 else set()) if pattern == "one_gap" else (
                {2, 7, 9, 13, 15, 17, 18} if pattern == "shared_gaps" else {number + 2})
            source[alpha] = [row for i, row in enumerate(source[alpha]) if i not in drop]
    forbid_bootstrap(monkeypatch)
    report = infer_primary_family(source)
    assert report["status"] == "INCONCLUSIVE"
    assert len(report["coordinates"]) == 8
    assert all(row["lower"] is None and row["upper"] is None for row in report["coordinates"])
    assert all(gate is None for gate in report["directional_gates"].values())
    assert all(len(a["rows"]) == 19 for a in report["alphas"].values())
    if pattern == "shared_gaps":
        assert all(a["paired_quarters"] == 12 and a["minimum_support_met"]
                   for a in report["alphas"].values())
        assert all(row["mean"] is None for row in report["coordinates"])
        assert all(row["available_pair_mean_descriptive"] is not None for row in report["coordinates"])
    if pattern == "entire_alpha":
        assert report["alphas"][PRIMARY_ALPHAS[0]]["slot_status"] == ("MISSING",) * 19


def test_mixed_anchor_scopes_are_not_even_descriptively_pooled(monkeypatch):
    source, _ = family()
    source["A-SC"][7] = quarter(index=7, comparison=scope(kind="own_anchor", role="descriptive"))
    forbid_bootstrap(monkeypatch)
    report = infer_primary_family(source)
    assert report["status"] == "INCONCLUSIVE"
    summary = report["alphas"]["A-SC"]
    assert "MIXED_CONTRAST_OR_ANCHOR_SCOPE" in summary["reasons"]
    assert all(v is None for v in summary["available_pair_means_descriptive"].values())
    assert len(report["coordinates"]) == 8


@pytest.mark.parametrize("change_all_alpha_quarters", (False, True))
def test_changed_identity_within_or_between_alpha_series_blocks_family(monkeypatch, change_all_alpha_quarters):
    source, _ = family()
    changed = range(19) if change_all_alpha_quarters else [8]
    for i in changed:
        obs = {k: replace(v, economics_id="incompatible-account")
               for k, v in source["A-HMA"][i].observations.items()}
        source["A-HMA"][i] = measure_quarter("A-HMA", FOLDS[i].fold_id, obs, scope=scope("A-HMA"))
    forbid_bootstrap(monkeypatch)
    report = infer_primary_family(source)
    assert report["status"] == "INCONCLUSIVE"
    assert "INCOMPATIBLE_FAMILY_METRIC_OR_ECONOMICS" in report["reasons"]
    if not change_all_alpha_quarters:
        assert report["alphas"]["A-HMA"]["all_quarter_means"] is None


def test_mature_meta_has_at_most_six_fitted_quarters_and_is_descriptive_only(monkeypatch):
    source = {}
    for alpha in PRIMARY_ALPHAS:
        comparison = scope(alpha, kind="own_anchor", role="mature_meta")
        source[alpha] = [quarter(alpha, i, comparison=comparison,
            meta_fitted=i >= 13, matured_origins=max(0, i - 1)) for i in range(19)]
    forbid_bootstrap(monkeypatch)
    report = infer_primary_family(source)
    assert report["status"] == "INCONCLUSIVE" and report["mature_meta_promotion"] is False
    for summary in report["alphas"].values():
        mature = summary["mature_meta"]
        assert mature["fold_ids"] == tuple(f.fold_id for f in FOLDS[13:])
        assert mature["quarters"] == 6
        assert mature["descriptive_only"] and not mature["twelve_mature_evaluation_quarters"]
        assert mature["promotion_claim"] is False
    with pytest.raises(ValueError, match="history frontier"):
        quarter(index=7, comparison=scope(kind="own_anchor", role="mature_meta"),
                meta_fitted=True, matured_origins=12)


def test_exact_slots_determinism_and_validation_of_inputs():
    rows = [quarter(index=2), quarter(index=0)]
    report = summarize_quarters("A-SC", rows)
    assert report == summarize_quarters("A-SC", reversed(rows))
    assert report["slots"][0] == "2022Q1" and report["slots"][-1] == "2026Q3"
    assert report["paired_calendar_days"] == 90 + 92
    assert report["minimum_support_met"] is False
    with pytest.raises(ValueError, match="duplicate"):
        summarize_quarters("A-SC", rows + rows)
    with pytest.raises(ValueError, match="alpha/quarter"):
        summarize_quarters("A-HMA", rows)
    with pytest.raises(ValueError, match="original metric"):
        summarize_quarters("A-SC", [replace(rows[0], metrics={"R": 1000.})])
    with pytest.raises(ValueError, match="registered quarter"):
        measure_quarter("A-SC", "2022-01", {}, scope=scope())
    with pytest.raises(ValueError, match="four named"):
        measure_quarter("A-SC", "2022Q1", {"made_up_finance": {}}, scope=scope())
    with pytest.raises(TypeError, match="MetricObservation"):
        measure_quarter("A-SC", "2022Q1", {"reference_is": {"raw_sharpe": 1.}}, scope=scope())
    with pytest.raises(ValueError, match="four registered"):
        infer_primary_family({"RSI": []})
    with pytest.raises(ValueError, match="legacy_reference"):
        scope(kind="own_anchor")
    with pytest.raises(ValueError, match="meta OFF"):
        quarter(index=18, matured_origins=17, meta_fitted=True)


def test_frozen_registration_and_no_numeric_rng_or_input_mutation():
    source, _ = family(r=1., q=.5)
    before = tuple(tuple(rows) for rows in source.values())
    np.random.seed(99)
    expected_next = np.random.random()
    np.random.seed(99)
    one = infer_primary_family(source)
    assert np.random.random() == expected_next
    two = infer_primary_family(dict(reversed(list(source.items()))))
    assert one == two
    assert before == tuple(tuple(rows) for rows in source.values())
    assert FAMILY_CONFIDENCE == .95 and MARGINAL_CONFIDENCE == .99375
    assert BOOTSTRAP_DRAWS == 16_384 and BOOTSTRAP_SEED == 731


def test_numeric_overflow_is_disposition_not_a_finite_fake_contrast(monkeypatch):
    row = quarter(values=(1e308, -1e308, -1e308, 1e308))
    assert row.status == "UNSUPPORTED" and "NONFINITE_CONTRAST" in row.reasons
    assert all(value is None for value in row.metrics.values())
    source, _ = family()
    source["A-SC"][0] = row
    forbid_bootstrap(monkeypatch)
    assert infer_primary_family(source)["status"] == "INCONCLUSIVE"


def test_nonfinite_descriptive_mean_is_not_an_overflowing_primary_estimate(monkeypatch):
    rows = [quarter(index=i, values=(1e307, 0., 0., 0.)) for i in range(19)]
    report = summarize_quarters("A-SC", rows)
    assert "NONFINITE_CONTRAST_MEAN" in report["reasons"]
    assert report["all_quarter_means"] is None
    assert all(value is None for value in report["available_pair_means_descriptive"].values())
    forbid_bootstrap(monkeypatch)
    assert infer_primary_family({"A-SC": rows})["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("failure", ("exception", "nonfinite", "reversed_bounds", "shape"))
def test_bootstrap_failure_is_inconclusive_and_does_not_issue_directional_gates(monkeypatch, failure):
    source, _ = family()

    class BrokenOwner:
        def __init__(self, *args, **kwargs):
            pass

        def conf_int(self, *args, **kwargs):
            if failure == "exception":
                raise FloatingPointError("synthetic owner failure")
            if failure == "nonfinite":
                return np.full((2, 8), np.nan)
            if failure == "reversed_bounds":
                return np.array([[1.] * 8, [-1.] * 8])
            return np.zeros((2, 7))

    monkeypatch.setattr("arch.bootstrap.MovingBlockBootstrap", BrokenOwner)
    report = infer_primary_family(source)
    assert report["status"] == "INCONCLUSIVE"
    assert all(gate is None for gate in report["directional_gates"].values())
    assert all(item["status"] == "INCONCLUSIVE" and item["lower"] is None
               for item in report["coordinates"])
    assert report["reasons"][0].startswith("BOOTSTRAP_")
