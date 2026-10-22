"""Independent full-roster synthetic expectations; no corpus, model or finance."""

from copy import deepcopy
import json

import pytest

from tools.meta_model_research.family_analysis import (
    FOLDS,
    GROUPS,
    METRICS,
    PANELS,
    ROSTER,
    VERSION,
    summarize_development,
)


def fixture():
    rows, baseline = [], []
    for panel in PANELS:
        for group in GROUPS:
            for fold in FOLDS:
                common = dict(
                    panel=panel,
                    group=group,
                    fold=fold,
                    snapshot_id=f"PRIVATE-SNAPSHOT-{panel}-{group}-{fold}",
                    anchor=f"PRIVATE-ANCHOR-{group}-{fold}",
                    cutoff="2023-01-01T00:00Z",
                    label_available_at="2023-02-01T00:00Z",
                    revision_available_at="2023-02-02T00:00Z",
                    status="META_MODEL_PROPOSAL",
                )
                baseline.append(
                    dict(
                        common,
                        policy="P0",
                        winner="PRIVATE-P0",
                        loss=4.0,
                        served_metrics=dict(y_mse=4.0, q_mse=4.0, y_mae=2.0),
                        training=dict(
                            train_origin_macro_mse=3.0, coefficients=[12345.0]
                        ),
                        economics=dict(
                            R=1.0, IS_effect=0.25, Q=0.75, winner_witness_exists=True
                        ),
                    )
                )
                for code in ROSTER:
                    rows.append(
                        dict(
                            common,
                            code=code,
                            winner="PRIVATE-NEW",
                            loss=2.0,
                            served_metrics=dict(
                                y_mse=2.0,
                                q_mse=2.0,
                                **{
                                    metric: 0.5
                                    if "accuracy" in metric or "spearman" in metric
                                    else 1.5
                                    if "mae" in metric
                                    else 1.25
                                    if "slope" in metric
                                    else 0.125
                                    for metric in METRICS
                                },
                            ),
                            null_reasons={},
                            training=dict(
                                served_y_mse=1.0,
                                backend=dict(
                                    state=dict(coefficients=[98765.0]),
                                    secret_id="PRIVATE-MODEL",
                                ),
                            ),
                            economics=dict(
                                R=1.5,
                                IS_effect=0.5,
                                Q=1.0,
                                winner_witness_exists=True,
                                selected_params={"PRIVATE-PARAM": 1234},
                            ),
                            proposed_params={"PRIVATE-PARAM": 999},
                            fit_id="PRIVATE-FIT",
                        )
                    )
    nominees = {
        panel: {
            group: dict(
                policy="RESEARCH_NOMINEES",
                nominees=["H200", "X3"],
                reason="SUPPORTED_GROUP_CHRONOLOGICAL_DEVELOPMENT_SCREEN",
                private_id="PRIVATE-NOMINEE",
                private_params={"alpha": 1234},
            )
            for group in GROUPS
        }
        for panel in PANELS
    }
    return (
        dict(schema="m4.ml03.finite-screen.v1", rows=rows, nominees=nominees),
        dict(schema="m4.ml02.fixed-pool-replay.v1", rows=baseline),
    )


@pytest.fixture
def data():
    return fixture()


def cell(summary, code="B1", group=GROUPS[0], panel="base"):
    return summary["summaries"][panel]["cells"][group][code]


def target(data, *, code="B1", group=GROUPS[0], panel="base", fold=13):
    return next(
        r
        for r in data[0]["rows"]
        if (r["code"], r["group"], r["panel"], r["fold"]) == (code, group, panel, fold)
    )


def set_loss(row, value):
    row["loss"] = value
    row["served_metrics"]["y_mse"] = row["served_metrics"]["q_mse"] = value


def test_complete_roster_has_independent_constant_moments_and_paired_units(data):
    assert len(data[0]["rows"]) == 480 and len(data[1]["rows"]) == 96
    before = deepcopy(data)
    summary = summarize_development(*data)
    assert data == before
    assert summary["schema"] == VERSION
    for panel in PANELS:
        for group in GROUPS:
            for code in ROSTER:
                c = cell(summary, code, group, panel)
                assert c["served_loss"] == dict(n=12, missing=0, mean=2.0, median=2.0)
                assert c["train_served_loss"]["mean"] == 1.0
                assert c["y_mae"]["mean"] == c["q_mae"]["mean"] == 1.5
                assert c["y_spearman"]["mean"] == c["q_pair_accuracy"]["mean"] == 0.5
                assert c["y_calibration_slope"]["mean"] == 1.25
                assert c["q_calibration_intercept"]["mean"] == 0.125
                paired = c["paired_vs_P0"]
                for key, expected in (
                    ("delta_mse", -2.0),
                    ("relative_mse_change_percent", -50.0),
                    ("delta_R", 0.5),
                    ("delta_IS_effect", 0.25),
                    ("delta_Q", 0.25),
                ):
                    assert paired[key] == dict(
                        n=12, missing=0, mean=expected, median=expected
                    )
                assert paired["relative_mse_change_percent_from_matched_means"] == -50.0
                assert paired["winner_counts"]["known_new_winner"] == 12
                assert paired["matched_identity_checks"] == 60
        macro = summary["summaries"][panel]["macro"]["B1"]
        assert macro["served_loss"] == dict(n=4, missing=0, mean=2.0, median=2.0)
        assert macro["paired_vs_P0"]["winner_counts"]["known_new_winner"] == 48


def test_failed_sparse_rows_and_nulls_retain_calendar_and_missing_support(data):
    row = target(data)
    for key in tuple(row):
        if key not in ("panel", "group", "fold", "code"):
            del row[key]
    row.update(status="FIT_FAILED_RETAINED", loss=None)
    null = target(data, fold=14)
    set_loss(null, None)
    null["served_metrics"]["y_spearman"] = None
    null["null_reasons"] = dict(
        y_mse="NO_VALID_LABELED_PANEL_ROWS", y_spearman="PRIVATE-REASON-ID"
    )
    c = cell(summarize_development(*data))
    assert c["calendar_origins"] == 12 and c["failed_fits"] == 1
    assert c["served_loss"] == dict(n=10, missing=2, mean=2.0, median=2.0)
    assert c["train_served_loss"]["n"] == 11
    assert c["y_spearman"]["n"] == 10
    assert c["null_reason_counts"]["y_mse"] == {
        "FIT_FAILED_RETAINED": 1,
        "NO_VALID_LABELED_PANEL_ROWS": 1,
    }
    assert c["null_reason_counts"]["y_spearman"]["OTHER_PRIVATE_REASON"] == 1
    assert c["paired_vs_P0"]["delta_mse"]["n"] == 10
    assert c["paired_vs_P0"]["winner_counts"]["uncompared_winner"] == 1


def test_missing_or_undefined_new_winners_never_become_zero_economics(data):
    target(data)["economics"] = dict(
        R=None, Q=None, IS_effect=None, winner_witness_exists=False
    )
    target(data, fold=14)["economics"] = dict(
        R=None, Q=None, IS_effect=None, winner_witness_exists=True
    )
    del target(data, fold=15)["economics"]
    c = cell(summarize_development(*data))
    paired = c["paired_vs_P0"]
    assert paired["delta_R"] == dict(n=9, missing=3, mean=0.5, median=0.5)
    assert paired["delta_Q"]["n"] == paired["delta_IS_effect"]["n"] == 9
    assert paired["winner_counts"]["missing_new_winner"] == 1
    assert paired["winner_counts"]["undefined_new_winner"] == 1
    assert paired["winner_counts"]["unknown_new_winner_witness"] == 1
    assert paired["winner_counts"]["known_new_winner"] == 9


def test_unchanged_winner_is_not_counted_as_new(data):
    target(data)["winner"] = "PRIVATE-P0"
    counts = cell(summarize_development(*data))["paired_vs_P0"]["winner_counts"]
    assert counts["compared_winner"] == 12
    assert counts["changed_winner"] == counts["known_new_winner"] == 11


def test_entire_failed_roster_is_present_but_unmeasured_not_zero(data):
    for row in data[0]["rows"]:
        keys = {key: row[key] for key in ("panel", "group", "fold", "code")}
        row.clear()
        row.update(keys, status="FIT_FAILED_RETAINED", loss=None)
    for panel in PANELS:
        for group in GROUPS:
            data[0]["nominees"][panel][group] = dict(
                policy="P0",
                nominees=[],
                reason="FAMILY_CALIBRATION_ORIGIN_SUPPORT_INSUFFICIENT",
            )
    summary = summarize_development(*data)
    for panel in PANELS:
        for code in ROSTER:
            macro = summary["summaries"][panel]["macro"][code]
            assert macro["calendar_origins"] == macro["failed_fits"] == 48
            assert macro["served_loss"] == dict(n=0, missing=4, mean=None, median=None)
            assert macro["origin_macro_rmse"] is None
            counts = macro["paired_vs_P0"]["winner_counts"]
            assert counts["known_new_winner"] == counts["missing_new_winner"] == 0
            assert counts["uncompared_winner"] == 48


def test_origin_then_equal_group_macro_not_pooled_available_rows(data):
    values = (1.0, 3.0, 5.0, 7.0)
    for gi, group in enumerate(GROUPS):
        for fold in FOLDS:
            set_loss(
                target(data, group=group, fold=fold),
                values[gi] if gi == 0 or fold == 13 else None,
            )
    summary = summarize_development(*data)
    macro = summary["summaries"]["base"]["macro"]["B1"]
    assert macro["served_loss"]["mean"] == 4.0
    assert macro["served_loss"]["mean"] != pytest.approx((12 + 3 + 5 + 7) / 15)
    assert list(macro["supported_loss_origins"].values()) == [12, 1, 1, 1]
    assert macro["paired_vs_P0"]["delta_mse"]["mean"] == 0.0


def test_wholly_unsupported_group_has_null_four_group_macro(data):
    for fold in FOLDS:
        set_loss(target(data, fold=fold), None)
    macro = summarize_development(*data)["summaries"]["base"]["macro"]["B1"]
    assert macro["served_loss"] == dict(n=3, missing=1, mean=None, median=None)
    assert macro["paired_vs_P0"]["delta_mse"]["mean"] is None


def test_relative_comparison_uses_matched_p0_not_full_baseline_mean(data):
    set_loss(target(data), None)
    data[1]["rows"][0]["loss"] = 100.0
    data[1]["rows"][0]["served_metrics"]["y_mse"] = 100.0
    data[1]["rows"][0]["served_metrics"]["q_mse"] = 100.0
    p = cell(summarize_development(*data))["paired_vs_P0"]
    assert p["matched_P0_mse"]["mean"] == 4.0
    assert p["relative_mse_change_percent_from_matched_means"] == -50.0
    assert p["delta_mse"]["n"] == 11


def test_zero_p0_loss_keeps_absolute_delta_but_relative_is_undefined(data):
    for row in data[1]["rows"]:
        set_loss(row, 0.0)
    p = cell(summarize_development(*data))["paired_vs_P0"]
    assert p["delta_mse"]["mean"] == 2.0
    assert p["relative_mse_change_percent"] == dict(
        n=0, missing=12, mean=None, median=None
    )
    assert p["relative_mse_change_percent_from_matched_means"] is None


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("mutation", ["duplicate", "missing"])
def test_required_rosters_include_null_and_failed_cells(data, which, mutation):
    if mutation == "duplicate":
        data[which]["rows"].append(deepcopy(data[which]["rows"][0]))
    else:
        data[which]["rows"].pop()
    with pytest.raises(ValueError, match="DUPLICATE_KEY|INCOMPLETE_ROSTER"):
        summarize_development(*data)


@pytest.mark.parametrize(
    "field",
    ["snapshot_id", "anchor", "cutoff", "label_available_at", "revision_available_at"],
)
@pytest.mark.parametrize("missing", [False, True])
def test_mismatched_or_one_sided_bindings_fail_closed(data, field, missing):
    if missing:
        del target(data)[field]
    else:
        target(data)[field] = (
            "2023-03-01T00:00Z"
            if field.endswith("_at") or field == "cutoff"
            else "WRONG-PRIVATE-ID"
        )
        if field == "label_available_at":
            target(data)["revision_available_at"] = "2023-03-02T00:00Z"
    with pytest.raises(ValueError, match="MATCHED_BINDING"):
        summarize_development(*data)


def test_equivalent_utc_bindings_and_optional_absence_on_both_sides(data):
    target(data)["cutoff"] = "2022-12-31T19:00:00-05:00"
    del target(data)["snapshot_id"]
    del data[1]["rows"][0]["snapshot_id"]
    # The baseline binding is shared with all five codes at this origin.
    for code in ROSTER[1:]:
        del target(data, code=code)["snapshot_id"]
    assert cell(summarize_development(*data))["paired_vs_P0"]["delta_mse"]["n"] == 12


@pytest.mark.parametrize(
    "path",
    ["loss", "served_metrics", "training", "economics", "private_metadata", "baseline"],
)
def test_nonfinite_values_fail_closed_even_in_nonpublic_metadata(data, path):
    if path == "loss":
        target(data)["loss"] = float("nan")
    elif path == "baseline":
        data[1]["rows"][0]["loss"] = float("inf")
    else:
        target(data)[path] = dict(hidden_nonfinite=float("nan"))
    with pytest.raises(ValueError, match="NONFINITE"):
        summarize_development(*data)


@pytest.mark.parametrize(
    "mutation",
    [
        "negative-loss",
        "failed-with-loss",
        "loss-mismatch",
        "economic-identity",
        "partial-economics",
        "unwitnessed-economics",
        "version",
        "unknown-code",
    ],
)
def test_invalid_numeric_or_roster_contracts_fail_closed(data, mutation):
    row = target(data)
    if mutation == "negative-loss":
        set_loss(row, -1.0)
    elif mutation == "failed-with-loss":
        row["status"] = "FIT_FAILED_RETAINED"
    elif mutation == "loss-mismatch":
        row["served_metrics"]["y_mse"] = 9.0
    elif mutation == "economic-identity":
        row["economics"]["R"] = 9.0
    elif mutation == "partial-economics":
        row["economics"]["Q"] = None
    elif mutation == "unwitnessed-economics":
        row["economics"]["winner_witness_exists"] = False
    elif mutation == "version":
        data[0]["schema"] = "unknown"
    else:
        row["code"] = "X999"
    with pytest.raises(ValueError, match="MLR03_ANALYSIS"):
        summarize_development(*data)


def test_baseline_full_replay_filters_only_p0_development(data):
    data[1]["rows"] += [
        dict(data[1]["rows"][0], policy="P1", loss=500.0),
        dict(data[1]["rows"][0], fold=25, loss=500.0),
    ]
    assert (
        cell(summarize_development(*data))["paired_vs_P0"]["delta_mse"]["mean"] == -2.0
    )


def test_public_projection_drops_private_metadata_and_never_nominates_from_train_loss(
    data,
):
    summary = summarize_development(*data)
    encoded = json.dumps(summary, allow_nan=False)
    assert "PRIVATE" not in encoded
    for key in (
        "coefficients",
        "proposed_params",
        "snapshot_id",
        "fit_id",
        "artifact_id",
        "anchor",
    ):
        assert key not in encoded
    assert summary["scope"] == "descriptive_development_only"
    assert summary["numerical_economic_ci"] is summary["shortlist_computed"] is False
    assert summary["economic_intervals"] is None
    assert summary["public_activation"] is summary["economic_promotion"] is False
    target(data)["training"]["served_y_mse"] = 1e12
    other = summarize_development(*data)
    for panel in PANELS:
        assert (
            other["summaries"][panel]["nominees"]
            == summary["summaries"][panel]["nominees"]
        )
        for group in GROUPS:
            assert summary["summaries"][panel]["nominees"][group]["nominees"] == [
                "H200",
                "X3",
            ]


@pytest.mark.parametrize("codes", [["X999"], ["B1", "B1"], ["B1", "H135", "H200"]])
def test_unknown_duplicate_or_excess_nominees_fail_closed(data, codes):
    data[0]["nominees"]["base"][GROUPS[0]]["nominees"] = codes
    with pytest.raises(ValueError, match="NOMINEES_INVALID"):
        summarize_development(*data)


def test_nomination_private_reason_objects_are_sanitized_not_copied(data):
    data[0]["nominees"]["base"][GROUPS[0]]["reason"] = {"private_id": "PRIVATE-REASON"}
    record = summarize_development(*data)["summaries"]["base"]["nominees"][GROUPS[0]]
    assert record["reason"] == "OTHER_PRIVATE_REASON"
    assert "PRIVATE-REASON" not in json.dumps(record)


def test_row_permutation_does_not_change_summary(data):
    first = summarize_development(*data)
    data[0]["rows"].reverse()
    data[1]["rows"].reverse()
    assert summarize_development(*data) == first
