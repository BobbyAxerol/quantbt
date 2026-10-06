"""Source-bound C01 nested qualification; not installed/public/economic proof."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tools.qms_pre02_qualification import CUTOFFS, SINGLE, TRIPLE, passing_junit, file_hash
from tools.qms_pre03_source_guard import ENTRY, ROOT, MANIFEST, verify as source_guard
from tools.qms_pre_e06_inventory import GUIDE, GUIDE_SHA, check_public_text

ROUTES = ("signal_notional", "notional", "unit", "pct_equity", "dca_ladder")
SINGLE = tuple("current_pool_order_total_tie_rule" if n == "m04_current_pool_order_total_tie_rule" else n for n in SINGLE) + (
    "actual_selected_inner_diagnostics_are_not_anchor_copies",)
VERIFICATION = (
    "tests/meta_selection/pre_e06_02_support.py", "tests/meta_selection/pre_e06_03_support.py",
    "tests/meta_selection/test_pre_e06_02_conformance.py",
    "tests/meta_selection/test_pre_e06_03_conformance.py",
    "tests/meta_selection/test_pre_e06_03_runtime.py", "tests/meta_selection/test_pre_e06_03_policy.py",
    "tests/meta_selection/test_pre_e06_03_gate.py",
    "tools/qms_pre03_qualification.py", "tools/qms_pre03_source_guard.py",
    "tools/qms_pre02_source_guard.py", "tools/qms_execution_source_guard.py",
)


def matrix_gate(root):
    cases = {}
    for c in root.iter("testcase"):
        name = c.get("name")
        if not name or name in cases or any(c.find(k) is not None for k in ("error", "failure")):
            raise ValueError("non-passing/duplicate nested conformance case")
        cases[name] = c
    expected, skip = set(), set()
    for route in ROUTES:
        expected.update(f"test_pre03_{n}[{route}]" for n in SINGLE)
        for n in TRIPLE:
            for i in range(3):
                name = f"test_pre03_{n}[{route}-cutoff{i}]"
                expected.add(name)
                if n == "matured_scalar_prepared_reference" and route == "dca_ladder":
                    skip.add(name)
    if set(cases) != expected or {n for n, c in cases.items() if c.find("skipped") is not None} != skip:
        raise ValueError("missing nested route/cutoff gate or unexpected skip")
    rows = []
    for route in ROUTES:
        props = [p.get("value") for p in cases[f"test_pre03_matured_actual_fit_rank_and_applied_params[{route}]"].iter("property")
                 if p.get("name") == "pre02_matured"]
        if len(props) != 1:
            raise ValueError("actual nested mature-fit receipt missing")
        group = json.loads(props[0])
        if tuple(r["cutoff"] for r in group) != CUTOFFS:
            raise ValueError("registered nested cutoffs changed")
        for r in group:
            if (r["route"] != route or r["matured_origins"] < 12 or r["training_rows"] <= 0
                    or r["predictions"] <= 0 or r["model_status"] != "META_MODEL_PROPOSAL"):
                raise ValueError("vacuous nested actual fit/rank")
        rows.extend(group)
    if not any(r["changed_from_anchor"] for r in rows):
        raise ValueError("missing actual nested non-anchor application")
    return dict(required_pass=len(expected)-len(skip), not_applicable=len(skip), routes=len(ROUTES),
        mature_decisions=len(rows), actual_nonanchor_decisions=sum(r["changed_from_anchor"] for r in rows), rows=rows)


def build(lane, regression, matrix):
    guard = source_guard()
    if file_hash(ROOT/GUIDE) != GUIDE_SHA:
        raise ValueError("scientific guide changed")
    historical = json.loads((ROOT/"benchmarks/optimization/meta_selection/qms_pre_e06_02_closure.json").read_text())
    retained = dict(historical["historical_seal_sha256"])
    retained.update(historical["historical_retained_sha256"])
    retained["benchmarks/optimization/meta_selection/qms_pre_e06_02_closure.json"] = sha256(subprocess.check_output(
        ["git", "show", f"{ENTRY}:benchmarks/optimization/meta_selection/qms_pre_e06_02_closure.json"], cwd=ROOT)).hexdigest()
    for name, expected in retained.items():
        if file_hash(ROOT/name) != expected:
            raise ValueError("historical evidence/artifact changed")
    merged = ET.Element("testsuites")
    for name in matrix:
        merged.append(ET.parse(lane/name).getroot())
    matrix_result = matrix_gate(merged)
    unique = set().union(*(passing_junit(lane/n) for n in regression))
    names = set(subprocess.check_output(["git", "ls-files", "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", "src", "rust"],
        cwd=ROOT, text=True).splitlines())
    payload = dict(schema="qms-pre-e06-03-source-conformance-v1", phase="PRE-E06-03",
        status="PASS_LOCAL_NESTED_SOURCE_CONFORMANCE", baseline=ENTRY, source_guard=guard,
        protocol=dict(cohort=guard["cohort"], history_start="2020-04-01", rolling_is="90D", forward="monthly",
            inner_train="30D", inner_window="expanding", inner_forward="monthly", inner_min_folds=2,
            trials=8, seed=731, lambda_reg=10., min_matured_origins=12, q_hat_floor=-.1,
            numeric_threads=1, private_alpha_used=False, full_outer_is_auxiliary_evaluations_charged=True),
        matrix=matrix_result, regression_unique_cases=len(unique),
        junit_sha256={str((lane/n).relative_to(ROOT)): file_hash(lane/n) for n in (*matrix, *regression)},
        reviewed_source_manifest_sha256=file_hash(MANIFEST), runtime_source_sha256={n:file_hash(ROOT/n) for n in sorted(names)},
        verification_source_sha256={n:file_hash(ROOT/n) for n in VERIFICATION},
        historical_preserved_sha256=retained, guide_sha256=GUIDE_SHA,
        c01_activated="NESTED_MODE1_SCALAR_FIVE_ONLY", c05_activated=False,
        installed_current_source="DEFERRED_PRE_E06_06", remote="DEFERRED_E08_OWNER_APPROVAL",
        public="PENDING_OWNER_PUBLICATION", economic="NOT_ASSESSED_SYNTHETIC_SOFTWARE_ONLY", publication=False)
    check_public_text(json.dumps(payload))
    return payload


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lane", type=Path, default=ROOT/".maturin/qms08/pre-e06-03")
    p.add_argument("--matrix", nargs="+", required=True)
    p.add_argument("--regression", nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.lane.is_symlink() or not a.lane.resolve().is_relative_to(ROOT/".maturin/qms08") or a.output.exists():
        raise ValueError("invalid lane or existing sealed receipt")
    value = build(a.lane.resolve(), a.regression, a.matrix)
    a.output.write_text(json.dumps(value, indent=2, sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in value["matrix"].items() if k != "rows"}, sort_keys=True))


if __name__ == "__main__":
    main()
