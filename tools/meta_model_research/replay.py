"""Registered fixed-pool P0/P1/P2 replay; no optimizer or account imports."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd

from quantbt.optimization.meta_selection.common import canonical, digest, wire
from quantbt.optimization.meta_selection.history import HistorySnapshot
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import PUBLIC, ROOT, load_corpus, pin, read, save_new, verify_freeze
from .linear import LinearResearch, Policy, dumps_artifact, evaluate_revision, loads_artifact
from .protocol import GROUPS, StudyProtocol, choose_recipe
from .recovery import add_null_evidence, recover_group


def base_revision(revision):
    """A derived acquisition sensitivity; never overwrite the source revision."""
    panel = replace(revision.panel, required_members=(revision.task.anchor_candidate_evaluation_id,),
                    extra_union_members=())
    return replace(revision, panel=panel,
                   outcomes=tuple(o for o in revision.outcomes if o.evaluation_id in panel.members),
                   parent_revision_id=None, correction_reason=None)


def view(snapshot, panel):
    return snapshot if panel == "union" else replace(
        snapshot, revisions=tuple(base_revision(r) for r in snapshot.revisions))


def forward_effect(artifact, revision):
    """Known-witness economics only; a missing new winner is not zero."""
    task = revision.task
    candidates = {c.evaluation_id: c for c in task.candidates}
    outcomes = {o.evaluation_id: o.observation for o in revision.outcomes}
    a, w = task.anchor_candidate_evaluation_id, artifact.decision.proposed_evaluation_id
    observations = (candidates[a].observation, candidates[w].observation,
                    outcomes.get(a), outcomes.get(w))
    if any(o is None or o.status.value != "VALID" for o in observations):
        return dict(status="MISSING_OR_UNDEFINED_WINNER_WITNESS", R=None, Q=None, IS_effect=None,
                    winner_witness_exists=w in outcomes)
    ia, iw, oa, ow = (o.raw_sharpe for o in observations)
    R, Q, effect = (ia - oa) - (iw - ow), ow - oa, ia - iw
    if not np.isclose(R, effect + Q, atol=1e-12, rtol=1e-12):
        raise ValueError("signed R/Q decomposition failed")
    return dict(status="OBSERVED_KNOWN_WINNER", R=R, Q=Q, IS_effect=effect,
                anchor_is=ia, selected_is=iw, anchor_forward=oa, selected_forward=ow,
                winner_witness_exists=True)


def model_diagnostics(fitted, snapshot):
    model = fitted.outcome.model
    if model is None:
        return dict(status="NO_FIT", K=snapshot.origin_count, N=len(snapshot.training_rows))
    beta = np.asarray(model.coefficients)
    gram, b = np.asarray(model.reference_gram), np.asarray(model.reference_b)
    lam = model.settings.lambda_reg
    data_gram = gram - lam * np.eye(len(beta))
    y2 = sum(r.origin_weight * r.y**2 for r in snapshot.training_rows)
    sse = max(0., float(beta @ data_gram @ beta - 2 * beta @ b + y2))
    return dict(status="FIT", K=snapshot.origin_count, N=len(snapshot.training_rows), d=len(beta),
                lambda_sum=lam, alpha_mean=lam / snapshot.origin_count,
                train_origin_macro_mse=sse / snapshot.origin_count,
                effective_degrees_of_freedom=float(np.trace(np.linalg.solve(gram, data_gram))),
                beta_l2=float(np.linalg.norm(beta)), condition=model.diagnostics["condition_number"]
                if "condition_number" in model.diagnostics else None,
                relative_residual=model.diagnostics["relative_residual"],
                feature_constants=int(sum(model.scaler["constant"])),
                feature_unobserved=int(sum(not x for x in model.scaler["observed"])),
                coefficients=tuple(beta))


def assert_retained_p0(artifact, saved):
    decision = artifact.decision
    old = saved["record"]["proposal"]
    if (decision.proposed_evaluation_id != saved["record"]["selected_evaluation_id"]
            or decision.status != saved["record"]["final_selection_reason"]):
        raise ValueError("frozen P0 selected decision differs from retained V1")
    if old is not None:
        expected = {p["evaluation_id"]: p for p in old["predictions"]}
        actual = {p["evaluation_id"]: p for p in decision.predictions}
        if expected.keys() != actual.keys() or tuple(sorted(old["tie_set"])) != tuple(sorted(decision.tie_set)):
            raise ValueError("P0 full-pool prediction/tie roster differs")
        for eid, prediction in expected.items():
            for field in ("yhat", "qhat", "distance", "eligible", "exclusion"):
                a, b = actual[eid][field], prediction[field]
                if isinstance(a, float) and isinstance(b, float):
                    if not np.isclose(a, b, rtol=1e-9, atol=1e-10):
                        raise ValueError("P0 full-pool numeric prediction differs")
                elif a != b:
                    raise ValueError("P0 full-pool exclusion differs")
    return True


def persist_gzip(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(gzip.compress(canonical(value).encode(), compresslevel=6, mtime=0))
    return pin(path)


class Replay:
    def __init__(self, output, *, registration=None, reuse=None):
        self.output, self.protocol = Path(output), StudyProtocol()
        self.registration = registration or PUBLIC / "ml01_registration_v2.json"
        self.reuse = Path(reuse) if reuse else None
        self.started, self.cpu_started = time.perf_counter(), time.process_time()
        self.previous_work = read(self.reuse / "failure.json") if self.reuse else None
        self.runtime = NumericRuntime(native_policy="require")
        reserve = (self.previous_work["fits"]["regression_fit_charge"] + 2 + 400
                   if self.previous_work else 400)
        self.linear = LinearResearch(runtime=self.runtime, max_fits=4000-reserve, max_cache_entries=64)
        self.fit_seconds = self.rank_seconds = self.report_seconds = 0.
        self.restore_checks = self.saved_matches = self.reference_solves = 0

    def guard(self):
        p = self.protocol
        if (time.process_time() - self.cpu_started +
                (self.previous_work["cpu_seconds"] if self.previous_work else 0)) > p.max_cpu_seconds:
            raise ValueError("registered CPU ceiling reached")
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 > p.max_rss_bytes:
            raise ValueError("registered RSS ceiling reached")
        free = os.statvfs(ROOT)
        if free.f_bavail * free.f_frsize < p.min_disk_free_bytes:
            raise ValueError("disk reserve reached")
        available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))
        if available < p.min_available_ram_bytes:
            raise ValueError("available RAM floor reached")
        if sum(f.stat().st_size for f in self.output.rglob("*") if f.is_file()) > p.max_incremental_bytes:
            raise ValueError("retained byte ceiling reached")

    def execute(self, corpus, fold, policy, panel, *, retain_restore=False, measure=True,
                artifact_stage="outer"):
        self.guard()
        revision, saved = corpus.revisions[fold], corpus.selections[fold]
        snapshot = view(corpus.snapshot(fold), panel)
        task = revision.task
        tick = time.perf_counter()
        fitted = self.linear.fit(policy, corpus.schema, snapshot,
                                 fit_completed_at=task.decision_sealed_at)
        self.fit_seconds += time.perf_counter() - tick
        tick = time.perf_counter()
        artifact = self.linear.propose(task, fitted, schema=corpus.schema)
        self.rank_seconds += time.perf_counter() - tick
        tick = time.perf_counter()
        if panel == "union" and policy.name == "P0":
            assert_retained_p0(artifact, saved)
            self.saved_matches += 1
        metrics = (evaluate_revision(artifact, revision,
                   available_as_of=revision.revision_available_at + pd.Timedelta(nanoseconds=1),
                   panel=panel) if measure else None)
        row = dict(group=corpus.group, fold=fold, panel=panel, policy=policy.name,
                   alpha=policy.alpha, cutoff=task.data_cutoff.isoformat(),
                   label_available_at=max(o.label_available_at for o in revision.outcomes).isoformat(),
                   revision_available_at=revision.revision_available_at.isoformat(),
                   snapshot_id=snapshot.snapshot_id, research_fit_id=fitted.fit_id,
                   artifact_id=artifact.artifact_id,
                   winner=artifact.decision.proposed_evaluation_id,
                   anchor=task.anchor_candidate_evaluation_id,
                   status=artifact.decision.status, K=fitted.origin_count,
                   loss=metrics.metrics["y_mse"] if metrics else None,
                   served_metrics=wire(metrics.metrics) if metrics else {},
                   metric_status=metrics.status if metrics else "PILOT_NO_OUTCOME_READ",
                   metric_null_reasons=wire(metrics.null_reasons) if metrics else {},
                   label_statuses=wire(metrics.label_statuses) if metrics else {},
                   known_rows=metrics.known_rows if metrics else None,
                   scored_rows=metrics.scored_rows if metrics else None,
                   economics=forward_effect(artifact, revision) if measure else None,
                   training=model_diagnostics(fitted, snapshot))
        if retain_restore:
            text = dumps_artifact(artifact)
            restored = loads_artifact(text, expected_artifact_id=artifact.artifact_id,
                                      available_as_of=artifact.decision.ready_at,
                                      task=task, schema=corpus.schema)
            assert restored.artifact_id == artifact.artifact_id
            persist_gzip(self.output / "portable" / artifact_stage /
                         f"{corpus.group}-{fold:02d}-{panel}-{policy.name}.json.gz",
                         json.loads(text))
            self.restore_checks += 1
        self.report_seconds += time.perf_counter() - tick
        return row, artifact

    def run(self):
        registration = read(self.registration)
        if registration["protocol_id"] != self.protocol.protocol_id:
            raise ValueError("protocol changed after preregistration")
        for source in registration["source_pins"]:
            if pin(source["path"]) != source:
                raise ValueError("sealed admission/protocol code changed")
        for source in registration.get("reuse_pins", ()):
            if pin(source["path"]) != source:
                raise ValueError("retained partial replay input changed")
        if self.reuse is not None and registration.get("reuse_root") != str(self.reuse.resolve()):
            raise ValueError("unregistered recovery root")
        verify_freeze()
        self.output.mkdir(parents=True, exist_ok=False)
        save_new(self.output / "start.json", dict(created_at=datetime.now(timezone.utc).isoformat(),
                  registration=pin(self.registration),
                  sources=[pin(Path(__file__)), pin(Path(__file__).with_name("linear.py"))],
                  protocol_id=self.protocol.protocol_id, real_data_outcomes_opened=False))
        corpora = {g: load_corpus(g) for g in GROUPS}
        cutoff = min(c.revisions[25].task.data_cutoff for c in corpora.values())
        pilot, pilot_tick = [], time.perf_counter()
        if self.reuse:
            previous_pilot = read(self.reuse / "pilot.json")
            pilot = previous_pilot["rows"]
        else:
            for group, corpus in corpora.items():
                first = next(i for i in range(57) if corpus.snapshot(i).origin_count >= 12)
                for fold in (first, 40, 56):
                    tick = time.perf_counter()
                    row, _ = self.execute(corpus, fold, Policy("P0"), "union", retain_restore=True,
                                          measure=False, artifact_stage="pilot")
                    pilot.append(dict(group=group, fold=fold, K=row["K"],
                                      wall_seconds=time.perf_counter()-tick))
        forecast = pilot_gate(pilot, self.protocol,
            elapsed_cpu=time.process_time()-self.cpu_started +
                        (self.previous_work["cpu_seconds"] if self.previous_work else 0))
        save_new(self.output / "pilot.json", dict(rows=pilot, new_fits=0 if self.reuse else 12,
                  reused_from=pin(self.reuse / "pilot.json") if self.reuse else None,
                  wall_seconds=time.perf_counter()-pilot_tick, forecast=forecast,
                  peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
        all_rows, recipes = [], {}
        for panel in ("base", "union"):
            if self.reuse:
                development = [add_null_evidence(row,
                    corpora[row["group"]].revisions[row["fold"]], panel)
                    for row in read(self.reuse / f"{panel}-development.json.gz")]
                for row in development:
                    if row["cutoff"] != corpora[row["group"]].revisions[row["fold"]].task.data_cutoff.isoformat():
                        raise ValueError("recovered inner chronological identity changed")
            else:
                development = []
                for group, corpus in corpora.items():
                    for fold in self.protocol.development_folds:
                        revision = corpus.revisions[fold]
                        if revision.revision_available_at >= cutoff:
                            continue
                        for alpha in self.protocol.grid:
                            row, _ = self.execute(corpus, fold, Policy("P2", alpha), panel)
                            development.append(row)
            panel_recipes = {g: choose_recipe(development, g, cutoff) for g in GROUPS}
            recipes[panel] = panel_recipes
            # Seal calibration before reading any new outer winner outcome.
            persist_gzip(self.output / f"{panel}-development.json.gz", development)
            save_new(self.output / f"{panel}-recipes.json", stringify_keys(panel_recipes))
            for group, corpus in corpora.items():
                existing = self.reuse / f"{panel}-{group}-rows.json.gz" if self.reuse else None
                if existing is not None and existing.exists():
                    group_rows, predictions = recover_group(read(existing),
                        read(self.reuse / f"{panel}-{group}-predictions.json.gz"),
                        corpus, panel, panel_recipes[group])
                    persist_gzip(self.output / f"{panel}-{group}-rows.json.gz", group_rows)
                    persist_gzip(self.output / f"{panel}-{group}-predictions.json.gz", predictions)
                    all_rows.extend(group_rows)
                    print(panel, group, "recovered57", flush=True)
                    continue
                group_rows, predictions = [], []
                for fold in range(57):
                    recipe = panel_recipes[group]
                    policies = [("P0", Policy("P0")), ("P1", Policy("P1"))]
                    if fold in self.protocol.evaluation_folds:
                        policies.append(("P2", Policy("P2", recipe["alpha"])
                                         if recipe["policy"] == "P2" else Policy("P0")))
                    for name, policy in policies:
                        row, artifact = self.execute(corpus, fold, policy, panel,
                            retain_restore=fold in (0, 25, 56) and name != "P2")
                        row["policy"] = name
                        row["resolved_policy"] = policy.name
                        row["recipe_reason"] = recipe["reason"] if name == "P2" else "FIXED"
                        group_rows.append(row)
                        predictions.append(dict(fold=fold, policy=name, fit_id=row["research_fit_id"],
                                                predictions=wire(artifact.decision.predictions)))
                    persist_gzip(self.output / "fold-checkpoints" / f"{panel}-{group}-{fold:02d}.json.gz",
                                 dict(rows=[r for r in group_rows if r["fold"] == fold],
                                      predictions=[r for r in predictions if r["fold"] == fold]))
                    print(panel, group, fold, "fits", self.linear.fit_count, flush=True)
                persist_gzip(self.output / f"{panel}-{group}-rows.json.gz", group_rows)
                persist_gzip(self.output / f"{panel}-{group}-predictions.json.gz", predictions)
                all_rows.extend(group_rows)
                self.linear.clear_cache()
        result = dict(schema="m4.ml02.fixed-pool-replay.v1", status="REPLAY_COMPLETE_ANALYSIS_PENDING",
                      created_at=datetime.now(timezone.utc).isoformat(), registration=registration["protocol_id"],
                      rows=all_rows, recipes=stringify_keys(recipes), saved_p0_matches=self.saved_matches,
                      portable_restore_checks=self.restore_checks,
                      previous_failed_work=self.previous_work,
                      recovery_scope="completed model-replay groups, not full-WFO recovery",
                      logical_fit_ledger=self.linear.metadata, native=wire(self.runtime.metadata),
                      wall_seconds=time.perf_counter()-self.started,
                      cpu_seconds=time.process_time()-self.cpu_started,
                      fit_seconds=self.fit_seconds, rank_seconds=self.rank_seconds,
                      report_seconds=self.report_seconds,
                      peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                      new_optimizer_proposals=0, new_financial_calls=0)
        return save_new(self.output / "result.json", result)


def stringify_keys(value):
    if isinstance(value, dict):
        return {str(k): stringify_keys(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [stringify_keys(v) for v in value]
    return value


def pilot_gate(rows, protocol, *, elapsed_cpu):
    if len(rows) != 12 or {r["group"] for r in rows} != set(GROUPS):
        raise ValueError("twelve registered representative pilot cells required")
    times = [r["wall_seconds"] for r in rows]
    projected = max(times) * 2248
    if (not all(np.isfinite(t) and t > 0 for t in times) or
            projected + elapsed_cpu > protocol.max_cpu_seconds):
        raise ValueError("pilot forecast exceeds remaining registered CPU budget")
    retained_forecast, rss_forecast = 32*1024**2, 768*1024**2
    if retained_forecast > protocol.max_incremental_bytes or rss_forecast > protocol.max_rss_bytes:
        raise ValueError("pilot memory/storage forecast exceeds registered budget")
    return dict(status="ADMITTED", median_cell_seconds=float(np.median(times)),
                worst_cell_seconds=max(times), conservative_remaining_seconds=projected,
                elapsed_cpu_seconds=elapsed_cpu, max_cpu_seconds=protocol.max_cpu_seconds,
                retained_forecast_bytes=retained_forecast, rss_forecast_bytes=rss_forecast,
                remark="conservative cold-host bound, not ETA; runtime/disk/RAM guards stay active")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--reuse", type=Path)
    args = parser.parse_args()
    runner = Replay(args.output, registration=args.registration, reuse=args.reuse)
    try:
        print(runner.run())
    except Exception as exc:
        if args.output.exists():
            save_new(args.output / "failure.json", dict(status="FAIL_RETAINED", error=repr(exc),
                     fits=runner.linear.metadata, cpu_seconds=time.process_time()-runner.cpu_started))
        raise


if __name__ == "__main__":
    main()
