"""Retain exact local receipts; remove only this run's inactive build scratch."""

import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from tools.qms08_package import ROOT, file_hash
from tools.qms_execution_source_guard import verify


def cleanup_previous():
    lane = ROOT / ".maturin/qms08/execution-package-v3"
    proof = json.loads((lane / "proof.json").read_text())
    paths = [lane / "proof.json", *lane.glob("*.log"),
             *[ROOT / r["path"] for r in proof["artifact_refs"]]]
    hashes = {str(p.relative_to(ROOT)): file_hash(p) for p in paths}
    before = shutil.disk_usage(ROOT).free
    removed = []
    for path in (lane / "consumer", lane / "stage/build"):
        if not path.exists():
            continue
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError("unreviewed scratch root")
        subprocess.check_call(["git", "check-ignore", "-q", str(path.relative_to(ROOT))], cwd=ROOT)
        shutil.rmtree(path)
        removed.append(str(path.relative_to(ROOT)))
    if hashes != {str(p.relative_to(ROOT)): file_hash(p) for p in paths}:
        raise ValueError("retained proof changed")
    output = ROOT / "benchmarks/optimization/meta_selection/qms_execution_cleanup_v3.json"
    if output.exists():
        raise ValueError("cleanup receipt already exists")
    receipt = dict(before_available_bytes=before, after_available_bytes=shutil.disk_usage(ROOT).free,
        removed=removed, retained_sha256=hashes, consumer_requires_reinstall=True,
        financial_qualification=False)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "retained_sha256"}))


def closeout():
    lane = ROOT / ".maturin/qms08/execution-package-v4"
    proof = json.loads((lane / "proof.json").read_text())
    if set(proof["records"]) != {"wheel", "sdist"}:
        raise ValueError("installed proof incomplete")
    if proof["source_guard"] != verify():
        raise ValueError("installed proof does not bind current source")
    supplement = json.loads((lane / "native-supplement.json").read_text())
    if len(supplement["routes"]) != 4 or not all(
            row["rust_fit_rank"] and row["observer_failures"] == 0 for row in supplement["routes"].values()):
        raise ValueError("installed native supplement incomplete")
    retained = lane / "test-logs"
    retained.mkdir(exist_ok=True)
    suites = {}
    for name in ("tests", "prepared", "regression", "final", "funding"):
        source = Path(f"/tmp/qms-execution-{name}.xml")
        target = retained / source.name
        shutil.copy2(source, target)
        xml = ET.parse(target).getroot()
        suites[name] = {key: sum(int(s.get(key, 0)) for s in xml.iter("testsuite"))
                        for key in ("tests", "failures", "errors", "skipped")}
    if suites["tests"]["tests"] != 48 or suites["tests"]["failures"] != 4:
        raise ValueError("unexpected historical initial test disposition")
    if any(suites[n][k] for n in ("prepared", "regression") for k in ("failures", "errors")):
        raise ValueError("final affected regression failed")
    if suites["prepared"]["tests"] != 4:
        raise ValueError("prepared replacement scope mismatch")
    # Initial XML's four failures were comparison-clock harness assertions,
    # not discarded tests. The exact four named reruns must pass.
    initial = ET.parse(retained / "qms-execution-tests.xml").getroot()
    replacement = ET.parse(retained / "qms-execution-prepared.xml").getroot()
    failed = {(t.get("classname"), t.get("name")) for t in initial.iter("testcase")
              if t.find("failure") is not None}
    rerun = {(t.get("classname"), t.get("name")) for t in replacement.iter("testcase")}
    if failed != rerun:
        raise ValueError("failed tests were not all rerun")
    if suites["final"]["tests"] != 151 or any(suites["final"][k] for k in ("failures", "errors", "skipped")):
        raise ValueError("final exact-source suite failed")
    if suites["funding"]["tests"] != 2 or any(suites["funding"][k] for k in ("failures", "errors", "skipped")):
        raise ValueError("funding follow-up failed")
    paths = [lane / "proof.json", lane / "native-supplement.json", *retained.glob("*.xml"), *lane.glob("*.log"),
             ROOT / "benchmarks/optimization/meta_selection/qms_execution_synthetic_study_v3.json",
             ROOT / "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"]
    paths += [ROOT / n for n in ("examples/wfo_meta_execution.py", "tools/qms_execution_study.py",
                                "tools/qms_execution_consumer.py", "tools/qms_execution_package.py")]
    paths += [ROOT / r["path"] for r in proof["artifact_refs"]]
    paths += list((ROOT / "benchmarks/optimization/meta_selection").glob("qms_execution_synthetic_study*.log"))
    before_hashes = {str(p.relative_to(ROOT)): file_hash(p) for p in paths}
    before = shutil.disk_usage(ROOT).free
    removed = []
    for path in (lane / "consumer", lane / "stage/build"):
        if not path.exists():
            continue
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError("unreviewed scratch root")
        subprocess.check_call(["git", "check-ignore", "-q", str(path.relative_to(ROOT))], cwd=ROOT)
        shutil.rmtree(path)
        removed.append(str(path.relative_to(ROOT)))
    if before_hashes != {str(p.relative_to(ROOT)): file_hash(p) for p in paths}:
        raise ValueError("retained evidence changed during cleanup")
    receipt = dict(schema="qms-execution-local-closeout-v1", source_guard=verify(),
        unique_passed_tests=48+suites["regression"]["tests"]+2, suites=suites,
        failed_exact_names_rerun=True, installed_proof_sha256=file_hash(lane / "proof.json"),
        retained_sha256=before_hashes, cleanup=dict(before_available_bytes=before,
            after_available_bytes=shutil.disk_usage(ROOT).free, removed=removed,
            source_stage_and_artifacts_retained=True, current_g01_tooling_retained=True,
            cleaned_consumer_requires_reinstall=True),
        software="PASS_LOCAL_BOUNDED", economics="NOT_PROMOTED_SYNTHETIC_ONLY",
        remote="DEFERRED_OWNER_GATE", publication=False)
    output = ROOT / "benchmarks/optimization/meta_selection/qms_execution_closeout_v4.json"
    if output.exists():
        raise ValueError("closeout receipts are immutable; choose a new version")
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps(dict(tests=receipt["unique_passed_tests"], cleanup=receipt["cleanup"], publication=False)))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup-previous", action="store_true")
    cleanup_previous() if parser.parse_args().cleanup_previous else closeout()
