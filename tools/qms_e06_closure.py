"""Local E06 evidence/cleanup gate; no financial policy or release operations."""

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.qms_e06_qualification import LANE, MODES, REPEATS, ROOT, file_hash, write_once
from tools.qms_pre05_qualification import passed_cases
from tools.qms_pre06_contract import (
    EXTENSION_SHA, GUIDE, artifact_source, checked_hashes, source_inventory,
)
from tools.qms_pre_e06_inventory import check_public_text

ENTRY = "c0dfcc5fc0e9830630c0c81a4cec847581b4eebf"
CLEANABLE = ("wheel-consumer", "sdist-consumer")


def validate_matrix(value, registration, *, installed):
    rows = value["rows"]
    expected_count = 6 if installed else 6 * REPEATS
    if value["installed"] is not installed or value["cells"] != expected_count or len(rows) != expected_count:
        raise ValueError("incomplete E06 workload matrix")
    for mode in MODES:
        for witness in (False, True):
            sample = [r for r in rows if r["mode"] == mode and r["witness"] is witness]
            if len(sample) != (1 if installed else REPEATS):
                raise ValueError("missing/duplicated E06 workload")
            for row in sample:
                if (row["semantic_sha256"] != registration["expected_cells"][mode]
                        or not row["account_rebuild_exact"] or not row["applied_params"]
                        or row["observer_failures"]):
                    raise ValueError("logical work or accounting mismatch")
                if mode != "off" and (row["models"] < 1 or row["minimum_origins"] < 12
                                       or row["raw_pairs_checked"] < 2):
                    raise ValueError("cold fallback is not mature qualification")
                if installed:
                    identity = row["identity"]
                    if (identity["core"] != "1.1.2" or identity["native"] != "0.4.3"
                            or identity["modules"] != 260 or identity["native_sha256"] != EXTENSION_SHA
                            or "site-packages" not in Path(identity["core_origin"]).parts):
                        raise ValueError("noninstalled/wrong artifact identity")
    return expected_count


def privacy():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines())
    allowed = ("tools/qms_e06_", "tests/meta_selection/test_e06_", "docs/",
               "upgrade/implement.md", "benchmarks/optimization/meta_selection/qms_e06_closure.json")
    for name in names:
        if not name.startswith(allowed):
            raise ValueError(f"unapproved E06 file: {name}")
        patch = subprocess.check_output(["git", "diff", "--unified=0", ENTRY, "--", name], cwd=ROOT, text=True)
        additions = "\n".join(l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
        check_public_text(additions if patch else (ROOT / name).read_text())
    return dict(files=len(names), private_alpha_access=False, publication=False)


def scratch(name):
    if name not in CLEANABLE:
        raise ValueError("unreviewed E06 cleanup path")
    path = LANE / name
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("symlinked E06 cleanup root")
    subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=ROOT, check=True)
    if path.exists() and not (path / "pyvenv.cfg").is_file():
        raise ValueError("not the registered disposable consumer")
    return path


def cleanup(registration):
    roots = tuple(scratch(n) for n in CLEANABLE)
    if (LANE / "cleanup.json").exists():
        value = json.loads((LANE / "cleanup.json").read_text())
        if any(p.exists() for p in roots) or value["deleted"] != [str(p.relative_to(ROOT)) for p in roots]:
            raise ValueError("cleanup root drift")
        checked_hashes(value["protected_sha256"])
        return value
    processes = subprocess.check_output(["ps", "-eo", "args"], text=True)
    if any(str(p) in processes for p in roots):
        raise ValueError("consumer still in use")
    protected = {**registration["protected_sha256"],
        **{str(p.relative_to(ROOT)): file_hash(p) for p in LANE.rglob("*")
           if p.is_file() and not any(p.is_relative_to(r) for r in roots)}}
    checked_hashes(protected)
    before = os.statvfs(ROOT)
    for path in roots:
        if not path.exists():
            raise ValueError("missing disposable consumer before first cleanup")
        shutil.rmtree(path)
    checked_hashes(protected)
    if (source_inventory() != registration["runtime_sha256"]
            or file_hash(ROOT / GUIDE) != registration["guide_sha256"]):
        raise ValueError("runtime changed during cleanup")
    after = os.statvfs(ROOT)
    value = dict(schema="qms-e06-cleanup-v1", deleted=[str(p.relative_to(ROOT)) for p in roots],
        protected_sha256=protected, protected_files=len(protected), runtime_unchanged=True,
        free_bytes_before=before.f_bavail * before.f_frsize,
        free_bytes_after=after.f_bavail * after.f_frsize,
        actual_free_bytes_change=after.f_bavail * after.f_frsize - before.f_bavail * before.f_frsize,
        free_inodes_after=after.f_favail, cleaned_consumers_require_reinstall=True,
        retained_tooling=".maturin/qms08/g01-package-v1/consumer", publication=False)
    write_once(LANE / "cleanup.json", value)
    return value


def main():
    registration = json.loads((LANE / "registration.json").read_text())
    checked_hashes(registration["protected_sha256"])
    if (source_inventory() != registration["runtime_sha256"]
            or file_hash(ROOT / GUIDE) != registration["guide_sha256"]):
        raise ValueError("source/artifact drift")
    artifacts = {k: artifact_source(Path(registration["artifacts"][k]), registration["core_inventory"])
                 for k in ("wheel", "sdist")}
    suites = {"financial-contract-v1.xml": 71, "mature-no-leakage-v1.xml": 23,
              "backend-meta-v1.xml": 16}
    cases = set()
    for name, expected in suites.items():
        passed = passed_cases(LANE / name)
        if len(passed) != expected:
            raise ValueError(f"incomplete E06 regression: {name}")
        cases.update(passed)
    harness = passed_cases(LANE / "closure-harness-v1.xml")
    if len(harness) != 14:
        raise ValueError("incomplete E06 gate harness")
    cases.update(harness)
    evidence = {}
    for kind in ("source", "wheel", "sdist"):
        value = json.loads((LANE / (kind + "-matrix-v1.json")).read_text())
        count = validate_matrix(value, registration, installed=kind != "source")
        evidence[kind] = dict(cells=count, sha256=file_hash(LANE / (kind + "-matrix-v1.json")))
        if kind != "source":
            proof = json.loads((LANE / (kind + "-backend-meta-v1.json")).read_text())
            if (proof["tests"] != 16 or proof["skipped"] or not proof["installed_only"]
                    or proof["identity"] != value["rows"][0]["identity"]
                    or len(passed_cases(LANE / (kind + "-backend-meta-v1.xml"))) != 16):
                raise ValueError("missing installed four-family proof")
            evidence[kind]["mature_tests"] = 16
    kernel = json.loads((LANE / "intrabar-kernel-v1.json").read_text())
    if kernel["fixture"]["bars"] != 2000 or not kernel["evidence"]["terminal_and_path_parity"]:
        raise ValueError("financial benchmark lacks matched parity")
    safe = privacy()
    cleaned = cleanup(registration)
    verification = ["tools/qms_e06_qualification.py", "tools/qms_e06_closure.py",
        "tests/meta_selection/test_e06_intrabar_fold_contract.py",
        "tests/meta_selection/test_e06_intrabar_meta.py", "tests/meta_selection/test_e06_closure.py"]
    receipt = dict(schema="qms-e06-local-closure-v1", phase="QMS-E06",
        status="COMPLETE_LOCAL_SOFTWARE_QUALIFIED_OPT_IN", runtime_entry=ENTRY,
        runtime_inventory_sha256=sha256(json.dumps(registration["runtime_sha256"], sort_keys=True).encode()).hexdigest(),
        runtime_files=len(registration["runtime_sha256"]), runtime_changed=False,
        guide_sha256=registration["guide_sha256"], artifacts=artifacts,
        native_sha256=file_hash(registration["artifacts"]["native"]),
        distinct_source_pass=len(cases), unexpected_skip=0, evidence=evidence,
        installed_rerun_pass=32, installed_reruns_not_new_distinct_tests=True,
        verification_source_sha256={n: file_hash(ROOT / n) for n in verification},
        privacy=safe, cleanup_sha256=file_hash(LANE / "cleanup.json"),
        protected_files=cleaned["protected_files"], freed_bytes=cleaned["actual_free_bytes_change"],
        financial_benchmark_sha256=file_hash(LANE / "intrabar-kernel-v1.json"),
        economic="REAL_MARKET_NOT_ASSESSED_NOT_PROMOTED", meta_default_changed=False,
        remote="DEFERRED_E08_OWNER_APPROVAL", next_phase_started=False, publication=False)
    check_public_text(json.dumps(receipt, sort_keys=True))
    write_once(ROOT / "benchmarks/optimization/meta_selection/qms_e06_closure.json", receipt)
    print(json.dumps(dict(status=receipt["status"], source_tests=len(cases), installed_tests=32,
        freed_mib=receipt["freed_bytes"] / 1024**2, publication=False)))


def verify_handoff():
    receipt = json.loads((ROOT / "benchmarks/optimization/meta_selection/qms_e06_closure.json").read_text())
    registration = json.loads((LANE / "registration.json").read_text())
    checked_hashes(receipt["verification_source_sha256"])
    checked_hashes(registration["protected_sha256"])
    cleaned = cleanup(registration)
    if (file_hash(LANE / "cleanup.json") != receipt["cleanup_sha256"]
            or source_inventory() != registration["runtime_sha256"]
            or file_hash(ROOT / GUIDE) != receipt["guide_sha256"]
            or not cleaned["runtime_unchanged"]):
        raise ValueError("E06 final handoff drift")
    for kind in ("source", "wheel", "sdist"):
        evidence = receipt["evidence"][kind]
        if file_hash(LANE / (kind + "-matrix-v1.json")) != evidence["sha256"]:
            raise ValueError("E06 retained matrix drift")
    for kind in ("wheel", "sdist"):
        if artifact_source(Path(registration["artifacts"][kind]), registration["core_inventory"]) != receipt["artifacts"][kind]:
            raise ValueError("E06 retained artifact drift")
    return dict(status=receipt["status"], runtime_unchanged=True, preserved_hashes=True,
        cleaned_consumers_require_reinstall=True, publication=False)


if __name__ == "__main__":
    main()
