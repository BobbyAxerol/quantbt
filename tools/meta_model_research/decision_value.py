"""ML-06 registration and sealed full-pool decision replay, before new finance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import resource
import time

from threadpoolctl import threadpool_info

from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import PUBLIC, ROOT, load_corpus, pin, read, save_new, verify_freeze
from .decision_policy import (
    POLICIES,
    choose,
    query_key,
    query_queue,
    zero_control,
    assert_native_reduction,
)
from .families import FamilySpec
from .learners import FamilyResearch
from .prediction_checks import validate_bound_predictions
from .protocol import GROUPS
from .replay import persist_gzip

DEFAULT = ROOT / "upgrade/private/meta_model_research_v1/ml06/attempt-01"
OLD = ROOT / "upgrade/private/meta_model_research_v1/ml02/replay-02"
SCREEN = ROOT / "upgrade/private/meta_model_research_v1/ml03/screen-01"
NATIVE = ROOT / ".maturin/mode5-m5111/goal-native-gate01/native"
PRIVATE = ROOT / "upgrade/local/mode5_upgrade_v1/m5-11-6/attempt-01"


def guard(output, cpu_start=None):
    space = os.statvfs(ROOT)
    if space.f_bavail * space.f_frsize < 5 * 1024**3 + 192 * 1024**2:
        raise RuntimeError("ML06_DISK_RESERVE_PLUS_FORECAST")
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 > 1536 * 1024**2:
        raise RuntimeError("ML06_OWNED_RSS")
    mem = next(
        int(s.split()[1]) * 1024
        for s in Path("/proc/meminfo").read_text().splitlines()
        if s.startswith("MemAvailable:")
    )
    if mem < 512 * 1024**2:
        raise RuntimeError("ML06_AVAILABLE_RAM")
    if cpu_start is not None and time.process_time() - cpu_start > 1200:
        raise RuntimeError("ML06_COLD_CPU_CAP")
    if (
        output.exists()
        and sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        > 128 * 1024**2
    ):
        raise RuntimeError("ML06_RETAINED_CAP")
    if any(t["num_threads"] != 1 for t in threadpool_info()):
        raise RuntimeError("ML06_NUMERIC_THREADS")


def register(output):
    guard(output)
    if output.exists():
        raise FileExistsError("new immutable ML06 attempt required")
    closures = [
        pin(PUBLIC / n)
        for n in (
            "ml02_closure.json",
            "ml03_closure.json",
            "ml04_closure.json",
            "ml05_closure.json",
            "ml05_zero_closure.json",
        )
    ]
    inputs = [pin(p / "result.json") for p in (OLD, SCREEN)]
    inputs += [pin(OLD / f"union-{g}-predictions.json.gz") for g in GROUPS]
    inputs += [pin(SCREEN / f"union-{g}-predictions.json.gz") for g in GROUPS]
    sources = [
        pin(p)
        for p in sorted(Path(__file__).parent.glob("*.py"))
        if not p.name.startswith("decision_")
        or p.name in ("decision_value.py", "decision_policy.py")
    ]
    sources += [
        pin(PRIVATE / n)
        for n in (
            "scheduled_binding.py",
            "wfo_provider.py",
            "transaction_control.py",
            "first_origin.py",
            "first_origin_v2.py",
            "admission.py",
            "price_guard.py",
        )
    ]
    source_alpha = [pin(p) for p in sorted((ROOT / "upgrade/alphas").rglob("*.py"))]
    record = dict(
        schema="m4.ml06.registration.v1",
        created_at=datetime.now(timezone.utc).isoformat(),
        owner_approval="Duyet va ban lam ngay: Phase M4-ML-06; bao cao chi tiet",
        baseline=verify_freeze(),
        policies=list(POLICIES),
        groups=list(GROUPS),
        previous_closures=closures,
        input_pins=inputs,
        source_pins=sources,
        protected_alphas=source_alpha,
        native=pin(next(NATIVE.rglob("*.so"))),
        guide=pin(ROOT / "upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md"),
        stage_source_policy="decision replay sources pinned here; later query/analysis/diagnostic sources pinned before their execution",
        history="qualified logged union, strict as-of, new queries evaluation-only",
        roles=dict(
            acquisition=list(range(13)),
            development=list(range(13, 25)),
            evaluation=list(range(25, 57)),
        ),
        method="original monthly730D ETHUSDT1h, original routes/metric/economics",
        query_priority="X,G,F; origin then fixed group order; deduplicated immutable query identity",
        policies_description=dict(
            N="native",
            R="ridge_v1",
            X="frozen_x2",
            G="ridge_min_y_q_floor_0",
            F="ridge_max_q_q_floor_minus_0.1",
        ),
        max_learner_fits=160,
        max_missing_queries=128,
        max_financial_calls=132,
        max_cold_cpu_seconds=1200,
        max_financial_cpu_seconds=7200,
        inference=dict(
            coordinates=16,
            draws=16384,
            seed=731,
            block_months=3,
            confidence=0.95,
            complete_months=32,
            min_days=365,
            min_origins=12,
        ),
        retained_bytes=128 * 1024**2,
        scratch_bytes=64 * 1024**2,
        reserve_bytes=5 * 1024**3,
        initial_free_bytes=os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize,
        scratch=str(output / "scratch"),
        fresh_optimization_proposals=0,
        review_status="reviewed_exploratory_conditional_logged_history",
        production_activation=False,
    )
    return save_new(output / "registration.json", record)


def verify_inputs(output):
    reg = read(output / "registration.json")
    for key in ("previous_closures", "input_pins", "source_pins", "protected_alphas"):
        for ref in reg[key]:
            if pin(ref["path"]) != ref:
                raise ValueError("registered ML06 input changed: " + ref["path"])
    if pin(reg["native"]["path"]) != reg["native"]:
        raise ValueError("native binary changed")
    verify_freeze()
    return reg


def status_of(revision, winner):
    outcome = next(
        (o.observation for o in revision.outcomes if o.evaluation_id == winner), None
    )
    return "MISSING_EXECUTION" if outcome is None else outcome.status.value


def decision_row(corpus, fold, policy, predictions, status, fitted_id=None):
    revision, saved = corpus.revisions[fold], corpus.selections[fold]
    task = revision.task
    anchor = task.anchor_candidate_evaluation_id
    selected = choose(predictions, anchor, policy)
    candidates = {c.evaluation_id: c for c in task.candidates}
    winner = selected["winner"]
    route = (
        "callback_python_original"
        if corpus.group == "A-SC"
        else "native_actual_feedback_transaction_v1"
    )
    return dict(
        group=corpus.group,
        fold=fold,
        policy=policy,
        month=task.forward_start.strftime("%Y-%m"),
        role="evaluation"
        if fold >= 25
        else "development"
        if fold >= 13
        else "acquisition",
        cutoff=task.data_cutoff.isoformat(),
        snapshot_id=corpus.snapshot(fold).snapshot_id,
        model_status=status,
        K=saved["record"]["matured_origins"],
        fit_id=fitted_id,
        anchor=anchor,
        **selected,
        changed_id=winner != anchor,
        changed_effective=digest(candidates[winner].effective_params)
        != digest(candidates[anchor].effective_params),
        params_digest=digest(candidates[winner].effective_params),
        witness_status=status_of(revision, winner),
        query_id=query_key(task, candidates[winner], route_identity=route),
        forward_start=task.forward_start.isoformat(),
        forward_end=task.forward_end.isoformat(),
        seal_clock=task.decision_sealed_at.isoformat(),
        route_identity=route,
    )


def seal(output):
    reg = verify_inputs(output)
    cpu, wall = time.process_time(), time.perf_counter()
    engine = FamilyResearch(
        runtime=NumericRuntime(native_policy="require"), max_fits=160
    )
    all_rows, inputs, zero_rows = [], [], []
    counts = dict(saved_native=0, saved_ridge=0, new_x_fits=0, source_pool_candidates=0)
    for group in GROUPS:
        guard(output, cpu)
        corpus = load_corpus(group)
        inputs += list(corpus.pins)
        group_rows, prediction_rows = [], []
        for fold in range(57):
            guard(output, cpu)
            task, saved = corpus.revisions[fold].task, corpus.selections[fold]
            record = saved["record"]
            proposed = record["proposal"]
            predictions = [] if proposed is None else proposed["predictions"]
            status = record["final_selection_reason"]
            row = decision_row(corpus, fold, "R", predictions, status)
            if row["winner"] != record["selected_evaluation_id"] or row[
                "params_digest"
            ] != digest(record["selected_params"]):
                raise ValueError("actual Ridge retention differs")
            bound = dict(
                cutoff=task.data_cutoff.isoformat(),
                label_available_at=max(
                    o.label_available_at for o in corpus.revisions[fold].outcomes
                ).isoformat(),
                revision_available_at=corpus.revisions[
                    fold
                ].revision_available_at.isoformat(),
                status=status,
                anchor=row["anchor"],
                winner=row["winner"],
            )
            validate_bound_predictions(
                bound, predictions, corpus.revisions[fold], corpus.schema
            )
            assert_native_reduction(predictions, row)
            zero_rows.append(
                dict(
                    group=group,
                    fold=fold,
                    **zero_control(
                        predictions,
                        row["anchor"],
                        {c.evaluation_id: c for c in task.candidates},
                    ),
                )
            )
            counts["saved_ridge"] += 1
            group_rows += [decision_row(corpus, fold, "N", predictions, status), row]
            counts["saved_native"] += 1
            counts["source_pool_candidates"] += len(task.candidates)
            if fold >= 25:
                group_rows += [
                    decision_row(corpus, fold, p, predictions, status)
                    for p in ("G", "F")
                ]
                fitted = engine.fit(
                    FamilySpec("X2"),
                    corpus.schema,
                    corpus.snapshot(fold),
                    fit_completed_at=task.decision_sealed_at,
                )
                artifact = engine.propose(task, fitted, schema=corpus.schema)
                x = decision_row(
                    corpus,
                    fold,
                    "X",
                    wire(artifact.decision.predictions),
                    artifact.decision.status,
                    fitted.fit_id,
                )
                if x["winner"] != artifact.decision.proposed_evaluation_id:
                    raise ValueError("X2 canonical winner differs")
                validate_bound_predictions(
                    dict(bound, status=artifact.decision.status, winner=x["winner"]),
                    wire(artifact.decision.predictions),
                    corpus.revisions[fold],
                    corpus.schema,
                )
                group_rows.append(x)
                prediction_rows.append(
                    dict(
                        group=group,
                        fold=fold,
                        policy="X",
                        fit_id=fitted.fit_id,
                        snapshot_id=fitted.snapshot_id,
                        predictions=wire(artifact.decision.predictions),
                        training=wire(fitted.training),
                    )
                )
        counts["new_x_fits"] = engine.fits
        persist_gzip(output / f"{group}-sealed-decisions.json.gz", group_rows)
        persist_gzip(output / f"{group}-x-predictions.json.gz", prediction_rows)
        all_rows += group_rows
        engine.clear()
    queue = query_queue(all_rows)
    save_new(
        output / "query-roster.json",
        dict(
            schema="m4.ml06.query-roster.v1",
            registration=pin(output / "registration.json"),
            rows=queue,
            queued=len(queue),
            admitted=queue[:128],
            not_admitted=queue[128:],
            priority=reg["query_priority"],
            all_policy_decisions_sealed=True,
        ),
    )
    result = dict(
        schema="m4.ml06.decision-seal.v1",
        status="SEALED_BEFORE_NEW_FORWARD_QUERIES",
        rows=all_rows,
        counts=counts,
        zero_controls=zero_rows,
        inputs=inputs,
        predictions=[pin(output / f"{g}-x-predictions.json.gz") for g in GROUPS],
        query_roster=pin(output / "query-roster.json"),
        new_learner_fits=engine.fits,
        regression_numeric_charge=engine.regression_fit_charge,
        cpu_seconds=time.process_time() - cpu,
        wall_seconds=time.perf_counter() - wall,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        threads=wire(threadpool_info()),
        new_financial_calls=0,
        new_optimizer_proposals=0,
    )
    verify_inputs(output)
    return save_new(output / "sealed.json", result)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("register", "seal"))
    p.add_argument("--output", type=Path, default=DEFAULT)
    a = p.parse_args()
    print(register(a.output) if a.stage == "register" else seal(a.output))


if __name__ == "__main__":
    main()
