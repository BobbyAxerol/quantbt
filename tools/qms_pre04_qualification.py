"""Source-bound C05 gate; no installed/public or economic promotion."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tools.qms_pre04_source_guard import ROOT, ENTRY, MANIFEST, verify
from tools.qms_pre_e06_inventory import GUIDE, GUIDE_SHA

Q6 = "tests.meta_selection.test_qms06_prepared"


def cases(path):
    result = {}
    for c in ET.parse(path).iter("testcase"):
        key = (c.get("classname"), c.get("name"))
        if not all(key) or key in result:
            raise ValueError("duplicate/missing case identity")
        result[key] = c
    if not result:
        raise ValueError("empty qualification shard")
    return result


def pass_case(c):
    return not any(c.find(k) is not None for k in ("failure", "error", "skipped"))


def reconcile(regression, current_q6):
    if len(regression) != 590 or len(current_q6) != 46:
        raise ValueError("incomplete historical regression/current native shard")
    failures = {k for k, c in regression.items() if not pass_case(c)}
    if len(failures) != 12 or any(k[0] != Q6 for k in failures):
        raise ValueError("unexpected regression failure outside archived QMS06 fixture")
    if any(k[0] != Q6 or k not in regression or not pass_case(c) for k, c in current_q6.items()):
        raise ValueError("non-passing/mismatched current native regression")
    if not failures <= current_q6.keys():
        raise ValueError("not every failed native case has a passing rerun")
    resolved = {k: c for k, c in regression.items() if pass_case(c)}
    resolved.update(current_q6)
    if len(resolved) != 590:
        raise ValueError("regression identities lost")
    return resolved


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def build(lane, native):
    source = verify()
    if file_hash(ROOT/GUIDE) != GUIDE_SHA:
        raise ValueError("scientific guide changed")
    core = cases(lane/"policy-final-verified.xml")
    if len(core) != 104 or any(not pass_case(c) for c in core.values()):
        raise ValueError("new policy qualification incomplete or non-passing")
    previous = cases(lane/"regression.xml")
    rerun = cases(lane/"prepared-current.xml")
    regression = reconcile(previous, rerun)
    extra = cases(lane/"docs-final-verified.xml")
    if len(extra) != 7 or any(not pass_case(c) for c in extra.values()):
        raise ValueError("documentation/example gate failed")
    names = subprocess.check_output(["git", "ls-files", "--", "src", "rust"], cwd=ROOT, text=True).splitlines()
    historical = json.loads((ROOT/"benchmarks/optimization/meta_selection/qms_pre_e06_03_closure.json").read_text())
    retained = dict(historical["historical_preserved_sha256"])
    retained.update({"benchmarks/optimization/meta_selection/qms_pre_e06_03_"+s+".json": file_hash(
        ROOT/("benchmarks/optimization/meta_selection/qms_pre_e06_03_"+s+".json"))
        for s in ("closure", "cost", "reviewed_source")})
    for name, expected in retained.items():
        if file_hash(ROOT/name) != expected:
            raise ValueError("historical evidence changed")
    logs = ("policy-final-verified.xml", "regression.xml", "prepared-current.xml", "docs-final-verified.xml")
    union = set(core) | set(regression) | set(extra)
    return dict(schema="qms-pre-e06-04-closure-v1", phase="PRE-E06-04",
        status="PASS_LOCAL_APPROVED_C05_RUNTIME", baseline=ENTRY, source_guard=source,
        new_policy_pass=len(core), old_regression_unique_pass=len(regression),
        docs_example_pass=len(extra), distinct_scoped_pass=len(union), skip=0,
        historical_fixture_failure_disposition=dict(initial_failures=12,
            reason="QMS06 fixture selected archived 0.4.3.dev2 without legacy_zero_base_v1",
            current_rerun_pass=46, no_production_fallback_or_tolerance_relaxed=True),
        junit_sha256={str((lane/n).relative_to(ROOT)): file_hash(lane/n) for n in logs},
        reviewed_source_manifest_sha256=file_hash(MANIFEST),
        runtime_source_sha256={n: file_hash(ROOT/n) for n in sorted(names)},
        verification_source_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in [
            *sorted((ROOT/"tests/meta_selection").glob("test_pre04*.py")),
            ROOT/"tools/qms_pre04_qualification.py", ROOT/"tools/qms_pre04_source_guard.py",
            ROOT/"examples/wfo_conditional_policies.py",
            ROOT/"benchmarks/optimization/meta_selection/benchmark_pre04_policy.py"]},
        historical_preserved_sha256=retained, native_provider_sha256=file_hash(native),
        software_cost_sha256=file_hash(ROOT/"benchmarks/optimization/meta_selection/qms_pre_e06_04_cost.json"),
        guide_sha256=GUIDE_SHA, old_defaults_changed=False,
        financial_engine_or_ridge_changed=False, economic="NOT_ASSESSED", publication=False,
        installed_current_source="DEFERRED_PRE_E06_06", remote="DEFERRED_E08_OWNER_APPROVAL",
        public="PENDING_OWNER_PUBLICATION")


def cleanup_snapshot(receipt, lane, native, closure):
    """Verify protected bytes and budget; this phase has no disposable builds."""
    protected = {}
    for key in ("runtime_source_sha256", "verification_source_sha256",
                "historical_preserved_sha256", "junit_sha256"):
        protected.update({str(ROOT/name): digest for name, digest in receipt[key].items()})
    protected.update({str(ROOT/GUIDE): GUIDE_SHA,
                      str(MANIFEST): receipt["reviewed_source_manifest_sha256"],
                      str(native.resolve()): receipt["native_provider_sha256"],
                      str(closure.resolve()): file_hash(closure),
                      str(ROOT/"benchmarks/optimization/meta_selection/qms_pre_e06_04_cost.json"):
                          receipt["software_cost_sha256"]})
    protected.update({str(p): file_hash(p) for p in lane.rglob("*") if p.is_file()})
    before = {name: file_hash(Path(name)) for name in protected}
    if before != protected:
        raise ValueError("protected evidence/source changed before cleanup")
    fs_before = os.statvfs(ROOT)
    paths = [p for p in lane.rglob("*") if p.is_file()]
    logical_bytes = sum(p.stat().st_size for p in paths)
    allocated_bytes = sum(p.stat().st_blocks*512 for p in paths)
    if allocated_bytes > 512*1024**2 or fs_before.f_bavail*fs_before.f_frsize < 5*1024**3:
        raise ValueError("registered scratch/headroom budget exceeded")
    # Zero deletion is intentional: journals and failed XML are retained evidence.
    after = {name: file_hash(Path(name)) for name in protected}
    if after != before:
        raise ValueError("protected evidence/source changed during cleanup")
    fs_after = os.statvfs(ROOT)
    return dict(schema="qms-pre-e06-04-cleanup-v1", status="PASS_ZERO_DELETION",
                reviewed_reclaimable_paths=[], deleted_paths=[], new_environment=False,
                new_native_build=False, task_attributed_reclaimed_bytes=0,
                logical_lane_bytes=logical_bytes, allocated_lane_bytes=allocated_bytes,
                protected_file_count=len(protected), protected_sha256=protected,
                protected_before_after_equal=True,
                before_available_bytes=fs_before.f_bavail*fs_before.f_frsize,
                after_available_bytes=fs_after.f_bavail*fs_after.f_frsize,
                before_free_inodes=fs_before.f_favail, after_free_inodes=fs_after.f_favail)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lane", type=Path, required=True)
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cleanup-output", type=Path)
    args = p.parse_args()
    receipt = build(args.lane.resolve(), args.native)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    if args.cleanup_output is not None:
        cleanup = cleanup_snapshot(receipt, args.lane.resolve(), args.native, args.output)
        args.cleanup_output.write_text(json.dumps(cleanup, indent=2, sort_keys=True)+"\n")
    print(json.dumps({k: receipt[k] for k in ("status", "new_policy_pass", "old_regression_unique_pass",
                                            "docs_example_pass", "distinct_scoped_pass")}, sort_keys=True))


if __name__ == "__main__":
    main()
