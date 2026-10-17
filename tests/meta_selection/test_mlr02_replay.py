"""Independent aggregation and source-bound pipeline checks for ML-02."""

from dataclasses import replace
import math

import pytest

from tools.meta_model_research.analysis import family_inference, paired_coordinates
from tools.meta_model_research.protocol import GROUPS, StudyProtocol, choose_recipe
from tools.meta_model_research.replay import base_revision, view
from tests.meta_selection.test_qms03_history import make_task, revision_for


def test_base_only_view_preserves_original_and_origin_normalization():
    task, schema = make_task(n=20, year=2020)
    revision = revision_for(task, schema)
    if not revision.panel.extra_union_members:
        from quantbt.optimization.meta_selection.panel import freeze_panel
        outside = next(c for c in task.candidates if c.evaluation_id not in revision.panel.base_members)
        panel = freeze_panel(task, schema, required_winners=(outside.evaluation_id,),
                             sealed_at=revision.panel.sealed_at)
        # Use the existing fixture builder to create terminal dispositions for the union.
        labels = {o.evaluation_id: o for o in revision.outcomes}
        labels[outside.evaluation_id] = replace(revision.outcomes[0],
                                                evaluation_id=outside.evaluation_id)
        revision = replace(revision, panel=panel,
                           outcomes=tuple(labels[i] for i in panel.members))
    original_id = revision.revision_id
    restricted = base_revision(revision)
    assert restricted.task is revision.task
    assert restricted.panel.base_members == revision.panel.base_members
    assert not restricted.panel.extra_union_members
    assert len(restricted.outcomes) == 16
    assert revision.revision_id == original_id
    assert restricted.revision_id != original_id
    assert math.isclose(sum(r.origin_weight for r in restricted.training_rows), 1.)


def rows_fixture():
    rows = []
    for group in GROUPS:
        for fold in StudyProtocol().evaluation_folds:
            for policy in ("P0", "P1", "P2"):
                shift = {"P0": 0., "P1": 1., "P2": 2.}[policy]
                rows.append(dict(group=group, panel="base", fold=fold, policy=policy,
                                 loss=4-shift, winner=policy,
                                 economics=dict(Q=shift, R=3*shift, IS_effect=2*shift,
                                                winner_witness_exists=True)))
    return rows


def test_group_origin_paired_oracle_and_missing_calendar_fail_closed():
    rows = rows_fixture()
    paired = paired_coordinates(rows, "base")
    assert len(paired) == 4 * 32 * 2
    assert all(r["delta_loss"] == -1 and r["delta_Q"] == 1 and r["delta_R"] == 3
               for r in paired if r["policy"] == "P1")
    changed = [dict(r) for r in paired]
    changed[0]["delta_Q"] = None
    ci = family_inference(changed)
    assert ci["intervals"] is None and not ci["numerical_bootstrap_executed"]
    with pytest.raises(ValueError, match="duplicate"):
        paired_coordinates(rows + rows[:1], "base")


def test_future_inner_outcomes_and_heldout_values_cannot_choose_lambda():
    rows = [dict(group=g, fold=f, alpha=a, loss=(a-.3)**2,
                 label_available_at="2023-01-01T00:00Z", revision_available_at="2023-01-01T00:01Z")
            for g in GROUPS for f in range(13, 25) for a in StudyProtocol().grid]
    cutoff = "2024-01-31T23:00Z"
    first = choose_recipe(rows, "A-HMA", cutoff)
    changed = [dict(r, loss=1e20) if r["group"] == "A-HMA" else dict(r) for r in rows]
    changed += [dict(group="A-SC", fold=24, alpha=.1, loss=-1e20,
                     label_available_at=cutoff, revision_available_at=cutoff)]
    assert choose_recipe(changed, "A-HMA", cutoff) == first
    assert choose_recipe(list(reversed(changed)), "A-HMA", cutoff) == first


def test_late_published_january_label_excluded_by_actual_frontier():
    from tools.meta_model_research.protocol import permitted_calibration_rows
    row = dict(group="A-SC", fold=24, alpha=.1, loss=0,
               label_available_at="2024-01-31T23:00:14Z",
               revision_available_at="2024-01-31T23:00:20Z")
    assert not permitted_calibration_rows([row], "A-HMA", "2024-01-31T23:00:00Z")


def test_complete_calendar_bootstrap_matches_constant_independent_oracle():
    paired = paired_coordinates(rows_fixture(), "base")
    inferred = family_inference(paired)
    assert inferred["numerical_bootstrap_executed"]
    assert inferred["intervals"]["P1:delta_loss"] == [-1., -1.]
    assert inferred["intervals"]["P1:delta_Q"] == [1., 1.]
    assert inferred["intervals"]["P1:delta_R"] == [3., 3.]
    assert inferred["coordinate_confidence"] == pytest.approx(1-(1-.95)/6)


def test_pilot_gate_forecasts_before_scale_and_rejects_cost_excess():
    from tools.meta_model_research.replay import pilot_gate
    rows = [dict(group=g, wall_seconds=.2) for g in GROUPS for _ in range(3)]
    result = pilot_gate(rows, StudyProtocol(), elapsed_cpu=100)
    assert result["status"] == "ADMITTED"
    assert result["conservative_remaining_seconds"] == pytest.approx(449.6)
    with pytest.raises(ValueError, match="twelve"):
        pilot_gate(rows[:3], StudyProtocol(), elapsed_cpu=0)
    with pytest.raises(ValueError, match="CPU"):
        pilot_gate([dict(r, wall_seconds=10) for r in rows], StudyProtocol(), elapsed_cpu=0)


def test_recovery_retains_null_reasons_and_checks_actual_prediction_loss():
    from tools.meta_model_research.recovery import complete_metric_evidence
    from tools.meta_model_research.linear import evaluate_revision
    from tests.meta_selection.test_mlr02_linear import corpus, artifact
    data = corpus()
    _, a = artifact(data)
    revision = revision_for(data[3], data[0])
    metrics = evaluate_revision(a, revision,
        available_as_of=revision.revision_available_at + __import__("pandas").Timedelta(seconds=1))
    row = dict(scored_rows=metrics.scored_rows, loss=metrics.metrics["y_mse"],
               metric_status=metrics.status, served_metrics=dict(metrics.metrics))
    recovered = complete_metric_evidence(row, a.decision.predictions, revision, "union")
    assert recovered["metric_null_reasons"] == dict(metrics.null_reasons)
    assert recovered["label_statuses"] == dict(metrics.label_statuses)
    if row["loss"] is not None:
        broken = dict(row, served_metrics=dict(row["served_metrics"], y_mse=row["loss"]+1))
        with pytest.raises(ValueError, match="metric differs"):
            complete_metric_evidence(broken, a.decision.predictions, revision, "union")
