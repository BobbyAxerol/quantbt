"""Small matched native W3 transport benchmark; not an alpha/economic claim."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import resource
import statistics
import subprocess
from time import perf_counter

import numpy as np
import optuna

from quantbt.backends.reactive_wfo_support import ReactiveWfoRuntimeConfigV1
from quantbt.optimization.meta_selection.common import wire
from tests.meta_selection.test_local_reactive import execute
from tools.qms_c02_source_guard import ROOT, verify


def fingerprint(result):
    state = sha256()
    state.update(json.dumps(result.params_by_fold, sort_keys=True).encode())
    state.update(np.asarray(result.trial_table.objective, dtype=np.float64).tobytes())
    for fold in result.fold_results:
        for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
            state.update(np.asarray(getattr(fold.result, field), dtype=np.float64).tobytes())
    for task in result.metadata["meta_selection"]["tasks"]:
        state.update(json.dumps([wire(c.observation) for c in task.candidates], sort_keys=True).encode())
    return state.hexdigest()


def measure(repeats=3):
    if repeats < 1:
        raise ValueError("repeats must be positive")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    execute("shadow")  # Exclude interpreter/JIT/cache warm-up from paired samples.
    rows = {"inprocess": [], "process": []}
    fingerprints = set()
    for _ in range(repeats):
        for mode in ("inprocess", "process"):
            start = perf_counter()
            result, _, runtime = execute("shadow", runtime_config=ReactiveWfoRuntimeConfigV1(worker_mode=mode))
            wall = perf_counter() - start
            fingerprints.add(fingerprint(result))
            meta = result.metadata["meta_selection"]
            rows[mode].append(dict(wall_seconds=wall,
                score_seconds=result.metadata["runtime"]["score_seconds"],
                score_bars=result.metadata["runtime"]["score_bars"],
                witness_transport=meta["witness_transport"],
                worker=result.metadata["runtime"]["worker"],
                observer_attempts=meta["observer_attempts"], observer_failures=meta["observer_failures"]))
            runtime.close()
    if len(fingerprints) != 1:
        raise AssertionError("paired native objective/account/original observation changed")
    import _quantbt_native

    native_dir = Path(_quantbt_native.__file__).parent
    binary = next(native_dir.glob("_quantbt_native*.so"))
    return dict(schema="qms-c02-transport-evidence-v1", publication=False,
        source_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        source_guard=verify(), native_extension_sha256=sha256(binary.read_bytes()).hexdigest(),
        fixture=dict(bars=180, folds=4, trials_per_fold=8, is_subperiods=2,
            candidate_directions=[-1., 1.], native_policy="reference", meta="shadow",
            account="reset_flat", market="synthetic_daily", warmup_excluded=True),
        repeats=repeats, fingerprint=next(iter(fingerprints)), exact_paired_parity=True,
        samples=rows, median_seconds={k: statistics.median(r["wall_seconds"] for r in v) for k, v in rows.items()},
        same_process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.,
        memory_note="same-process high-water mark, not fresh-process baseline or summed worker RSS",
        claim="transport qualification; not representative alpha speed or economic improvement")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("receipt exists; use a fresh output")
    result = measure(args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(parity=result["exact_paired_parity"], median_seconds=result["median_seconds"],
                         same_process_peak_rss_mib=result["same_process_peak_rss_mib"])))
