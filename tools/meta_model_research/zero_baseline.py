"""Cold matched-label zero-reference skill, without fitting or execution."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import resource
import time

import numpy as np

from .admission import PUBLIC, ROOT, load_corpus, pin, read, save_new, verify_freeze
from .family_protocol import ROSTER
from .prediction_checks import validate_bound_predictions
from .protocol import GROUPS


MODELS = ("P0",) + ROSTER


def matched_losses(truth, predictions):
    """One origin: every model must use exactly the same non-anchor label IDs."""
    if set(predictions) != set(MODELS) or not truth:
        raise ValueError("complete model roster and nonempty truth required")
    ids = set(truth)
    if any(set(p) != ids for p in predictions.values()):
        raise ValueError("cross-model scored-label mask mismatch")
    if any(
        type(v) not in (float, int) or not math.isfinite(v)
        for values in (truth, *predictions.values())
        for v in values.values()
    ):
        raise ValueError("finite true and served values required")
    order = sorted(ids)
    y = np.array([truth[k] for k in order])
    return dict(
        ZERO=float(np.mean(y * y)),
        **{
            code: float(np.mean((np.array([p[k] for k in order]) - y) ** 2))
            for code, p in predictions.items()
        },
    )


def reduce_cells(cells):
    """Equal rows within origin, equal origins within group, equal group macro."""
    if len({(c["group"], c["fold"]) for c in cells}) != len(cells):
        raise ValueError("duplicate origin")
    groups = {}
    for group in GROUPS:
        rows = [c for c in cells if c["group"] == group]
        if not rows:
            raise ValueError("missing group cannot become a zero macro weight")
        groups[group] = dict(
            origins=len(rows),
            labeled_rows=sum(c["n"] for c in rows),
            mse={
                code: float(np.mean([c["mse"][code] for c in rows]))
                for code in ("ZERO",) + MODELS
            },
        )
    macro = {
        code: float(np.mean([groups[g]["mse"][code] for g in GROUPS]))
        for code in ("ZERO",) + MODELS
    }
    skill = {
        code: 1 - macro[code] / macro["ZERO"] if macro["ZERO"] > 0 else None
        for code in MODELS
    }
    return dict(
        groups=groups,
        macro_mse=macro,
        zero_reference_skill=skill,
        sqrt_macro_mse={k: math.sqrt(v) for k, v in macro.items()},
    )


def run(output):
    started = time.process_time()
    old_root = ROOT / "upgrade/private/meta_model_research_v1/ml02/replay-02"
    new_root = ROOT / "upgrade/private/meta_model_research_v1/ml03/screen-01"
    before = [
        pin(PUBLIC / n)
        for n in ("ml02_closure.json", "ml03_closure.json", "ml05_closure.json")
    ]
    old, new = read(old_root / "result.json"), read(new_root / "result.json")
    for document, path, field in (
        (read(PUBLIC / "ml02_closure.json"), old_root / "result.json", "input_pins"),
        (read(PUBLIC / "ml03_closure.json"), new_root / "result.json", "inputs"),
    ):
        assert pin(path) in document[field], "unbound retained result"
    registration = dict(
        schema="m4.ml05.zero-registration.v1",
        baseline=verify_freeze(),
        source=pin(Path(__file__)),
        previous_closures=before,
        models=list(MODELS),
        panels=["base", "union"],
        folds=list(range(13, 25)),
        estimator="mean rows/origin then origins/group then four-group macro",
        scope="reviewed development; no gate, model or parameter selection",
        max_cpu_seconds=120,
        max_rss_bytes=1610612736,
        max_incremental_bytes=2097152,
        new_fits=0,
        new_financial_calls=0,
    )
    reg = save_new(output / "registration.json", registration)
    corpora = {g: load_corpus(g) for g in GROUPS}
    inputs = [pin(old_root / "result.json"), pin(new_root / "result.json")]
    results, nulls = {}, []
    for panel in ("base", "union"):
        cells = []
        for group, corpus in corpora.items():
            if (
                time.process_time() - started > 120
                or resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                > 1610612736
            ):
                raise RuntimeError("cold budget exceeded")
            old_file, new_file = (
                p / f"{panel}-{group}-predictions.json.gz" for p in (old_root, new_root)
            )
            inputs.extend((pin(old_file), pin(new_file)))
            records = [
                r
                for r in read(old_file)
                if r["policy"] == "P0" and 13 <= r["fold"] < 25
            ]
            records += [dict(r, policy=r["code"]) for r in read(new_file)]
            predictions = {(r["fold"], r["policy"]): r["predictions"] for r in records}
            if len(predictions) != len(records) or set(predictions) != {
                (f, c) for f in range(13, 25) for c in MODELS
            }:
                raise ValueError("saved prediction roster mismatch")
            rows = {
                (r["fold"], r.get("code", "P0")): r
                for r in new["rows"]
                if r["panel"] == panel and r["group"] == group
            }
            rows.update(
                {
                    (r["fold"], "P0"): r
                    for r in old["rows"]
                    if r["panel"] == panel
                    and r["group"] == group
                    and r["policy"] == "P0"
                    and 13 <= r["fold"] < 25
                }
            )
            for fold in range(13, 25):
                revision = corpus.revisions[fold]
                members = (
                    revision.panel.base_members
                    if panel == "base"
                    else revision.panel.members
                )
                truth = {
                    r.candidate_evaluation_id: float(r.y)
                    for r in revision.training_rows
                    if r.candidate_evaluation_id in members
                }
                served = {}
                for code in MODELS:
                    ps = validate_bound_predictions(
                        rows[fold, code],
                        predictions[fold, code],
                        revision,
                        corpus.schema,
                    )
                    served[code] = {
                        eid: float(ps[eid]["yhat"])
                        for eid in truth
                        if eid in ps and ps[eid]["yhat"] is not None
                    }
                masks = [set(p) for p in served.values()]
                if any(m != masks[0] for m in masks):
                    raise ValueError("cross-model scored-label mask mismatch")
                if not masks[0]:
                    if any(rows[fold, c]["loss"] is not None for c in MODELS):
                        raise ValueError("unscored origin has reported loss")
                    nulls.append(
                        dict(
                            panel=panel,
                            group=group,
                            fold=fold,
                            reason="NO_COMMON_SERVED_LABELS",
                        )
                    )
                    continue
                truth = {k: v for k, v in truth.items() if k in masks[0]}
                losses = matched_losses(truth, served)
                for code in MODELS:
                    if not math.isclose(
                        losses[code],
                        rows[fold, code]["loss"],
                        rel_tol=1e-9,
                        abs_tol=1e-10,
                    ):
                        raise ValueError("retained model MSE differs")
                cells.append(dict(group=group, fold=fold, n=len(truth), mse=losses))
        results[panel] = dict(reduce_cells(cells), cells=cells)
    for ref in inputs + before + [registration["source"]]:
        if pin(ref["path"]) != ref:
            raise ValueError("input/source changed")
    return dict(
        schema="m4.ml05.zero-baseline.v1",
        status="PASS_MATCHED_DESCRIPTIVE",
        registration=reg,
        results=results,
        undefined_origins=nulls,
        input_pins=inputs,
        baseline=verify_freeze(),
        cpu_seconds=time.process_time() - started,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        fits=0,
        optimizer_proposals=0,
        financial_calls=0,
        causal_or_economic_promotion=False,
        interpretation="skill vs fixed Y=0, not mean-reference R2; no significance claim",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    p = parser.parse_args().output
    print(save_new(p / "result.json", run(p)))
