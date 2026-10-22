"""Untimed ownership/stage diagnostics, separate from matched E07 cost medians."""

import argparse
import json
import os
import subprocess
import sys

from tools.qms_e07_contract import LANE, ROOT, check_registration, write_once
from tools.qms_e07_qualification import prepared

FIELDS = ("engine", "native_event_backend_requested", "native_event_backend_resolved",
    "state_owner", "strategy_callback_count", "emitted_command_count", "primary_engine_runs",
    "oracle_engine_runs", "python_shadow_accounting", "reactive_static_replay_count",
    "native_static_execution_boundary_calls", "observability", "execution_counters",
    "prepared_market_cache")


def capture(case):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from tests.meta_selection import e07_support as e07
    from tools.qms_pre05_workloads import semantic
    from tools.qms01_baseline import safe
    from quantbt.optimization.meta_selection.common import wire
    cell, request = prepared(case, "active", True)
    value = e07.execute(request)
    logical, _ = semantic(value.result, cell, value.context)
    accounts = [f.result for f in value.result.fold_results] if case[0] == "reactive_reset" else [value.result]
    meta = e07.output(value)["meta_selection"]
    records = [{k: r[k] for k in ("fold_id", "observer_seconds") if k in r} for r in meta["records"]]
    return dict(case=list(case), semantic_sha256=logical, diagnostic_only=True,
        callback_owner="python_strategy", financial_owner=case[1],
        accounts=[safe({k: a.metadata[k] for k in FIELDS if k in a.metadata}) for a in accounts],
        stages=records, meta_elapsed_seconds=dict(meta["elapsed_seconds"]),
        timing_limits="fit_select_combined_no_separate_search_fit_rank_timers",
        numeric_backends=[wire(m.backend) for m in meta["models"].values()],
        witness_transport=safe(meta.get("witness_transport")),
        w3_runtime=safe(value.result.metadata.get("runtime")), publication=False)


def main():
    from tests.meta_selection.e07_support import CASES
    check_registration()
    reference = json.loads((LANE / "source-matrix-v3.json").read_text())
    expected = {tuple(r["case"]): r["semantic_sha256"] for r in reference["rows"]
                if r["mode"] == "active" and r["variant"]}
    rows = []
    for case in CASES:
        command = [sys.executable, "-m", "tools.qms_e07_observability", "--case", *case]
        env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   PYTHONPATH=str(ROOT / "src")+":"+str(ROOT))
        process = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        with (LANE / ("observability-"+"-".join(case)+".log")).open("x") as stream:
            stream.write(process.stdout+process.stderr)
        if process.returncode:
            raise ValueError("ownership diagnostic failed; retained log")
        row = json.loads(process.stdout)
        if row["semantic_sha256"] != expected[case]:
            raise ValueError("ownership diagnostic changed logical work")
        rows.append(row)
    write_once(LANE / "observability-v1.json", dict(rows=rows, diagnostic_only=True, publication=False))
    print(json.dumps(dict(status="PASS_OWNERSHIP_DIAGNOSTICS", cells=len(rows))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs=2)
    args = parser.parse_args()
    if args.case:
        print(json.dumps(capture(tuple(args.case)), sort_keys=True))
    else:
        main()
