"""Finite ML07 registration/sealing; never owns optimizer or financial state."""

from datetime import datetime, timezone
from pathlib import Path
import os
import resource
import time


from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import ROOT, PUBLIC, read, pin, save_new, load_corpus, verify_freeze
from .decision_value import DEFAULT as PREVIOUS, NATIVE, decision_row
from .decision_analysis import measure
from .forward_target import fit_forward
from .protocol import GROUPS
from .replay import persist_gzip


DEFAULT = ROOT / "upgrade/private/meta_model_research_v1/ml07/attempt-01"


def guard(output, started=None):
    space = os.statvfs(ROOT)
    if space.f_bavail * space.f_frsize < 5 * 1024**3 + 96 * 1024**2:
        raise RuntimeError("ML07_DISK_RESERVE")
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 > 1536:
        raise RuntimeError("ML07_RSS")
    available = next(
        int(r.split()[1]) * 1024
        for r in Path("/proc/meminfo").read_text().splitlines()
        if r.startswith("MemAvailable:")
    )
    if available < 512 * 1024**2:
        raise RuntimeError("ML07_RAM_RESERVE")
    if started is not None and time.process_time() - started > 900:
        raise RuntimeError("ML07_CPU_CAP")
    if (
        output.exists()
        and sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        > 64 * 1024**2
    ):
        raise RuntimeError("ML07_RETAINED_CAP")


def register(output=DEFAULT):
    guard(output)
    if output.exists():
        raise FileExistsError("new immutable ML07 attempt required")
    old = read(PUBLIC / "ml06_closure.json")
    if old["technical_gate"] != "PASS_ADMITTED_SCOPE":
        raise ValueError("qualified ML06 required")
    sources = [pin(p) for p in sorted(Path(__file__).parent.glob("forward_*.py"))]
    record = dict(
        schema="m4.ml07.registration.v1",
        created_at=datetime.now(timezone.utc).isoformat(),
        owner_approval="Continue research and bounded tests; no production adoption",
        baseline=verify_freeze(),
        sources=sources,
        stage_sources="Any later-arriving delegated helper is pinned before its first execution; no edits to already pinned owners",
        inputs=[
            pin(PUBLIC / "ml06_closure.json"),
            pin(PUBLIC / "ml06_summary.json"),
            pin(PREVIOUS / "sealed.json"),
            pin(PREVIOUS / "query-roster.json"),
        ],
        native=pin(next(NATIVE.rglob("*.so"))),
        guide=pin(ROOT / "upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md"),
        policies=["structural_Y_ZERO", "structural_Y_IS", "R_RETENTION12", "QD", "QF"],
        groups=list(GROUPS),
        evaluation=list(range(25, 57)),
        history="original logged union; strict asof; new query observations never train",
        ranking=dict(QD="min implied Y", QF="max Qhat", guard=-0.1, tolerance=1e-10),
        retention="latest published prior month and preceding11 consecutive original R months; all VALID published<=cutoff, meanQ>0; otherwise native; no gap compression",
        query_priority="QF then QD; chronological fold then fixed group order; exact dedup",
        max_fit_charges=300,
        max_financial_calls=32,
        max_financial_cpu_seconds=900,
        max_cold_cpu_seconds=900,
        retained_bytes=64 * 1024**2,
        scratch_bytes=32 * 1024**2,
        reserve_bytes=5 * 1024**3,
        scratch=str(output / "scratch"),
        initial_free_bytes=os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize,
        inference="descriptive reviewed conditional replay; no new intervals or promotion",
        new_optimizer_proposals=0,
        production_activation=False,
    )
    return save_new(output / "registration.json", record)


def verify(output=DEFAULT):
    reg = read(output / "registration.json")
    for ref in reg["sources"] + reg["inputs"] + [reg["native"]]:
        if pin(ref["path"]) != ref:
            raise ValueError("ML07 registered source/input changed: " + ref["path"])
    verify_freeze()
    return reg


def existing_queries():
    return [read(p) for p in sorted((PREVIOUS / "queries").glob("*.json"))]


def seal(output=DEFAULT):
    verify(output)
    from .forward_controls import structural_choice, retention_gate

    source = pin(Path(__file__).with_name("forward_controls.py"))
    save_new(output / "seal-helper-source.json", dict(source=source))
    started, wall = time.process_time(), time.perf_counter()
    rt = NumericRuntime(native_policy="require")
    if not rt.native:
        raise ValueError("qualified native Q fit required")
    rows, predictions, controls = [], [], []
    old = read(PREVIOUS / "sealed.json")
    charges = 2
    for group in GROUPS:
        corpus = load_corpus(group)
        prior = []
        for fold in range(57):
            guard(output, started)
            revision = corpus.revisions[fold]
            task = revision.task
            native = next(
                r
                for r in old["rows"]
                if r["group"] == group and r["fold"] == fold and r["policy"] == "N"
            )
            ridge = next(
                r
                for r in old["rows"]
                if r["group"] == group and r["fold"] == fold and r["policy"] == "R"
            )
            saved = (corpus.selections[fold]["record"]["proposal"] or {}).get(
                "predictions", []
            )
            for ranking in ("min_y", "max_q"):
                controls.append(
                    dict(
                        group=group,
                        fold=fold,
                        ranking=ranking,
                        **structural_choice(
                            saved, task.anchor_candidate_evaluation_id, ranking
                        ),
                    )
                )
            gate = retention_gate(
                prior,
                current_month=task.forward_start.strftime("%Y-%m"),
                cutoff=task.data_cutoff.isoformat(),
            )
            if fold >= 25:
                base = dict(ridge if gate["accepted"] else native)
                rows.append(dict(base, policy="R_RETENTION12", gate=gate))
                fitted = fit_forward(corpus.schema, corpus.snapshot(fold), task, rt)
                charges += fitted["charge"]
                if charges > 300:
                    raise RuntimeError("ML07_FIT_CAP")
                predictions.append(dict(group=group, fold=fold, **fitted))
                for policy, parent in (("QD", "R"), ("QF", "F")):
                    row = decision_row(
                        corpus,
                        fold,
                        parent,
                        fitted["predictions"],
                        fitted["status"],
                        fitted.get("model_id"),
                    )
                    rows.append(dict(row, policy=policy))
            # Only the actual original Ridge outcomes can authorize retention.
            m = measure(revision, ridge["winner"], {})
            clock = max(
                revision.revision_available_at,
                max(
                    (o.label_available_at for o in revision.outcomes),
                    default=revision.revision_available_at,
                ),
            )
            prior.append(
                dict(
                    month=task.forward_start.strftime("%Y-%m"),
                    available_at=clock.isoformat(),
                    status=m["measurement_status"],
                    Q=None if m["effect"] is None else m["effect"]["Q"],
                )
            )
        print(
            dict(group=group, sealed_rows=len(rows), numeric_charges=charges),
            flush=True,
        )
    persist_gzip(output / "predictions.json.gz", predictions)
    result = dict(
        schema="m4.ml07.sealed.v1",
        status="PASS_SEALED_BEFORE_NEW_FINANCE",
        rows=rows,
        controls=controls,
        fit_charges=charges,
        logical_primary_fits=128,
        prediction_ref=pin(output / "predictions.json.gz"),
        cpu_seconds=time.process_time() - started,
        wall_seconds=time.perf_counter() - wall,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    )
    if pin(source["path"]) != source:
        raise ValueError("ML07 helper source changed during sealing")
    return save_new(output / "sealed.json", result)


def causal_controls(output=DEFAULT):
    import pandas as pd
    from .decision_controls import require_predictions
    from .family_controls import synthetic_correction

    verify(output)
    started = time.process_time()
    rt = NumericRuntime(native_policy="require")
    sealed = read(output / "predictions.json.gz")
    rows = []
    charges = 2
    for group in GROUPS:
        corpus = load_corpus(group)
        for fold in (25, 40, 56):
            task = corpus.revisions[fold].task
            original = corpus.snapshot(fold)
            future = corpus.revisions[-1]
            corpus.history.append(
                synthetic_correction(
                    future,
                    corpus.schema,
                    future.revision_available_at + pd.Timedelta(days=1),
                )
            )
            current = corpus.snapshot(fold)
            if current.snapshot_id != original.snapshot_id:
                raise ValueError("ML07 future correction entered snapshot")
            rt.work_cache.clear()
            actual = fit_forward(corpus.schema, current, task, rt)
            old = next(r for r in sealed if r["group"] == group and r["fold"] == fold)
            require_predictions(actual["predictions"], old["predictions"])
            charges += actual["charge"]
            proof = dict(
                group=group,
                fold=fold,
                future_snapshot_exact=True,
                fresh_fit=True,
                predictions_exact=True,
            )
            if group == "A-HMA" and fold == 40:
                for r in original.revisions:
                    corpus.history.append(
                        synthetic_correction(
                            r, corpus.schema, task.data_cutoff - pd.Timedelta(days=1)
                        )
                    )
                changed = corpus.history.snapshot(
                    family_id=current.family_id,
                    authorized_corpora=current.authorized_corpora,
                    outcome_origins=current.outcome_origins,
                    research_exposures=current.research_exposures,
                    information_as_of=current.information_as_of,
                )
                rt.work_cache.clear()
                positive = fit_forward(corpus.schema, changed, task, rt)
                charges += positive["charge"]
                by = {r["evaluation_id"]: r for r in actual["predictions"]}
                difference = max(
                    abs(r["qhat"] - by[r["evaluation_id"]]["qhat"])
                    for r in positive["predictions"]
                )
                if difference <= 1e-12:
                    raise ValueError("ML07 permitted-past control vacuous")
                proof["permitted_past_prediction_delta"] = difference
                corpus = load_corpus(group)
            rows.append(proof)
    total = charges + read(output / "sealed.json")["fit_charges"]
    if total > 300:
        raise RuntimeError("ML07 controls fit cap")
    return save_new(
        output / "causal-controls.json",
        dict(
            schema="m4.ml07.causal-controls.v1",
            status="PASS",
            rows=rows,
            fit_charges=charges,
            total_fit_charges=total,
            logical_control_fits=13,
            cpu_seconds=time.process_time() - started,
            new_financial_calls=0,
        ),
    )
