"""Sealed engineering replay: actual fit/rank, revisions, panels and resume."""

from dataclasses import replace

from quantbt.optimization.meta_selection.common import wire
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.panel import freeze_panel
from quantbt.optimization.meta_selection.persistence import (
    dumps_revision,
    loads_revision,
)
from quantbt.optimization.meta_selection.records import OutcomeStatus
from quantbt.optimization.meta_selection.selection import MetaSelector
from tests.meta_selection.test_qms03_history import (
    make_task,
    revision_for,
    snapshot,
    stamp,
    witnesses,
)
from tests.meta_selection.test_qms04_ridge import policy_fixture


def replay(runtime, *, resume=False):
    schema, initial, _, template = policy_fixture()
    initial_revision = initial.revisions[0]
    history = MetaHistory()
    history.append(initial_revision)
    published = [initial_revision]
    learner = RidgeLearner(
        settings=RidgeSettings(min_matured_origins=1, epsilon=0.3), runtime=runtime
    )
    selector = MetaSelector(runtime=runtime)
    decisions = []
    for year in range(2023, 2029):
        base, _ = make_task(n=4, year=year)
        candidates = tuple(
            replace(
                c,
                candidate_id=t.candidate_id,
                requested_params=t.requested_params,
                effective_params=t.effective_params,
                observation=replace(c.observation, raw_sharpe=t.observation.raw_sharpe),
                objective=t.objective,
            )
            for c, t in zip(base.candidates, template.candidates, strict=True)
        )
        task = replace(base, family=template.family, candidates=candidates)
        if year == 2026:
            available = stamp("2026-06-01")
            old = initial_revision
            outcomes = tuple(
                replace(
                    o,
                    label_available_at=available,
                    observation=replace(
                        o.observation,
                        status=OutcomeStatus.CENSORED,
                        raw_sharpe=None,
                        sample_std=None,
                        sample_count=0,
                    )
                    if i == 1
                    else o.observation,
                )
                for i, o in enumerate(old.outcomes)
            )
            correction = replace(
                old,
                outcomes=outcomes,
                parent_revision_id=old.revision_id,
                correction_reason="late reviewed censor replaces origin weights",
                revision_available_at=available,
            )
            history.append(correction)
            published.append(correction)
        if resume and year == 2026:
            restored = MetaHistory()
            for revision in published:
                restored.append(
                    loads_revision(
                        dumps_revision(revision),
                        verified_output_witnesses=witnesses(revision),
                        reviewed_revision_ids=(revision.revision_id,),
                    )
                )
            history = restored
            runtime.work_cache.clear()
            learner = RidgeLearner(settings=learner.settings, runtime=runtime)
        view = snapshot(history, task, task.data_cutoff)
        fit = learner.fit(schema, view, fit_completed_at=task.search_completed_at)
        decision = selector.propose(task, fit, full_ranking=True)
        decision = replace(
            decision,
            mode="active",
            actual_evaluation_id=decision.proposed_evaluation_id,
        )
        panel = freeze_panel(
            task,
            schema,
            required_winners=(decision.actual_evaluation_id,),
            sealed_at=task.decision_sealed_at,
        )
        revision = replace(revision_for(task, schema), panel=panel)
        history.append(revision)
        published.append(revision)
        decisions.append(
            wire(
                {
                    "year": year,
                    "task_id": task.task_id,
                    "snapshot_id": view.snapshot_id,
                    "revisions": tuple(r.revision_id for r in view.revisions),
                    "fit_rows": fit.model.fit_row_references,
                    "scaler": fit.model.scaler,
                    "schema": fit.model.schema,
                    "coefficients": fit.model.coefficients,
                    "anchor": task.anchor_candidate_evaluation_id,
                    "pool": tuple(c.evaluation_id for c in task.candidates),
                    "proposal": decision.proposed_evaluation_id,
                    "actual": decision.actual_evaluation_id,
                    "params": decision.proposed_params,
                    "status": decision.status,
                    "guard": decision.guard,
                    "ties": decision.tie_set,
                    "ranking": decision.ranked_ids,
                    "predictions": decision.predictions,
                    "reference_boundary_fallback": decision.numeric[
                        "reference_boundary_fallback"
                    ],
                    "panel": panel.panel_id,
                    "panel_members": panel.members,
                    "outcome_revision": revision.revision_id,
                    "information_as_of": task.data_cutoff,
                }
            )
        )
    # Rewind after publishing corrections: an old cutoff still resolves old bytes.
    old_view = snapshot(history, initial_revision.task, stamp("2023-12-31"))
    assert initial_revision.revision_id in {r.revision_id for r in old_view.revisions}
    assert len(published) == 8
    return {
        "decisions": decisions,
        "published_revisions": [r.revision_id for r in published],
        "old_cutoff_snapshot": old_view.snapshot_id,
        "retained_history": len(history._revisions),
        "numeric": wire(runtime.metadata),
        "resume": resume,
        "warm_start": "off",
        "current_forward_used": False,
        "synthetic_engineering_only": True,
    }


def compare_sequences(a, b):
    import numpy as np

    assert a["published_revisions"] == b["published_revisions"]
    assert a["old_cutoff_snapshot"] == b["old_cutoff_snapshot"]
    for x, y in zip(a["decisions"], b["decisions"], strict=True):
        for key in x:
            if key in {"coefficients", "predictions", "reference_boundary_fallback"}:
                continue
            assert x[key] == y[key], key
        np.testing.assert_allclose(
            x["coefficients"], y["coefficients"], rtol=1e-9, atol=1e-10
        )
        for p, q in zip(x["predictions"], y["predictions"], strict=True):
            for key in p:
                if key in {"yhat", "qhat", "distance"}:
                    np.testing.assert_allclose(p[key], q[key], rtol=1e-9, atol=1e-10)
                else:
                    assert p[key] == q[key], key
