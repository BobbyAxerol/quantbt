"""Independent local C03 source/test/artifact receipt; never authorizes release."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from tools.check_release_artifacts import inspect_artifact
from tools.qms08_gate import CHECKS
from tools.qms_c03_source_guard import ROOT, verify


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def checks(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("use a fresh C03 checks directory")
    output.mkdir(parents=True)
    records = {}
    for name in CHECKS:
        command = [sys.executable, "tools/" + name]
        if name.startswith("generate_") or name == "check_canonical_source_layout.py":
            command.append("--check")
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        log = output / (name + ".log")
        log.write_text("$ " + " ".join(command) + "\n" + result.stdout + result.stderr)
        if result.returncode:
            raise ValueError(f"C03 source/docs check failed: {log}")
        records[name] = dict(command=command, path=str(log.relative_to(ROOT)), sha256=digest(log))
    (output / "proof.json").write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
    return records


def qualify(*, junit, package, cost, check_proof):
    source = verify()
    junit_paths = [junit] if isinstance(junit, (str, Path)) else list(junit)
    cases = [case for path in junit_paths for case in ET.parse(path).getroot().iter("testcase")]
    if not cases or any(c.find(s) is not None for c in cases for s in ("failure", "error", "skipped")):
        raise ValueError("C03 requires passing actual regression, with no skips")
    members = {f"C03-T{i:02d}": [c.get("name") for c in cases
        if c.get("name", "").startswith(f"test_c03_t{i:02d}_")] for i in range(1, 9)}
    if any(not names for names in members.values()):
        raise ValueError("C03 gate missing required test IDs")
    installed = json.loads(Path(package).read_text())
    if installed["publication"] or installed["native_rebuilt"] or installed["source_guard"] != source:
        raise ValueError("C03 installed proof identity/scope mismatch")
    if not all(installed[k] for k in ("source_exact_wheel", "source_exact_sdist", "artifact_allowlist")):
        raise ValueError("C03 installed source/allowlist gate failed")
    for ref in installed["artifact_refs"]:
        path = ROOT / ref["path"]
        if digest(path) != ref["sha256"] or path.stat().st_size != ref["bytes"] or inspect_artifact(path):
            raise ValueError("C03 artifact bytes/allowlist mismatch")
    for name, expected in installed["logs"].items():
        if digest(Path(package).parent / name) != expected:
            raise ValueError("C03 installed execution log changed")
    if set(installed["consumers"]) != {"wheel", "sdist"}:
        raise ValueError("C03 wheel/sdist proof missing")
    for label, consumer in installed["consumers"].items():
        if len(consumer["matrix"]) != 8 or len(consumer["meta_matrix"]) != 8:
            raise ValueError("C03 actual installed sampler matrix incomplete")
        if any(not row["repeat_account_exact"] for row in consumer["matrix"]):
            raise ValueError("C03 account repeat mismatch")
        if any(not row["process_pool_account_exact"] for row in consumer["meta_matrix"]):
            raise ValueError("C03 process meta sampler proof missing")
        if not consumer["closed_children"] or consumer["process_recipes"] != 4 or consumer["frozen_pool_recipes"] != 4:
            raise ValueError("C03 process/frozen-pool proof missing")
        if digest(consumer["native_origin"]) != consumer["native_sha256"]:
            raise ValueError("C03 installed native bytes changed")
        if digest(ROOT / "examples/wfo_reactive_samplers.py") != consumer["example_sha256"]:
            raise ValueError("C03 installed example changed")
        recorded = json.loads((Path(package).parent / f"c03-{label}.log").read_text().splitlines()[1])
        if recorded != consumer:
            raise ValueError("C03 consumer does not match execution log")
    timings = json.loads(Path(cost).read_text())
    if timings["source_guard"] != source or len(timings["cells"]) != 8 or timings["economic_claim"]:
        raise ValueError("C03 engineering evidence identity/scope changed")
    for cell in timings["cells"]:
        if len(cell["samples"]) != 3 or len({r["decision_account_digest"] for r in cell["samples"]}) != 1:
            raise ValueError("C03 same-cell measured decision parity failed")
    documents = json.loads(Path(check_proof).read_text())
    if set(documents) != set(CHECKS):
        raise ValueError("C03 docs/source gates incomplete")
    for record in documents.values():
        if digest(ROOT / record["path"]) != record["sha256"]:
            raise ValueError("C03 docs/source execution log changed")
    return dict(schema="qms-c03-local-gate-v1", implementation_status="COMPLETE_APPROVED_LOCAL_SCOPE",
        technical_gate="PASS_LOCAL", owner_review="PENDING", publication_authorized=False,
        economic_superiority="NOT_CLAIMED", remote_current_source="NOT_RUN",
        source_guard=source, tests=len(cases), c03_test_members=members,
        references={str(Path(p).relative_to(ROOT)): digest(p) for p in
                    map(lambda p: Path(p).resolve(), (*junit_paths, package, cost, check_proof))},
        prepared_release_pair=[installed["core"], installed["native"]],
        limitations=["No extra meta mode activation", "No public meta batching or continuous carry/multi-symbol",
            "No persisted exact RNG checkpoint", "No conditional Sobol or mixed/constrained centroid",
            "Remote/public release remains owner-controlled"])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gather-checks", type=Path)
    parser.add_argument("--junit", type=Path, nargs="+")
    parser.add_argument("--package", type=Path)
    parser.add_argument("--cost", type=Path)
    parser.add_argument("--check-proof", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.gather_checks:
        checks(args.gather_checks)
        print("C03 source/documentation checks: PASS")
    else:
        if args.output.exists() and not args.check:
            raise ValueError("use a new receipt path or --check; do not overwrite an archived receipt")
        result = qualify(junit=args.junit, package=args.package, cost=args.cost, check_proof=args.check_proof)
        if args.check:
            if json.loads(args.output.read_text()) != result:
                raise ValueError("stored C03 receipt differs from verified execution")
        else:
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(dict(tests=result["tests"], technical_gate=result["technical_gate"], publication=False)))
