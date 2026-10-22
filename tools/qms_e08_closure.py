"""Seal local E08 evidence and remove only its registered inactive scratch."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from tools.qms_e08_package import LANE as PACKAGE
from tools.qms_e08_regression import LANE, commands
from tools.qms_e08_source_guard import ROOT, verify
from tools.qms_installed_execution import EXPECTED, artifact_manifest, digest, validate_row
from tools.qms_pre06_contract import checked_hashes, write_once
from tools.qms_pre_e06_inventory import check_public_text
from tools.qms_pre05_qualification import REGISTERED_NA, passed_cases

CLEANABLE = ("build-env", "pair", "sdist", "stage/build")
META_REPAIR = frozenset({("tests.meta_selection.test_pre_e06_06_exit", "test_privacy_gate_current_public_patch")})
PATCH_FILES = frozenset({
    ".github/workflows/qms-candidate.yml", "README.md", "upgrade/implement.md",
    "examples/intrabar_bracket_diagnostic.py", "tests/meta_selection/e08_support.py",
    "tests/meta_selection/test_e07_closure.py", "tests/meta_selection/test_e07_mature.py",
    "tests/meta_selection/test_pre_e06_06_artifacts.py", "tests/meta_selection/test_pre_e06_06_exit.py",
    "tools/qms_e07_contract.py", "tools/qms_installed_execution.py", "tools/qms_pre05_source_guard.py",
    "tools/qms_pre06_contract.py", "tools/qms_pre06_qualification.py",
    "src/quantbt/wfo_execution.py", "src/quantbt/optimization/meta_selection/telemetry.py",
})
PATCH_PREFIXES = ("docs/", "handoff/", "tools/qms_e08_", "tests/meta_selection/test_e08_",
                  "benchmarks/optimization/meta_selection/qms_e08_")


def privacy():
    verify()
    names = set(subprocess.check_output(["git", "diff", "--name-only", "0da632e"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines())
    for name in sorted(names):
        path = ROOT/name
        if name not in PATCH_FILES and not name.startswith(PATCH_PREFIXES):
            raise ValueError(f"unapproved E08 patch file: {name}")
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("E08 public patch must be a regular repository file")
        patch = subprocess.check_output(["git", "diff", "--unified=0", "0da632e", "--", name], cwd=ROOT, text=True)
        additions = "\n".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
        check_public_text(additions if patch else path.read_text())
    return dict(checked_files=len(names), private_alpha_access=False, private_study=False, publication=False)


def regression(label, path, row, *, repaired_by=frozenset()):
    registration = json.loads(path.with_suffix(".registration.json").read_text())
    admitted = REGISTERED_NA if label == "meta" else frozenset()
    if (registration["source_guard"] != verify() or registration["command"] != list(map(str, commands()[label]))
            or registration["admitted_na"] != [list(c) for c in sorted(admitted)]
            or registration["publication"] is not False or row["publication"] is not False
            or row["returncode"] not in ((1,) if repaired_by else (0,))):
        raise ValueError("regression registration/returncode drift")
    log, xml = path.with_suffix(".log"), path.with_suffix(".xml")
    if digest(log) != row["log_sha256"] or digest(xml) != row["xml_sha256"]:
        raise ValueError("source regression evidence changed")
    failures = {(c.get("classname"), c.get("name")) for c in ET.parse(xml).iter("testcase")
                if c.find("failure") is not None or c.find("error") is not None}
    if failures != repaired_by:
        raise ValueError("unexpected failure or missing registered verification repair")
    cases = set(passed_cases(xml, admitted_na=admitted, repaired_by=repaired_by))
    skips = { (c.get("classname"), c.get("name")) for c in ET.parse(xml).iter("testcase") if c.find("skipped") is not None }
    if skips != admitted:
        raise ValueError("incomplete registered N/A comparators")
    if not repaired_by and (row["distinct_pass"] != len(cases) or {tuple(c) for c in row["cases"]} != cases
                           or row["admitted_skips"] != len(skips)):
        raise ValueError("self-attested regression counts differ from XML")
    return cases, dict(distinct_pass=len(cases), admitted_skips=len(skips),
        receipt=str(path.relative_to(ROOT)), sha256=digest(path),
        registration_sha256=digest(path.with_suffix(".registration.json")),
        repaired_failures=[list(c) for c in sorted(repaired_by)])


def scratch(name):
    if name not in CLEANABLE:
        raise ValueError("unreviewed E08 cleanup root")
    path = PACKAGE/name
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("symlinked E08 cleanup root")
    subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=ROOT, check=True)
    if not path.is_dir() or (name != "stage/build" and not (path/"pyvenv.cfg").is_file()):
        raise ValueError("registered E08 scratch identity missing")
    return path


def verify_local():
    guard = verify()
    proof = json.loads((PACKAGE/"proof.json").read_text())
    manifest = artifact_manifest(proof)
    installed = json.loads((PACKAGE/"installed-execution-proof.json").read_text())
    request = json.loads((PACKAGE/"installed-execution-proof/manifest.json").read_text())
    if request != manifest or set(installed["rows"]) != {k+"-"+g for k in ("pair", "sdist") for g in EXPECTED}:
        raise ValueError("incomplete exact execution proof")
    for key, row in installed["rows"].items():
        validate_row(row, key.split("-", 1)[1], manifest)
    for name, expected in installed["retained_sha256"].items():
        if digest(PACKAGE/"installed-execution-proof"/name) != expected:
            raise ValueError("installed execution evidence changed")
    integrated = json.loads((PACKAGE/"integrated-proof.json").read_text())
    if (set(integrated["rows"]) != {"pair", "sdist"} or any(len(r) != 8 for r in integrated["rows"].values())
            or integrated["artifact_refs"] != proof["artifact_refs"] or integrated["publication"] is not False):
        raise ValueError("incomplete integrated exact artifacts")
    for name, expected in integrated["retained_sha256"].items():
        if digest(PACKAGE/"integrated-proof"/name) != expected:
            raise ValueError("integrated installed evidence changed")
    regressions = {}
    cases = set()
    for label in ("meta", "wfo", "account", "plot"):
        matches = sorted(LANE.glob(label+"-regression-*.json"))
        matches = [p for p in matches if not p.name.endswith(".registration.json")]
        records = [(p, json.loads(p.read_text())) for p in matches]
        if not records:
            raise ValueError(f"no {label} regression")
        path, row = max(records, key=lambda item: item[0].stat().st_mtime_ns)
        if label == "meta" and row["returncode"]:
            repairs = [p for p in LANE.glob("meta-repair-regression-*.json") if not p.name.endswith(".registration.json")]
            if not repairs:
                raise ValueError("missing narrow verification rerun")
            repair_path = max(repairs, key=lambda p: p.stat().st_mtime_ns)
            repaired, repair_summary = regression("meta-repair", repair_path, json.loads(repair_path.read_text()))
            if not META_REPAIR <= repaired:
                raise ValueError("privacy failure was not actually rerun")
            original, summary = regression(label, path, row, repaired_by=META_REPAIR)
            cases.update(original | repaired)
            regressions[label] = dict(**summary, repair=repair_summary, status="PASS_AFTER_NARROW_VERIFICATION_REPAIR")
        else:
            actual, summary = regression(label, path, row)
            cases.update(actual)
            regressions[label] = dict(**summary, status="PASS")
    return dict(source_guard=guard, artifacts=proof["artifact_refs"], source_distinct_pass=len(cases),
        regressions=regressions, installed_execution_pass=sum(r["counts"]["tests"] for r in installed["rows"].values()),
        installed_integrated_consumers=sum(len(r) for r in integrated["rows"].values()),
        installed_execution_sha256=digest(PACKAGE/"installed-execution-proof.json"),
        integrated_installed_sha256=digest(PACKAGE/"integrated-proof.json"))


def cleanup():
    roots = tuple(scratch(n) for n in CLEANABLE)
    processes = subprocess.check_output(["ps", "-eo", "args"], text=True)
    if any(str(p) in processes for p in roots):
        raise ValueError("E08 scratch still in use")
    protected = {str(p.relative_to(ROOT)): digest(p) for p in LANE.rglob("*")
        if p.is_file() and not any(p.is_relative_to(r) for r in roots)}
    for ref in json.loads((PACKAGE/"proof.json").read_text())["artifact_refs"]:
        protected[ref["path"]] = ref["sha256"]
    checked_hashes(protected)
    before = os.statvfs(ROOT)
    for path in roots:
        shutil.rmtree(path)
    checked_hashes(protected)
    after = os.statvfs(ROOT)
    result = dict(schema="qms-e08-cleanup-v1", deleted=[str(p.relative_to(ROOT)) for p in roots],
        protected_sha256=protected, protected_files=len(protected),
        free_bytes_before=before.f_bavail*before.f_frsize, free_bytes_after=after.f_bavail*after.f_frsize,
        actual_free_bytes_change=(after.f_bavail-before.f_bavail)*after.f_frsize,
        free_inodes_after=after.f_favail, cleaned_consumers_require_reinstall=True,
        retained_tooling=".maturin/qms08/g01-package-v1/consumer", publication=False)
    write_once(LANE/"cleanup.json", result)
    return result


def main():
    destination = ROOT/"benchmarks/optimization/meta_selection/qms_e08_closure.json"
    if destination.exists() or (LANE/"cleanup.json").exists():
        raise ValueError("refuse closure/cleanup overwrite")
    qualification = verify_local()
    safe = privacy()
    cleaned = cleanup()
    if verify_local() != qualification:
        raise ValueError("qualification changed during cleanup")
    receipt = dict(schema="qms-e08-local-closure-v1", phase="QMS-E08",
        status="COMPLETE_LOCAL_SOFTWARE_QUALIFIED_OPT_IN", **qualification,
        cleanup_sha256=digest(LANE/"cleanup.json"), freed_bytes=cleaned["actual_free_bytes_change"],
        protected_files=cleaned["protected_files"], remote="DEFERRED_BY_OWNER_LOCAL_ONLY",
        privacy=safe,
        public="PENDING_OWNER_APPROVED_PUBLICATION", economic_promotion=False, publication=False,
        source_sha256={str(p.relative_to(ROOT)): digest(p) for p in (
            *(ROOT/"tools").glob("qms_e08_*.py"), *(ROOT/"tests/meta_selection").glob("test_e08_*.py"))})
    check_public_text(json.dumps(receipt, sort_keys=True))
    write_once(destination, receipt)
    print(json.dumps({k: receipt[k] for k in ("status", "source_distinct_pass", "installed_execution_pass",
        "installed_integrated_consumers", "freed_bytes", "remote", "publication")}))


if __name__ == "__main__":
    main()
