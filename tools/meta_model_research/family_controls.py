"""Actual mature-history family controls, never a new economic observation."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_info

from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import PUBLIC, load_corpus, pin, read, save_new, verify_freeze
from .families import FamilySpec
from .family_protocol import ROSTER
from .learners import FamilyResearch
from .prediction_checks import validate_bound_predictions
from .screening import guard


def synthetic_correction(revision, schema, available):
    """Coherent positive control: +3 * native parameter distance in FWD Sharpe.

    Anchor is unchanged. These deliberately fabricated labels only test causal
    data access and non-vacuous model sensitivity; never economic efficacy.
    """
    task = revision.task
    geometry = schema.parameter_geometry(task.candidates)
    ai = next(i for i, c in enumerate(task.candidates)
              if c.evaluation_id == task.anchor_candidate_evaluation_id)
    distances = {c.evaluation_id: float(v) for c, v in zip(
        task.candidates, np.linalg.norm(geometry - geometry[ai], axis=1))}
    outcomes = tuple(
        replace(o, observation=replace(o.observation,
            raw_sharpe=o.observation.raw_sharpe + 3 * distances[o.evaluation_id]))
        if o.observation.status.value == "VALID" else o for o in revision.outcomes
    )
    return replace(revision, outcomes=outcomes, revision_available_at=available,
                   parent_revision_id=revision.revision_id,
                   correction_reason="SYNTHETIC_CAUSAL_CONTROL_NOT_ECONOMIC_LABEL",
                   verification="reviewed_import")


def require_same_decision(first, other):
    if (first.fit.fit_id != other.fit.fit_id
            or first.decision.predictions != other.decision.predictions
            or first.decision.tie_set != other.decision.tie_set
            or first.decision.proposed_evaluation_id != other.decision.proposed_evaluation_id
            or first.decision.guard != other.decision.guard):
        raise ValueError("future information changed earlier actual family decision")


def run(output):
    start, cpu = time.perf_counter(), time.process_time()
    closure = read(PUBLIC / "ml03_closure.json")
    if closure["technical_gate"] != "PASS" or not closure["no_nominees"]:
        raise ValueError("this bounded control requires the closed no-nominee screen")
    registration = dict(
        schema="m4.ml04.control-registration.v1",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        previous_gate=pin(PUBLIC / "ml03_closure.json"), baseline=verify_freeze(),
        group="A-HMA", fold=25, roster=list(ROSTER), panels=["union"],
        source_pins=[pin(Path(__file__)), pin(Path(__file__).with_name("learners.py")),
                     pin(Path(__file__).with_name("families.py"))],
        future_control="revision56 correction +1 day; fresh models at earlier cutoff",
        past_control="replace every allowed historical revision; +3 * parameter distance in FWD Sharpe; anchor unchanged; correction available cutoff-1day",
        no_new_economic_labels=True, max_logical_fits=15,
        fixed_adaptive_economics="N/A_NO_SUPPORTED_NOMINEE", targeted_query_budget_used=0,
        cost=dict(max_cpu_seconds=7200, max_owned_rss_bytes=1610612736,
                  incremental_bytes=268435456, disk_reserve_bytes=5368709120),
    )
    registration_ref = save_new(output / "registration.json", registration)
    corpus = load_corpus("A-HMA")
    revision, schema = corpus.revisions[25], corpus.schema
    task = revision.task
    saved = corpus.selections[25]["snapshot"]

    def snapshot():
        return corpus.history.snapshot(
            family_id=saved["family_id"], authorized_corpora=saved["authorized_corpora"],
            outcome_origins=saved["outcome_origins"],
            research_exposures=saved["research_exposures"],
            information_as_of=saved["information_as_of"])

    def fit_all(history):
        engine = FamilyResearch(runtime=NumericRuntime(native_policy="require"), max_fits=64)
        artifacts = {}
        for code in ROSTER:
            guard(output, cpu)
            fitted = engine.fit(FamilySpec(code), schema, history,
                                fit_completed_at=task.decision_sealed_at)
            if fitted.model is None:
                raise ValueError("actual control must exercise a mature fit")
            artifacts[code] = engine.propose(task, fitted, schema=schema, full_ranking=True)
            shadow = engine.propose(task, fitted, schema=schema, mode="shadow", full_ranking=True)
            decision = artifacts[code].decision
            if (shadow.decision.predictions != decision.predictions
                    or shadow.decision.proposed_evaluation_id != decision.proposed_evaluation_id
                    or shadow.decision.actual_evaluation_id != task.anchor_candidate_evaluation_id):
                raise ValueError("shadow proposal changed scores or applied native anchor")
            row = dict(cutoff=task.data_cutoff,
                       label_available_at=max(o.label_available_at for o in revision.outcomes),
                       revision_available_at=revision.revision_available_at,
                       status=decision.status, anchor=decision.anchor_evaluation_id,
                       winner=decision.proposed_evaluation_id, tie_set=decision.tie_set)
            validate_bound_predictions(row, decision.predictions, revision, schema)
        return artifacts, dict(fits=engine.fits, regression_fit_charge=engine.regression_fit_charge,
                               external_runtime_qualification_fits=2)

    first = snapshot()
    base, base_bill = fit_all(first)
    future = corpus.revisions[56]
    corpus.history.append(synthetic_correction(future, schema,
                          future.revision_available_at + pd.Timedelta(days=1)))
    second = snapshot()
    if first.snapshot_id != second.snapshot_id:
        raise ValueError("unavailable correction changed earlier snapshot")
    repeated, future_bill = fit_all(second)
    for code in ROSTER:
        require_same_decision(base[code], repeated[code])
    for past in first.revisions:
        corpus.history.append(synthetic_correction(past, schema,
                              task.data_cutoff - pd.Timedelta(days=1)))
    third = snapshot()
    if third.origin_count != first.origin_count or third.snapshot_id == first.snapshot_id:
        raise ValueError("past corrections must replace origins without inflating support")
    changed, past_bill = fit_all(third)
    rows = []
    for code in ROSTER:
        a, b = base[code], changed[code]
        if a.fit.model.model_id == b.fit.model.model_id:
            raise ValueError("permitted-past model positive control is vacuous")
        old = {p["evaluation_id"]: p["yhat"] for p in a.decision.predictions if p["yhat"] is not None}
        new = {p["evaluation_id"]: p["yhat"] for p in b.decision.predictions if p["yhat"] is not None}
        delta = max(abs(old[k] - new[k]) for k in old)
        if delta <= 1e-10:
            raise ValueError("permitted-past served prediction positive control is vacuous")
        rows.append(dict(code=code, future_fresh_fit_exact=True,
                         full_pool_predictions=len(a.decision.predictions),
                         K=first.origin_count, model_id=a.fit.model.model_id,
                         snapshot_id=first.snapshot_id, artifact_id=a.artifact_id,
                         permitted_past_max_prediction_delta=delta,
                         past_origin_count_unchanged=True, shadow_contract=True))
    if pin(Path(__file__)) != registration["source_pins"][0]:
        raise ValueError("control source changed during execution")
    return dict(schema="m4.ml04.actual-family-controls.v1", status="PASS",
                registration=registration_ref, baseline=verify_freeze(), rows=rows,
                fit_bill=[base_bill, future_bill, past_bill],
                cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-start,
                peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                threadpools=wire(threadpool_info()), new_financial_calls=0,
                new_optimizer_proposals=0, new_economic_labels=0,
                fixed_adaptive_economics="N/A_NO_SUPPORTED_NOMINEE",
                shadow_scope="score/application metadata only, not a new account execution",
                future_market_scope="existing unchanged strategy/engine proofs; no new financial market-mutation execution",
                mutation_recipe_id=digest(registration["past_control"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    print(save_new(output / "actual-controls.json", run(output)))


if __name__ == "__main__":
    main()
