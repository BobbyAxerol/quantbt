"""Source-bound local exit gate and reviewed phase-only cleanup."""

import argparse
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

from tools.qms08_package import ROOT, file_hash
from tools.qms_pre06_contract import (
    CLEANABLE, ENTRY, LANE, OWNER, PRE05, artifact_source, checked_hashes,
    cleanup_path, prerequisites, validate_matrix, write_once,
)
from tools.qms_pre05_qualification import REGISTERED_NA, passed_cases
from tools.qms_pre_e06_inventory import check_public_text
from tools.qms_release_consumers import validate_consumers
from tools.qms_pre06_regression import ACCOUNT


def collection_disposition(paths, account_xml):
    """Only the recorded missing test dependency, never a financial failure."""
    if {p.name for p in paths} != {"account-regression.xml", "account-regression-v2.xml"} or len(paths) != 2:
        raise ValueError("unexpected collection attempts")
    passed = passed_cases(account_xml)
    modules = {name for name, _ in passed}
    if modules != {"tests." + n.replace("/", ".") for n in ACCOUNT}:
        raise ValueError("all original account modules must separately pass")
    for path in paths:
        cases = list(ET.parse(path).iter("testcase"))
        if len(cases) != 1:
            raise ValueError("collection attempt contains executed/extra cases")
        case = cases[0]
        error = case.find("error")
        if (case.get("classname") != "" or case.get("name") != "tests.test_phase59_linear_accounting_fill_replay"
                or error is None or error.get("message") != "collection failure"
                or "ModuleNotFoundError: No module named 'hypothesis'" not in (error.text or "")
                or any(case.find(k) is not None for k in ("failure", "skipped"))):
            raise ValueError("not the registered missing Hypothesis collection error")
    dependency = json.loads((LANE / "test-dependency-reuse.json").read_text())
    if (dependency["versions"]["hypothesis"] != "6.164.0"
            or dependency["versions"]["sortedcontainers"] != "2.4.0"
            or dependency["changed_numeric_dependencies"] is not False
            or not dependency["record_verified_sha256"]):
        raise ValueError("test-dependency correction not verified")
    return dict(status="RESOLVED_TEST_ENV_COLLECTION_ONLY", counted_as_pass=False,
                collection_junit_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in paths},
                separately_passing_account_junit_sha256=file_hash(account_xml),
                account_modules=len(modules), account_cases=len(passed),
                test_dependency_receipt_sha256=file_hash(LANE / "test-dependency-reuse.json"))


def regression(xmls, *, failed_xmls=()):
    cases, actual_na = set(), set()
    for path in xmls:
        cases.update(passed_cases(path, admitted_na=REGISTERED_NA))
        actual_na.update((c.get("classname"), c.get("name")) for c in ET.parse(path).iter("testcase")
                         if c.find("skipped") is not None)
    repaired = {}
    for path in failed_xmls:
        failed = {(c.get("classname"), c.get("name")) for c in ET.parse(path).iter("testcase")
                  if any(c.find(k) is not None for k in ("failure", "error"))}
        if not failed or not failed <= cases:
            raise ValueError("unresolved regression failures")
        cases.update(passed_cases(path, admitted_na=REGISTERED_NA, repaired_by=cases))
        actual_na.update((c.get("classname"), c.get("name")) for c in ET.parse(path).iter("testcase")
                         if c.find("skipped") is not None)
        repaired[str(path.relative_to(ROOT))] = sorted(failed)
    if actual_na != REGISTERED_NA:
        raise ValueError("unregistered/missing N/A cases")
    # Every previously passing identity in the affected regression must run again.
    prior = json.loads(PRE05.read_text())
    required = set()
    for name in prior["junit_sha256"]:
        required.update(passed_cases(ROOT / name, admitted_na=REGISTERED_NA))
    if not required <= cases:
        raise ValueError(f"previous passing regression cases not rerun: {sorted(required-cases)}")
    return dict(distinct_pass=len(cases), registered_na=len(actual_na),
                cases=sorted(cases), repaired_failures=repaired,
                junit_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in xmls},
                failed_junit_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in failed_xmls})


def installed():
    path = LANE / "package-v1/proof.json"
    proof = json.loads(path.read_text())
    registration = json.loads((LANE / "registration.json").read_text())
    if proof["status"] != "PASS_LOCAL_INSTALLED_ARTIFACTS" or proof["source"] != prerequisites():
        raise ValueError("installed proof is stale/incomplete")
    if file_hash(LANE / "registration.json") != proof["registration_sha256"]:
        raise ValueError("registration changed")
    checked_hashes(proof["artifact_refs"])
    checked_hashes(proof["logs"])
    for name in proof["artifact_refs"]:
        path = ROOT / name
        if "quantbt_engine" in path.name:
            artifact_source(path, registration["core_inventory"])
    if set(proof["results"]) != {"wheel", "sdist"}:
        raise ValueError("both independent installed artifacts required")
    fitted = 0
    for kind, result in proof["results"].items():
        validate_consumers(result["mandatory"]["consumers"], core="1.1.2", native="0.4.3")
        checked_hashes(result["mandatory"]["consumer_source_sha256"])
        full_path = ROOT / result["full_work"]
        if file_hash(full_path) != result["full_work_sha256"]:
            raise ValueError("installed full-work receipt changed")
        full = json.loads(full_path.read_text())
        validate_matrix(full["cells"], registration["expected_cells"])
        if (full["installed_only"] is not True or full["skipped"]
                or not full["exact_conditional_continuation"]
                or full["continuation_states"] != ["COMPLETE", "FAIL", "PRUNED"]
                or not full["conditional_actual_folds"]
                or kind + "-consumer" not in full["identity"]["core_origin"]):
            raise ValueError("missing installed C01/C05/continuation/origin proof")
        extra = result["extra"]
        if set(extra) != {"g01", "scalar", "portfolio", "package", "execution", "execution-native"}:
            raise ValueError("missing installed original-account consumers")
        if extra["g01"]["checks"] != 3 or extra["g01"]["skipped"] or not extra["g01"]["financial_profile_parity"]:
            raise ValueError("liquidation compatibility unqualified")
        expected_routes = {"intrabar", "event_driven", "order_commands", "delivery_arbitrage"}
        for label in ("execution", "execution-native"):
            if set(extra[label]["routes"]) != expected_routes:
                raise ValueError("incomplete installed execution routes")
            flags = ("shadow_account_exact", "active_rebuild_exact") if label == "execution" else (
                "explicit_rust_financial_route", "rust_fit_rank")
            if any(any(row.get(flag) is not True for flag in flags) for row in extra[label]["routes"].values()):
                raise ValueError("execution accounting/native authority proof failed")
        for label, count in (("scalar", 8), ("portfolio", 2), ("package", 3)):
            if len(extra[label]["cells"]) != count or any(
                    r["off_shadow_account_exact"] is not True for r in extra[label]["cells"]):
                raise ValueError("original domain account proof incomplete")
        fitted += sum(r["mode"] != "off" for r in full["cells"].values())
    return dict(package_sha256=file_hash(LANE / "package-v1/proof.json"),
                artifacts=proof["artifact_refs"], independent_artifacts=2,
                full_work_cells=152, actual_matured_fit_cells=fitted,
                no_checkout_runtime=True, native_rebuilt=False)


def privacy():
    names = subprocess.check_output(["git", "diff", "--name-only", ENTRY], cwd=ROOT, text=True).splitlines()
    names += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    for name in names:
        if not name.startswith(("tools/qms_pre06_", "tests/meta_selection/test_pre_e06_06_",
                                "docs/", "handoff/", "methodology/", "upgrade/implement.md",
                                "benchmarks/optimization/meta_selection/qms_pre_e06_06")):
            raise ValueError(f"unapproved phase scope: {name}")
        diff = subprocess.check_output(["git", "diff", "--unified=0", ENTRY, "--", name], cwd=ROOT, text=True)
        if not diff:
            diff = (ROOT / name).read_text()
        check_public_text("\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
                          if diff.startswith("diff ") else diff)
    return dict(private_alpha_access=False, new_private_study=False, patch_files=len(set(names)),
                artifact_allowlist_checked=True, publication=False)


def cleanup():
    excluded = [cleanup_path(n) for n in CLEANABLE]
    protected = {str(p.relative_to(ROOT)): file_hash(p) for p in LANE.rglob("*")
                 if p.is_file() and not any(p.is_relative_to(s) for s in excluded)}
    # The builder/regression processes have returned before this finalizer.
    # Refuse cleanup if a host-visible process still names any disposable root.
    processes = subprocess.check_output(["ps", "-eo", "args"], text=True)
    if any(str(p) in processes for p in excluded):
        raise ValueError("scratch still referenced by an active visible process")
    before = shutil.disk_usage(ROOT).free
    deleted = []
    for path in excluded:
        if path.exists():
            shutil.rmtree(path)
            deleted.append(str(path.relative_to(ROOT)))
    checked_hashes(protected)
    source = prerequisites()
    after = shutil.disk_usage(ROOT).free
    stats = os.statvfs(ROOT)
    receipt = dict(schema="qms-pre06-cleanup-v1", deleted=deleted,
                   protected_sha256=protected, protected_files=len(protected),
                   free_bytes_before=before, free_bytes_after=after,
                   actual_free_bytes_change=after-before, free_inodes=stats.f_favail,
                   runtime_source_unchanged=True, source=source,
                   preserved_envs=[".venv", ".maturin/qms08/g01-package-v1/consumer"],
                   retained_offline_cache="/tmp/quantbt-uv-cache",
                   cleaned_consumers_require_reinstall=True, publication=False)
    write_once(LANE / "cleanup.json", receipt)
    return receipt


def main(args):
    xmls = [LANE / name for name in args.junit]
    failures = [LANE / name for name in args.failed_junit]
    regression_result, installed_result = regression(xmls, failed_xmls=failures), installed()
    collections = [LANE / name for name in args.collection_junit]
    if collections:
        account_xml = LANE / args.account_junit
        if account_xml not in xmls:
            raise ValueError("account rerun must be in the required passing regression")
        regression_result["collection_disposition"] = collection_disposition(collections, account_xml)
    privacy_result = privacy()
    cleanup_result = cleanup()
    changed_tools = subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "tools", "tests"],
                                            cwd=ROOT, text=True).splitlines()
    receipt = dict(schema="qms-pre-e06-06-local-v1", phase="PRE-E06-06", status="READY_FOR_E06_LOCAL",
                   source=prerequisites(), installed=installed_result, regression=regression_result,
                   privacy=privacy_result, cleanup_sha256=file_hash(LANE / "cleanup.json"),
                   qualification_source_sha256={n: file_hash(ROOT / n) for n in changed_tools},
                   owner_cost_acceptance_sha256=file_hash(OWNER), economic_promotion=False,
                   remote="DEFERRED_E08_OWNER_APPROVAL", publication=False,
                   next_phase_started=False, free_bytes_after=cleanup_result["free_bytes_after"])
    write_once(ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_06_closure.json", receipt)
    print(json.dumps({k: receipt[k] for k in ("phase", "status", "publication", "next_phase_started")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", nargs="+", required=True, help="retained passing XML names within the phase lane")
    parser.add_argument("--failed-junit", nargs="*", default=[])
    parser.add_argument("--collection-junit", nargs="*", default=[])
    parser.add_argument("--account-junit", default="account-regression-v3.xml")
    main(parser.parse_args())
