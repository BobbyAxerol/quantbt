"""Opt-in endpoint output is lossless original data, not a second observation."""

import pytest

from tools.qms_pre05_workloads import Cell, execute, metadata, prepare
from tools.qms08_package import ROOT


@pytest.fixture(scope="module", params=("pct_equity", "intrabar", "event_driven", "order_commands", "reactive_reset"))
def observed(request):
    from tests.meta_selection import pre_e06_02_support as ordinary

    cell = Cell("domain", request.param, "active")
    # Historical serialized witnesses cannot qualify a changed financial source.
    historical = ordinary.run(cell.route, data=ordinary.tape(cell.route, end="2022-05-31"), numeric="require")
    prepared = prepare(cell, ROOT / ".maturin/qms08/pre-e06-05", frozen_history=historical.context.history)
    result = execute(prepared, cell)
    return cell, result, prepared[2]


def test_e07_result_exposes_exact_current_run_revisions(observed):
    cell, result, context = observed
    meta = metadata(result, cell)["meta_selection"]
    revisions = meta["observed_revisions"]
    assert len(revisions) == len(meta["tasks"]) == len(meta["records"]) == 1
    for revision, task, record in zip(revisions, meta["tasks"], meta["records"], strict=True):
        assert revision is context.history._revisions[revision.revision_id]
        assert revision.task is task
        assert revision.revision_id == record["observer_revision_id"]
        assert revision.panel.members == record["panel_members"]
        assert len(revision.outcomes) == record["observer_evaluations"]
        assert record["matured_origins"] >= 12 and meta["models"]
        assert task.decision_sealed_at < task.first_forward_action_at
        assert revision.revision_available_at > task.forward_end
        assert all(o.observation.verification == "original_result" for o in revision.outcomes)
        assert set(o.evaluation_id for o in revision.outcomes) == set(revision.panel.members)
        assert not set(r.revision_id for r in revisions).intersection(record["training_revision_ids"])


def test_e07_rq_can_be_reconstructed_without_retaining_history(observed):
    cell, result, _ = observed
    meta = metadata(result, cell)["meta_selection"]
    for record, revision in zip(meta["records"], meta["observed_revisions"], strict=True):
        candidates = {c.evaluation_id: c for c in revision.task.candidates}
        forward = {o.evaluation_id: o.observation for o in revision.outcomes}
        anchor, selected = (candidates[record[k]] for k in
                            ("native_selected_evaluation_id", "selected_evaluation_id"))
        observations = (anchor.observation, selected.observation,
                        forward[anchor.evaluation_id], forward[selected.evaluation_id])
        assert all(o.status.value == "VALID" for o in observations)
        a, m, fa, fm = (o.raw_sharpe for o in observations)
        assert ((a-fa)-(m-fm)) == pytest.approx((a-m)+(fm-fa))
        applied = result.params_by_fold if cell.route == "reactive_reset" else result.metadata["walk_forward"]["params_by_fold"]
        assert record["selected_params"] == dict(selected.effective_params) == applied[record["fold_id"]]


@pytest.mark.parametrize("route", ("event_driven", "order_commands", "reactive_reset"))
def test_e07_disabled_has_no_meta_sidecar_or_observer(route):
    cell = Cell("domain", route, "off")
    result = execute(prepare(cell, ROOT / ".maturin/qms08/pre-e06-05"), cell)
    assert "meta_selection" not in metadata(result, cell)
