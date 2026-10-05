"""Bounded sampler costs, not a cross-recipe speedup or economic acceptance study."""

from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import time

from examples.wfo_reactive_samplers import RECIPES, configuration, execute
from tools.qms_c03_source_guard import verify


def decision_digest(result):
    import numpy as np
    from quantbt.optimization.meta_selection.common import wire

    def buffer(field):
        values = np.ascontiguousarray(field, dtype=np.float64)
        return dict(shape=values.shape, dtype=str(values.dtype), sha256=sha256(values.tobytes()).hexdigest())

    value = dict(params=result.params_by_fold,
        trials=[dict(params=r.params, objective=r.objective, pruned=r.pruned)
                for r in result.trial_table.itertuples()],
        account=[{k: buffer(getattr(f.result, k)) for k in
                  ("equity", "returns", "positions", "fees", "funding", "margin")} for f in result.fold_results])
    return sha256(json.dumps(wire(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sample(recipe, scheduler, *, legacy=False):
    config = configuration(recipe)
    ranges = None
    if legacy:
        config = replace(config, sampler_config=None)
        ranges = {"qty": (.5, 2.), "hold": (2, 8), "direction": 1.}
    started, cpu = time.perf_counter(), time.process_time()
    result = execute(config=config, ranges=ranges, scheduler=scheduler)
    wall, cpu = time.perf_counter() - started, time.process_time() - cpu
    studies = result.metadata.get("sampler_studies", [])
    runtime = result.metadata["runtime"]
    return dict(wall_seconds=wall, cpu_seconds=cpu,
        sampler_wall_seconds=sum(s["sampler_wall_seconds"] for s in studies) if studies else None,
        native_score_wall_seconds=runtime["score_seconds"], physical_score_calls=runtime["score_calls"],
        physical_score_bars=runtime["score_bars"], decision_account_digest=decision_digest(result),
        attempts=sum(s["attempts"] for s in studies) if studies else 16,
        states=studies[0]["states"] if studies else None,
        relative_proposals=studies[0]["relative_proposal_trials"] if studies else None,
        sampling_contract=result.metadata["sampling_contract"],
        same_process_cumulative_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.)


def run(repeats=3):
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    source = verify()
    cells = []
    for scheduler in ("certified_sequential_v1", "throughput_batch_v1"):
        for recipe in RECIPES:
            sample(recipe, scheduler)
            rows = [sample(recipe, scheduler) for _ in range(repeats)]
            assert len({r["decision_account_digest"] for r in rows}) == 1
            cells.append(dict(recipe=recipe, scheduler=scheduler, samples=rows,
                median_wall_ms=statistics.median(r["wall_seconds"] for r in rows) * 1000,
                median_sampler_ms=statistics.median(r["sampler_wall_seconds"] for r in rows) * 1000,
                median_score_ms=statistics.median(r["native_score_wall_seconds"] for r in rows) * 1000))
    sample("tpe_legacy", "certified_sequential_v1", legacy=True)
    legacy = [sample("tpe_legacy", "certified_sequential_v1", legacy=True) for _ in range(repeats)]
    opt_in = cells[0]
    assert {r["decision_account_digest"] for r in legacy} == {r["decision_account_digest"] for r in opt_in["samples"]}
    return dict(schema="qms-c03-sampler-scheduler-cost-v1", source_guard=source,
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        fixture=dict(bars=180, oos_folds=4, trials=16, seed=731, is_subperiods=1,
            batch_size=4, repeats=repeats, warmup_per_cell=1, account="segmented_reset_flat"),
        python=platform.python_version(), optuna=optuna.__version__,
        threads={key: os.environ.get(key) for key in
                 ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS")},
        cells=cells, omitted_legacy=legacy,
        legacy_median_wall_ms=statistics.median(r["wall_seconds"] for r in legacy) * 1000,
        exact_legacy_optin_decisions_accounts=True, economic_claim=False, publication=False,
        measurement_scope="inprocess full run with preparation/selection/account adaptation; imports and first warmup excluded",
        rss_scope="same-process cumulative high-water only; not fresh-process or process-tree RSS gate",
        comparisons="different recipe and B>1 scheduler pools; absolute engineering costs, not equal-work speedups")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(cells=len(evidence["cells"]), legacy_ms=evidence["legacy_median_wall_ms"],
        costs=[dict(recipe=c["recipe"], scheduler=c["scheduler"], wall_ms=c["median_wall_ms"],
                    sampler_ms=c["median_sampler_ms"]) for c in evidence["cells"]])))
