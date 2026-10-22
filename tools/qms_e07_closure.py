"""Source-exact local E07 qualification and narrow inactive-scratch cleanup."""

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.qms_e07_contract import (
    ENTRY, GUIDE, LANE, ROOT, check_registration, file_hash, validate_matrix, write_once,
)
from tools.qms_pre05_qualification import passed_cases
from tools.qms_pre06_contract import EXTENSION_SHA, artifact_source, checked_hashes
from tools.qms_pre_e06_inventory import check_public_text

CLEANABLE = ("build-env", "wheel-consumer", "sdist-consumer", "stage/build")
SUITES = {"output-v1.xml": 13, "output-regression-v1.xml": 66,
    "lifecycle-v2.xml": 15, "final-v2.xml": 61,
    "gate-v1.xml": 12, "financial-transport-regression-v1.xml": 175,
}
MATRICES = {"source": "source-matrix-v3.json", "wheel": "wheel-matrix-v1.json",
            "sdist": "sdist-matrix-v1.json"}


def installed_identity(value):
    if (value["core"] != "1.1.2" or value["native"] != "0.4.3"
            or value["modules"] != 260 or value["native_sha256"] != EXTENSION_SHA
            or "site-packages" not in Path(value["core_origin"]).parts):
        raise ValueError("wrong/noninstalled E07 runtime identity")
    return value


def cell_key(row):
    return tuple(row["case"]), row["mode"], row["variant"]


def workload_evidence():
    reference = None
    evidence = {}
    for kind, name in MATRICES.items():
        value = json.loads((LANE / name).read_text())
        installed = kind != "source"
        count = validate_matrix(value, repeats=1 if installed else 3)
        if value["installed"] is not installed or value["cells"] != count:
            raise ValueError("wrong workload surface/count")
        if reference is None:
            reference = {cell_key(r): r["semantic_sha256"] for r in value["rows"]}
        for row in value["rows"]:
            if row["semantic_sha256"] != reference[cell_key(row)]:
                raise ValueError("installed source/financial/decision mismatch")
            if installed:
                installed_identity(row["identity"])
        evidence[kind] = dict(cells=count, sha256=file_hash(LANE / name))
        if installed:
            identity = json.loads((LANE / (kind+"-tests-identity.json")).read_text())
            installed_identity(identity)
            if identity != value["rows"][0]["identity"]:
                raise ValueError("installed tests/matrix origins differ")
            if len(passed_cases(LANE / (kind+"-tests-v1.xml"))) != 28:
                raise ValueError("incomplete installed lifecycle/output proof")
            if (len(passed_cases(LANE / (kind+"-bounds-v1.xml"))) != 8
                    or json.loads((LANE / (kind+"-bounds-v1-identity.json")).read_text()) != identity):
                raise ValueError("incomplete installed quantity/rejection proof")
            evidence[kind]["rerun_tests"] = 36
    return evidence


def privacy():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines())
    allowed = ("tools/qms_e07_", "tests/meta_selection/test_e07_",
        "tests/meta_selection/e07_support.py", "examples/wfo_meta_reactive_grid.py", "docs/",
        "upgrade/implement.md", "handoff/WFO_META_CURRENT.md",
        "src/quantbt/optimization/meta_selection/runtime.py",
        "benchmarks/optimization/meta_selection/qms_e07_closure.json")
    for name in names:
        if not name.startswith(allowed):
            raise ValueError(f"unapproved E07 patch path: {name}")
        patch = subprocess.check_output(["git", "diff", "--unified=0", ENTRY, "--", name], cwd=ROOT, text=True)
        additions = "\n".join(line[1:] for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++"))
        check_public_text(additions if patch else (ROOT / name).read_text())
    return dict(files=len(names), private_alpha_access=False, private_data_access=False,
                source_amendment="three_exact_opt_in_output_insertions", publication=False)


def scratch(name):
    if name not in CLEANABLE:
        raise ValueError("unreviewed E07 cleanup root")
    path = LANE / name
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("symlinked E07 cleanup root")
    subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=ROOT, check=True)
    marker = path.is_dir() if name == "stage/build" else (path / "pyvenv.cfg").is_file()
    if path.exists() and not marker:
        raise ValueError("not the registered E07 build/consumer scratch")
    return path


def cleanup(registration):
    roots = tuple(scratch(name) for name in CLEANABLE)
    if (LANE / "cleanup.json").exists():
        value = json.loads((LANE / "cleanup.json").read_text())
        if any(p.exists() for p in roots) or value["deleted"] != [str(p.relative_to(ROOT)) for p in roots]:
            raise ValueError("E07 cleanup identity drift")
        checked_hashes(value["protected_sha256"])
        return value
    processes = subprocess.check_output(["ps", "-eo", "args"], text=True)
    if any(str(p) in processes for p in roots):
        raise ValueError("E07 scratch still used by a process")
    protected = {**registration["protected_sha256"],
        **{str(p.relative_to(ROOT)): file_hash(p) for p in LANE.rglob("*")
           if p.is_file() and not any(p.is_relative_to(r) for r in roots)}}
    checked_hashes(protected)
    before = os.statvfs(ROOT)
    for path in roots:
        if not path.exists():
            raise ValueError("registered E07 scratch missing before first cleanup")
        shutil.rmtree(path)
    checked_hashes(protected)
    check_registration()
    after = os.statvfs(ROOT)
    value = dict(schema="qms-e07-cleanup-v1", deleted=[str(p.relative_to(ROOT)) for p in roots],
        protected_sha256=protected, protected_files=len(protected), runtime_unchanged_during_cleanup=True,
        free_bytes_before=before.f_bavail*before.f_frsize,
        free_bytes_after=after.f_bavail*after.f_frsize,
        actual_free_bytes_change=(after.f_bavail-before.f_bavail)*after.f_frsize,
        free_inodes_after=after.f_favail, cleaned_consumers_require_reinstall=True,
        retained_tooling=".maturin/qms08/g01-package-v1/consumer", publication=False)
    write_once(LANE / "cleanup.json", value)
    return value


def artifacts(registration):
    manifest = json.loads((LANE / "artifacts.json").read_text())
    for kind, name in manifest["paths"].items():
        if file_hash(Path(name)) != manifest["sha256"][kind]:
            raise ValueError("E07 exact artifact changed")
    if manifest["sha256"]["native"] != registration["native"]["wheel_sha256"]:
        raise ValueError("E07 reused a different native wheel")
    return {kind: artifact_source(Path(manifest["paths"][kind]), registration["core_inventory"])
            for kind in ("wheel", "sdist")}


def main():
    registered = check_registration()
    exact_artifacts = artifacts(registered)
    cases = set()
    for name, expected in SUITES.items():
        passed = passed_cases(LANE / name)
        if len(passed) != expected:
            raise ValueError(f"incomplete E07 qualification shard: {name}")
        cases.update(passed)
    evidence = workload_evidence()
    ownership = json.loads((LANE / "observability-v1.json").read_text())
    from tests.meta_selection.e07_support import CASES
    if (not ownership["diagnostic_only"] or len(ownership["rows"]) != 5
            or {tuple(r["case"]) for r in ownership["rows"]} != set(CASES)):
        raise ValueError("incomplete ownership diagnostics")
    safe = privacy()
    cleaned = cleanup(registered)
    verification = ["examples/wfo_meta_reactive_grid.py", "tests/meta_selection/e07_support.py",
        *[str(p.relative_to(ROOT)) for p in (ROOT / "tests/meta_selection").glob("test_e07_*.py")],
        *[str(p.relative_to(ROOT)) for p in (ROOT / "tools").glob("qms_e07_*.py")]]
    receipt = dict(schema="qms-e07-local-closure-v1", phase="QMS-E07", entry=ENTRY,
        status="COMPLETE_LOCAL_SOFTWARE_QUALIFIED_OPT_IN", runtime_files=len(registered["runtime_sha256"]),
        runtime_inventory_sha256=sha256(json.dumps(registered["runtime_sha256"], sort_keys=True).encode()).hexdigest(),
        runtime_change="three_exact_opt_in_output_insertions_only", guide_sha256=registered["guide_sha256"],
        artifacts=exact_artifacts, native_sha256=registered["native"]["wheel_sha256"], native_rebuilt=False,
        distinct_source_pass=len(cases), unexpected_skip=0, evidence=evidence,
        installed_rerun_pass=72, installed_reruns_not_new_distinct_tests=True,
        verification_source_sha256={n: file_hash(ROOT / n) for n in verification},
        privacy=safe, cleanup_sha256=file_hash(LANE / "cleanup.json"),
        protected_files=cleaned["protected_files"], freed_bytes=cleaned["actual_free_bytes_change"],
        mature_process_cells=3, financial_replay_for_reporting=0,
        observability_sha256=file_hash(LANE / "observability-v1.json"),
        scope="mode4_causal_event_callback_commands_continuous_numeric_w3_reset_flat",
        economic="REAL_MARKET_NOT_ASSESSED_NOT_PROMOTED", meta_default_changed=False,
        remote="DEFERRED_E08_OWNER_APPROVAL", next_phase_started=False, publication=False)
    check_public_text(json.dumps(receipt, sort_keys=True))
    write_once(ROOT / "benchmarks/optimization/meta_selection/qms_e07_closure.json", receipt)
    print(json.dumps(dict(status=receipt["status"], source_tests=len(cases), installed_tests=72,
        workload_cells=sum(e["cells"] for e in evidence.values()),
        freed_mib=receipt["freed_bytes"]/1024**2, publication=False)))


def verify_handoff():
    registered = check_registration()
    receipt = json.loads((ROOT / "benchmarks/optimization/meta_selection/qms_e07_closure.json").read_text())
    checked_hashes(receipt["verification_source_sha256"])
    cleaned = cleanup(registered)
    if (file_hash(LANE / "cleanup.json") != receipt["cleanup_sha256"]
            or artifacts(registered) != receipt["artifacts"]
            or file_hash(LANE / "observability-v1.json") != receipt["observability_sha256"]):
        raise ValueError("E07 cleanup/artifact handoff drift")
    for kind, name in MATRICES.items():
        if file_hash(LANE / name) != receipt["evidence"][kind]["sha256"]:
            raise ValueError("E07 retained matrix drift")
    return dict(status=receipt["status"], preserved_hashes=True,
        cleaned_consumers_require_reinstall=cleaned["cleaned_consumers_require_reinstall"], publication=False)


if __name__ == "__main__":
    main()
