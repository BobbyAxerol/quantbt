"""Independent QMS-08 coverage/artifact verifier and cold report regeneration."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tomllib
import xml.etree.ElementTree as ET

from tools.qms08_research import empirical_disposition, paired_decomposition

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "benchmarks/optimization/meta_selection"
ENTRY = "559b4d1"
TEST_IDS = tuple(f"Q{p}-T{i:02d}" for p in range(1, 9) for i in range(1, 9))
GATES = (
    "G8-REGRESSION",
    "G8-END_TO_END",
    "G8-EMPIRICAL_SCOPE",
    "G8-DOCS",
    "G8-PACKAGE",
    "G8-OWNER",
)
CHECKS = (
    "check_canonical_source_layout.py",
    "generate_native_event_contracts.py",
    "generate_product_contracts.py",
    "generate_public_api_inventory.py",
    "check_module_architecture.py",
    "check_benchmark_governance.py",
    "check_docs_links.py",
    "scan_public_secrets.py",
)


def hash_file(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def source_manifest():
    names = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "src/quantbt",
            "rust",
            "pyproject.toml",
            "uv.lock",
            "tools/qms08*",
            "tests/meta_selection",
            "examples/wfo*",
            "docs/meta_selection/USAGE.md",
            "docs/meta_selection/QUALIFICATION.md",
            "docs/meta_selection.md",
            "docs/endpoint.md",
            "docs/optimization.md",
            "docs/native/capabilities.md",
            "docs/walkforward_causal.md",
            "methodology/walk_forward.md",
            "examples/README.md",
            "README.md",
            ".github/workflows/qms-candidate.yml",
            ".github/workflows/ci.yml",
            ".github/workflows/native-release.yml",
            ".github/workflows/publish.yml",
            ".github/actions/qms-fixtures/action.yml",
            "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {n: hash_file(ROOT / n) for n in sorted(set(names))}


def test_coverage(junit):
    root = ET.parse(junit).getroot()
    cases = list(root.iter("testcase"))
    if not cases or any(
        c.find(s) is not None for c in cases for s in ("failure", "error", "skipped")
    ):
        raise ValueError("QMS-08 requires passing actual tests without errors/skips")
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if any(int(s.get(k, 0)) for s in suites for k in ("failures", "errors", "skipped")):
        raise ValueError("non-passing JUnit suite")
    if sum(int(s.get("tests", 0)) for s in suites) != len(cases):
        raise ValueError("JUnit test-count mismatch")
    members = {
        test: [
            c.get("name")
            for c in cases
            if c.get("name", "").startswith(
                "test_" + test.lower().replace("-", "_") + "_"
            )
        ]
        for test in TEST_IDS
    }
    if any(not rows for rows in members.values()):
        raise ValueError("missing required QMS test IDs")
    return {"tests": len(cases), "members": members, "junit_sha256": hash_file(junit)}


def verify_pair(proof, *, source_revision=None):
    from tools.qms08_package import CORE, NATIVE, FEATURES

    release_pair = proof["schema"] == "qms-release-installed-pair-v1"
    if release_pair:
        from tools.qms08_package import declared_pair
        CORE, NATIVE = declared_pair()
        FEATURES = "cargo-default"
    elif proof["schema"] != "qms08-installed-candidate-v1":
        raise ValueError("unknown installed pair proof schema")
    if (proof["core"], proof["native"], proof["features"]) != (CORE, NATIVE, FEATURES):
        raise ValueError("candidate pair mismatch")
    if (
        any(
            proof[k] is not True
            for k in (
                "build_only",
                "source_exact_wheel_sdist",
                "artifact_allowlist",
                "source_versions_unchanged",
            )
        )
        or proof["release_authorized"] is not False
    ):
        raise ValueError("candidate completion/publication flag invalid")
    if set(proof["consumers"]) != {"core_off", "core_optimization", "pair", "sdist"}:
        raise ValueError("installed consumer lanes missing")
    if proof["consumers"]["core_off"]["off_optional_dependencies_loaded"] is not False:
        raise ValueError("disabled dependency scope changed")
    core = proof["consumers"]["core_optimization"]
    if (
        core["missing_native_require_fails"] is not True
        or core["off_shadow_parity"] is not True
    ):
        raise ValueError("core-only fallback/require contract failed")
    for name in ("pair", "sdist"):
        p = proof["consumers"][name]
        if (
            p["active_reference_prepared_parity"] is not True
            or p["off_shadow_parity"] is not True
            or p["actual_meta_folds"] != 6
            or p["sampler_recipes"]
            != ["tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"]
            or p["numeric_blocks"]["selected_backend_by_block"]["gram_solve"] != "rust"
            or p["native_version"] != NATIVE
            or p["core_version"] != CORE
        ):
            raise ValueError("actual installed pair feature proof invalid")
    for ref in proof["artifact_refs"]:
        path = (ROOT / ref["path"]).resolve()
        if (
            not path.is_relative_to(ROOT / ".maturin/qms08")
            or hash_file(path) != ref["sha256"]
            or path.stat().st_size != ref["bytes"]
        ):
            raise ValueError("candidate artifact bytes/path changed")
    if len(proof["artifact_refs"]) != 3:
        raise ValueError("wheel/sdist/native artifacts missing")
    for name, expected in proof["logs"].items():
        path = (ROOT / name).resolve()
        if (
            not path.is_relative_to(ROOT / ".maturin/qms08")
            or hash_file(path) != expected
        ):
            raise ValueError("candidate execution log changed")
    lanes = set()
    for name, recorded in proof["consumers"].items():
        logs = [ROOT / n for n in proof["logs"] if n.endswith(f"/{name}-consumer.log")]
        outputs = (
            [line for line in logs[0].read_text().splitlines() if line.startswith("{")]
            if len(logs) == 1
            else []
        )
        if len(outputs) != 1 or json.loads(outputs[0]) != recorded:
            raise ValueError(
                "installed consumer scalar/metadata does not match actual log"
            )
        lanes.add(logs[0].parent)
    if len(lanes) != 1:
        raise ValueError("installed consumers must share one candidate artifact lane")
    stage = next(iter(lanes)) / "stage"
    if release_pair:
        build = next(iter(lanes)) / "native-build.log"
        command = build.read_text().splitlines()[0]
        if "--features" in command or "--no-default-features" in command:
            raise ValueError("release proof must use ordinary Cargo default features")
        features = tomllib.loads((stage / "rust/native_event/Cargo.toml").read_text())["features"]["default"]
        if set(features) != {"qms-numeric-candidate", "qms-prepared-witness-candidate"}:
            raise ValueError("default release QMS capabilities missing")
    expected_changes = {
        "pyproject.toml",
        "src/quantbt/__init__.py",
        "src/quantbt/core/generated_product_contracts.py",
        "rust/native_event/Cargo.toml",
        "rust/native_event/pyproject.toml",
        "rust/crates/quantbt-domain/src/generated_product_contracts.rs",
    }
    if release_pair:
        expected_changes = set()
    if set(proof["stage_differences"]) != expected_changes:
        raise ValueError("unapproved stage identity adaptation")
    def source_bytes(name):
        if source_revision is None:
            return (ROOT / name).read_bytes()
        return subprocess.check_output(
            ["git", "show", f"{source_revision}:{name}"], cwd=ROOT
        )

    names = subprocess.check_output(
        (["git", "ls-files", "src/quantbt", "rust"] if source_revision is None
         else ["git", "ls-tree", "-r", "--name-only", source_revision,
               "src/quantbt", "rust"]), cwd=ROOT, text=True
    ).splitlines()
    for n in names + [
        "pyproject.toml",
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "MANIFEST.in",
    ]:
        original, staged = sha256(source_bytes(n)).hexdigest(), hash_file(stage / n)
        if n in expected_changes:
            if proof["stage_differences"][n] != {"source": original, "staged": staged}:
                raise ValueError("stage adaptation/source drift")
        elif n == "rust/Cargo.lock":
            original_lock = tomllib.loads(source_bytes(n).decode())
            staged_lock = tomllib.loads((stage / n).read_text())
            package = [
                p for p in original_lock["package"] if p["name"] == "quantbt-native"
            ]
            source_version = tomllib.loads(source_bytes("rust/native_event/Cargo.toml").decode())["package"]["version"]
            if len(package) != 1 or package[0]["version"] != source_version:
                raise ValueError("ambiguous source lock identity")
            if not release_pair:
                package[0]["version"] = "0.4.3-dev.4"
            if original_lock != staged_lock:
                raise ValueError("staged Cargo lock changed beyond candidate identity")
        elif original != staged and (release_pair or n != "README.md"):
            raise ValueError("non-identity source drift in installed artifact")
    return True


def gather_checks():
    import sys

    folder = ROOT / ".maturin/qms08/checks"
    folder.mkdir(parents=True, exist_ok=True)
    records = {}
    for name in CHECKS:
        command = [sys.executable, "tools/" + name]
        if name.startswith("generate_") or name == "check_canonical_source_layout.py":
            command.append("--check")
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        log = folder / (name + ".log")
        log.write_text("$ " + " ".join(command) + "\n" + result.stdout + result.stderr)
        if result.returncode:
            raise ValueError(f"documentation/source gate failed: {name}; see {log}")
        records[name] = {
            "command": command,
            "returncode": result.returncode,
            "path": str(log.relative_to(ROOT)),
            "sha256": hash_file(log),
        }
    (folder / "proof.json").write_text(
        json.dumps(records, sort_keys=True, indent=2) + "\n"
    )
    return records


def verify_checks(records):
    if set(records) != set(CHECKS):
        raise ValueError("required documentation/source execution gates missing")
    for name, record in records.items():
        path = (ROOT / record["path"]).resolve()
        if (
            type(record["returncode"]) is not int
            or record["returncode"] != 0
            or not path.is_relative_to(ROOT / ".maturin/qms08/checks")
            or hash_file(path) != record["sha256"]
            or record["command"][1] != "tools/" + name
            or not path.read_text().startswith(
                "$ " + " ".join(record["command"]) + "\n"
            )
        ):
            raise ValueError("documentation/source gate execution log invalid")


def validate(evidence, junit):
    if (
        evidence["schema"] != "qms08-qualification-v1"
        or evidence["entry"] != ENTRY
        or evidence["source_hashes"] != source_manifest()
    ):
        raise ValueError("QMS08 source/schema changed")
    coverage = test_coverage(junit)
    verify_checks(evidence["source_checks"])
    if evidence["required_test_ids"] != list(TEST_IDS) or evidence[
        "required_gates"
    ] != list(GATES):
        raise ValueError("untrusted required-gate/test registry")
    required_history = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            ENTRY,
            "benchmarks/optimization/meta_selection",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    if set(evidence["historical_artifacts"]) != set(required_history):
        raise ValueError("historical artifact registry missing")
    for name, expected in evidence["historical_artifacts"].items():
        original = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
        if (
            sha256(original).hexdigest() != expected
            or hash_file(ROOT / name) != expected
        ):
            raise ValueError("sealed historical artifact changed")
    if evidence["empirical"] != empirical_disposition():
        raise ValueError("unapproved or fabricated economic claim")
    if evidence["paired_report"] != paired_decomposition(evidence["saved_raw_pairs"]):
        raise ValueError("saved-output report/scalar mismatch")
    if (
        evidence["owner_review"] != "PENDING"
        or evidence["release_authorized"] is not False
        or evidence["complete_scientific_study"] is not False
    ):
        raise ValueError("unapproved completion/publication claim")
    versions = set()
    for proof in evidence["packages"]:
        verify_pair(proof)
        version = proof["consumers"]["pair"]["python"].split()[0].rsplit(".", 1)[0]
        if version in versions:
            raise ValueError("duplicate interpreter lane")
        versions.add(version)
    if versions != {"3.11", "3.12", "3.13"}:
        raise ValueError("local supported interpreter matrix incomplete")
    # Stage-only identity adaptation is permitted; checkout financial code is not.
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            ENTRY,
            "--name-only",
            "--",
            "src",
            "rust",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=ROOT,
        text=True,
    )
    if changed.strip():
        raise ValueError("protected execution/version sources changed in QMS08")
    return {
        "schema": "qms08-gate-receipt-v1",
        "source_manifest_sha256": sha256(
            json.dumps(evidence["source_hashes"], sort_keys=True).encode()
        ).hexdigest(),
        "evidence_sha256": sha256(
            json.dumps(
                evidence, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest(),
        "coverage": coverage,
        "test_dispositions": {
            test: (
                {
                    "Q8-T03": "NOT_RUN_REAL_ALPHA",
                    "Q8-T04": "PASS_NOT_RUN_DISPOSITION",
                    "Q8-T07": "PASS_LOCAL_REMOTE_PENDING",
                    "Q8-T08": "PASS_SOFTWARE_OWNER_PENDING",
                }.get(test, "PASS")
            )
            for test in TEST_IDS
        },
        "required_gates": list(GATES),
        "gates": {
            "G8-REGRESSION": "PASS",
            "G8-END_TO_END": "PASS",
            "G8-EMPIRICAL_SCOPE": "NOT_RUN_BUDGET",
            "G8-DOCS": "PASS",
            "G8-PACKAGE": "PASS_LOCAL_3_INTERPRETERS_REMOTE_PENDING",
            "G8-OWNER": "PENDING",
        },
        "software_status": "SOFTWARE_CANDIDATE_READY",
        "empirical_status": "EMPIRICAL_VALIDATION_NOT_RUN",
        "owner_review": "PENDING",
        "release_authorized": False,
    }


def collect_evidence():
    paths = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            ENTRY,
            "benchmarks/optimization/meta_selection",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    packages = [
        json.loads(p.read_text())
        for p in sorted((ROOT / ".maturin/qms08/qualified").glob("cp*/proof.json"))
    ]
    evidence = {
        "schema": "qms08-qualification-v1",
        "entry": ENTRY,
        "source_hashes": source_manifest(),
        "required_test_ids": list(TEST_IDS),
        "required_gates": list(GATES),
        "historical_artifacts": {n: hash_file(ROOT / n) for n in paths},
        "packages": packages,
        "source_checks": json.loads(
            (ROOT / ".maturin/qms08/checks/proof.json").read_text()
        ),
        "empirical": empirical_disposition(),
        "saved_raw_pairs": [],
        "paired_report": paired_decomposition([]),
        "owner_review": "PENDING",
        "release_authorized": False,
        "complete_scientific_study": False,
        "performance_reference": "QMS07 sealed matched-source measurements; no new optimization claim in QMS08",
        "remote_matrix": "NOT_RUN; workflow prepared, no push/dispatch authorized",
    }
    return evidence


def create(junit):
    evidence = collect_evidence()
    return evidence, validate(evidence, junit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--gather-checks", action="store_true")
    parser.add_argument("--junit", type=Path, default=DIRECTORY / "qms08_tests.xml")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.gather_checks:
        gather_checks()
        print("QMS08 actual source/documentation commands passed and logged")
        return
    ep, rp = (
        DIRECTORY / "qms08_qualification_evidence.json",
        DIRECTORY / "qms08_gate_receipt.json",
    )
    if args.check or args.report:
        evidence = json.loads(ep.read_text())
        receipt = validate(evidence, args.junit)
        if receipt != json.loads(rp.read_text()):
            raise ValueError("receipt does not match verified execution")
    else:
        if ep.exists() or rp.exists():
            raise ValueError("do not overwrite sealed QMS08 artifacts")
        evidence, receipt = create(args.junit)
        ep.write_text(
            json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )
        rp.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    if args.report:
        args.report.write_text(
            "# QMS-08 Verified Summary\n\n"
            + f"Software: {receipt['software_status']}. Tests: {receipt['coverage']['tests']}. "
            f"Required IDs: {len(receipt['coverage']['members'])}.\n\n"
            f"Empirical: {receipt['empirical_status']}. Owner: PENDING. Release: not authorized.\n\n"
            + "\n".join(f"- {k}: {v}" for k, v in receipt["gates"].items())
            + "\n"
        )
    print(
        "QMS08 verified source, 64 test IDs, raw metrics, artifact bytes and installed consumers"
    )


if __name__ == "__main__":
    main()
