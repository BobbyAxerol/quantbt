"""Independent local source/test/package/cost gate; no publication authorization."""

from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

from tools.check_release_artifacts import inspect_artifact
from tools.qms08_gate import CHECKS
from tools.qms_c03_gate import checks
from tools.qms_c04_source_guard import ROOT, verify


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def verify_package(path):
    path = Path(path)
    installed = json.loads(path.read_text())
    if installed["source_guard"] != verify() or installed["publication"] or installed["native_rebuilt"]:
        raise ValueError("C04 package source/scope mismatch")
    if [installed["core"], installed["native"]] != ["1.1.2", "0.4.3"]:
        raise ValueError("C04 release identity mismatch")
    if not all(installed[k] for k in ("source_exact_wheel", "source_exact_sdist", "artifact_allowlist")):
        raise ValueError("C04 package allowlist/source proof missing")
    for ref in installed["artifact_refs"]:
        artifact = ROOT / ref["path"]
        if file_hash(artifact) != ref["sha256"] or artifact.stat().st_size != ref["bytes"] or inspect_artifact(artifact):
            raise ValueError("C04 artifact byte/allowlist mismatch")
    for name, expected in installed["logs"].items():
        if file_hash(path.parent / name) != expected:
            raise ValueError("C04 package execution log changed")
    if file_hash(path.parent / "proof.json") != installed["transport_proof_sha256"]:
        raise ValueError("C04 reused installed transport proof changed")
    if set(installed["consumers"]) != {"wheel", "sdist"}:
        raise ValueError("C04 installed wheel/sdist consumers missing")
    recipes = {"tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"}
    for label, consumer in installed["consumers"].items():
        if len(consumer["matrix"]) != 4 or {r["recipe"] for r in consumer["matrix"]} != recipes:
            raise ValueError("C04 installed four-recipe matrix missing")
        if not consumer["no_source_imports"] or not consumer["no_financial_replay"] or consumer["publication"]:
            raise ValueError("C04 installed import/replay/publication scope mismatch")
        if "site-packages" not in Path(consumer["core_origin"]).parts:
            raise ValueError("C04 consumer imported a source checkout")
        for row in consumer["matrix"]:
            if not row["fresh_process_exact"] or row["attempts"] != 48 or row["split"] != 23:
                raise ValueError("C04 fresh-process continuation proof failed")
            if row["states"] != ["COMPLETE", "FAIL", "PRUNED"]:
                raise ValueError("C04 terminal-state proof incomplete")
        if file_hash(ROOT / "examples/optimization_exact_continuation.py") != consumer["example_sha256"]:
            raise ValueError("C04 installed public example changed")
        actual = json.loads((path.parent / f"c04-{label}.log").read_text().splitlines()[1])
        if actual != consumer:
            raise ValueError("C04 installed consumer differs from execution log")
    return installed


def verify_cost(path):
    cost = json.loads(Path(path).read_text())
    if cost["source_guard"] != verify() or len(cost["cells"]) != 8:
        raise ValueError("C04 cost source/workload mismatch")
    if cost["economic_claim"] or cost["endpoint_wfo_speedup_claim"] or cost["publication"]:
        raise ValueError("C04 unsupported cost/economic claim")
    expected_cells = {(recipe, history) for recipe in
                      ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")
                      for history in (32, 128)}
    if {(c["recipe"], c["history_attempts"]) for c in cost["cells"]} != expected_cells:
        raise ValueError("C04 cost recipe/history coverage incomplete")
    for cell in cost["cells"]:
        if len(cell["samples"]) != 3 or len({s["continued_witness_digest"] for s in cell["samples"]}) != 1:
            raise ValueError("C04 retained sample/continuation parity failed")
        if any(s["replay_account_evaluator_calls"] != 0 or s["bytes"] <= 0 for s in cell["samples"]):
            raise ValueError("C04 restore replayed an evaluator or lacks actual byte evidence")
        for key in ("owned_search_ms", "save_fsync_ms", "restore_ms", "bytes"):
            values = [s[key] for s in cell["samples"]]
            if not all(math.isfinite(v) and v >= 0 for v in values) or statistics.median(values) != cell["median"][key]:
                raise ValueError("C04 cost median/nonfinite mismatch")
    return cost


def qualify(*, junit, package, cost, check_proof):
    source = verify()
    members = {f"C04-T{i:02d}": [] for i in range(1, 7)}
    cases = [case for p in junit for case in ET.parse(p).getroot().iter("testcase")]
    if not cases or any(c.find(s) is not None for c in cases for s in ("failure", "error", "skipped")):
        raise ValueError("C04 requires actual passing regression with no skips")
    for case in cases:
        for i in range(1, 7):
            if case.get("name", "").startswith(f"test_c04_t{i:02d}_"):
                members[f"C04-T{i:02d}"].append(case.get("name"))
    if any(not names for names in members.values()):
        raise ValueError("C04 required test IDs missing")
    installed = verify_package(package)
    verify_cost(cost)
    records = json.loads(Path(check_proof).read_text())
    if set(records) != set(CHECKS):
        raise ValueError("C04 source/docs/check proof incomplete")
    for record in records.values():
        if file_hash(ROOT / record["path"]) != record["sha256"]:
            raise ValueError("C04 source/docs check log changed")
    paths = [*junit, package, cost, check_proof]
    return dict(schema="qms-c04-local-gate-v1", implementation_status="COMPLETE_APPROVED_LOCAL_SCOPE",
                technical_gate="PASS_LOCAL", source_guard=source, tests=len(cases), c04_test_members=members,
                references={str(Path(p).resolve().relative_to(ROOT)): file_hash(p) for p in paths},
                pair=[installed["core"], installed["native"]], publication_authorized=False,
                owner_review="PENDING", remote_current_source="NOT_RUN", economic_claim=False,
                limitations=["Owned session only; no automatic public WFO/W3/R3B resume",
                             "Pinned runtime, terminal barrier, supported pruner/callback codecs only",
                             "History-sized sampler replay; not constant-cost state import",
                             "Remote/public release and scientific acceptance require owner approval"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gather-checks", type=Path)
    parser.add_argument("--junit", nargs="+", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--cost", type=Path)
    parser.add_argument("--check-proof", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.gather_checks:
        checks(args.gather_checks)
        print("C04 source/documentation checks: PASS")
    else:
        if args.output.exists() and not args.check:
            raise ValueError("preserve historical receipt; use a fresh path or --check")
        result = qualify(junit=args.junit, package=args.package, cost=args.cost, check_proof=args.check_proof)
        if args.check:
            if json.loads(args.output.read_text()) != result:
                raise ValueError("C04 stored receipt mismatch")
        else:
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(dict(tests=result["tests"], technical_gate=result["technical_gate"], publication=False)))
