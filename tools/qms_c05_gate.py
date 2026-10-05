"""Independent C05 spec-only gate; cannot grant runtime/release authorization."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tools.qms_c04_source_guard import verify as verify_c04

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "681cb00"
GUIDE = "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
GUIDE_SHA = "adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d"
PROTECTED = ("src", "rust", "quantbt", "pyproject.toml", "uv.lock", "contracts", GUIDE)
REVIEW_FILES = (
    "docs/meta_selection/CONDITIONAL_GEOMETRY_REVIEW.md",
    "tools/qms_c05_latent.py", "tools/qms_c05_representative.py", "tools/qms_c05_gate.py",
    "tests/meta_selection/test_c05_latent_review.py",
    "tests/meta_selection/test_c05_representative_review.py",
    "tests/meta_selection/test_c05_public_lock.py", "tests/meta_selection/test_c05_gate.py",
)


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def require_no_production_changes(names):
    if names:
        raise ValueError(f"C05 spec-only scope changed protected source: {names}")


def source_lock():
    from tools.qms_e02_source_guard import ALLOW as E02_ALLOW, verify as verify_e02
    verify_e02()
    from tools.qms_e01_source_guard import NAME as E01_NAME, verify as verify_e01
    verify_e01()
    changed = subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", *PROTECTED], cwd=ROOT, text=True).splitlines()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", *PROTECTED], cwd=ROOT, text=True).splitlines()
    require_no_production_changes([name for name in [*changed, *untracked]
                                  if name != E01_NAME and name not in E02_ALLOW])
    if file_hash(ROOT / GUIDE) != GUIDE_SHA:
        raise ValueError("C05 detailed guide changed")
    earlier = verify_c04()
    return dict(schema="qms-c05-protected-source-v1", baseline=ENTRY,
                changed_production_files=[], guide_sha256=GUIDE_SHA,
                previous_c04_guard=earlier, pair=["1.1.2", "0.4.3"],
                production_activation=False, financial_rng_math_unchanged=True)


def test_evidence(paths):
    members = {f"C05-T{i:02d}": [] for i in range(1, 7)}
    seen = set()
    cases = []
    for path in paths:
        root = ET.parse(path).getroot()
        if any(int(s.get("errors", 0)) or int(s.get("failures", 0)) for s in root.iter("testsuite")):
            raise ValueError("C05 requires passing tests, with no skips/collection errors")
        for case in root.iter("testcase"):
            if any(case.find(state) is not None for state in ("failure", "error", "skipped")):
                raise ValueError("C05 requires passing tests, with no skips/collection errors")
            key = (case.get("classname"), case.get("name"))
            if not all(key) or key in seen:
                raise ValueError("missing/duplicate executed test identities")
            seen.add(key)
            cases.append(case)
            for i in range(1, 7):
                if case.get("name").startswith(f"test_c05_t{i:02d}_"):
                    members[f"C05-T{i:02d}"].append(case.get("name"))
    if not cases or any(not values for values in members.values()):
        raise ValueError("C05 required independent test IDs missing")
    return len(cases), members


def require_review_scope(receipt):
    if receipt.get("schema") != "qms-c05-spec-gate-v1" or receipt.get("technical_gate") != "PASS_LOCAL_SPEC":
        raise ValueError("C05 wrong gate identity")
    for key in ("production_activation", "publication_authorized", "economic_claim", "speedup_claim"):
        if receipt.get(key) is not False:
            raise ValueError("C05 cannot enable runtime/publication or claim economic/performance superiority")
    if receipt.get("owner_methodology_approval") != "PENDING" or receipt.get("remote_qualification") != "NOT_RUN":
        raise ValueError("C05 cannot manufacture approval/remote qualification")
    if receipt.get("implementation_status") != "SPEC_AND_TESTS_COMPLETE_RUNTIME_NOT_ACTIVATED":
        raise ValueError("C05 cannot advertise implemented production geometry")


def qualify(*, junit, check_proof):
    source = source_lock()
    count, members = test_evidence(junit)
    from tools.qms08_gate import CHECKS
    checks = json.loads(Path(check_proof).read_text())
    if set(checks) != set(CHECKS):
        raise ValueError("C05 documentation/source checks incomplete")
    for row in checks.values():
        if file_hash(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("C05 check execution log changed")
    receipt = dict(schema="qms-c05-spec-gate-v1", technical_gate="PASS_LOCAL_SPEC",
        implementation_status="SPEC_AND_TESTS_COMPLETE_RUNTIME_NOT_ACTIVATED",
        source_lock=source, tests=count, c05_test_members=members,
        review_file_sha256={p: file_hash(ROOT / p) for p in REVIEW_FILES},
        evidence_sha256={str(Path(p).resolve().relative_to(ROOT)): file_hash(p)
                         for p in [*junit, check_proof]},
        production_activation=False, owner_methodology_approval="PENDING",
        remote_qualification="NOT_RUN", publication_authorized=False,
        economic_claim=False, speedup_claim=False,
        remaining=["Owner acceptance of new math and separate activation",
                   "Actual conditional sampler/category RNG and public selector integration",
                   "Approved scheduler/checkpoint/artifact/economic qualification"])
    require_review_scope(receipt)
    return receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, nargs="+", required=True)
    parser.add_argument("--check-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = qualify(junit=args.junit, check_proof=args.check_proof)
    if args.check:
        if json.loads(args.output.read_text()) != result:
            raise ValueError("C05 stored receipt differs from verified execution")
    else:
        if args.output.exists():
            raise ValueError("preserve historical receipt; use a new path or --check")
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(tests=result["tests"], gate=result["technical_gate"], activation=False)))
