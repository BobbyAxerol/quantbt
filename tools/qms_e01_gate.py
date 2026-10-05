"""Revalidate E01 execution, artifact, command-log and immutable-receipt evidence."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import tarfile
import xml.etree.ElementTree as ET
import zipfile

from tools.qms_e01_audit import compare
from tools.qms_e01_source_guard import ROOT, verify as source_guard
from tools.qms_installed_consumers import source_hashes
from tools.qms_release_consumers import validate_consumers
from tools.qms01_baseline import GUIDE, GUIDE_SHA, ROUTES
from tools.verify_wheels import core_wheel_source_differences


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def check_tests(paths):
    members = {f"E01-T{i:02}": [] for i in range(1, 6)}
    cases = set()
    for path in paths:
        suites = ET.parse(path).getroot()
        for suite in suites.iter("testsuite"):
            if any(int(suite.get(k, 0)) for k in ("failures", "errors", "skipped")):
                raise ValueError("E01 JUnit contains failures/errors/skips")
        for case in suites.iter("testcase"):
            if any(case.find(k) is not None for k in ("failure", "error", "skipped")):
                raise ValueError("E01 JUnit contains non-passing case")
            identity = (case.get("classname"), case.get("name"))
            if not all(identity):
                raise ValueError("E01 JUnit lacks case identity")
            cases.add(identity)
            for i in range(1, 6):
                if identity[1].startswith(f"test_e01_t{i:02}_"):
                    members[f"E01-T{i:02}"].append(identity[1])
    if not cases or any(not rows for rows in members.values()):
        raise ValueError("E01 executed test group missing")
    return dict(unique_tests=len(cases), members=members)


def check_package(package):
    if (package.get("schema") != "qms-e01-installed-source-pair-v1"
            or (package.get("core"), package.get("native")) != ("1.1.2", "0.4.3")
            or package.get("publication") is not False or package.get("economic_claim") is not False
            or set(package.get("consumers", {})) != {"wheel", "sdist"}):
        raise ValueError("E01 installed proof schema/pair/lanes mismatch")
    artifacts = package.get("artifact_refs", [])
    if len(artifacts) != 3:
        raise ValueError("E01 artifacts missing")
    for ref in artifacts:
        path = (ROOT / ref["path"]).resolve()
        if (not path.is_relative_to(ROOT / ".maturin/qms08")
                or file_hash(path) != ref["sha256"] or path.stat().st_size != ref["bytes"]):
            raise ValueError("E01 artifact bytes/path changed")
    core = ROOT / next(r["path"] for r in artifacts if "quantbt_engine-" in r["path"] and r["path"].endswith(".whl"))
    if any(core_wheel_source_differences(core, ROOT / "src/quantbt").values()):
        raise ValueError("E01 installed wheel differs from canonical source")
    sdist = ROOT / next(r["path"] for r in artifacts if r["path"].endswith(".tar.gz"))
    with tarfile.open(sdist) as archive:
        members = {m.name.split("/src/quantbt/", 1)[1]: sha256(archive.extractfile(m).read()).hexdigest()
            for m in archive.getmembers() if m.isfile() and "/src/quantbt/" in m.name and m.name.endswith(".py")}
    expected = {p.relative_to(ROOT / "src/quantbt").as_posix(): file_hash(p) for p in (ROOT / "src/quantbt").rglob("*.py")}
    if members != expected:
        raise ValueError("E01 installed sdist differs from canonical source")
    native = ROOT / next(r["path"] for r in artifacts if "quantbt_native-" in r["path"])
    with zipfile.ZipFile(native) as archive:
        binaries = [name for name in archive.namelist() if name.endswith(".so")]
        if len(binaries) != 1:
            raise ValueError("E01 native wheel binary missing/ambiguous")
        native_hash = sha256(archive.read(binaries[0])).hexdigest()
    for bundle in package["consumers"].values():
        validate_consumers(bundle["consumers"], core=package["core"], native=package["native"])
        if bundle["consumer_source_sha256"] != source_hashes(ROOT):
            raise ValueError("E01 consumer source changed after execution")
        if set(bundle["logs"]) != set(bundle["consumers"]):
            raise ValueError("E01 consumer logs missing")
        for name, evidence in bundle["logs"].items():
            log = Path(evidence["log_path"]).resolve()
            if not log.is_relative_to(ROOT / ".maturin/qms08") or file_hash(log) != evidence["log_sha256"]:
                raise ValueError("E01 consumer log changed")
            payloads = [line for line in log.read_text().splitlines() if line.startswith("{")]
            if not payloads or json.loads(payloads[-1]) != bundle["consumers"][name]:
                raise ValueError("E01 consumer record is not its actual logged output")
        w3 = bundle["consumers"]["qms_local_consumer.py"]
        c03 = bundle["consumers"]["qms_c03_consumer.py"]
        if w3["native_extension_sha256"] != native_hash or c03["native_sha256"] != native_hash:
            raise ValueError("E01 loaded native binary differs from artifact")
    return dict(installed_lanes=["wheel", "sdist"], actual_consumer_runs=8,
                native_extension_sha256=native_hash, artifacts=artifacts)


def verify(*, before, after, package, junit):
    old, new = json.loads(before.read_text()), json.loads(after.read_text())
    compare(old, new)
    source = source_guard()
    if (old.get("schema") != "qms-e01-native-identity-v1" or new.get("schema") != old["schema"]
            or old["walkforward_sha256"] != source["before_sha256"]
            or new["walkforward_sha256"] != source["after_sha256"]):
        raise ValueError("E01 snapshot does not bind actual before/after source")
    for name, expected in old["historical_receipts"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT / "benchmarks/optimization/meta_selection") or file_hash(path) != expected:
            raise ValueError("E01 historical receipt changed")
    if [(r["mode"], r["schedule"]) for r in new["lanes"]] != list(ROUTES):
        raise ValueError("E01 native route matrix missing")
    if file_hash(ROOT / GUIDE) != GUIDE_SHA or new["guide_sha256"] != GUIDE_SHA:
        raise ValueError("E01 protected guide changed")
    groups = check_tests(junit)
    installed = check_package(json.loads(package.read_text()))
    return dict(schema="qms-e01-gate-v1", status="PASS_LOCAL_APPROVED_SCOPE",
        gates={f"E01-T{i:02}": "PASS" for i in range(1, 6)}, regression=groups,
        source_guard=source, native_account_rng_exact=True, installed=installed,
        inputs={str(p.relative_to(ROOT)): file_hash(p) for p in (before, after, package, *junit)},
        native_routes=new["lanes"], historical_receipts_unchanged=True,
        guide_sha256=GUIDE_SHA, remote="PENDING_FINAL_SOURCE_E08", public="PENDING_OWNER_RELEASE",
        empirical="NOT_ASSESSED_NO_NEW_STUDY", performance="NOT_BENCHMARKED_REPORT_ONLY",
        publication=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "package", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--junit", type=Path, action="append", required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    if output.exists():
        raise ValueError("sealed E01 gate exists; choose a fresh output")
    receipt = verify(**args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(status=receipt["status"], tests=receipt["regression"]["unique_tests"], publication=False)))
