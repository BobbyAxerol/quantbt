"""Actual-history ML-02 causality controls; mutations are never economic labels."""

from dataclasses import replace
from pathlib import Path
import argparse

import numpy as np
import pandas as pd

from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import load_corpus, save_new
from .linear import LinearResearch, Policy


def run():
    corpus = load_corpus("A-HMA")
    task, schema = corpus.revisions[25].task, corpus.schema
    saved = corpus.selections[25]["snapshot"]

    def snapshot():
        return corpus.history.snapshot(
            family_id=saved["family_id"], authorized_corpora=saved["authorized_corpora"],
            outcome_origins=saved["outcome_origins"], research_exposures=saved["research_exposures"],
            information_as_of=saved["information_as_of"])

    def correction(original, available):
        anchor = original.task.anchor_candidate_evaluation_id
        outcomes = tuple(replace(o, observation=replace(o.observation,
            raw_sharpe=o.observation.raw_sharpe + (3 if o.evaluation_id != anchor else 0)))
            if o.observation.status.value == "VALID" else o for o in original.outcomes)
        return replace(original, outcomes=outcomes, revision_available_at=available,
                       parent_revision_id=original.revision_id,
                       correction_reason="SYNTHETIC_MUTATION_CONTROL_NOT_REAL_ACCOUNT_OR_ECONOMIC_LABEL",
                       verification="reviewed_import")

    engine = LinearResearch(runtime=NumericRuntime(native_policy="require"), max_fits=50)
    policies = (Policy("P0"), Policy("P1"), Policy("P2", .3))
    first = snapshot()
    base = []
    for policy in policies:
        fitted = engine.fit(policy, schema, first, fit_completed_at=task.decision_sealed_at)
        base.append(engine.propose(task, fitted, schema=schema))
    future = corpus.revisions[56]
    corpus.history.append(correction(future, future.revision_available_at + pd.Timedelta(days=1)))
    second = snapshot()
    if second.snapshot_id != first.snapshot_id:
        raise ValueError("future correction changed earlier information rights")
    rows = []
    for policy, previous in zip(policies, base):
        fitted = engine.fit(policy, schema, second, fit_completed_at=task.decision_sealed_at)
        other = engine.propose(task, fitted, schema=schema)
        if (previous.fit.fit_id != fitted.fit_id or previous.decision.predictions != other.decision.predictions
                or previous.decision.proposed_evaluation_id != other.decision.proposed_evaluation_id
                or previous.decision.tie_set != other.decision.tie_set):
            raise ValueError("actual-history future mutation changed served decision")
        rows.append(dict(policy=policy.name, future_invariance=True,
                         full_pool_predictions=len(other.decision.predictions)))
    past = corpus.revisions[0]
    corpus.history.append(correction(past, task.data_cutoff - pd.Timedelta(days=1)))
    third = snapshot()
    if third.snapshot_id == first.snapshot_id or third.origin_count != first.origin_count:
        raise ValueError("valid past correction must replace, not append an origin")
    for policy, previous, row in zip(policies, base, rows):
        fitted = engine.fit(policy, schema, third, fit_completed_at=task.decision_sealed_at)
        other = engine.propose(task, fitted, schema=schema)
        delta = float(np.max(np.abs(np.asarray(fitted.outcome.model.coefficients)
                                     - np.asarray(previous.fit.outcome.model.coefficients))))
        if delta <= 1e-12 or other.fit.snapshot_id == previous.fit.snapshot_id:
            raise ValueError("positive control is vacuous")
        row.update(permitted_past_changes_model=True, max_coefficient_change=delta)
    return dict(schema="m4.ml02.actual-history-controls.v1", status="PASS",
                group="A-HMA", fold=25, K=first.origin_count, rows=rows,
                fit_bill=engine.metadata, financial_executions=0,
                mutations="synthetic temporary in-memory controls, never admitted as real labels",
                note="P2 here is a fixed-grid learner/control; actual shared-calibration route remains fallback")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(save_new(args.output, run()))


if __name__ == "__main__":
    main()
