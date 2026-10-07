"""Complete public E07 workloads, same logical work and original accounting."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
from statistics import median
import subprocess
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / ".maturin/qms08/e07-qualification-v1"


def prepare_imports(installed=False):
    if installed:
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location("e07_installed_identity", ROOT / "tools/qms_pre06_consumer.py")
        checker = module_from_spec(spec)
        spec.loader.exec_module(checker)
        expected = json.loads((LANE / "registration.json").read_text())["core_inventory"]
        identity = checker.identity(expected)
        sys.path.append(str(ROOT))
        return checker, identity
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
    return None, None


def freeze_histories():
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from quantbt.optimization.meta_selection.common import digest
    from quantbt.optimization.meta_selection.persistence import dumps_revision
    from tests.meta_selection import e07_support as e07
    from tools.qms_e07_contract import check_registration, file_hash, write_once
    check_registration()
    evidence = {}
    for case in e07.CASES:
        name = "-".join(case)
        value = e07.run(case, "shadow", start="2020-04-01")
        revisions = tuple(value.context.history._revisions.values())
        payload = dict(schema="pre05-frozen-history-v1", route=case[0], group="e07",
            revisions=[dict(revision_id=r.revision_id, json=dumps_revision(r)) for r in revisions],
            original_output_witnesses={o.output_ref: digest(o) for r in revisions
                for o in (*(c.observation for c in r.task.candidates), *(o.observation for o in r.outcomes))})
        path = LANE / "history" / (name + ".json")
        write_once(path, payload)
        evidence[name] = dict(sha256=file_hash(path), revisions=len(revisions))
        print(json.dumps(dict(history=name, revisions=len(revisions))), flush=True)
    write_once(LANE / "history-seal.json", evidence)


def prepared(case, mode, variant):
    from tests.meta_selection import e07_support as e07
    from tools.qms_pre05_workloads import Cell, load_history
    from tools.qms_e07_contract import file_hash
    seal = json.loads((LANE / "history-seal.json").read_text())
    name = "-".join(case)
    path = LANE / "history" / (name + ".json")
    if file_hash(path) != seal[name]["sha256"]:
        raise ValueError("frozen own-family history drift")
    history = load_history(path) if mode != "off" else None
    return Cell("domain", case[0], mode), e07.prepare_run(case, mode, history=history, variant=variant)


def verify(value, cell):
    from tests.meta_selection import e07_support as e07
    from tools.qms_pre05_workloads import semantic
    import numpy as np
    e07.rebuild(value)
    logical, _ = semantic(value.result, cell, value.context)
    meta = e07.output(value).get("meta_selection", {})
    row = dict(semantic_sha256=logical, models=len(meta.get("models", {})),
        minimum_origins=min((r["matured_origins"] for r in meta.get("records", ())), default=0),
        observer_failures=meta.get("observer_failures", 0), account_rebuild_exact=True,
        raw_pairs_checked=0, output_revisions=len(meta.get("observed_revisions", ())),
        account_scope="segmented_reset_flat" if value.route == "reactive_reset" else "continuous_original",
        callback_owner="python_strategy", financial_owner="rust" if value.route == "reactive_reset" else value.endpoint.config.wfo_execution_config.native_backend,
        synthetic_economic_pairs=[])
    accounts = [f.result for f in value.result.fold_results] if value.route == "reactive_reset" else [value.result]
    row["final_equity"] = [float(a.equity.iloc[-1]) for a in accounts]
    from quantbt.optimization.meta_selection.common import digest
    row["account_pool_sha256"] = digest(dict(
        accounts=[{k: sha256(getattr(a, k).to_numpy(dtype="<f8").tobytes()).hexdigest()
            for k in ("equity", "returns", "positions", "fees", "funding", "margin")} for a in accounts],
        params=value.result.params_by_fold if value.route == "reactive_reset" else e07.output(value)["params_by_fold"],
        pools=[[(c.effective_params, c.objective, c.observation) for c in t.candidates] for t in meta.get("tasks", ())]))
    row["financial_observability"] = []
    for account in accounts:
        observations = {}
        for name in ("strategy_observability", "reactive_numeric_observability", "execution_plan_v1", "native_backend"):
            original = account.metadata.get(name)
            if isinstance(original, dict):
                observations[name] = {k: v for k, v in original.items()
                    if isinstance(v, (str, int, float, bool, type(None)))}
            elif isinstance(original, str):
                observations[name] = original
        row["financial_observability"].append(observations)
    if cell.mode == "off":
        if meta:
            raise ValueError("off path gained a meta sidecar")
        return row
    record, task = meta["records"][0], meta["tasks"][0]
    if record["final_selection_reason"] != "META_MODEL_PROPOSAL" or record["current_outer_oos_used_for_selection"]:
        raise ValueError("cold/leaky qualification")
    revision = meta["observed_revisions"][0]
    if revision.revision_id != record["observer_revision_id"]:
        raise ValueError("result cannot independently bind observed outcomes")
    candidates = {c.evaluation_id: c for c in task.candidates}
    forward = {o.evaluation_id: o.observation for o in revision.outcomes}
    for outcome in revision.outcomes:
        candidate = candidates[outcome.evaluation_id]
        for is_forward, observation in ((False, candidate.observation), (True, outcome.observation)):
            original = e07.independent(value, task, candidate, forward=is_forward)
            report = original.full_report(scope="full", trading_days=365)
            np.testing.assert_allclose(observation.raw_sharpe, report["sharpe"], rtol=1e-12, atol=1e-12)
            if observation.activity_count != report["num_trades"] or observation.verification != "original_result":
                raise ValueError("original measurement differs")
            row["raw_pairs_checked"] += 1
    anchor, selected = (candidates[record[k]] for k in ("native_selected_evaluation_id", "selected_evaluation_id"))
    observations = (anchor.observation, selected.observation, forward[anchor.evaluation_id], forward[selected.evaluation_id])
    valid = all(o.status.value == "VALID" for o in observations)
    a, m, fa, fm = (o.raw_sharpe for o in observations)
    row["synthetic_economic_pairs"] = [dict(valid=valid, statuses=[o.status.value for o in observations],
        native_is=a, selected_is=m, native_forward=fa, selected_forward=fm,
        is_contribution=a-m if valid else None, forward_q=fm-fa if valid else None,
        decay_reduction=(a-fa)-(m-fm) if valid else None,
        same_winner=anchor.evaluation_id == selected.evaluation_id,
        uncertainty="NOT_ESTIMABLE_ONE_SYNTHETIC_FOLD", economic_promotion=False)]
    return row


def memory():
    fields = {}
    for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
        if line.startswith(("Rss:", "Pss:")):
            name, amount, _unit = line.split()
            fields[name[:-1].lower()+"_mib"] = int(amount)/1024
    return fields


def worker(args):
    checker, identity = prepare_imports(args.installed)
    from tools.qms_e07_contract import write_once
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    case = tuple(args.case)
    from tests.meta_selection import e07_support as e07
    if not args.installed:
        _, warm = prepared(case, args.mode, args.variant)
        e07.execute(warm)
    cell, request = prepared(case, args.mode, args.variant)
    started, cpu = perf_counter(), process_time()
    value = e07.execute(request)
    wall, used = perf_counter()-started, process_time()-cpu
    # Account/measurement verification is outside timed execution.
    process_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    resident = memory()
    checked = verify(value, cell)
    if checker:
        checker.origins(Path(identity["core_origin"]))
    row = dict(case=list(case), mode=args.mode, variant=args.variant, repeat=args.repeat,
        wall_seconds=wall, cpu_seconds=used, process_peak_rss_mib=process_peak,
        after_call_memory=resident, identity=identity, **checked)
    write_once(args.output, row)
    print(json.dumps(dict(case=case, mode=args.mode, variant=args.variant, wall_seconds=wall, status="PASS")), flush=True)


def matrix(args):
    from tools.qms_e07_contract import MODES, REPEATS, check_registration, validate_matrix, write_once
    from tests.meta_selection.e07_support import CASES
    check_registration()
    rows = []
    for repeat in range(1 if args.installed else REPEATS):
        for case in CASES:
            for mode in MODES:
                for variant in (False, True):
                    name = f"{args.prefix}-{repeat}-{'-'.join(case)}-{mode}-{int(variant)}"
                    out = LANE / (name+".json")
                    command = [sys.executable, "-I", __file__, "--worker", "--case", *case,
                        "--mode", mode, "--repeat", str(repeat), "--output", str(out)]
                    if variant:
                        command.append("--variant")
                    if args.installed:
                        command.append("--installed")
                    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
                    env.pop("PYTHONPATH", None)
                    process = subprocess.run(command, cwd="/tmp", env=env, capture_output=True, text=True)
                    with (LANE / (name+".log")).open("x") as stream:
                        stream.write(process.stdout+process.stderr)
                    if process.returncode:
                        raise ValueError(f"failed E07 cell: {name}; retained log")
                    rows.append(json.loads(out.read_text()))
                    print(process.stdout.strip(), flush=True)
    result = dict(rows=rows, installed=args.installed, cells=len(rows), publication=False)
    validate_matrix(result, repeats=1 if args.installed else REPEATS)
    result["summary"] = [{"case": list(case), "mode": mode, "variant": variant,
        "median_wall_seconds": median(r["wall_seconds"] for r in rows
            if tuple(r["case"]) == case and r["mode"] == mode and r["variant"] is variant)}
        for case in CASES for mode in MODES for variant in (False, True)]
    write_once(args.output, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--histories", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--case", nargs=2)
    parser.add_argument("--mode", choices=("off", "shadow", "active"))
    parser.add_argument("--variant", action="store_true")
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--prefix", default="source-v1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args)
    else:
        prepare_imports(args.installed)
        if args.register:
            from tools.qms_e07_contract import register
            print(json.dumps(dict(status="REGISTERED", files=len(register()["runtime_sha256"]))))
        elif args.histories:
            freeze_histories()
        else:
            matrix(args)
