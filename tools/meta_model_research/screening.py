"""Finite development screening. Never opens an optimizer or financial engine."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_info

from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import PUBLIC, ROOT, load_corpus, pin, read, save_new, verify_freeze
from .families import FamilyFitError, FamilySpec, _xgboost
from .family_protocol import FamilyProtocol, ROSTER, common_nominees
from .learners import FamilyResearch, dumps_family_artifact, loads_family_artifact
from .linear import evaluate_revision
from .protocol import GROUPS, StudyProtocol
from .replay import forward_effect, persist_gzip, view


def pilot_forecast(rows, *, elapsed_cpu):
    if (
        len(rows) != 12
        or {r["group"] for r in rows} != set(GROUPS)
        or any(
            {r["code"] for r in rows if r["group"] == g} != {"B1", "H135", "X3"}
            for g in GROUPS
        )
        or any(
            r["K"] < 12 or not np.isfinite(r["wall_seconds"]) or r["wall_seconds"] <= 0
            for r in rows
        )
    ):
        raise ValueError("twelve registered family pilot cells required")
    times = [r["wall_seconds"] for r in rows]
    bound = max(times) * 480
    if bound + elapsed_cpu > FamilyProtocol().max_cpu_seconds:
        raise RuntimeError("ML03_PILOT_REMAINING_CPU_NOT_ADMITTED")
    return dict(
        rows=rows,
        median_seconds=float(np.median(times)),
        worst_seconds=max(times),
        remaining_upper_seconds=bound,
        status="ADMITTED",
        elapsed_cpu_seconds=elapsed_cpu,
    )


def guard(output, cpu_start):
    if time.process_time() - cpu_start > FamilyProtocol().max_cpu_seconds:
        raise RuntimeError("ML03_CPU_CEILING")
    if (
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        > StudyProtocol().max_rss_bytes
    ):
        raise RuntimeError("ML03_RSS_CEILING")
    space = os.statvfs(ROOT)
    if space.f_bavail * space.f_frsize < 5 * 1024**3:
        raise RuntimeError("ML03_DISK_RESERVE")
    available = next(
        int(s.split()[1]) * 1024
        for s in Path("/proc/meminfo").read_text().splitlines()
        if s.startswith("MemAvailable:")
    )
    if available < 512 * 1024**2:
        raise RuntimeError("ML03_AVAILABLE_RAM_FLOOR")
    if sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) > 128 * 1024**2:
        raise RuntimeError("ML03_RETAINED_BUDGET")
    if any(x["num_threads"] != 1 for x in threadpool_info()):
        raise RuntimeError("ML03_NUMERIC_THREADS_NOT_ONE")


def registration(output):
    approval = read(PUBLIC / "ml03_owner_approval.json")
    if (
        approval["finite_roster"] != "APPROVED"
        or approval["optional_private_cpu_wheel"] != "APPROVED"
    ):
        raise ValueError("owner-approved roster and dependency required")
    module = _xgboost()
    dependency = read(PUBLIC / "ml03_dependency_admission.json")
    if dependency["status"] != "PASS_CPU_WHEEL_SYNTHETIC_QUALIFICATION":
        raise ValueError("exact optional dependency qualification required")
    source_names = (
        "admission.py",
        "protocol.py",
        "linear.py",
        "family_protocol.py",
        "families.py",
        "learners.py",
        "screening.py",
        "replay.py",
    )
    sources = [pin(Path(__file__).with_name(name)) for name in source_names]
    payload = dict(
        schema="m4.ml03.finite-screen-registration.v1",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        source_pins=sources,
        baseline=verify_freeze(),
        family_protocol=asdict(FamilyProtocol()),
        family_protocol_id=FamilyProtocol().protocol_id,
        history_protocol_id=StudyProtocol().protocol_id,
        owner_approval=pin(PUBLIC / "ml03_owner_approval.json"),
        dependency=pin(PUBLIC / "ml03_dependency_admission.json"),
        comparator=pin(PUBLIC / "ml02_results.json"),
        prior_closure=pin(PUBLIC / "ml02_closure.json"),
        output=str(output.resolve()),
        calibration_frontier="2024-01-31T23:00:00+00:00",
        development_folds=list(range(13, 25)),
        panels=["base", "union"],
        roster=list(ROSTER),
        acquisition_and_evaluation_reused_but_not_rescored=True,
        pilot="four groups x (B1 first-mature, H135 fold40, X3 fold56); cost/train only, no current forward outcomes",
        model_nomination="held-group-out complete-block shared roster; no support -> zero nominees and KEEP_V1",
        acceptance="unchanged >=2% gain/family95% loss-Q-R rules; no economic promotion from development loss",
        new_optimizer_proposals=0,
        new_financial_calls=0,
        review_status="reviewed_exploratory_not_independent_OOS",
        xgboost_version=module.__version__,
        new_outcomes_opened=False,
    )
    save_new(output / "registration.json", payload)
    return payload


class Screen:
    def __init__(self, output):
        self.output = Path(output)
        self.started, self.cpu_started = time.perf_counter(), time.process_time()
        self.engine = FamilyResearch(runtime=NumericRuntime(native_policy="require"))
        self.rows, self.failed, self.restore_checks = [], [], 0
        self.fit_seconds = self.rank_seconds = self.report_seconds = 0.0

    def execute(
        self, corpus, fold, code, panel, *, measure, portable=False, stage="development"
    ):
        guard(self.output, self.cpu_started)
        snapshot = view(corpus.snapshot(fold), panel)
        revision, task = corpus.revisions[fold], corpus.revisions[fold].task
        tick = time.perf_counter()
        fitted = self.engine.fit(
            FamilySpec(code),
            corpus.schema,
            snapshot,
            fit_completed_at=task.decision_sealed_at,
        )
        self.fit_seconds += time.perf_counter() - tick
        tick = time.perf_counter()
        artifact = self.engine.propose(task, fitted, schema=corpus.schema)
        self.rank_seconds += time.perf_counter() - tick
        tick = time.perf_counter()
        metrics = (
            evaluate_revision(
                artifact,
                revision,
                panel=panel,
                available_as_of=revision.revision_available_at
                + pd.Timedelta(nanoseconds=1),
            )
            if measure
            else None
        )
        row = dict(
            group=corpus.group,
            fold=fold,
            code=code,
            panel=panel,
            K=fitted.K,
            cutoff=task.data_cutoff.isoformat(),
            snapshot_id=fitted.snapshot_id,
            fit_id=fitted.fit_id,
            artifact_id=artifact.artifact_id,
            winner=artifact.decision.proposed_evaluation_id,
            anchor=task.anchor_candidate_evaluation_id,
            status=artifact.decision.status,
            label_available_at=max(
                o.label_available_at for o in revision.outcomes
            ).isoformat(),
            revision_available_at=revision.revision_available_at.isoformat(),
            loss=metrics.metrics["y_mse"] if metrics else None,
            served_metrics=wire(metrics.metrics) if metrics else {},
            null_reasons=wire(metrics.null_reasons) if metrics else {},
            scored_rows=metrics.scored_rows if metrics else None,
            label_statuses=wire(metrics.label_statuses) if metrics else {},
            training=wire(fitted.training),
            economics=forward_effect(artifact, revision) if measure else None,
            proposed_params_digest=digest(artifact.decision.proposed_params),
        )
        if portable:
            text = dumps_family_artifact(artifact)
            other = loads_family_artifact(
                text,
                expected_artifact_id=artifact.artifact_id,
                task=task,
                schema=corpus.schema,
            )
            if other.artifact_id != artifact.artifact_id:
                raise ValueError("fresh restore identity mismatch")
            persist_gzip(
                self.output
                / "portable"
                / stage
                / f"{panel}-{corpus.group}-{fold:02d}-{code}.json.gz",
                json.loads(text),
            )
            self.restore_checks += 1
        self.report_seconds += time.perf_counter() - tick
        return row, wire(artifact.decision.predictions)

    def run(self):
        self.output.mkdir(parents=True, exist_ok=False)
        guard(self.output, self.cpu_started)
        reg = registration(self.output)
        corpora = {g: load_corpus(g) for g in GROUPS}
        pilot = []
        for group, corpus in corpora.items():
            first = next(i for i in range(57) if corpus.snapshot(i).origin_count >= 12)
            for code, fold in (("B1", first), ("H135", 40), ("X3", 56)):
                tick = time.perf_counter()
                row, _ = self.execute(
                    corpus,
                    fold,
                    code,
                    "union",
                    measure=False,
                    portable=True,
                    stage="pilot",
                )
                pilot.append(
                    dict(
                        group=group,
                        code=code,
                        fold=fold,
                        K=row["K"],
                        wall_seconds=time.perf_counter() - tick,
                    )
                )
        save_new(
            self.output / "pilot.json",
            pilot_forecast(pilot, elapsed_cpu=time.process_time() - self.cpu_started),
        )
        self.engine.clear()
        for panel in ("base", "union"):
            for group, corpus in corpora.items():
                rows, scores = [], []
                for fold in range(13, 25):
                    for code in ROSTER:
                        try:
                            row, predictions = self.execute(
                                corpus,
                                fold,
                                code,
                                panel,
                                measure=True,
                                portable=fold in (13, 24),
                            )
                        except FamilyFitError as exc:
                            revision = corpus.revisions[fold]
                            row = dict(
                                group=group,
                                fold=fold,
                                code=code,
                                panel=panel,
                                status="FIT_FAILED_RETAINED",
                                loss=None,
                                diagnostic=wire(exc.metadata),
                                label_available_at=max(
                                    o.label_available_at for o in revision.outcomes
                                ).isoformat(),
                                revision_available_at=revision.revision_available_at.isoformat(),
                            )
                            self.failed.append(row)
                            predictions = []
                        rows.append(row)
                        scores.append(
                            dict(fold=fold, code=code, predictions=predictions)
                        )
                    persist_gzip(
                        self.output
                        / "checkpoints"
                        / f"{panel}-{group}-{fold:02d}.json.gz",
                        dict(
                            rows=[r for r in rows if r["fold"] == fold],
                            predictions=[p for p in scores if p["fold"] == fold],
                        ),
                    )
                    print(
                        panel,
                        group,
                        fold,
                        "logicalfits",
                        self.engine.fits,
                        "bill",
                        self.engine.regression_fit_charge,
                        flush=True,
                    )
                persist_gzip(self.output / f"{panel}-{group}-rows.json.gz", rows)
                persist_gzip(
                    self.output / f"{panel}-{group}-predictions.json.gz", scores
                )
                self.rows.extend(rows)
                self.engine.clear()
        for ref in reg["source_pins"]:
            if pin(ref["path"]) != ref:
                raise ValueError("screen source changed while running")
        nominees = {
            panel: {
                g: common_nominees(
                    [r for r in self.rows if r["panel"] == panel],
                    g,
                    reg["calibration_frontier"],
                )
                for g in GROUPS
            }
            for panel in ("base", "union")
        }
        result = dict(
            schema="m4.ml03.finite-screen.v1",
            status="SCREEN_COMPLETE_ANALYSIS_PENDING",
            registration=pin(self.output / "registration.json"),
            rows=self.rows,
            nominees=nominees,
            fits=self.engine.fits,
            failed_fits=self.engine.failed_fits,
            regression_fit_charge=self.engine.regression_fit_charge,
            cache_hits=self.engine.cache_hits,
            failed_recipe_rows=self.failed,
            portable_restore_checks=self.restore_checks,
            wall_seconds=time.perf_counter() - self.started,
            cpu_seconds=time.process_time() - self.cpu_started,
            fit_seconds=self.fit_seconds,
            rank_seconds=self.rank_seconds,
            report_seconds=self.report_seconds,
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            threads=threadpool_info(),
            native=wire(self.engine.runtime.metadata),
            new_optimizer_proposals=0,
            new_financial_calls=0,
        )
        return save_new(self.output / "result.json", result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runner = Screen(args.output)
    try:
        print(runner.run())
    except BaseException as exc:
        if args.output.exists():
            save_new(
                args.output / "failure.json",
                dict(
                    status="FAIL_RETAINED",
                    error=repr(exc),
                    fits=runner.engine.fits,
                    regression_fit_charge=runner.engine.regression_fit_charge,
                    cpu_seconds=time.process_time() - runner.cpu_started,
                ),
            )
        raise


if __name__ == "__main__":
    main()
