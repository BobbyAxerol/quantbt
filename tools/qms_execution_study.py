"""Frozen synthetic endpoint comparison. Not an economic promotion receipt."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ("intrabar", "event_driven", "order_commands", "delivery_arbitrage")


def paired_metrics(observations):
    import math
    from quantbt.optimization.meta_selection.records import OutcomeStatus
    if any(o.status != OutcomeStatus.VALID or o.raw_sharpe is None
           or not math.isfinite(o.raw_sharpe) for o in observations):
        return None
    ia, oa, im, om = (o.raw_sharpe for o in observations)
    return dict(is_anchor=ia, forward_anchor=oa, is_selected=im, forward_selected=om,
        decay_anchor=ia-oa, decay_selected=im-om, R=(ia-oa)-(im-om), Q=om-oa)


def worker(route, mode, end):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from examples.wfo_meta_execution import execute, market
    from quantbt.optimization.meta_selection.common import wire
    started = perf_counter()
    endpoint, result, context = execute(route, mode=mode, data=market(route, end=end), trials=8, support=12)
    elapsed = perf_counter()-started
    wf = result.metadata["walk_forward"]
    side = wf.get("meta_selection", {})
    report = result.full_report(scope="full", trading_days=365)
    pairs, dispositions = [], []
    decisions = {r["task_id"]: r for r in side.get("records", ())}
    for revision in context.history._revisions.values():
        task = revision.task
        decision = decisions.get(task.task_id)
        if decision is None:
            continue
        selected = decision["selected_evaluation_id"]
        candidates = {c.evaluation_id: c for c in task.candidates}
        outcomes = {o.evaluation_id: o for o in revision.outcomes}
        anchor = task.anchor_candidate_evaluation_id
        if selected not in outcomes or anchor not in outcomes:
            continue
        observations = (candidates[anchor].observation, outcomes[anchor].observation,
                        candidates[selected].observation, outcomes[selected].observation)
        metrics = paired_metrics(observations)
        dispositions.append(dict(task_id=task.task_id, included=metrics is not None,
            statuses=[o.status.value for o in observations]))
        if metrics is not None:
            pairs.append(dict(task_id=task.task_id, **metrics))
    return dict(route=route, mode=mode, wall_seconds=elapsed,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.,
        bars=len(result.equity), folds=wf["n_folds"], params_by_fold=wf["params_by_fold"],
        trial_rows=len(wf["trial_table"]), final_equity=float(report["final_equity"]),
        sharpe=float(report["sharpe"]), fees=float(result.fees.sum()), funding=float(result.funding.sum()),
        observer_attempts=side.get("observer_attempts", 0), observer_failures=side.get("observer_failures", 0),
        numeric=wire([r["numeric_backend"] for r in side.get("records", ())]), pairs=pairs,
        pair_dispositions=dispositions,
        fitted_models=len(side.get("models", {})),
        changed_selections=sum(r["selected_evaluation_id"] != r["native_selected_evaluation_id"]
                               for r in side.get("records", ())),
        selection_status=[r["final_selection_reason"] for r in side.get("records", ())],
        economic_promotion=False, data_kind="synthetic_basic_execution_alpha")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=ROUTES)
    parser.add_argument("--mode", choices=("off", "shadow", "active"), default="off")
    parser.add_argument("--end", default="2022-06-30")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.mode, args.end), sort_keys=True, allow_nan=False))
        return
    env = {**os.environ, "PYTHONPATH": str(ROOT/"src")+os.pathsep+str(ROOT),
           "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMBA_NUM_THREADS": "1"}
    rows = []
    for route in ROUTES:
        for mode in ("off", "shadow", "active"):
            process = subprocess.run([sys.executable, "-m", "tools.qms_execution_study", "--worker", route,
                "--mode", mode, "--end", args.end], cwd=ROOT, env=env, capture_output=True, text=True)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.with_name(f"{args.output.stem}_{route}_{mode}.log").write_text(
                    process.stdout + process.stderr)
            if process.returncode:
                raise RuntimeError(f"{route}/{mode} failed ({process.returncode}): {process.stderr[-2500:]}")
            row = json.loads(process.stdout)
            rows.append(row)
            print(f"{route}/{mode}: {row['wall_seconds']:.3f}s; {row['folds']} folds; "
                  f"{row['observer_failures']} observer failures", flush=True)
    from tools.qms_execution_source_guard import verify
    receipt = dict(schema="qms-synthetic-execution-study-v1", rows=rows, seed=731, trials_per_fold=8,
        min_matured_origins=12, estimator_changed=False, retuned_after_outcomes=False,
        source_guard=verify(), paired_metric_status="four_original_VALID_observations_only",
        data_kind="synthetic_basic_execution_alpha", promotion=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False)+"\n")
    else:
        print(json.dumps(receipt, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
