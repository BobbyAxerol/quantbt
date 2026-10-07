"""Source-bound local parity/cost receipt; never silently approve point failures."""

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tools.qms_pre05_analysis import collect
from tools.qms_pre05_source_guard import ROOT, ENTRY, MANIFEST, verify
from tools.qms_pre_e06_inventory import GUIDE, GUIDE_SHA

NA_REASON = "This route has its own original account, not the same-close scalar scorer"
REGISTERED_NA = frozenset(
    (
        "tests.meta_selection.test_pre_e06_02_conformance",
        f"test_pre02_matured_scalar_prepared_reference[{route}-cutoff{i}]",
    )
    for route in (
        "dca_ladder",
        "portfolio",
        "basket",
        "arbitrage",
        "intrabar",
        "event_driven",
        "order_commands",
        "delivery_arbitrage",
        "reactive_reset",
    )
    for i in range(3)
) | frozenset(
    (
        "tests.meta_selection.test_pre_e06_03_conformance.TestNestedConformance",
        f"test_pre03_matured_scalar_prepared_reference[dca_ladder-cutoff{i}]",
    )
    for i in range(3)
)


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def passed_cases(path, *, admitted_na=frozenset()):
    cases = {}
    seen = set()
    for case in ET.parse(path).iter("testcase"):
        key = (case.get("classname"), case.get("name"))
        if not all(key) or key in seen:
            raise ValueError("duplicate/missing JUnit identity")
        seen.add(key)
        skipped = case.find("skipped")
        if (
            key in admitted_na
            and skipped is not None
            and skipped.get("message") == NA_REASON
            and case.find("failure") is None
            and case.find("error") is None
        ):
            continue
        if any(case.find(k) is not None for k in ("failure", "error", "skipped")):
            raise ValueError("qualification requires passing cases without skips")
        cases[key] = case
    if not cases:
        raise ValueError("empty qualification shard")
    return cases


def cost_disposition(cost):
    disabled = [r for r in cost["rows"] if r["mode"] == "off"]
    if len(cost["rows"]) != 76 or len(disabled) != 32:
        raise ValueError("incomplete registered cost matrix")
    if cost["point_budgets"] != dict(p50_pct=3, p95_pct=5):
        raise ValueError("owner budget changed")
    for row in cost["rows"]:
        if not row["exact_semantic_parity"]:
            raise ValueError("semantic parity failure")
        expected = (
            "PASS"
            if row["p50_change_pct"] <= 3 and row["p95_change_pct"] <= 5
            else "NOT_MET"
        )
        if row["mode"] == "off" and row["disabled_point_budget"] != expected:
            raise ValueError("point budget misclassified")
    missed = [r["cell"] for r in disabled if r["disabled_point_budget"] != "PASS"]
    return dict(
        disabled_pass=32 - len(missed),
        disabled_not_met=missed,
        accepted_cost_disposition=not missed,
        statistical_noninferiority_certified=False,
    )


def artifact_inventory(lane, cost):
    from tools.qms_pre05_profile_matrix import registered_profile_cells

    cost_path = ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_05_cost.json"
    if json.loads(cost_path.read_text()) != cost:
        raise ValueError("published cost table differs from complete raw samples")
    registration = json.loads((lane / "registration.json").read_text())
    if (
        registration["entry"] != ENTRY
        or registration["warm_repeats"] != 21
        or registration["numeric_threads"] != 1
        or registration["disabled_budget"]
        != dict(owner_approved=True, p50_pct=3, p95_pct=5)
        or [c["id"] for c in registration["cells"]] != [r["cell"] for r in cost["rows"]]
    ):
        raise ValueError("cost registration changed or incomplete")
    expected = {
        str((lane / "profiles" / f"isolated-{arm}-{c.identity}.json").relative_to(ROOT))
        for c in registered_profile_cells(cost)
        for arm in ("reference", "optimized")
    }
    profiles = json.loads((lane / "isolated-profiles.json").read_text())
    if len(profiles) != len(expected) or set(profiles) != expected:
        raise ValueError("primary paired profile inventory incomplete or duplicated")
    block = lane / "portable-block-cost-isolated.json"
    value = json.loads(block.read_text())
    if (
        value["run_context"] != "isolated"
        or value["warm_pairs"] != 21
        or value["calls_per_arm_sample"] != 50
        or value["financial_calls"] != 0
        or not value["exact_portable_parity"]
        or value["full_wfo_speed_claim"]
        or value["history_sha256"] != file_hash(lane / "history/domain-pct_equity.json")
    ):
        raise ValueError("primary block cost contract changed")
    paths = [
        cost_path,
        cost_path.with_suffix(".md"),
        lane / "registration.json",
        lane / "isolated-profiles.json",
        lane / "profile-summary.json",
        block,
    ]
    paths.extend(ROOT / name for name in profiles)
    paths.extend((ROOT / name).with_suffix(".pstats") for name in profiles)
    paths.extend(sorted((lane / "history").glob("*.json")))
    return {str(p.relative_to(ROOT)): file_hash(p) for p in paths}


def build(lane, native, shards, *, label="matched-v3"):
    source = verify()
    if file_hash(ROOT / GUIDE) != GUIDE_SHA:
        raise ValueError("scientific guide changed")
    cost = collect(lane, label)
    disposition = cost_disposition(cost)
    artifacts = artifact_inventory(lane, cost)
    union = set()
    actual_na = set()
    for shard in shards:
        union.update(passed_cases(shard, admitted_na=REGISTERED_NA))
        actual_na.update(
            (c.get("classname"), c.get("name"))
            for c in ET.parse(shard).iter("testcase")
            if c.find("skipped") is not None
        )
    if actual_na != REGISTERED_NA:
        raise ValueError("registered N/A conformance coverage incomplete or unexpected")
    previous_lane = ROOT / ".maturin/qms08/pre-e06-04"
    required = set()
    for name in (
        "policy-final-verified.xml",
        "regression.xml",
        "docs-final-verified.xml",
    ):
        required.update(
            (c.get("classname"), c.get("name"))
            for c in ET.parse(previous_lane / name).iter("testcase")
        )
    if not required <= union:
        raise ValueError(
            "historical regression identities missing from current passing reruns"
        )
    for module, count in (
        ("harness", 3),
        ("portable", 35),
        ("guard", 4),
        ("analysis", 5),
        ("chronological", 2),
        ("receipt", 10),
        ("evidence", 5),
        ("w3", 3),
        ("conditional", 2),
    ):
        found = {
            k for k in union if k[0] == "tests.meta_selection.test_pre_e06_05_" + module
        }
        if len(found) != count:
            raise ValueError("new phase qualification missing: " + module)
    old = json.loads(
        (
            ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_04_closure.json"
        ).read_text()
    )
    retained = dict(old["historical_preserved_sha256"])
    retained.update(
        {
            f"benchmarks/optimization/meta_selection/qms_pre_e06_04_{n}.json": file_hash(
                ROOT / f"benchmarks/optimization/meta_selection/qms_pre_e06_04_{n}.json"
            )
            for n in ("closure", "cost", "reviewed_source")
        }
    )
    for name, digest in retained.items():
        if file_hash(ROOT / name) != digest:
            raise ValueError("historical receipt changed")
    names = subprocess.check_output(
        ["git", "ls-files", "--", "src", "rust"], cwd=ROOT, text=True
    ).splitlines()
    if (
        file_hash(native)
        != "e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba"
    ):
        raise ValueError("unqualified native provider")
    return dict(
        schema="qms-pre-e06-05-local-v1",
        phase="PRE-E06-05",
        status="PASS_LOCAL_PARITY_AND_POINT_COST"
        if disposition["accepted_cost_disposition"]
        else "PASS_LOCAL_PARITY_COST_DISPOSITION_OPEN",
        baseline=ENTRY,
        source_guard=source,
        distinct_scoped_pass=len(union),
        registered_not_applicable_skip_ids=sorted(actual_na),
        private_full_study_replay="NOT_REEXECUTED_UNCHANGED_FINANCIAL_SOURCE",
        junit_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in shards},
        runtime_source_sha256={n: file_hash(ROOT / n) for n in sorted(names)},
        verification_source_sha256={
            str(p.relative_to(ROOT)): file_hash(p)
            for p in sorted(
                (
                    *(ROOT / "tools").glob("qms_pre05*.py"),
                    *(ROOT / "tests/meta_selection").glob("test_pre_e06_05*.py"),
                )
            )
        },
        reviewed_source_manifest_sha256=file_hash(MANIFEST),
        historical_preserved_sha256=retained,
        native_provider_sha256=file_hash(native),
        guide_sha256=GUIDE_SHA,
        samples_sha256={r["cell"]: r["sample_sha256"] for r in cost["rows"]},
        primary_artifacts_sha256=artifacts,
        registered_cells=76,
        paired_warm_executions=76 * 21 * 2,
        warmups=76 * 2,
        full_semantic_parity=True,
        cost_disposition=disposition,
        financial_or_ridge_or_sampler_changed=False,
        economic="NOT_ASSESSED_PERFORMANCE_ONLY",
        installed_current_source="DEFERRED_PRE_E06_06",
        remote="DEFERRED_OWNER_APPROVAL",
        publication=False,
    )


def cleanup_snapshot(lane, protected):
    """Retain evidence; no disposable environment or compilation was created."""
    paths = {p for p in lane.rglob("*") if p.is_file()}
    paths.update(protected)
    before = {str(p): file_hash(p) for p in sorted(paths)}
    fs = os.statvfs(ROOT)
    allocated = sum(p.stat().st_blocks * 512 for p in lane.rglob("*") if p.is_file())
    if allocated > 1024**3 or fs.f_bavail * fs.f_frsize < 5 * 1024**3:
        raise ValueError("registered disk budget exceeded")
    if before != {str(p): file_hash(p) for p in sorted(paths)}:
        raise ValueError("protected files changed during cleanup verification")
    return dict(
        status="PASS_ZERO_DELETION",
        deleted_paths=[],
        reviewed_reclaimable_paths=[],
        allocated_lane_bytes=allocated,
        available_bytes=fs.f_bavail * fs.f_frsize,
        free_inodes=fs.f_favail,
        protected_sha256=before,
        protected_before_after_equal=True,
        new_environment=False,
        new_native_build=False,
        task_attributed_reclaimed_bytes=0,
    )


def main():
    import argparse
    from tools.qms_pre05_benchmark import write_once

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--shard", type=Path, action="append", required=True)
    args = parser.parse_args()
    lane = ROOT / ".maturin/qms08/pre-e06-05"
    receipt = build(lane, args.native.resolve(), [p.resolve() for p in args.shard])
    closure = (
        ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_05_closure.json"
    )
    write_once(closure, receipt)
    protected = [ROOT / n for n in receipt["runtime_source_sha256"]]
    protected += [ROOT / n for n in receipt["verification_source_sha256"]]
    protected += [ROOT / n for n in receipt["historical_preserved_sha256"]]
    protected += [ROOT / n for n in receipt["primary_artifacts_sha256"]]
    protected += [ROOT / GUIDE, MANIFEST, args.native.resolve(), closure]
    cleanup = cleanup_snapshot(lane, protected)
    write_once(lane / "cleanup.json", cleanup)
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in ("status", "distinct_scoped_pass", "cost_disposition")
            }
        )
    )


if __name__ == "__main__":
    main()
