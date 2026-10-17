"""Early cold and late fitted source-bound controls; no new strategy execution."""

from pathlib import Path
import time

import pandas as pd

from quantbt.optimization.meta_selection.numerics import NumericRuntime
from .admission import load_corpus, pin, save_new
from .families import FamilySpec
from .family_controls import require_same_decision, synthetic_correction
from .family_protocol import ROSTER
from .learners import FamilyResearch


def run(output):
    registration = dict(schema="m4.ml04.checkpoint-registration.v1",
        folds=[0, 56], group="A-HMA", roster=list(ROSTER),
        source=pin(Path(__file__)), helper=pin(Path(__file__).with_name("family_controls.py")),
        mutation="latest revision56 correction available after its outcome; fresh independent fits at each earlier cutoff",
        max_logical_fits=10, new_financial_calls=0, new_optimizer_proposals=0)
    reg = save_new(output / "registration.json", registration)
    cpu = time.process_time()
    rows, bills = [], []
    for fold in (0, 56):
        corpus = load_corpus("A-HMA")
        task, schema = corpus.revisions[fold].task, corpus.schema
        before = corpus.snapshot(fold)
        saved = corpus.selections[fold]["snapshot"]
        artifacts = []
        for version in ("before", "future_mutated"):
            if version == "future_mutated":
                future = corpus.revisions[56]
                corpus.history.append(synthetic_correction(future, schema,
                    future.revision_available_at + pd.Timedelta(days=1)))
                snap = corpus.history.snapshot(**{k: saved[k] for k in (
                    "family_id", "authorized_corpora", "outcome_origins",
                    "research_exposures", "information_as_of")})
                if snap.snapshot_id != before.snapshot_id:
                    raise ValueError("unavailable future changed checkpoint history")
            else:
                snap = before
            engine = FamilyResearch(runtime=NumericRuntime(native_policy="require"), max_fits=64)
            current = []
            for code in ROSTER:
                fit = engine.fit(FamilySpec(code), schema, snap,
                                 fit_completed_at=task.decision_sealed_at)
                artifact = engine.propose(task, fit, schema=schema, full_ranking=True)
                if fold == 0 and (fit.model is not None
                        or artifact.decision.status != "META_SUPPORT_INSUFFICIENT"):
                    raise ValueError("cold checkpoint fabricated a fit")
                if fold == 56 and (fit.model is None
                        or artifact.decision.status != "META_MODEL_PROPOSAL"):
                    raise ValueError("late checkpoint must really fit and score")
                current.append(artifact)
            artifacts.append(current)
            bills.append(dict(fold=fold, version=version, logical_fits=engine.fits,
                numeric_fit_charge=engine.regression_fit_charge,
                external_runtime_qualification_fits=2))
        for code, a, b in zip(ROSTER, *artifacts):
            require_same_decision(a, b)
            rows.append(dict(fold=fold, code=code, K=before.origin_count,
                real_fit=a.fit.model is not None, future_fresh_fit_exact=True,
                status=a.decision.status, full_pool_predictions=len(a.decision.predictions)))
    if pin(Path(__file__)) != registration["source"]:
        raise ValueError("checkpoint source changed")
    return dict(schema="m4.ml04.checkpoints.v1", status="PASS", registration=reg,
        rows=rows, fit_bill=bills, cpu_seconds=time.process_time()-cpu,
        roster_count=len(ROSTER), new_financial_calls=0,
        new_optimizer_proposals=0, no_independent_oos_or_efficacy_claim=True)
