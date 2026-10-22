"""Cold ML07 measurements over sealed decisions and original metric witnesses."""

from collections import Counter
from pathlib import Path
import resource
import time


from .admission import PUBLIC, read, pin, save_new, load_corpus
from .decision_analysis import measure, paired, summarize
from .decision_value import DEFAULT as PREVIOUS
from .forward_study import DEFAULT, existing_queries, verify
from .protocol import GROUPS
from .replay import persist_gzip


def analyze(output=DEFAULT):
    from .forward_controls import structural_losses

    verify(output)
    started = time.process_time()
    save_new(
        output / "analysis-registration.json",
        dict(
            source=pin(Path(__file__)),
            seal=pin(output / "sealed.json"),
            query_roster=pin(output / "query-roster.json"),
            new_fits=0,
            new_financial_calls=0,
        ),
    )
    sealed = read(output / "sealed.json")
    predictions = read(output / "predictions.json.gz")
    old = read(PREVIOUS / "sealed.json")
    queries = existing_queries() + [
        read(p) for p in sorted((output / "queries").glob("*.json"))
    ]
    groups, ledger = {}, []
    for group in GROUPS:
        corpus = load_corpus(group)
        xp = {
            r["fold"]: r["predictions"]
            for r in read(PREVIOUS / f"{group}-x-predictions.json.gz")
        }
        qp = {r["fold"]: r for r in predictions if r["group"] == group}
        rows = []
        for row in [
            r for r in old["rows"] if r["group"] == group and r["fold"] >= 25
        ] + [r for r in sealed["rows"] if r["group"] == group]:
            fold = row["fold"]
            extras = {
                r["request"]["winner"]: r
                for r in queries
                if r["request"]["group"] == group and r["request"]["fold"] == fold
            }
            rows.append(
                dict(row, **measure(corpus.revisions[fold], row["winner"], extras))
            )
        losses, unavailable = [], []
        for fold in range(25, 57):
            revision = corpus.revisions[fold]
            models = {
                "R": {
                    p["evaluation_id"]: p
                    for p in (corpus.selections[fold]["record"]["proposal"] or {}).get(
                        "predictions", []
                    )
                },
                "X": {p["evaluation_id"]: p for p in xp[fold]},
                "Q_RIDGE": {p["evaluation_id"]: p for p in qp[fold]["predictions"]},
            }
            training = revision.training_rows
            if not training or any(
                any(
                    r.candidate_evaluation_id not in d
                    or d[r.candidate_evaluation_id]["yhat"] is None
                    for d in models.values()
                )
                for r in training
            ):
                unavailable.append(fold)
                continue
            candidates = {c.evaluation_id: c for c in revision.task.candidates}
            for r in training:
                delta = (
                    candidates[r.candidate_evaluation_id].observation.raw_sharpe
                    - revision.task.anchor.observation.raw_sharpe
                )
                losses.append(
                    dict(
                        origin=revision.task.forward_start.strftime("%Y-%m"),
                        weight=r.origin_weight,
                        delta_is=delta,
                        y=r.y,
                        predictions={
                            name: d[r.candidate_evaluation_id]["yhat"]
                            for name, d in models.items()
                        },
                    )
                )
        policies = ("N", "R", "X", "F", "R_RETENTION12", "QD", "QF")
        aggregate = {
            p: summarize([r for r in rows if r["policy"] == p]) for p in policies
        }
        contrasts = {
            a + "-" + b: paired(rows, a, b)
            for a, b in (
                ("R_RETENTION12", "R"),
                ("QD", "R"),
                ("QF", "R"),
                ("QF", "F"),
                ("QF", "QD"),
            )
        }
        for value in contrasts.values():
            value.pop("rows")
        gates = [r["gate"] for r in rows if r["policy"] == "R_RETENTION12"]
        groups[group] = dict(
            policies=aggregate,
            contrasts=contrasts,
            structural_loss=structural_losses(losses) if losses else None,
            structural_loss_unsupported_origins=unavailable,
            retention=dict(
                accepted=sum(g["accepted"] for g in gates),
                origins=len(gates),
                reasons=dict(Counter(g["reason"] for g in gates)),
            ),
        )
        ledger += rows
    macro = {}
    for group, g in groups.items():
        # The reducer owns exact per-origin weighting. Keep group losses separate
        # when support differs; a pooled candidate mean would over-weight activity.
        macro[group] = g["structural_loss"]
    work = dict(
        primary=read(output / "sealed.json"),
        controls=read(output / "causal-controls.json"),
    )
    result = dict(
        schema="m4.ml07.analysis.v1",
        status="PASS_REGISTERED_DESCRIPTIVE_SCOPE",
        groups=groups,
        work=dict(
            primary_fit_charges=work["primary"]["fit_charges"],
            control_fit_charges=work["controls"]["fit_charges"],
            total_fit_charges=work["controls"]["total_fit_charges"],
            logical_fits=work["primary"]["logical_primary_fits"]
            + work["controls"]["logical_control_fits"],
            primary_cpu_seconds=work["primary"]["cpu_seconds"],
            control_cpu_seconds=work["controls"]["cpu_seconds"],
        ),
        uncertainty="No new CI or promotion; reviewed logged-history, missing masks explicit",
        cpu_seconds=time.process_time() - started,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        new_fits=0,
        new_financial_calls=0,
        new_optimizer_proposals=0,
    )
    persist_gzip(output / "measured-decisions.json.gz", ledger)
    return save_new(output / "analysis.json", result)


def build_summary(output=DEFAULT):
    value = read(output / "analysis.json")
    value["factorial"] = read(output / "factorial.json")["result"]
    value["work"]["financial"] = {
        stage: read(output / f"{stage}-result.json") for stage in ("pilot", "remaining")
    }
    for stage in value["work"]["financial"].values():
        stage.pop("query_pins")
    value["work"]["outside_query_budget"] = len(
        read(output / "query-roster.json")["outside_budget"]
    )
    value["technical_scope"] = (
        "source research only; no production/installed/CI/release change"
    )
    value["input_hashes"] = {
        name: pin(output / name)["sha256"]
        for name in (
            "registration.json",
            "sealed.json",
            "causal-controls.json",
            "query-roster.json",
            "analysis.json",
            "factorial.json",
        )
    }
    return save_new(PUBLIC / "ml07_summary.json", value)
