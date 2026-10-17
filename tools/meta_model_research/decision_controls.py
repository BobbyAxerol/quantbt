"""Fresh causal fits against retained decisions at registered actual vintages."""

from __future__ import annotations

from pathlib import Path
import time

import numpy as np
import pandas as pd

from quantbt.optimization.meta_selection.common import wire
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import load_corpus, pin, read, save_new
from .decision_policy import choose
from .decision_value import SCREEN, verify_inputs
from .families import FamilySpec
from .family_controls import synthetic_correction
from .learners import FamilyResearch
from .linear import LinearResearch, Policy
from .protocol import GROUPS


def require_predictions(actual, expected):
    a = {p["evaluation_id"]: p for p in actual}
    b = {p["evaluation_id"]: p for p in expected}
    if a.keys() != b.keys():
        raise ValueError("fresh future control changed pool")
    for eid in a:
        for key in ("raw_is", "yhat", "qhat", "distance"):
            x, y = a[eid][key], b[eid][key]
            if x is None or y is None:
                if x != y:
                    raise ValueError("future changed score support")
            elif not np.isclose(x, y, rtol=1e-9, atol=1e-10):
                raise ValueError("future changed predictions")
        if (
            a[eid]["eligible"] != b[eid]["eligible"]
            or a[eid]["exclusion"] != b[eid]["exclusion"]
        ):
            raise ValueError("future changed guard")


def run_controls(output):
    verify_inputs(output)
    started = time.process_time()
    source = pin(Path(__file__))
    save_new(
        output / "controls-registration.json",
        dict(
            schema="m4.ml06.controls-registration.v1",
            source=source,
            source_control=pin(Path(__file__).with_name("family_controls.py")),
            check_points="first actually fitted, fold40, fold56 per alpha",
            mutations="unavailable future/current revision correction; fresh fits; HMA40 permitted-past positive controls",
            fit_ceiling=17,
            new_financial_calls=0,
            metric_tolerances="existing MLR02 1e-9 relative/1e-10 absolute; IDs/ties exact",
            fresh_scope="X2 at 12 actual checkpoints; Ridge at HMA three checkpoints plus past control; unchanged original all-alpha Ridge checkpoint proofs reused",
            future_market_boundary="reuse original source-bound 100 actual route checkpoint cells; no market enters learner",
        ),
    )
    runtime = NumericRuntime(native_policy="require")
    linear = LinearResearch(runtime=runtime, max_fits=40)
    family = FamilyResearch(runtime=runtime, max_fits=40)
    rows = []
    for group in GROUPS:
        corpus = load_corpus(group)
        x_saved = {
            r["fold"]: r["predictions"]
            for r in read(SCREEN / f"union-{group}-predictions.json.gz")
            if r["code"] == "X2"
        }
        x_saved.update(
            {
                r["fold"]: r["predictions"]
                for r in read(output / f"{group}-x-predictions.json.gz")
            }
        )
        first = next(
            i
            for i, s in enumerate(corpus.selections)
            if s["record"]["final_selection_reason"] == "META_MODEL_PROPOSAL"
        )
        for fold in (first, 40, 56):
            task = corpus.revisions[fold].task
            original = corpus.snapshot(fold)
            future = corpus.revisions[56]
            corpus.history.append(
                synthetic_correction(
                    future,
                    corpus.schema,
                    future.revision_available_at + pd.Timedelta(days=1),
                )
            )
            current = corpus.snapshot(fold)
            if current.snapshot_id != original.snapshot_id:
                raise ValueError("late/future correction changed as-of history")
            # Cleared caches force numeric execution instead of a tautological hit.
            linear.clear_cache()
            family.clear()
            r = None
            if group == "A-HMA":
                fitted = linear.fit(
                    Policy("P0"),
                    corpus.schema,
                    current,
                    fit_completed_at=task.decision_sealed_at,
                )
                r = linear.propose(task, fitted, schema=corpus.schema)
            fx = family.fit(
                FamilySpec("X2"),
                corpus.schema,
                current,
                fit_completed_at=task.decision_sealed_at,
            )
            x = family.propose(task, fx, schema=corpus.schema)
            old = corpus.selections[fold]["record"]["proposal"]
            if r is not None:
                require_predictions(wire(r.decision.predictions), old["predictions"])
            require_predictions(wire(x.decision.predictions), x_saved[fold])
            ridge_predictions = (
                old["predictions"] if r is None else r.decision.predictions
            )
            for policy, predictions in (
                ("R", ridge_predictions),
                ("G", ridge_predictions),
                ("F", ridge_predictions),
                ("X", x.decision.predictions),
            ):
                expected = choose(
                    old["predictions"] if policy != "X" else x_saved[fold],
                    task.anchor_candidate_evaluation_id,
                    policy,
                )
                actual = choose(
                    predictions, task.anchor_candidate_evaluation_id, policy
                )
                if expected != actual:
                    raise ValueError("future changed policy/ties")
            rows.append(
                dict(
                    group=group,
                    fold=fold,
                    K=current.origin_count,
                    pool=len(task.candidates),
                    snapshot=current.snapshot_id,
                    fresh_X_fit=True,
                    fresh_R_fit=r is not None,
                    guard_ties_winners_exact=True,
                    policies=["N", "R", "X", "G", "F"],
                    future_label_invariance=True,
                )
            )
            if group == "A-HMA" and fold == 40:
                for revision in original.revisions:
                    corpus.history.append(
                        synthetic_correction(
                            revision,
                            corpus.schema,
                            task.data_cutoff - pd.Timedelta(days=1),
                        )
                    )
                changed = corpus.history.snapshot(
                    family_id=current.family_id,
                    authorized_corpora=current.authorized_corpora,
                    outcome_origins=current.outcome_origins,
                    research_exposures=current.research_exposures,
                    information_as_of=current.information_as_of,
                )
                if (
                    changed.origin_count != current.origin_count
                    or changed.snapshot_id == current.snapshot_id
                ):
                    raise ValueError("past correction failed origin replacement")
                fr = linear.fit(
                    Policy("P0"),
                    corpus.schema,
                    changed,
                    fit_completed_at=task.decision_sealed_at,
                )
                rr = linear.propose(task, fr, schema=corpus.schema)
                fxx = family.fit(
                    FamilySpec("X2"),
                    corpus.schema,
                    changed,
                    fit_completed_at=task.decision_sealed_at,
                )
                xx = family.propose(task, fxx, schema=corpus.schema)
                deltas = {
                    code: max(
                        abs(a["yhat"] - b["yhat"])
                        for a, b in zip(
                            old_a.decision.predictions, new_a.decision.predictions
                        )
                        if a["yhat"] is not None
                    )
                    for code, old_a, new_a in (("R", r, rr), ("X", x, xx))
                }
                if min(deltas.values()) <= 1e-12:
                    raise ValueError("permitted-past positive control vacuous")
                rows[-1]["past_positive_control"] = deltas
                # Later checkpoints use an independent original history, not corrected labels.
                corpus = load_corpus(group)
    if len(rows) != 12 or family.fits + linear.fit_count > 17:
        raise ValueError("bounded actual controls roster differs")
    result = dict(
        schema="m4.ml06.actual-controls.v1",
        status="PASS",
        rows=rows,
        logical_fits=family.fits + linear.fit_count,
        family_bill=dict(fits=family.fits, numeric_charge=family.regression_fit_charge),
        ridge_bill=linear.metadata,
        cpu_seconds=time.process_time() - started,
        source=source,
        new_financial_calls=0,
        new_optimizer_proposals=0,
        mutation_scope="synthetic in-memory causal controls, never economic observations",
    )
    if pin(source["path"]) != source:
        raise ValueError("control source changed")
    return save_new(output / "controls.json", result)
