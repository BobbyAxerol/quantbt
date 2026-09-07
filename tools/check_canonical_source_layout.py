#!/usr/bin/env python3
"""Fail when a retired root QuantBT mirror or a non-canonical import returns.

This is the active NEXT-03 source-layout gate.  It deliberately permits the
reviewed root-only benchmark, example, reference-oracle, and migration tooling
surfaces while rejecting only production-module duplicates at repository root.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.next03_source_inventory import (  # noqa: E402
    CANONICAL_ROOT,
    RETIRED_MIRROR_ENTRIES,
    ROOT_ONLY_SURFACES,
    build_inventory,
    root_mirror_entry_present,
    validate_inventory,
    _load_retirement_baseline,
)


def root_mirror_regrowth(root: Path = ROOT) -> list[str]:
    """Return actionable errors for only the reviewed root mirror namespace."""

    findings = [
        f"retired root mirror entry has reappeared: {entry}"
        for entry in RETIRED_MIRROR_ENTRIES
        if root_mirror_entry_present(entry, root=root)
    ]
    canonical_top_levels = {
        path.relative_to(CANONICAL_ROOT).parts[0]
        for path in CANONICAL_ROOT.rglob("*.py")
        if path.is_file()
    }
    allowed_root_names = set(ROOT_ONLY_SURFACES)
    for name in sorted(canonical_top_levels - allowed_root_names - set(RETIRED_MIRROR_ENTRIES)):
        if root_mirror_entry_present(name, root=root):
            findings.append(f"unreviewed root production namespace overlaps src/quantbt: {name}")
    return sorted(set(findings))


def _canonical_import_probe(root: Path = ROOT) -> str:
    """Prove a checkout-parent import resolves the canonical src package only."""

    script = """
import sys
from pathlib import Path

repository = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repository.parent))
sys.path.insert(1, str(repository / 'src'))

import quantbt
from quantbt import NativeEventBackend, QuantBTEndpoint, ResearchAuditArtifactV1
from quantbt.backends import NativeEventBackend as DirectNativeEventBackend
from quantbt.core.research_audit import ResearchAuditArtifactV1 as DirectResearchAuditArtifactV1
from quantbt.endpoint import QuantBTEndpoint as DirectQuantBTEndpoint

origin = Path(quantbt.__file__).resolve()
expected = repository / 'src' / 'quantbt' / '__init__.py'
assert origin == expected, (origin, expected)
assert QuantBTEndpoint is DirectQuantBTEndpoint
assert NativeEventBackend is DirectNativeEventBackend
assert ResearchAuditArtifactV1 is DirectResearchAuditArtifactV1
print(origin)
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(root)],
        cwd=root.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            "canonical import/type-identity probe failed:\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout.strip()


def validate_canonical_source_layout(root: Path = ROOT) -> list[str]:
    """Return all layout failures without modifying tracked files."""

    violations = root_mirror_regrowth(root)
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]
    if package_find.get("where") != ["src"]:
        violations.append("setuptools package discovery must remain src-only")
    if "quantbt*" not in package_find.get("include", []):
        violations.append("setuptools package discovery must include quantbt*")
    baseline = _load_retirement_baseline(root / "contracts" / "next03_root_mirror_retirement_baseline.json")
    inventory = build_inventory(retirement_baseline=baseline)
    violations.extend(validate_inventory(inventory, retirement_baseline=baseline))
    if inventory.get("mirror", {}).get("state") != "canonical_only":
        violations.append("active source layout must be canonical_only")
    try:
        _canonical_import_probe(root)
    except RuntimeError as exc:
        violations.append(str(exc))
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="kept for CI command consistency")
    parser.parse_args(argv)
    violations = validate_canonical_source_layout()
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("canonical source layout/no-regrowth gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
