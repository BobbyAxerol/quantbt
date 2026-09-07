#!/usr/bin/env python3
"""Validate the artifact-bound local qualification record for NEXT-03.

This checker is intentionally fail-closed. It proves that a committed source
candidate still matches the package source and registry hashes used to build
the local artifact pair. It does not turn a local CPython 3.12 proof into a
published multi-platform release certificate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "contracts" / "next03_product_qualification.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = "quantbt-next03-product-qualification-v1"
_STATUS = "LOCAL_QUALIFIED_RELEASE_VERSION_REQUIRED"
_REQUIRED_PROOF = frozenset(
    {
        "source_hash_parity",
        "clean_install",
        "direct_target_smoke",
        "public_surface_smoke",
        "editable_source_smoke",
    }
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_canonical_source_layout import validate_canonical_source_layout  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, file_sha256  # noqa: E402


def _git_is_ancestor(root: Path, commit: object) -> bool:
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return False
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return completed.returncode == 0


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _proof_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return root / candidate


def validate_product_qualification(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    root: Path = ROOT,
) -> list[str]:
    """Return deterministic violations without touching artifacts or source."""

    try:
        payload: Mapping[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"NEXT-03 qualification manifest is unreadable: {exc}"]

    violations: list[str] = []
    if payload.get("schema") != _SCHEMA:
        violations.append("unsupported NEXT-03 qualification schema")
    if payload.get("status") != _STATUS:
        violations.append("qualification status must remain local and version-gated")

    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping):
        return violations + ["qualification candidate must be an object"]
    if candidate.get("candidate_tree_was_clean") is not True:
        violations.append("candidate must record a clean source tree")
    if candidate.get("source_layout") != "canonical_only":
        violations.append("candidate source layout must be canonical_only")
    if not _git_is_ancestor(root, candidate.get("commit")):
        violations.append("candidate commit must be an ancestor of the current checkout")

    identity = capture_measurement_identity(
        root=root,
        warmup_procedure="NEXT-03 final package qualification",
        data_sha256="next03-package-no-market-data",
        intent_sha256="next03-package-no-execution-intent",
    )
    for field in (
        "canonical_source_sha256",
        "product_registry_sha256",
        "lifecycle_registry_sha256",
    ):
        if not _valid_sha(candidate.get(field)):
            violations.append(f"candidate {field} must be a sha256")
        elif candidate[field] != identity.get(field):
            violations.append(f"candidate {field} no longer matches the checkout")
    violations.extend(validate_canonical_source_layout(root))

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping):
        violations.append("artifacts must be an object")
    else:
        for name in ("core_wheel", "core_sdist", "native_wheel"):
            row = artifacts.get(name)
            if not isinstance(row, Mapping) or not str(row.get("filename", "")).strip():
                violations.append(f"artifact {name} lacks a filename")
            elif not _valid_sha(row.get("sha256")):
                violations.append(f"artifact {name} lacks a sha256")
        native = artifacts.get("native_wheel", {})
        if isinstance(native, Mapping) and native.get("platform") != "linux-x86_64-cp312":
            violations.append("local native artifact must declare linux-x86_64-cp312 exactly")

    proof_ref = payload.get("consumer_proof")
    if not isinstance(proof_ref, Mapping):
        violations.append("consumer_proof must be an object")
    else:
        proof_path = _proof_path(root, proof_ref.get("path"))
        if proof_path is None or not proof_path.is_file():
            violations.append("consumer proof file is missing or escapes the repository")
        elif not _valid_sha(proof_ref.get("sha256")) or file_sha256(proof_path) != proof_ref["sha256"]:
            violations.append("consumer proof checksum does not match")
        else:
            try:
                proof = json.loads(proof_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                violations.append(f"consumer proof is unreadable: {exc}")
            else:
                required = frozenset(proof_ref.get("required", ()))
                if required != _REQUIRED_PROOF:
                    violations.append("consumer proof required fields drift")
                elif any(proof.get(field) is not True for field in required):
                    violations.append("consumer proof is missing a required passed lane")
                pair = proof.get("native_pair")
                if not isinstance(pair, Mapping) or pair.get("status") != "exact_staged_pair":
                    violations.append("consumer proof does not certify the exact native pair")

    qualification = payload.get("qualification")
    if not isinstance(qualification, Mapping):
        violations.append("qualification must be an object")
    else:
        release = qualification.get("release_profile")
        if not isinstance(release, Mapping) or release.get("status") != "passed":
            violations.append("release profile must be recorded as passed")
        elif int(release.get("shards", 0)) < 1:
            violations.append("release profile must record at least one shard")
        rust = qualification.get("rust_workspace")
        if not isinstance(rust, Mapping) or any(rust.get(key) != "passed" for key in ("fmt", "clippy", "tests")):
            violations.append("Rust workspace qualification is incomplete")
        if qualification.get("open_correctness_blockers") != []:
            violations.append("local qualification cannot hide open correctness blockers")

    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, Mapping):
        violations.append("outcomes must be an object")
    else:
        expected = {
            "single_source_distribution": "MET",
            "installed_docs_examples": "MET",
            "research_audit_compatibility": "PASS",
            "cross_domain_regression": "PASS",
            "remote_cpython_matrix": "PENDING_REMOTE",
            "public_publish": "VERSION_REQUIRED",
        }
        if any(outcomes.get(key) != value for key, value in expected.items()):
            violations.append("outcomes do not accurately represent the local-only gate")

    handoff = payload.get("release_handoff")
    if not isinstance(handoff, Mapping) or not isinstance(handoff.get("required_before_publication"), list):
        violations.append("release handoff must retain explicit pre-publication work")
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    violations = validate_product_qualification(args.manifest.resolve())
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("NEXT-03 local product qualification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
