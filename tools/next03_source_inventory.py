#!/usr/bin/env python3
"""Generate the Phase NEXT-03 source-layout inventory.

``src/quantbt`` is the canonical production package.  Until the reviewed
retirement change lands, a subset of it is mirrored at repository root for
legacy local imports.  This tool records every canonical module, the exact
mirror relation where one exists, and the root-only developer/oracle surfaces
that must not be deleted as part of mirror retirement.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import tomllib
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = ROOT / "src" / "quantbt"
DEFAULT_INVENTORY = ROOT / "contracts" / "next03_source_layout_inventory.json"
DEFAULT_DOC = ROOT / "docs" / "architecture" / "source_layout.md"

# This is an inventory of the historical compatibility mirror, not a second
# package-discovery rule.  The list deliberately excludes root tooling,
# independent references, examples, and benchmark harnesses.
RETIRED_MIRROR_ENTRIES = (
    "__init__.py",
    "backtester.py",
    "endpoint.py",
    "engines.py",
    "errors.py",
    "portfolio.py",
    "walkforward.py",
    "adapters",
    "api",
    "backends",
    "core",
    "engine_spi",
    "metrics",
    "optimization",
    "options",
    "planning",
    "preparation",
    "reporting",
    "results",
    "sizing",
    "strategies",
    "verification",
    "viz",
)

ROOT_ONLY_SURFACES = {
    "benchmarks": "developer_benchmark_tooling",
    "examples": "developer_examples",
    "reference": "independent_python_oracles",
    "quantbt_phase34_merge_gate.py": "historical_migration_gate",
}


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _is_mirrored(relative: Path) -> bool:
    if relative.as_posix() in RETIRED_MIRROR_ENTRIES:
        return True
    return bool(relative.parts and relative.parts[0] in RETIRED_MIRROR_ENTRIES)


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _root_only_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for surface, role in sorted(ROOT_ONLY_SURFACES.items()):
        path = ROOT / surface
        if path.is_file():
            records.append(
                {
                    "path": surface,
                    "role": role,
                    "sha256": _sha256(path),
                }
            )
            continue
        if path.is_dir():
            for file in _python_files(path):
                records.append(
                    {
                        "path": file.relative_to(ROOT).as_posix(),
                        "role": role,
                        "sha256": _sha256(file),
                    }
                )
    return records


def _build_metadata() -> dict[str, Any]:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_find = payload["tool"]["setuptools"]["packages"]["find"]
    return {
        "distribution": str(payload["project"]["name"]),
        "version": str(payload["project"]["version"]),
        "package_find_where": list(package_find["where"]),
        "package_find_include": list(package_find["include"]),
        "manifest": "MANIFEST.in",
        "native_distribution": "rust/native_event/pyproject.toml",
    }


def build_inventory() -> dict[str, Any]:
    """Return an inventory without changing the source tree."""

    canonical_records: list[dict[str, Any]] = []
    mirror_present: list[str] = []
    mirror_drift: list[str] = []
    for source in _python_files(CANONICAL_ROOT):
        relative = source.relative_to(CANONICAL_ROOT)
        root_copy = ROOT / relative
        record: dict[str, Any] = {
            "canonical_path": (Path("src") / "quantbt" / relative).as_posix(),
            "sha256": _sha256(source),
            "owner": "canonical_quantbt_package",
            "consumer_proof": "tests/test_next03_source_inventory.py",
            "rollback": "git-revert of the isolated root-mirror retirement commit",
        }
        if _is_mirrored(relative):
            if root_copy.is_file():
                root_hash = _sha256(root_copy)
                status = "verified_byte_identical" if root_hash == record["sha256"] else "drift"
                record.update(
                    {
                        "root_path": relative.as_posix(),
                        "root_sha256": root_hash,
                        "disposition": "retirement_candidate" if status == "verified_byte_identical" else "blocked_drift",
                        "mirror_status": status,
                    }
                )
                mirror_present.append(relative.as_posix())
                if status == "drift":
                    mirror_drift.append(relative.as_posix())
            else:
                record.update(
                    {
                        "root_path": relative.as_posix(),
                        "disposition": "retirement_candidate",
                        "mirror_status": "absent",
                    }
                )
        else:
            record.update(
                {
                    "disposition": "canonical_package_only",
                    "mirror_status": "not_in_historical_mirror_scope",
                }
            )
        canonical_records.append(record)

    root_entries_present = [entry for entry in RETIRED_MIRROR_ENTRIES if (ROOT / entry).exists()]
    if mirror_drift:
        mirror_state = "blocked_drift"
    elif root_entries_present:
        mirror_state = "verified_retirement_ready"
    else:
        mirror_state = "canonical_only"

    return {
        "schema": "quantbt-next03-source-layout-v1",
        "canonical_source": "src/quantbt",
        "build": _build_metadata(),
        "mirror": {
            "historical_entries": list(RETIRED_MIRROR_ENTRIES),
            "state": mirror_state,
            "present_entries": root_entries_present,
            "verified_files": len(mirror_present),
            "drifted_files": mirror_drift,
            "retirement_owner": "packaging",
            "retirement_test": "tests/test_next03_source_inventory.py",
        },
        "canonical_modules": canonical_records,
        "root_only_support": _root_only_records(),
        "consumer_inventory": {
            "test_source_priority": "tests/conftest.py",
            "ci_consumers": [
                ".github/workflows/ci.yml",
                ".github/workflows/native.yml",
                ".github/workflows/native-release.yml",
                ".github/workflows/publish.yml",
                ".github/workflows/publish-native.yml",
                ".github/workflows/publish-testpypi.yml",
            ],
            "migration_docs": [
                "docs/release_packaging.md",
                "docs/migration/native_release_handoff.md",
                "CONTRIBUTING.md",
            ],
        },
    }


def validate_inventory(payload: dict[str, Any]) -> list[str]:
    """Return deterministic violations for a generated inventory."""

    violations: list[str] = []
    if payload.get("schema") != "quantbt-next03-source-layout-v1":
        violations.append("unsupported NEXT-03 source inventory schema")
    if payload.get("canonical_source") != "src/quantbt":
        violations.append("canonical source must remain src/quantbt")
    build = payload.get("build", {})
    if build.get("package_find_where") != ["src"]:
        violations.append("setuptools package discovery must remain src-only")
    if "quantbt*" not in build.get("package_find_include", []):
        violations.append("setuptools package discovery must include quantbt*")
    mirror = payload.get("mirror", {})
    state = mirror.get("state")
    if state not in {"verified_retirement_ready", "canonical_only"}:
        violations.append(f"invalid mirror retirement state: {state!r}")
    if mirror.get("drifted_files"):
        violations.append("historical root mirror has byte drift")
    records = payload.get("canonical_modules", [])
    if not records:
        violations.append("canonical module inventory must not be empty")
    for record in records:
        if not (ROOT / record["canonical_path"]).is_file():
            violations.append(f"missing canonical module: {record['canonical_path']}")
        if record.get("disposition") == "blocked_drift":
            violations.append(f"unresolved mirror drift: {record['canonical_path']}")
    if state == "verified_retirement_ready":
        missing = set(RETIRED_MIRROR_ENTRIES) - set(mirror.get("present_entries", []))
        if missing:
            violations.append(f"partial root mirror is not retirement-ready: {sorted(missing)}")
    if state == "canonical_only" and mirror.get("present_entries"):
        violations.append("canonical-only inventory still has root mirror entries")
    for record in payload.get("root_only_support", []):
        if not (ROOT / record["path"]).is_file():
            violations.append(f"root-only support file is missing: {record['path']}")
    return sorted(set(violations))


def render_markdown(payload: dict[str, Any]) -> str:
    mirror = payload["mirror"]
    canonical_modules = payload["canonical_modules"]
    package_only = sum(item["disposition"] == "canonical_package_only" for item in canonical_modules)
    return "\n".join(
        (
            "# Canonical Source Layout",
            "",
            "Generated by `tools/next03_source_inventory.py`; do not hand-edit.",
            "",
            "## Source Of Truth",
            "",
            f"- Canonical package: `{payload['canonical_source']}`.",
            f"- Distribution: `{payload['build']['distribution']}=={payload['build']['version']}`.",
            f"- Setuptools discovery: `{payload['build']['package_find_where']}` / `{payload['build']['package_find_include']}`.",
            f"- Historical root-mirror state: `{mirror['state']}`.",
            f"- Canonical Python modules: `{len(canonical_modules)}`; historical mirror files verified: `{mirror['verified_files']}`; canonical-only modules: `{package_only}`.",
            "",
            "## Retirement Scope",
            "",
            "The historical root compatibility entries are a reviewed retirement candidate only. "
            "Root benchmark harnesses, examples, independent reference oracles, and migration tooling are not mirror files and are retained.",
            "",
            "Before a root-mirror deletion, clean wheel/consumer and type-identity proofs must pass. "
            "After deletion, `canonical_only` is the required state and CI must prevent regrowth instead of recreating a second source tree.",
            "",
            "## Evidence",
            "",
            "The machine-readable inventory contains per-file hashes, disposition, owner, consumer proof, and rollback reference:",
            "",
            "- [`contracts/next03_source_layout_inventory.json`](../../contracts/next03_source_layout_inventory.json)",
            "- [`tests/test_next03_source_inventory.py`](../../tests/test_next03_source_inventory.py)",
        )
    )


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument("--check", action="store_true", help="verify generated artifacts without writing")
    args = parser.parse_args(argv)
    payload = build_inventory()
    violations = validate_inventory(payload)
    if violations:
        raise SystemExit("NEXT-03 source inventory failed: " + "; ".join(violations))
    inventory = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(payload) + "\n"
    if args.check:
        expected_inventory = args.inventory.read_text(encoding="utf-8") if args.inventory.is_file() else ""
        expected_doc = args.doc.read_text(encoding="utf-8") if args.doc.is_file() else ""
        if inventory != expected_inventory or markdown != expected_doc:
            raise SystemExit("NEXT-03 source inventory artifacts are stale; rerun tools/next03_source_inventory.py")
        return 0
    _write(args.inventory, inventory)
    _write(args.doc, markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
