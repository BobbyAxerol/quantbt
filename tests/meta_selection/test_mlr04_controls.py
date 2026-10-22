"""Synthetic negative controls for the bounded actual-history verifier."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.meta_selection.test_mlr02_linear import corpus
from tools.meta_model_research.families import FamilySpec
from tools.meta_model_research.family_controls import require_same_decision, synthetic_correction
from tools.meta_model_research.learners import FamilyResearch


def fitted(data):
    engine = FamilyResearch()
    fit = engine.fit(FamilySpec("B1"), data[0], data[2],
                     fit_completed_at=data[3].decision_sealed_at)
    return engine.propose(data[3], fit, schema=data[0], full_ranking=True)


def test_mutation_is_explicit_and_preserves_anchor_source_and_original():
    schema, _, _, _, revisions = corpus()
    original = revisions[0]
    available = original.revision_available_at + pd.Timedelta(days=1)
    changed = synthetic_correction(original, schema, available)
    assert changed.parent_revision_id == original.revision_id
    assert changed.correction_reason == "SYNTHETIC_CAUSAL_CONTROL_NOT_ECONOMIC_LABEL"
    assert changed.task is original.task and changed.panel is original.panel
    assert changed.revision_available_at == available
    anchor = original.task.anchor_candidate_evaluation_id
    geom = schema.parameter_geometry(original.task.candidates)
    ai = next(i for i,c in enumerate(original.task.candidates) if c.evaluation_id == anchor)
    distance = {c.evaluation_id: np.linalg.norm(g-geom[ai])
                for c,g in zip(original.task.candidates,geom)}
    for before, after in zip(original.outcomes, changed.outcomes):
        assert after.label_available_at == before.label_available_at
        assert after.observation.raw_sharpe == pytest.approx(
            before.observation.raw_sharpe+3*distance[before.evaluation_id])
        if before.evaluation_id == anchor:
            assert before.observation == after.observation


def test_exact_controls_reject_any_changed_fit_or_winner():
    data = corpus()
    first = fitted(data)
    require_same_decision(first, fitted(data))
    # Bypass the artifact's earlier constructor guard to exercise this verifier.
    mutated = SimpleNamespace(decision=first.decision, fit=replace(first.fit,
        fit_completed_at=first.fit.fit_completed_at-pd.Timedelta(nanoseconds=1)))
    with pytest.raises(ValueError, match="future information"):
        require_same_decision(first, mutated)


def test_shadow_uses_same_proposal_but_applies_native_anchor_not_the_model_winner():
    data = corpus()
    engine = FamilyResearch()
    fit = engine.fit(FamilySpec("B1"), data[0], data[2],
                     fit_completed_at=data[3].decision_sealed_at)
    proposed = engine.propose(data[3], fit, schema=data[0], full_ranking=True)
    shadow = engine.propose(data[3], fit, schema=data[0], mode="shadow", full_ranking=True)
    assert shadow.decision.predictions == proposed.decision.predictions
    assert shadow.decision.proposed_evaluation_id == proposed.decision.proposed_evaluation_id
    assert shadow.decision.actual_evaluation_id == data[3].anchor_candidate_evaluation_id
    assert proposed.decision.actual_evaluation_id is None
