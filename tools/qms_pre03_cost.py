"""Three matched fresh-process off/shadow/active nested scalar cost arms."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import resource
import statistics
import subprocess
import sys
from time import perf_counter

import optuna

from quantbt.optimization.meta_selection.common import wire, digest
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.persistence import dumps_revision, loads_revision
from tests.meta_selection import pre_e06_02_support as original
from tests.meta_selection.pre_e06_03_support import run, CUTOFFS
from tools.qms_pre03_source_guard import ROOT, verify


def child(mode, path):
    document = json.loads(path.read_text())
    history = MetaHistory()
    for row in document["revisions"]:
        history.append(loads_revision(row["json"], reviewed_revision_ids=(row["revision_id"],),
            verified_output_witnesses=document["original_output_witnesses"]))
    data = original.current(original.tape("pct_equity"), CUTOFFS[0])
    kwargs = dict(data=data, start="2022-05-01", numeric="require")
    run("pct_equity", "off", **kwargs)  # Same financial/JIT warm-up in every arm.
    started = perf_counter()
    value = run("pct_equity", mode, history=history, **kwargs)
    elapsed = perf_counter()-started
    wf = value.result.metadata["walk_forward"]
    m = wf.get("meta_selection", {})
    records = m.get("records", ())
    row = records[0] if records else {}
    if mode != "off" and (row.get("final_selection_reason") != "META_MODEL_PROPOSAL"
            or row.get("matured_origins", 0) < 12):
        raise ValueError("matched fitted cost requires actual matured model, not fallback")
    return dict(mode=mode, elapsed_seconds=elapsed,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        native_attempts=int(wf["fold_selection_table"].iloc[0]["study_trial_rows"]),
        selected_params=wf["params_by_fold"][0],
        auxiliary_outer_is_evaluations=row.get("auxiliary_outer_is_evaluations", 0),
        auxiliary_outer_is_seconds=row.get("auxiliary_outer_is_seconds", 0.),
        observer_evaluations=row.get("observer_evaluations", 0),
        observer_seconds=row.get("observer_seconds", 0.),
        meta_elapsed_seconds=m.get("elapsed_seconds", {}),
        numeric=wire(row.get("numeric_backend", {})),
        model_status=row.get("final_selection_reason", "OFF"),
        matured_origins=row.get("matured_origins", 0),
        current_outer_oos_used_for_selection=row.get("current_outer_oos_used_for_selection", False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lane", type=Path, default=ROOT/".maturin/qms08/pre-e06-03")
    p.add_argument("--child-mode", choices=("off", "shadow", "active"))
    p.add_argument("--history", type=Path)
    a = p.parse_args()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    if a.child_mode:
        print(json.dumps(child(a.child_mode, a.history), sort_keys=True))
        return
    verify()
    if a.lane.is_symlink() or not a.lane.resolve().is_relative_to(ROOT/".maturin/qms08"):
        raise ValueError("invalid cost lane")
    lane=a.lane.resolve()
    path=lane/"cost-history-v2.json"
    if path.exists() or (lane/"cost-v2.json").exists():
        raise ValueError("refuse to overwrite cost receipt")
    history=run("pct_equity").context.history
    revisions=tuple(history._revisions.values())
    path.write_text(json.dumps(dict(revisions=[dict(revision_id=r.revision_id, json=dumps_revision(r))
        for r in revisions], original_output_witnesses={o.output_ref:digest(o) for r in revisions
            for o in (*(c.observation for c in r.task.candidates), *(o.observation for o in r.outcomes))}),
        sort_keys=True)+"\n")
    rows=[]
    for repeat in range(3):
        for mode in ("off", "shadow", "active"):
            result=subprocess.run([sys.executable, "-m", "tools.qms_pre03_cost", "--child-mode", mode,
                "--history", str(path)], cwd=ROOT, text=True, capture_output=True, check=True)
            row=json.loads(result.stdout.splitlines()[-1])
            rows.append(dict(repeat=repeat, **row))
            print(json.dumps(dict(repeat=repeat, **row)), flush=True)
    payload=dict(schema="pre03-matched-cost-v1", target="pct_equity", repeats=3, numeric_threads=1,
        native_batch_policy="require", financial_prepared="off", cutoff=str(CUTOFFS[0]), trials=8, seed=731,
        warmup="one_financial_off_run_per_fresh_process", observer=True,
        history_sha256=sha256(path.read_bytes()).hexdigest(), economic_claim=False, rows=rows,
        p50={m:dict(elapsed_seconds=statistics.median(r["elapsed_seconds"] for r in rows if r["mode"]==m),
                   peak_rss_mib=statistics.median(r["peak_rss_mib"] for r in rows if r["mode"]==m))
             for m in ("off", "shadow", "active")})
    (lane/"cost-v2.json").write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")


if __name__ == "__main__":
    main()
