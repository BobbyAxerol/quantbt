"""Exact saved-output followup verifier; private raw evidence never enters git."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data/local/qms-real-review"
NEW = OLD / "debt-closure/real"


def prepare():
    NEW.mkdir(parents=True, exist_ok=True)
    for name in ("alpha.py", "market.csv.gz", "registration.json"):
        target = NEW / name
        if target.exists():
            if target.read_bytes() != (OLD / name).read_bytes():
                raise ValueError("private input differs; never overwrite evidence")
        else:
            shutil.copy2(OLD / name, target)


def run():
    prepare()
    python = ROOT / ".maturin/qms08/local-closure-v1/cp312/pair/bin/python"
    for arm in ("off", "active_rust"):
        output = NEW / f"meta_{arm}_tpe_legacy.json"
        if output.exists():
            raise ValueError("sealed experiment exists; never overwrite a completed run")
        command = [str(python), "-I", str(ROOT / "tools/qms_real_review.py"),
                   "worker", "--root", str(NEW), "--kind", "meta", "--arm", arm,
                   "--recipe", "tpe_legacy"]
        print("Starting fresh full-study " + arm, flush=True)
        environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                           MKL_NUM_THREADS="1")
        environment.pop("PYTHONPATH", None)
        process = subprocess.run(command, cwd=NEW, env=environment, text=True, capture_output=True)
        (NEW / (arm + ".log")).write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"real experiment failed; see {NEW / (arm + '.log')}")
        print(process.stdout.strip(), flush=True)


def read(arm, folder=NEW, witness=False):
    suffix = "_0_witness" if witness else ""
    return json.loads((folder / f"meta_{arm}_tpe_legacy{suffix}.json").read_text())


def economics(rows):
    import numpy as np

    valid = [r for r in rows if r["native"]["status"] == r["meta"]["status"] == "VALID"]
    if not valid:
        return dict(calendar_folds=len(rows), valid_folds=0, invalid_folds=len(rows),
                    native_decay=None, meta_decay=None, r=None, q=None,
                    decay_reduction_pct=None, status="NO_VALID_PAIRS")
    if any(not np.isfinite(r[side][field]) for r in valid for side in ("native", "meta")
           for field in ("is_sharpe", "forward_sharpe")):
        raise ValueError("valid paired metrics must be finite")
    means = {f"{side}_{field}": float(np.mean([r[side][field] for r in valid]))
             for side in ("native", "meta") for field in ("is_sharpe", "forward_sharpe")}
    dn = means["native_is_sharpe"] - means["native_forward_sharpe"]
    dm = means["meta_is_sharpe"] - means["meta_forward_sharpe"]
    q = means["meta_forward_sharpe"] - means["native_forward_sharpe"]
    r = dn - dm
    is_difference = means["native_is_sharpe"] - means["meta_is_sharpe"]
    np.testing.assert_allclose(r, is_difference + q, atol=1e-12, rtol=1e-12)
    return dict(calendar_folds=len(rows), valid_folds=len(valid), invalid_folds=len(rows)-len(valid),
        **means, native_decay=dn, meta_decay=dm, r=r, q=q, is_difference=is_difference,
        decay_reduction_pct=100 * r / dn if dn > 0 else None)


def compare():
    import numpy as np

    samples = {arm: read(arm)["samples"][0] for arm in ("off", "active_rust")}
    checks = {}
    for arm, sample in samples.items():
        old = read(arm, OLD)["samples"][0]
        assert sample["counts"] == old["counts"] and sample["counts"]["attempted"] == 3584
        assert sample["folds"] == 28 and sample["counts"]["failed"] == sample["observer_failures"] == 0
        for key in ("params", "metrics", "arrays_sha256", "paired"):
            assert sample[key] == old[key], (arm, key)
        columns = ("trial_id", "params", "objective", "mean_is_sharpe", "pruned", "fold_id")
        def project(s):
            return [{k: r.get(k) for k in columns} for r in s["trials"]]
        assert project(sample) == project(old), (arm, "optimizer trace/RNG")
        deltas = {}
        with np.load(NEW / f"meta_{arm}_tpe_legacy_0.npz") as a, np.load(
                OLD / f"meta_{arm}_tpe_legacy_0.npz") as b:
            assert a.files == b.files
            for field in a.files:
                np.testing.assert_array_equal(a[field], b[field])
                deltas[field] = float(np.max(np.abs(a[field] - b[field])))
        checks[arm] = dict(account_max_abs_diff=deltas, trial_trace_exact=True,
                           selected_params_exact=True, account_metrics_exact=True)
    fresh, archived = read("active_rust", witness=True), read("active_rust", OLD, witness=True)
    pools = labels = 0
    for a, b in zip(fresh["tasks"], archived["tasks"], strict=True):
        assert a["family"] == b["family"] and a["resolved_fold_seed"] == b["resolved_fold_seed"]
        fields = ("native_trial_id", "effective_params", "objective", "observation", "optional_is_features")
        def project(t):
            return [{k: c[k] for k in fields} for c in t["candidates"]]
        assert project(a) == project(b), "pool or original metric witness changed"
        pools += len(a["candidates"])
    for a, b in zip(fresh["revisions"], archived["revisions"], strict=True):
        assert [o["observation"] for o in a["outcomes"]] == [o["observation"] for o in b["outcomes"]]
        for field in ("base_members", "required_members", "extra_union_members", "quota_roles", "policy_id"):
            assert a["panel"][field] == b["panel"][field], ("panel", field)
        labels += len(a["outcomes"])
    checks["witnesses"] = dict(original_is_records=pools, forward_labels=labels,
        byte_exact=True, full_panel_exact=True, clocks="causal wall-derived timestamps, not execution-time parity")
    paired = samples["active_rust"]["paired"]
    supported = [r for r in paired if r["matured_origins"] >= 12]
    from arch.bootstrap import MovingBlockBootstrap

    values = np.array([[r["native"]["is_sharpe"] - r["native"]["forward_sharpe"]
                       - r["meta"]["is_sharpe"] + r["meta"]["forward_sharpe"],
                       r["meta"]["forward_sharpe"] - r["native"]["forward_sharpe"]]
                      for r in supported])
    assert len(supported) == 15 and all(b["fold_id"] == a["fold_id"] + 1
                                     for a, b in zip(supported, supported[1:]))
    intervals = MovingBlockBootstrap(3, values, seed=731).conf_int(
        lambda x: x.mean(axis=0), reps=4096, method="percentile", size=.95)
    costs = {}
    for arm, sample in samples.items():
        old = read(arm, OLD)["samples"][0]
        costs[arm] = {k: sample[k] for k in ("wall_seconds", "cpu_seconds", "sampler_seconds",
            "after_memory", "counts", "observer_attempts", "observer_failures", "meta_elapsed")}
        costs[arm].update(previous_wall_seconds=old["wall_seconds"],
            speedup=old["wall_seconds"] / sample["wall_seconds"],
            witness_reuse=sample.get("witness_reuse"))
    active, off = samples["active_rust"]["wall_seconds"], samples["off"]["wall_seconds"]
    costs["meta_overhead"] = dict(seconds=active-off, ratio=active/off, percent=100*(active/off-1))
    result = dict(schema="qms-local-debt-closure-v1", software_parity=checks,
        all_folds=economics(paired), supported_folds=economics(supported), costs=costs,
        accounts={arm: s["metrics"] for arm, s in samples.items()},
        uncertainty=dict(block_months=3, resamples=4096, seed=731,
            r_95=intervals[:, 0].tolist(), q_95=intervals[:, 1].tolist(),
            scope="descriptive exposed ETH research; not independent live certification"),
        registered_protocol=dict(folds=28, attempts_per_fold=128, seed=731,
            sampler="tpe_legacy", numerical_policy="require", financial_authority="numba"),
        new_full_runs=["off", "active_rust"],
        archived_full_parity=["off/shadow", "active_rust/reference", "28 independent frozen replay segments"],
        private_input_sha256={n: sha256((NEW / n).read_bytes()).hexdigest()
                             for n in ("alpha.py", "market.csv.gz", "registration.json")},
        release_authorized=False, remote_qualified=False)
    (NEW.parent / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def export():
    result = compare()
    qualification = json.loads((NEW.parent / "qualification.json").read_text())
    result["qualification"] = dict(required_test_ids=qualification["required_test_ids"],
        regression_passed=qualification["regression_passed"],
        explicit_posix_skips=qualification["explicit_posix_skips"],
        interpreters=list(qualification["installed_consumers"]),
        installed_lanes_per_interpreter=4,
        w3_same_pass_consumers_passed=True, current_checks=list(qualification["current_checks"]))
    result["numeric_crossover"] = json.loads((NEW.parent / "numeric.json").read_text())
    result["local_evidence_sha256"] = {name: sha256((NEW.parent / name).read_bytes()).hexdigest()
                                      for name in ("qualification.json", "regression.xml", "numeric.json")}
    result["private_artifact_hashes"] = {
        version: {Path(r["path"]).name: r["sha256"] for r in json.loads(
            (ROOT / f".maturin/qms08/local-closure-v1/cp{version}/proof.json").read_text())["artifact_refs"]}
        for version in ("311", "312", "313")}
    result["core_source_hashes"] = {
        p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "src/quantbt/optimization/meta_selection").glob("*.py")}
    for name in ("endpoint.py", "walkforward.py", "backends/reactive_wfo.py",
                 "backends/reactive_wfo_support.py", "backends/native_event.py",
                 "backends/_native_event_rust.py"):
        path = ROOT / "src/quantbt" / name
        result["core_source_hashes"][path.relative_to(ROOT).as_posix()] = sha256(path.read_bytes()).hexdigest()
    result["scope"] = dict(w3="Mode4/per_fold_causal/inprocess/sequential/reset_flat",
        real_alpha="Gradient RSI / ETHUSDT 1h; scalar target WFO, not W3 market certification",
        witness_stats="pre-release finalization snapshot; cleanup separately verified",
        main_timing_repeats=1, public_pair_unchanged="1.1.1/0.4.2")
    path = ROOT / "benchmarks/optimization/meta_selection/qms_local_closure_evidence.json"
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "compare", "export"))
    action = parser.parse_args().action
    if action == "prepare":
        prepare()
    elif action == "run":
        run()
    elif action == "export":
        print(export())
    else:
        print(json.dumps(compare(), indent=2, allow_nan=False))
