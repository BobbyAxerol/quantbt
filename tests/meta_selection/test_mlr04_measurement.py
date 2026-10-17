"""Raw label units, signed decay and explicit missing-witness expectations."""

from copy import deepcopy

import pytest

from tests.meta_selection.test_qms03_history import make_task, revision_for
from tools.meta_model_research.decision_measurement import check_economics


def fixture():
    task, schema = make_task(n=3)
    revision = revision_for(task, schema)
    a = task.anchor_candidate_evaluation_id
    w = next(c.evaluation_id for c in task.candidates if c.evaluation_id != a)
    cs = {c.evaluation_id:c.observation.raw_sharpe for c in task.candidates}
    os = {o.evaluation_id:o.observation.raw_sharpe for o in revision.outcomes}
    row = dict(anchor=a, winner=w, economics=dict(status="OBSERVED_KNOWN_WINNER",
        winner_witness_exists=True, anchor_is=cs[a], selected_is=cs[w],
        anchor_forward=os[a], selected_forward=os[w],
        R=(cs[a]-os[a])-(cs[w]-os[w]), Q=os[w]-os[a], IS_effect=cs[a]-cs[w]))
    return row, revision


def test_raw_units_and_signed_decomposition():
    row, revision = fixture()
    assert check_economics(row, revision)
    assert row['economics']['R'] == pytest.approx(row['economics']['Q']+row['economics']['IS_effect'])


@pytest.mark.parametrize('field',['anchor_is','selected_is','anchor_forward','selected_forward','R','Q','IS_effect'])
def test_independent_check_rejects_forged_metrics(field):
    row, revision = fixture()
    row['economics'][field] += .1
    with pytest.raises(ValueError,match='measurement differs'):
        check_economics(row,revision)


def test_unknown_forward_is_not_zero_or_a_conveniently_known_winner():
    row, _ = fixture()
    task, schema = make_task(n=30)
    revision = revision_for(task, schema)
    observed = {o.evaluation_id for o in revision.outcomes}
    row['anchor'] = task.anchor_candidate_evaluation_id
    row['winner'] = next(c.evaluation_id for c in task.candidates if c.evaluation_id not in observed)
    with pytest.raises(ValueError,match='missing/undefined'):
        check_economics(row,revision)
    row['economics']=dict(status='MISSING_OR_UNDEFINED_WINNER_WITNESS',winner_witness_exists=False,R=None,Q=None,IS_effect=None)
    assert not check_economics(row,revision)
    other=deepcopy(row); other['economics']['Q']=0.0
    with pytest.raises(ValueError,match='missing/undefined'):
        check_economics(other,revision)
