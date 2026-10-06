"""Source-bound local conformance gate, never an economic/release certificate."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tools.qms_pre02_source_guard import ENTRY, ROOT, verify as source_guard, verify_pre01_archive
from tools.qms_pre_e06_inventory import GUIDE, GUIDE_SHA, check_public_text


ROUTES = ("signal_notional", "notional", "unit", "pct_equity", "dca_ladder", "portfolio",
          "basket", "arbitrage", "intrabar", "event_driven", "order_commands", "delivery_arbitrage", "reactive_reset")
PREPARED = frozenset(ROUTES[:4])
SINGLE = ("matured_actual_fit_rank_and_applied_params", "full_multifold_continuous_original_account",
          "off_shadow_exact_search_rng_and_original_account", "m04_physical_history_order_same_active_decision",
          "m02_future_labels_and_candidate_archive_excluded", "m02_fitted_future_artifact_fail_closed",
          "m03_labels_published_during_search_do_not_enter_frozen_fit",
          "m03_permitted_correction_changes_real_fit_positive_control", "m04_current_pool_order_total_tie_rule",
          "m05_equal_availability_without_proven_publication_is_excluded", "m07_in_window_market_funding_invalidates_witness")
TRIPLE = ("m01_future_ohlcv_funding_real_active_runner", "original_raw_is_forward_and_final_account",
          "matured_rust_reference_fit_rank_account", "matured_cached_uncached_witness_exact", "matured_scalar_prepared_reference")
CUTOFFS = ("2022-04-30 00:00:00+00:00", "2023-04-30 00:00:00+00:00", "2024-04-30 00:00:00+00:00")
VERIFICATION = (
    "tests/meta_selection/pre_e06_02_support.py",
    "tests/meta_selection/test_pre_e06_02_conformance.py",
    "tests/meta_selection/test_pre_e06_02_measurement.py",
    "tests/meta_selection/test_pre_e06_02_gate.py",
    "tests/meta_selection/test_pre_e06_01_audit.py",
    "tests/meta_selection/test_qms07_performance.py",
    "tools/qms_pre02_source_guard.py",
    "tools/qms_execution_source_guard.py",
    "tools/qms_pre02_qualification.py",
)


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def matrix_gate(root):
    """Every public route and cutoff is mandatory; only scalar N/A may skip."""
    cases = {}
    for case in root.iter("testcase"):
        name = case.get("name")
        if not name or name in cases or case.find("error") is not None or case.find("failure") is not None:
            raise ValueError("non-passing/duplicate conformance case")
        cases[name] = case
    expected, not_applicable = set(), set()
    for route in ROUTES:
        expected.update(f"test_pre02_{name}[{route}]" for name in SINGLE)
        for name in TRIPLE:
            for i in range(3):
                key = f"test_pre02_{name}[{route}-cutoff{i}]"
                expected.add(key)
                if name == "matured_scalar_prepared_reference" and route not in PREPARED:
                    not_applicable.add(key)
    if set(cases) != expected or {n for n, c in cases.items() if c.find("skipped") is not None} != not_applicable:
        raise ValueError("missing route/cutoff gate or unexpected skipped required cell")
    rows = []
    for route in ROUTES:
        case = cases[f"test_pre02_matured_actual_fit_rank_and_applied_params[{route}]"]
        properties = [p.get("value") for p in case.iter("property") if p.get("name") == "pre02_matured"]
        if len(properties) != 1:
            raise ValueError("actual mature-fit receipt missing")
        route_rows = json.loads(properties[0])
        if tuple(r["cutoff"] for r in route_rows) != CUTOFFS:
            raise ValueError("registered cutoffs changed")
        for row in route_rows:
            if (row["route"] != route or row["matured_origins"] < 12 or row["training_rows"] <= 0
                    or row["predictions"] <= 0 or row["model_status"] != "META_MODEL_PROPOSAL"):
                raise ValueError("vacuous/missing actual active fit/rank")
        rows.extend(route_rows)
    if not any(row["changed_from_anchor"] for row in rows):
        raise ValueError("no actual non-anchor application in declared software fixture")
    return dict(required_pass=len(expected)-len(not_applicable), scalar_scorer_not_applicable=len(not_applicable),
                routes=len(ROUTES), mature_decisions=len(rows), rows=rows,
                actual_nonanchor_decisions=sum(row["changed_from_anchor"] for row in rows))


def passing_junit(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if (any(int(s.get(k, 0)) for s in root.iter("testsuite") for k in ("errors", "failures", "skipped"))
            or not cases or any(any(c.find(k) is not None for k in ("error", "failure", "skipped")) for c in cases)
            or any(not c.get("name") or not c.get("classname") for c in cases)):
        raise ValueError("missing/non-passing regression receipt")
    return {(c.get("classname"), c.get("name")) for c in cases}


def build(lane, regressions, matrices):
    source = source_guard()
    path = ROOT/"benchmarks/optimization/meta_selection/qms_pre_e06_01_inventory.json"
    archived = verify_pre01_archive(json.loads(path.read_text()))
    if file_hash(ROOT/GUIDE) != GUIDE_SHA:
        raise ValueError("scientific guide changed")
    # Retain original source seals and exact artifacts, rather than reseal them.
    historical = json.loads((ROOT/"benchmarks/optimization/meta_selection/qms_execution_closeout_v4.json").read_text())
    for name, expected in historical["retained_sha256"].items():
        if file_hash(ROOT/name) != expected:
            raise ValueError("historical artifact changed")
    merged = ET.Element("testsuites")
    for name in matrices:
        root = ET.parse(lane/name).getroot()
        if any(int(s.get(k, 0)) for s in root.iter("testsuite") for k in ("errors", "failures")):
            raise ValueError("non-passing public matrix shard")
        merged.append(root)
    matrix = matrix_gate(merged)
    paths = [lane/n for n in regressions]
    unique = set().union(*(passing_junit(p) for p in paths))
    names = subprocess.check_output(["git", "ls-files", "--", "src", "rust"], cwd=ROOT, text=True).splitlines()
    inputs = {str(p.relative_to(ROOT)): file_hash(p) for p in [*(lane/n for n in matrices), *paths]}
    protected = {n: file_hash(ROOT/n) for n in subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ENTRY, "--", "benchmarks/optimization/meta_selection", "docs/meta_selection"],
        cwd=ROOT, text=True).splitlines() if n.endswith(".json") or n.endswith("_REPORT.md")
        or n.endswith("REAL_DIAGNOSTIC.md") or n.endswith("QMSE03_G01_CLOSURE.md")}
    for name, expected in protected.items():
        before = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
        if sha256(before).hexdigest() != expected:
            raise ValueError("historical scientific/source receipt changed")
    payload = dict(schema="qms-pre-e06-02-source-conformance-v1", phase="PRE-E06-02",
        status="PASS_LOCAL_SOURCE_CONFORMANCE", baseline=ENTRY, source_guard=source,
        protocol=dict(id="pre-e06-matured-conformance-v1", amendment="PRE02-A01_OWNER_APPROVED",
            original_history_start="2021-01-01", approved_history_start="2020-04-01",
            monthly_forward=True, rolling_is="90D", trials=8, seed=731, lambda_reg=10.,
            min_matured_origins=12, q_hat_floor=-.1, numeric_threads=1, private_alpha_used=False),
        matrix=matrix, regression_unique_cases=len(unique), junit_sha256=inputs,
        runtime_source_sha256={n: file_hash(ROOT/n) for n in names}, historical_seal_sha256=protected,
        verification_source_sha256={n: file_hash(ROOT/n) for n in VERIFICATION},
        historical_retained_sha256=historical["retained_sha256"], guide_sha256=GUIDE_SHA,
        pre01_inventory_scope="HISTORICAL_COMMIT_ONLY_NOT_CURRENT_SOURCE",
        registered_routes=len(archived["routes"]), installed_current_source="DEFERRED_PRE_E06_06",
        remote="DEFERRED_E08_OWNER_APPROVAL", public="PENDING_OWNER_PUBLICATION",
        performance="NOT_A_MATCHED_BENCHMARK", economic="NOT_ASSESSED_SYNTHETIC_SOFTWARE_ONLY",
        c01_c05_activated=False, publication=False)
    check_public_text(json.dumps(payload))
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, default=ROOT/".maturin/qms08/pre-e06-02")
    parser.add_argument("--regression", nargs="+", required=True)
    parser.add_argument("--matrix", nargs="+", default=["conformance-v4.xml", "delivery-w3-v1.xml"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.lane.is_symlink() or not args.lane.resolve().is_relative_to(ROOT/".maturin/qms08"):
        raise ValueError("invalid evidence lane")
    payload = build(args.lane.resolve(), args.regression, args.matrix)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")
    print(json.dumps(dict(status=payload["status"], **{k: v for k, v in payload["matrix"].items() if k != "rows"})))


if __name__ == "__main__":
    main()
