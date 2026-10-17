"""Cold source/decision certificate and targeted post-screen cache compatibility."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import subprocess
import time

import numpy as np

from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import ROOT, load_corpus, pin, read, save_new, verify_freeze
from .families import FamilySpec
from .family_protocol import ROSTER, common_nominees
from .learners import FamilyResearch, loads_family_artifact
from .protocol import GROUPS
from .prediction_checks import validate_bound_predictions
from .replay import view


def certificate(output):
    started = time.process_time()
    result = read(output / "result.json")
    registration = read(output / "registration.json")
    if result["registration"] != pin(output / "registration.json"):
        raise ValueError("screen registration changed")
    source_changes = []
    for ref in registration["source_pins"]:
        if pin(ref["path"]) != ref:
            relative = str(Path(ref["path"]).relative_to(ROOT))
            if relative != "tools/meta_model_research/learners.py":
                raise ValueError("unqualified screen source change")
            archived = subprocess.check_output(
                ["git", "show", f"acf3bf0:{relative}"], cwd=ROOT
            )
            if sha256(archived).hexdigest() != ref["sha256"]:
                raise ValueError("historical screen source no longer archived")
            source_changes.append(
                dict(
                    before=ref,
                    after=pin(ref["path"]),
                    role="numeric-limit cache identity/preparation invalidation only; qualified below",
                )
            )
    required = {
        (p, g, f, c)
        for p in ("base", "union")
        for g in GROUPS
        for f in range(13, 25)
        for c in ROSTER
    }
    keys = [(r["panel"], r["group"], r["fold"], r["code"]) for r in result["rows"]]
    if len(keys) != len(set(keys)) or set(keys) != required:
        raise ValueError(
            "screen must contain all 480 cells, including undefined outcomes"
        )
    corpora = {g: load_corpus(g) for g in GROUPS}
    prediction_checks = 0
    for panel in ("base", "union"):
        for group, corpus in corpora.items():
            records = read(output / f"{panel}-{group}-predictions.json.gz")
            scores = {
                (r["fold"], r["code"]): r["predictions"]
                for r in records
            }
            required_scores = {(f, c) for f in range(13, 25) for c in ROSTER}
            if len(records) != len(scores) or set(scores) != required_scores:
                raise ValueError("saved prediction cells duplicated or missing")
            rows = [
                r for r in result["rows"] if r["panel"] == panel and r["group"] == group
            ]
            for row in rows:
                if row["status"] == "FIT_FAILED_RETAINED":
                    continue
                revision = corpus.revisions[row["fold"]]
                task = revision.task
                snapshot = view(corpus.snapshot(row["fold"]), panel)
                if (
                    row["snapshot_id"] != snapshot.snapshot_id
                    or row["K"] != snapshot.origin_count
                    or row["cutoff"] != task.data_cutoff.isoformat()
                    or row["anchor"] != task.anchor_candidate_evaluation_id
                ):
                    raise ValueError("fit/current pool information rights mismatch")
                candidates = {c.evaluation_id: c for c in task.candidates}
                if row["proposed_params_digest"] != digest(
                    candidates[row["winner"]].effective_params
                ):
                    raise ValueError("selected effective parameter dictionary mismatch")
                predictions = scores[row["fold"], row["code"]]
                if row["status"] == "META_MODEL_PROPOSAL":
                    if {p["evaluation_id"] for p in predictions} != set(candidates):
                        raise ValueError("whole-pool prediction roster differs")
                    valid = [p for p in predictions if p["yhat"] is not None]
                    anchor = next(
                        p for p in valid if p["evaluation_id"] == row["anchor"]
                    )
                    if (anchor["yhat"], anchor["qhat"], anchor["distance"]) != (
                        0.0,
                        0.0,
                        0.0,
                    ):
                        raise ValueError("served anchor not exactly zero")
                    for p in valid:
                        if not np.isclose(
                            p["qhat"],
                            p["raw_is"] - anchor["raw_is"] - p["yhat"],
                            rtol=1e-12,
                            atol=1e-12,
                        ) or p["eligible"] != (p["qhat"] >= -0.1):
                            raise ValueError("served Q units or guard differs")
                    safe = [p for p in valid if p["eligible"]]
                    floor = min(p["yhat"] for p in safe)
                    ties = [p for p in safe if p["yhat"] <= floor + 1e-10]
                    winner = min(
                        ties,
                        key=lambda p: (
                            p["distance"],
                            p["candidate_id"],
                            p["evaluation_id"],
                        ),
                    )
                    if winner["evaluation_id"] != row["winner"]:
                        raise ValueError(
                            "independent two-pass whole-pool decision differs"
                        )
                    prediction_checks += len(predictions)
                elif row["winner"] != row["anchor"]:
                    raise ValueError("fallback cannot apply a new candidate")
        nominees = {
            g: common_nominees(
                [r for r in result["rows"] if r["panel"] == panel],
                g,
                registration["calibration_frontier"],
            )
            for g in GROUPS
        }
        if nominees != result["nominees"][panel]:
            raise ValueError("registered group/time nomination differs")
    # A cache identity correction cannot invalidate retained model/decision values.
    engine = FamilyResearch(
        runtime=NumericRuntime(native_policy="require"), max_fits=64
    )
    matched = []
    corpus = corpora["A-HMA"]
    for panel in ("base", "union"):
        for code in ROSTER:
            row = next(
                r
                for r in result["rows"]
                if (r["panel"], r["group"], r["fold"], r["code"])
                == (panel, "A-HMA", 24, code)
            )
            document = read(
                output / "portable/development" / f"{panel}-A-HMA-24-{code}.json.gz"
            )
            from quantbt.optimization.meta_selection.common import canonical

            old = loads_family_artifact(
                canonical(document),
                expected_artifact_id=row["artifact_id"],
                task=corpus.revisions[24].task,
                schema=corpus.schema,
            )
            fitted = engine.fit(
                FamilySpec(code),
                corpus.schema,
                view(corpus.snapshot(24), panel),
                fit_completed_at=corpus.revisions[24].task.decision_sealed_at,
            )
            new = engine.propose(
                corpus.revisions[24].task, fitted, schema=corpus.schema
            )
            if new.artifact_id != old.artifact_id:
                raise ValueError(
                    "post-screen source compatibility changed a full actual decision"
                )
            matched.append(
                dict(
                    panel=panel,
                    group="A-HMA",
                    fold=24,
                    code=code,
                    artifact_id=new.artifact_id,
                )
            )
        engine.clear()
    return dict(
        schema="m4.ml03.cold-certificate.v1",
        status="PASS",
        baseline=verify_freeze(),
        screen=pin(output / "result.json"),
        registered_cells=len(keys),
        full_pool_prediction_checks=prediction_checks,
        nomination_matches=True,
        source_changes=source_changes,
        actual_fixed_input_compatibility=matched,
        compatibility_fits=engine.fits,
        compatibility_regression_fit_charge=engine.regression_fit_charge,
        cpu_seconds=time.process_time() - started,
        native=wire(engine.runtime.metadata),
        new_optimizer_proposals=0,
        new_financial_calls=0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--measurement-only", action="store_true")
    args = parser.parse_args()
    if args.measurement_only:
        print(
            save_new(
                args.output / "measurement-audit.json", measurement_audit(args.output)
            )
        )
    else:
        print(save_new(args.output / "cold-certificate.json", certificate(args.output)))


def measurement_audit(output):
    """Recompute served MSE/MAE from retained predictions and qualified raw label rows."""
    result = read(output / "result.json")
    corpora = {g: load_corpus(g) for g in GROUPS}
    checked, nulls, max_diff = 0, 0, 0.0
    for panel in ("base", "union"):
        for group, corpus in corpora.items():
            records = read(output / f"{panel}-{group}-predictions.json.gz")
            scores = {
                (r["fold"], r["code"]): r["predictions"]
                for r in records
            }
            if len(records) != len(scores) or set(scores) != {
                (f, c) for f in range(13, 25) for c in ROSTER
            }:
                raise ValueError("saved prediction cells duplicated or missing")
            for row in (
                r for r in result["rows"] if r["panel"] == panel and r["group"] == group
            ):
                revision = corpus.revisions[row["fold"]]
                members = (
                    revision.panel.base_members
                    if panel == "base"
                    else revision.panel.members
                )
                predictions = validate_bound_predictions(
                    row, scores[row["fold"], row["code"]], revision, corpus.schema
                )
                errors = []
                for label in revision.training_rows:
                    prediction = predictions.get(label.candidate_evaluation_id)
                    if (
                        label.candidate_evaluation_id not in members
                        or prediction is None
                        or prediction["yhat"] is None
                    ):
                        continue
                    error = prediction["yhat"] - label.y
                    qerror = prediction["qhat"] - label.q
                    if not np.isclose(qerror, -error, rtol=1e-9, atol=1e-10):
                        raise ValueError("actual Y/Q measurement signs/units differ")
                    errors.append(error)
                if len(errors) != row.get("scored_rows", 0):
                    raise ValueError("actual served-row support differs")
                if not errors:
                    if row["loss"] is not None:
                        raise ValueError(
                            "undefined actual model panel cannot produce a loss"
                        )
                    nulls += 1
                    continue
                expected = dict(
                    y_mse=float(np.mean(np.square(errors))),
                    q_mse=float(np.mean(np.square(errors))),
                    y_mae=float(np.mean(np.abs(errors))),
                    q_mae=float(np.mean(np.abs(errors))),
                )
                for name, value in expected.items():
                    actual = row["served_metrics"][name]
                    if not np.isclose(value, actual, rtol=1e-9, atol=1e-10):
                        raise ValueError("actual served label measurement differs")
                    max_diff = max(max_diff, abs(value - actual))
                if not np.isclose(
                    expected["y_mse"], row["loss"], rtol=1e-9, atol=1e-10
                ):
                    raise ValueError(
                        "reported objective loss differs from actual served Y"
                    )
                checked += 1
    return dict(
        schema="m4.ml03.actual-label-measurement-audit.v2",
        status="PASS",
        rows_checked=checked,
        undefined_rows_retained=nulls,
        maximum_metric_difference=max_diff,
        trusted_clocks_candidate_ids_raw_is_geometry_guard_ties_bound=True,
        result=pin(output / "result.json"),
        new_model_fits=0,
        new_financial_calls=0,
        new_optimizer_proposals=0,
    )


if __name__ == "__main__":
    main()
