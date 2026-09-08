#!/usr/bin/env python3
"""Generate the Phase NEXT-03 canonical-source inventory.

``src/quantbt`` is the sole production package.  The repository once carried
a byte-identical root compatibility mirror; its reviewed hashes are retained in
a separate immutable baseline so the source tree can stay single-source while
the retirement remains auditable and reversible by a scoped Git revert.
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
DEFAULT_RETIREMENT_BASELINE = ROOT / "contracts" / "next03_root_mirror_retirement_baseline.json"

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


def root_mirror_entry_present(entry: str, *, root: Path = ROOT) -> bool:
    """Return whether a retired entry contains importable root production code.

    ``git rm`` may leave ignored ``__pycache__`` directories behind in a live
    developer checkout. They are not a production mirror and must not block a
    canonical layout, while a symlink or any Python file remains a hard failure.
    """

    path = root / entry
    if path.is_symlink():
        return True
    if path.is_file():
        return path.suffix == ".py"
    return path.is_dir() and any(candidate.is_file() for candidate in path.rglob("*.py"))


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


def _retirement_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    """Freeze reviewed root hashes before the compatibility tree is removed."""

    records = []
    for record in payload["canonical_modules"]:
        if record.get("mirror_status") != "verified_byte_identical":
            continue
        records.append(
            {
                "canonical_path": record["canonical_path"],
                "historical_root_path": record["root_path"],
                "sha256": record["sha256"],
            }
        )
    return {
        "schema": "quantbt-next03-root-mirror-retirement-baseline-v1",
        "canonical_source": "src/quantbt",
        "historical_entries": list(RETIRED_MIRROR_ENTRIES),
        "verified_files": len(records),
        "records": records,
        "rollback": "git-revert of the isolated root-mirror retirement commit",
    }


def _load_retirement_baseline(path: Path = DEFAULT_RETIREMENT_BASELINE) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline_hashes(payload: dict[str, Any] | None) -> dict[str, str]:
    if payload is None:
        return {}
    if payload.get("schema") != "quantbt-next03-root-mirror-retirement-baseline-v1":
        return {}
    return {
        str(record["historical_root_path"]): str(record["sha256"])
        for record in payload.get("records", [])
        if isinstance(record, dict)
        and str(record.get("historical_root_path", ""))
        and str(record.get("sha256", ""))
    }


def build_inventory(
    *,
    retirement_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an inventory without changing the source tree."""

    baseline_hashes = _baseline_hashes(retirement_baseline)
    retirement_verified = retirement_baseline is not None and not validate_retirement_baseline(retirement_baseline)
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
            elif relative.as_posix() in baseline_hashes:
                record.update(
                    {
                        "root_path": relative.as_posix(),
                        "historical_root_sha256": baseline_hashes[relative.as_posix()],
                        "disposition": "retired_to_canonical",
                        "mirror_status": "retired",
                    }
                )
            elif retirement_verified:
                # The frozen ledger records files, not all future modules in
                # their directories. New src-only modules need no root mirror.
                record.update(
                    {
                        "disposition": "canonical_package_only",
                        "mirror_status": "not_in_historical_mirror_scope",
                    }
                )
            else:
                record.update(
                    {
                        "root_path": relative.as_posix(),
                        "disposition": "retirement_candidate",
                        "mirror_status": "absent_unproven",
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

    root_entries_present = [entry for entry in RETIRED_MIRROR_ENTRIES if root_mirror_entry_present(entry)]
    expected_entries = set(RETIRED_MIRROR_ENTRIES)
    present_entry_set = set(root_entries_present)
    if mirror_drift:
        mirror_state = "blocked_drift"
    elif present_entry_set == expected_entries:
        mirror_state = "verified_retirement_ready"
    elif root_entries_present:
        mirror_state = "partial_root_mirror"
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
            "present_verified_files": len(mirror_present),
            "historical_verified_files": len(baseline_hashes) if baseline_hashes else len(mirror_present),
            "drifted_files": mirror_drift,
            "retirement_baseline": (
                "contracts/next03_root_mirror_retirement_baseline.json"
                if retirement_baseline is not None
                else None
            ),
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


def validate_retirement_baseline(payload: dict[str, Any] | None) -> list[str]:
    """Validate the frozen pre-retirement hash ledger without reading root code."""

    if payload is None:
        return ["root-mirror retirement baseline is missing"]
    violations: list[str] = []
    if payload.get("schema") != "quantbt-next03-root-mirror-retirement-baseline-v1":
        violations.append("unsupported root-mirror retirement baseline schema")
    if payload.get("canonical_source") != "src/quantbt":
        violations.append("retirement baseline must name src/quantbt as canonical")
    if payload.get("historical_entries") != list(RETIRED_MIRROR_ENTRIES):
        violations.append("retirement baseline historical entry list is not exact")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        violations.append("retirement baseline records must be non-empty")
    else:
        paths = [str(record.get("historical_root_path", "")) for record in records if isinstance(record, dict)]
        if len(paths) != len(set(paths)):
            violations.append("retirement baseline has duplicate historical root paths")
        if int(payload.get("verified_files", -1)) != len(records):
            violations.append("retirement baseline verified file count is inconsistent")
        for record in records:
            if not isinstance(record, dict):
                violations.append("retirement baseline record must be an object")
                continue
            canonical = ROOT / str(record.get("canonical_path", ""))
            if not canonical.is_file():
                violations.append(f"retirement baseline canonical path is missing: {record.get('canonical_path')}")
            if not str(record.get("sha256", "")):
                violations.append("retirement baseline record is missing sha256")
    return sorted(set(violations))


def validate_inventory(
    payload: dict[str, Any],
    *,
    retirement_baseline: dict[str, Any] | None = None,
) -> list[str]:
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
    if state == "canonical_only":
        violations.extend(validate_retirement_baseline(retirement_baseline))
        retired = [record for record in records if record.get("mirror_status") == "retired"]
        if len(retired) != int(mirror.get("historical_verified_files", 0)):
            violations.append("canonical-only inventory is missing retired mirror provenance")
    for record in payload.get("root_only_support", []):
        if not (ROOT / record["path"]).is_file():
            violations.append(f"root-only support file is missing: {record['path']}")
    return sorted(set(violations))


def render_markdown(payload: dict[str, Any]) -> str:
    mirror = payload["mirror"]
    canonical_modules = payload["canonical_modules"]
    package_only = sum(item["disposition"] == "canonical_package_only" for item in canonical_modules)
    retired = sum(item["disposition"] == "retired_to_canonical" for item in canonical_modules)
    status_text = (
        "The historical root compatibility mirror has been retired."
        if mirror["state"] == "canonical_only"
        else "The historical root compatibility entries are a reviewed retirement candidate only."
    )
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
            f"- Canonical Python modules: `{len(canonical_modules)}`; retired mirror modules: `{retired}`; canonical-only modules: `{package_only}`.",
            "",
            "## Retirement Scope",
            "",
            status_text + " Root benchmark harnesses, examples, independent reference oracles, and migration tooling are not mirror files and are retained.",
            "",
            "`canonical_only` is the required state. CI prevents mirror regrowth instead of recreating a second source tree; rollback is a scoped Git revert of the retirement commit.",
            "",
            "## Evidence",
            "",
            "The machine-readable inventory contains per-file hashes, disposition, owner, consumer proof, and rollback reference:",
            "",
            "- [`contracts/next03_source_layout_inventory.json`](../../contracts/next03_source_layout_inventory.json)",
            "- [`contracts/next03_root_mirror_retirement_baseline.json`](../../contracts/next03_root_mirror_retirement_baseline.json)",
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
    parser.add_argument("--retirement-baseline", type=Path, default=DEFAULT_RETIREMENT_BASELINE)
    parser.add_argument("--check", action="store_true", help="verify generated artifacts without writing")
    args = parser.parse_args(argv)
    retirement_baseline = _load_retirement_baseline(args.retirement_baseline)
    provisional = build_inventory(retirement_baseline=retirement_baseline)
    if provisional["mirror"]["state"] == "verified_retirement_ready" and retirement_baseline is None:
        retirement_baseline = _retirement_baseline(provisional)
    payload = build_inventory(retirement_baseline=retirement_baseline)
    violations = validate_inventory(payload, retirement_baseline=retirement_baseline)
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
    if retirement_baseline is not None:
        _write(
            args.retirement_baseline,
            json.dumps(retirement_baseline, indent=2, sort_keys=True) + "\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
