"""Matched synthetic public portfolio studies; no empirical edge/promotion claim."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
from time import perf_counter

import numpy as np
import pandas as pd


def signature(result):
    from quantbt.optimization.meta_selection.common import digest
    wf = result.metadata["walk_forward"]
    buffers = {name: sha256(np.ascontiguousarray(getattr(result, name).to_numpy(),
        dtype=np.float64).tobytes()).hexdigest() for name in
        ("equity", "returns", "positions", "fees", "funding", "margin", "diagnostics")}
    side = wf.get("meta_selection")
    pools = [[dict(params=dict(c.effective_params), objective=c.objective,
        input=c.observation.input_signature, output=c.observation.output_ref)
        for c in task.candidates] for task in side["tasks"]] if side else None
    trials = wf["trial_table"].copy()
    for name in trials.select_dtypes(include="object").columns:
        trials[name] = trials[name].map(lambda v: json.dumps(v, sort_keys=True, default=str))
    return dict(account=digest(buffers), params=digest({str(k):v for k,v in wf["params_by_fold"].items()}),
        trials=sha256(pd.util.hash_pandas_object(trials, index=True).to_numpy().tobytes()).hexdigest(),
        pool=digest(pools) if pools is not None else None)


def worker(arm):
    import optuna
    from examples.wfo_meta_portfolio import execute
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    kwargs = {"off": dict(mode="off"), "reference": dict(mode="shadow", cache=False, witness=False),
              "prepared": dict(mode="shadow", cache=True, witness=True)}[arm]
    # Same cold work, then two complete fresh-account warm studies in each process.
    timings, identities = [], []
    for _ in range(3):
        start = perf_counter()
        _, result, _ = execute(**kwargs, support=1)
        timings.append(perf_counter()-start)
        identities.append(signature(result))
    assert identities[0] == identities[1] == identities[2]
    meta = result.metadata["walk_forward"].get("meta_selection")
    return dict(arm=arm, cold_seconds=timings[0], warm_seconds=timings[1:],
        warm_median_seconds=statistics.median(timings[1:]),
        fresh_process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        identity=identities[-1], attempted_trials=len(result.metadata["walk_forward"]["trial_table"]),
        folds=len(result.metadata["walk_forward"]["fold_table"]),
        observer_attempts=meta["observer_attempts"] if meta else 0,
        observer_failures=meta["observer_failures"] if meta else 0,
        witness=meta["witness_reuse"] if meta else None)


def profile(output):
    if output.exists():
        raise ValueError("sealed profile exists; use a fresh output")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root/"src"), OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    rows = {}
    for arm in ("off", "reference", "prepared"):
        process = subprocess.run([sys.executable, "-m", "tools.qms_e04_profile", "--worker", arm],
            cwd=root, env=env, text=True, capture_output=True, timeout=300, check=False)
        if process.returncode:
            raise RuntimeError(process.stdout+process.stderr)
        rows[arm] = json.loads(process.stdout.splitlines()[-1])
    assert rows["reference"]["identity"] == rows["prepared"]["identity"]
    assert rows["reference"]["witness"] is None
    assert rows["prepared"]["witness"]["schema"] == "qms-portfolio-prepared-witness-v1"
    for key in ("account", "params", "trials"):
        assert rows["off"]["identity"][key] == rows["prepared"]["identity"][key]
    result = dict(schema="qms-e04-public-portfolio-profile-v1", bars=730, symbols=2,
        seed=731, trials_per_fold=6, repeats=2, financial_authority="original_native_portfolio_numba",
        threads=1, rows=rows, prepared_reference_speedup=rows["reference"]["warm_median_seconds"]/
        rows["prepared"]["warm_median_seconds"], exact_parity=True, real_alpha=False,
        economic_claim=False, publication=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("off", "reference", "prepared"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker), sort_keys=True))
    else:
        if args.output is None:
            parser.error("--output required")
        receipt = profile(args.output)
        print(json.dumps(dict(speedup=receipt["prepared_reference_speedup"], exact_parity=True)))
