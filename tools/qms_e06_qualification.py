"""Source-bound intrabar qualification; public fixtures, never publish or retune."""

import argparse
from dataclasses import replace
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
LANE = ROOT / ".maturin/qms08/e06-qualification-v1"
MODES = ("off", "shadow", "active")
REPEATS = 3


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def register():
    sys.path.insert(0, str(ROOT))
    from tools.qms_pre06_contract import (
        artifact_source, checked_hashes, core_inventory, prerequisites,
    )

    prior = ROOT / ".maturin/qms08/pre-e06-06/registration.json"
    old = json.loads(prior.read_text())
    sources = prerequisites()
    inventory = core_inventory(ROOT / "src/quantbt")
    artifacts = {
        "wheel": ROOT / ".maturin/qms08/pre-e06-06/package-v1/dist/quantbt_engine-1.1.2-py3-none-any.whl",
        "sdist": ROOT / ".maturin/qms08/pre-e06-06/package-v1/dist/quantbt_engine-1.1.2.tar.gz",
        "native": ROOT / ".maturin/qms08/g01-package-v1-native/quantbt_native-0.4.3-cp312-cp312-manylinux_2_34_x86_64.whl",
    }
    for name in ("wheel", "sdist"):
        artifact_source(artifacts[name], inventory)
    from tools.qms_pre06_contract import native_reuse
    native_reuse(artifacts["native"])
    history = ROOT / ".maturin/qms08/pre-e06-05/history/domain-intrabar.json"
    protected = {str(p.relative_to(ROOT)): file_hash(p) for p in (
        prior, history, *artifacts.values(),
        ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_06_closure.json",
        ROOT / "docs/meta_selection/EXECUTION_WFO_REPORT.md",
        ROOT / "docs/meta_selection/PRE_E06_06_REPORT.md",
    )}
    checked_hashes(protected)
    disk = os.statvfs(ROOT)
    if disk.f_bavail * disk.f_frsize < (5 * 1024**3 + 2 * 1024**3):
        raise ValueError("insufficient registered headroom")
    cells = {
        mode: old["expected_cells"][f"domain-intrabar-{mode}-mode_4_is_only_robust-per_fold_causal-false-false"]
        for mode in MODES
    }
    value = dict(schema="qms-e06-registration-v1", entry="c0dfcc5",
        guide_sha256=sources["guide_sha256"], runtime_sha256=sources["runtime_sha256"],
        core_inventory=inventory, protected_sha256=protected,
        artifacts={k: str(v) for k, v in artifacts.items()}, expected_cells=cells,
        source_repeats=REPEATS, witness_modes=[False, True], meta_modes=list(MODES),
        warmups=1, attempted_trials=8, seed=731, minimum_origins=12,
        disk_budget_bytes=2 * 1024**3, safety_bytes=5 * 1024**3,
        free_bytes=disk.f_bavail * disk.f_frsize, free_inodes=disk.f_favail,
        scope="local synthetic software only", publication=False)
    write_once(LANE / "registration.json", value)
    print(json.dumps(dict(status="REGISTERED", runtime_files=len(value["runtime_sha256"]))))


def prepare(mode, witness):
    from quantbt import QuantBTEndpoint
    from tools.qms_pre05_workloads import Cell, prepare as original
    cell = Cell("domain", "intrabar", mode)
    bt, data, context, ranges = original(cell, ROOT / ".maturin/qms08/pre-e06-05")
    wf = bt.config.walkforward_config
    bt = QuantBTEndpoint(replace(bt.config, walkforward_config=replace(wf,
        metadata={**wf.metadata, "use_prepared_meta_witness": witness})))
    return cell, (bt, data, context, ranges)


def verify_run(result, cell, prepared):
    import numpy as np
    import pandas as pd
    from quantbt.optimization.meta_selection.records import OutcomeStatus
    from tests.meta_selection.pre_e06_02_support import (
        Run, account_equal, independent, rebuild_final,
    )
    from tools.qms_pre05_workloads import semantic
    bt, data, context, _ = prepared
    logical, _ = semantic(result, cell, context)
    value = Run("intrabar", bt, result, context, data)
    account_equal(result, rebuild_final(value))
    wf = result.metadata["walk_forward"]
    meta = wf.get("meta_selection", {})
    output = dict(semantic_sha256=logical, models=len(meta.get("models", {})),
        minimum_origins=min((r["matured_origins"] for r in meta.get("records", [])), default=0),
        observer_failures=meta.get("observer_failures", 0),
        account_rebuild_exact=True, raw_pairs_checked=0, applied_params=True,
        final_equity=float(result.equity.iloc[-1]), synthetic_economic_pairs=[])
    if result.metadata["wfo_execution_window"]["financial_replays"] != 0:
        raise ValueError("execution was replayed")
    if cell.mode == "off":
        return output
    task = meta["tasks"][0]
    record = meta["records"][0]
    if (record["final_selection_reason"] != "META_MODEL_PROPOSAL"
            or record["current_outer_oos_used_for_selection"]
            or task.decision_sealed_at >= task.first_forward_action_at
            or wf["params_by_fold"][0] != record["selected_params"]):
        raise ValueError("mature applied-selection contract failed")
    revision = next(r for r in context.history._revisions.values() if r.task.task_id == task.task_id)
    by_id = {c.evaluation_id: c for c in task.candidates}
    forward = {o.evaluation_id: o.observation for o in revision.outcomes}
    for outcome in revision.outcomes:
        candidate = by_id[outcome.evaluation_id]
        for is_forward, obs in ((False, candidate.observation), (True, outcome.observation)):
            original = independent(value, task, candidate, forward=is_forward)
            report = original.full_report(scope="full", trading_days=365)
            np.testing.assert_allclose(obs.raw_sharpe, report["sharpe"], rtol=1e-12, atol=1e-12)
            if obs.activity_count != report["num_trades"] or obs.verification != "original_result":
                raise ValueError("original measurement witness mismatch")
            from quantbt.metrics.performance import _array_returns_for_stats
            sample = _array_returns_for_stats(original.equity.index,
                original.equity.to_numpy(float), original.returns.to_numpy(float))
            if obs.sample_count != len(sample):
                raise ValueError("sample contract mismatch")
            np.testing.assert_allclose(obs.sample_std, np.std(sample, ddof=1), rtol=1e-12, atol=1e-12)
            expected = OutcomeStatus.CENSORED if original.liquidated else (
                OutcomeStatus.NO_VARIANCE if np.std(sample, ddof=1) <= 0 else OutcomeStatus.VALID)
            if obs.status != expected:
                raise ValueError("invalid outcome disposition")
            output["raw_pairs_checked"] += 1
        if outcome.label_available_at < task.forward_end + pd.Timedelta(days=1):
            raise ValueError("forward label availability backdated")
    anchor, selected = (by_id[record[k]] for k in
                        ("native_selected_evaluation_id", "selected_evaluation_id"))
    observations = (anchor.observation, selected.observation,
                    forward[anchor.evaluation_id], forward[selected.evaluation_id])
    valid = all(o.status == OutcomeStatus.VALID for o in observations)
    is_effect = anchor.observation.raw_sharpe - selected.observation.raw_sharpe if valid else None
    q = forward[selected.evaluation_id].raw_sharpe - forward[anchor.evaluation_id].raw_sharpe if valid else None
    output["synthetic_economic_pairs"].append(dict(valid=valid,
        statuses=[o.status.value for o in observations],
        same_winner=anchor.evaluation_id == selected.evaluation_id,
        is_contribution=is_effect, forward_q=q, decay_reduction=is_effect + q if valid else None,
        uncertainty="NOT_ESTIMABLE_ONE_SYNTHETIC_FOLD", real_market_promotion=False))
    return output


def worker(args):
    if args.installed:
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location("qms_installed_identity", ROOT / "tools/qms_pre06_consumer.py")
        checker = module_from_spec(spec)
        spec.loader.exec_module(checker)
        package = checker.identity(json.loads((LANE / "registration.json").read_text())["core_inventory"])
        sys.path.append(str(ROOT))
    else:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
        package = None
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from tools.qms_pre05_workloads import execute
    if not args.installed:
        cell, prepared = prepare(args.mode, args.witness)
        execute(prepared, cell)
    cell, prepared = prepare(args.mode, args.witness)
    started, cpu = perf_counter(), process_time()
    result = execute(prepared, cell)
    wall, used = perf_counter() - started, process_time() - cpu
    checked = verify_run(result, cell, prepared)
    registration = json.loads((LANE / "registration.json").read_text())
    if checked["semantic_sha256"] != registration["expected_cells"][args.mode]:
        raise ValueError("logical work differs from sealed PRE05 corpus")
    if args.installed:
        checker.origins(Path(package["core_origin"]))
    value = dict(schema="qms-e06-matched-cell-v1", mode=args.mode, witness=args.witness,
        wall_seconds=wall, cpu_seconds=used,
        process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        identity=package, **checked)
    write_once(args.output, value)
    print(json.dumps(dict(mode=args.mode, witness=args.witness, status="PASS",
        wall_seconds=wall, peak_rss_mib=value["process_peak_rss_mib"])))


def matrix(args):
    installed = args.installed
    rows = []
    for repeat in range(1 if installed else REPEATS):
        for mode in MODES:
            for witness in (False, True):
                name = f"{args.prefix}-{repeat}-{mode}-{int(witness)}"
                output = LANE / (name + ".json")
                command = [sys.executable, "-I", __file__, "--worker", "--mode", mode,
                    "--output", str(output)]
                if witness:
                    command.append("--witness")
                if installed:
                    command.append("--installed")
                env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
                env.pop("PYTHONPATH", None)
                start = perf_counter()
                process = subprocess.run(command, cwd="/tmp", env=env, capture_output=True, text=True)
                with (LANE / (name + ".log")).open("x") as stream:
                    stream.write(process.stdout + process.stderr)
                if process.returncode:
                    raise RuntimeError(f"E06 worker failed: {name}; see retained log")
                row = json.loads(output.read_text())
                row["worker_process_wall_seconds"] = perf_counter() - start
                rows.append(row)
                print(process.stdout.strip(), flush=True)
    summary = {}
    for mode in MODES:
        for witness in (False, True):
            sample = [r for r in rows if r["mode"] == mode and r["witness"] == witness]
            if len({r["semantic_sha256"] for r in sample}) != 1:
                raise ValueError("repeat logical-work mismatch")
            summary[f"{mode}-witness-{int(witness)}"] = dict(samples=len(sample),
                median_wall_seconds=median(r["wall_seconds"] for r in sample),
                median_cpu_seconds=median(r["cpu_seconds"] for r in sample),
                peak_rss_mib=max(r["process_peak_rss_mib"] for r in sample),
                minimum_origins=min(r["minimum_origins"] for r in sample),
                semantic_sha256=sample[0]["semantic_sha256"],
                economic=sample[0]["synthetic_economic_pairs"])
    write_once(args.output, dict(schema="qms-e06-matrix-v1", installed=installed,
        cells=len(rows), summary=summary, rows=rows, publication=False))


def installed_tests(args):
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("qms_installed_identity", ROOT / "tools/qms_pre06_consumer.py")
    checker = module_from_spec(spec)
    spec.loader.exec_module(checker)
    package = checker.identity(json.loads((LANE / "registration.json").read_text())["core_inventory"])
    sys.path.append(str(ROOT))
    import pytest
    # Test code may be loaded from checkout; the financial/meta core must not.
    code = pytest.main(["-q", "--import-mode=importlib", str(ROOT / "tests/meta_selection/test_e06_intrabar_meta.py"),
                       "--junitxml=" + str(args.output.with_suffix(".xml"))])
    checker.origins(Path(package["core_origin"]))
    if code:
        raise ValueError("installed intrabar meta conformance failed")
    from xml.etree import ElementTree as ET
    cases = ET.parse(args.output.with_suffix(".xml")).getroot().findall(".//testcase")
    if len(cases) != 16 or any(c.find(k) is not None for c in cases for k in ("skipped", "error", "failure")):
        raise ValueError("incomplete installed route qualification")
    write_once(args.output, dict(identity=package, tests=len(cases), skipped=0,
        installed_only=True, publication=False))


def install_consumers():
    sys.path.insert(0, str(ROOT))
    from tools.qms08_package import build_tool, run
    from tools.qms_pre06_contract import artifact_source, checked_hashes, source_inventory
    registration = json.loads((LANE / "registration.json").read_text())
    checked_hashes(registration["protected_sha256"])
    if source_inventory() != registration["runtime_sha256"]:
        raise ValueError("runtime drift before consumer installation")
    pins = ("numpy==2.2.6", "pandas==2.3.3", "numba==0.65.1", "optuna==4.8.0",
        "scipy==1.18.1", "cmaes==0.12.0", "arch==8.0.0", "scikit-learn==1.8.0",
        "threadpoolctl==3.7.0", "pytest==9.1.1")
    for kind in ("wheel", "sdist"):
        target = LANE / (kind + "-consumer")
        if target.exists() or target.is_symlink():
            raise ValueError("refuse to reuse or overwrite an installed consumer")
        artifact_source(Path(registration["artifacts"][kind]), registration["core_inventory"])
        run([build_tool("uv"), "venv", "--python", sys.executable, target],
            cwd=LANE, log=LANE / (kind + "-venv.log"))
        python = target / "bin/python"
        run([build_tool("uv"), "pip", "install", "--offline", "--python", python,
            registration["artifacts"][kind] + "[optimization]",
            registration["artifacts"]["native"], *pins],
            cwd=LANE, log=LANE / (kind + "-install.log"))
        run([build_tool("uv"), "pip", "check", "--python", python],
            cwd=LANE, log=LANE / (kind + "-dependencies.log"))
        print(json.dumps(dict(consumer=kind, installed=True)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--installed-tests", action="store_true")
    parser.add_argument("--install-consumers", action="store_true")
    parser.add_argument("--witness", action="store_true")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--prefix", default="source")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.register:
        register()
    elif args.install_consumers:
        install_consumers()
    elif args.installed_tests:
        installed_tests(args)
    elif args.worker:
        worker(args)
    else:
        matrix(args)
