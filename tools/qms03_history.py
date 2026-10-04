"""Bounded QMS-03 original-engine evidence; no private alpha or edge claim."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import resource
import subprocess
from time import perf_counter, process_time
import xml.etree.ElementTree as ET

import optuna
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.endpoint import _WalkForwardEndpointScorer
from quantbt.walkforward import WalkForwardEngine
from quantbt.core.wfo_contracts import strategy_fingerprint
from quantbt.optimization.meta_selection import (
    CandidateRoleRef,
    CompatibilityFamily,
    MetaTask,
)
from quantbt.optimization.meta_selection.capture import ISPoolCapture
from quantbt.optimization.meta_selection.common import canonical, digest, wire
from quantbt.optimization.meta_selection.descriptors import OriginBalancedStandardizer
from quantbt.optimization.meta_selection.history import MetaHistory, SealedTaskRevision
from quantbt.optimization.meta_selection.observer import (
    PostDecisionObserver,
    market_signature,
)
from quantbt.optimization.meta_selection.panel import freeze_panel
from quantbt.optimization.meta_selection.persistence import (
    dumps_revision,
    loads_revision,
    retention_chunk,
    restore_chunk,
)
from tools import qms01_baseline as baseline


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "benchmarks/optimization/meta_selection"
ENTRY = "3ce42bf"
GUIDE = baseline.GUIDE
optuna.logging.set_verbosity(optuna.logging.WARNING)


def original_engine_run(*, capture=True, centroid=False, mutate_future=False):
    data = baseline.market()
    if mutate_future:
        cutoff = pd.Timestamp("2021-01-01", tz="UTC")
        data.loc[data.index >= cutoff, ["open", "high", "low", "close"]] *= 1.7
    endpoint = baseline.endpoint(centroid=centroid, retention="none")
    wf_config = replace(
        endpoint.config.walkforward_config,
        metadata={
            **endpoint.config.walkforward_config.metadata,
            "use_scalar_trial_scoring": False,
        },
    )
    scorer = _WalkForwardEndpointScorer(
        endpoint.config,
        "signal_notional",
        wf_config=wf_config,
        market_data=data,
        meta_metric_support=capture,
    )
    observer = (
        ISPoolCapture(
            resolved_at=lambda fold: fold.train_index[-1] + pd.Timedelta(microseconds=1)
        )
        if capture
        else None
    )
    engine = WalkForwardEngine(
        endpoint.config.strategy_class,
        wf_config,
        scorer=scorer,
        is_pool_observer=observer,
    )
    result = engine.run(data=data, param_ranges={"window": (3, 31, 2)})
    return data, endpoint, scorer, result, observer


def financial_fixture(*, centroid=False):
    data, endpoint, scorer, result, capture = original_engine_run(centroid=centroid)
    revisions, rows = [], []
    observer = PostDecisionObserver(scorer._meta_adapter)
    family = None
    started, cpu = perf_counter(), process_time()
    for pool, fold in zip(capture.pools, result.folds, strict=True):
        schema = pool.schema
        family = CompatibilityFamily(
            strategy_fingerprint(endpoint.config.strategy_class),
            schema.space.identity,
            schema.schema_id,
            "SYNTHETIC-USD-linear",
            "1D",
            "rolling180D-quarterly-v1",
            scorer._meta_adapter.contract.metric_id,
            scorer._meta_economics_id,
            "original-endpoint-reset-v1",
            "mode4-causal-centroid-v1" if centroid else "mode4-causal-medoid-v1",
            "legacy-tpe-v1",
            "fresh-diagnostic-account-v1",
        )
        resolved = pool.candidates[0].resolved_at
        task = MetaTask(
            family,
            "qms03-synthetic-original-engine",
            "qms03-centroid" if centroid else "qms03-medoid",
            fold.train_index[-1],
            fold.train_index[0],
            fold.train_index[-1],
            fold.test_index[0],
            fold.test_index[-1],
            fold.train_index[-1],
            pool.seed,
            pool.candidates,
            pool.anchor_evaluation_id,
            (
                CandidateRoleRef(
                    "native_anchor", family.anchor_policy_id, pool.anchor_evaluation_id
                ),
            ),
            resolved,
            resolved,
            resolved + pd.Timedelta(microseconds=1),
            fold.test_index[0],
            pd.Timestamp.now(tz="UTC"),
            "historical_replay",
            "synthetic_counterfactual",
            "research_only",
            {
                "source": "actual WFO trial pool",
                "study_id": pool.study_id,
                "seed": pool.seed,
                "sampler": "tpe_legacy",
                "trials_requested": wf_config_trials(endpoint),
                "auxiliary_is_evaluations": pool.auxiliary_is_evaluations,
            },
        )
        panel = freeze_panel(task, schema, sealed_at=task.decision_sealed_at)

        def evaluate(candidate):
            prefix = data.loc[: fold.test_index[-1]]
            signal = endpoint.config.strategy_class(
                prefix,
                dict(candidate.effective_params),
                fold.train_index,
                fold.test_index,
                fold,
            )
            diagnostic = QuantBTEndpoint(scorer.score_config)
            financial = diagnostic.backtest(
                data=prefix.loc[fold.test_index], signal=signal
            )
            return financial, market_signature(
                prefix, fold.test_index, config=scorer.score_config
            )

        available = task.forward_end + pd.Timedelta(seconds=1)
        outcomes = observer.observe(
            task=task,
            panel=panel,
            evaluate=evaluate,
            expected_index=fold.test_index,
            label_available_at=available,
            reporting_lag_seconds=1,
        )
        revision = SealedTaskRevision(task, panel, outcomes, available)
        observations = [c.observation for c in task.candidates] + [
            o.observation for o in outcomes
        ]
        witnesses = {o.output_ref: digest(o) for o in observations}
        restored = loads_revision(
            dumps_revision(revision),
            verified_output_witnesses=witnesses,
            reviewed_revision_ids=(revision.revision_id,),
        )
        if restored.revision_id != revision.revision_id:
            raise AssertionError("original-engine checkpoint parity failed")
        chunk = retention_chunk(revision, chunk_id=f"qms03-{fold.fold_id}")
        if (
            restore_chunk(
                chunk,
                expected_logical_digest=chunk.logical_digest,
                verified_output_witnesses=witnesses,
                reviewed_revision_ids=(revision.revision_id,),
            )[0].revision_id
            != revision.revision_id
        ):
            raise AssertionError("existing columnar retention parity failed")
        for row in revision.training_rows:
            if abs(row.q - (row.raw_forward - row.anchor_forward)) > 1e-12:
                raise AssertionError("original-engine label algebra failed")
        revisions.append(revision)
        rows.append(
            {
                "task_id": task.task_id,
                "revision_id": revision.revision_id,
                "family_id": family.family_id,
                "fold_id": pool.fold_id,
                "seed": pool.seed,
                "pool_size": len(pool.candidates),
                "native_candidate_table_rows": int(
                    (result.candidate_table["schedule_fold_id"] == fold.fold_id).sum()
                )
                if "schedule_fold_id" in result.candidate_table
                else None,
                "anchor_evaluation_id": task.anchor_candidate_evaluation_id,
                "anchor_is": wire(task.anchor.observation),
                "auxiliary_is_evaluations": pool.auxiliary_is_evaluations,
                "panel_members": len(panel.members),
                "extra_union_evaluations": len(panel.extra_union_members),
                "outcomes": [wire(o) for o in outcomes],
                "training_rows": [wire(r) for r in revision.training_rows],
                "descriptor_shape": list(schema.encode(task.candidates).values.shape),
            }
        )
    history = MetaHistory(max_revisions=64)
    for revision in revisions:
        history.append(revision)
    cutoff = max(r.revision_available_at for r in revisions) + pd.Timedelta(seconds=1)
    view = history.snapshot(
        family_id=family.family_id,
        authorized_corpora=(revisions[0].task.corpus_id,),
        outcome_origins=("synthetic_counterfactual",),
        research_exposures=("research_only",),
        information_as_of=cutoff,
    )
    scaler = OriginBalancedStandardizer.fit(capture.pools[0].schema, view)
    transformed, unsupported = scaler.transform(
        capture.pools[-1].schema.encode(capture.pools[-1].candidates)
    )
    evidence = {
        "fixture": "actual original QuantBT engine on synthetic OHLCV, not economic edge evidence",
        "clock_mode": "historical_replay",
        "wall_generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "rows": rows,
        "training_snapshot_id": view.snapshot_id,
        "origin_count": view.origin_count,
        "training_rows": len(view.training_rows),
        "observer_attempts": observer.attempts,
        "observer_failures": observer.failures,
        "observer_seconds": observer.elapsed_seconds,
        "retention_and_transform_seconds": perf_counter() - started,
        "cpu_seconds": process_time() - cpu,
        "descriptor_backend": capture.pools[0].schema.backend,
        "last_transform_shape": list(transformed.shape),
        "last_unsupported_count": int(unsupported.sum()),
        "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / 1024,
        "rss_scope": "same-process absolute peak; not an isolated delta or production throughput claim",
    }
    return evidence, revisions, result


def wf_config_trials(endpoint):
    return int(endpoint.config.walkforward_config.optuna_trials)


def source_manifest():
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "src", "rust", "pyproject.toml", "poetry.lock", GUIDE],
            cwd=ROOT,
        )
        .decode()
        .splitlines()
    )
    paths += [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src/quantbt/optimization/meta_selection").glob("*.py")
    ]
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(set(paths))
    }


def report():
    medoid, _, _ = financial_fixture()
    centroid, _, _ = financial_fixture(centroid=True)
    return {
        "schema": "qms03-original-engine-evidence-v1",
        "entry_commit": ENTRY,
        "guide": GUIDE,
        "guide_sha256": hashlib.sha256((ROOT / GUIDE).read_bytes()).hexdigest(),
        "protected_source_hashes": source_manifest(),
        "core_version": "1.1.1",
        "native_version": "0.4.2",
        "workload": {
            "bars": 547,
            "trials_per_study": 6,
            "workers": 1,
            "is_subperiods": 3,
            "market": "public SMA example; synthetic daily OHLCV",
            "retention": "compact numeric records + witnesses",
        },
        "medoid": medoid,
        "centroid": centroid,
    }


def receipt(evidence, junit):
    root = ET.parse(junit).getroot()
    cases = list(root.iter("testcase"))
    groups = {
        f"Q3-T{n:02d}": sum(f"q3_t{n:02d}" in c.attrib["name"] for c in cases)
        for n in range(1, 9)
    }
    failed = [
        c
        for c in cases
        if any(c.find(tag) is not None for tag in ("error", "failure", "skipped"))
    ]
    if failed or not all(groups.values()):
        raise AssertionError("QMS-03 executed test groups incomplete/failed/skipped")
    return {
        "schema": "qms03-gate-receipt-v1",
        "entry_commit": ENTRY,
        "evidence_sha256": hashlib.sha256(canonical(evidence).encode()).hexdigest(),
        "junit_sha256": hashlib.sha256(Path(junit).read_bytes()).hexdigest(),
        "executed_test_groups": groups,
        "tests": len(cases),
        "failures": 0,
        "skips": 0,
        "technical": {
            gate: "PASS"
            for gate in (
                "G3-TASK",
                "G3-CAUSALITY",
                "G3-DESCRIPTORS",
                "G3-LABELS",
                "G3-PORTABLE_HISTORY",
            )
        },
        "G3-OWNER": "PENDING",
        "advancement": "not authorized",
        "empirical": "NOT_ASSESSED",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        evidence = json.loads((DIRECTORY / "qms03_history_evidence.json").read_text())
        recorded = json.loads((DIRECTORY / "qms03_gate_receipt.json").read_text())
        if (
            recorded != receipt(evidence, args.junit)
            or evidence["protected_source_hashes"] != source_manifest()
        ):
            raise SystemExit("QMS-03 receipt/source validation failed")
        print("QMS-03 executed receipt and current source hashes PASS")
    else:
        evidence = report()
        # Explicit evidence generator; not a manual source edit or default WFO side effect.
        (DIRECTORY / "qms03_history_evidence.json").write_text(
            canonical(evidence) + "\n"
        )
        (DIRECTORY / "qms03_gate_receipt.json").write_text(
            json.dumps(receipt(evidence, args.junit), indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    "medoid": {
                        k: evidence["medoid"][k]
                        for k in (
                            "origin_count",
                            "training_rows",
                            "observer_attempts",
                            "observer_failures",
                        )
                    },
                    "centroid": {
                        k: evidence["centroid"][k]
                        for k in (
                            "origin_count",
                            "training_rows",
                            "observer_attempts",
                            "observer_failures",
                        )
                    },
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
