"""Manifest and hash checks for the temporary root/source package mirror.

``src/quantbt`` is the wheel source of truth. The root-level Python tree is a
compatibility mirror for local Pool Alpha imports and is deliberately kept
outside the wheel build. The manifest is explicit so benchmarks and tools are
never mistaken for package source.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = PROJECT_ROOT / "src" / "quantbt"

MIRROR_ENTRIES = (
    "__init__.py",
    "backtester.py",
    "endpoint.py",
    "engines.py",
    "errors.py",
    "portfolio.py",
    "walkforward.py",
    "adapters",
    "backends",
    "core",
    "metrics",
    "optimization",
    "options",
    "api",
    "planning",
    "preparation",
    "engine_spi",
    "results",
    "strategies",
    "reporting",
    "sizing",
    "verification",
    "viz",
)


def sha256(path: Path) -> str:
    """Return the content hash used by mirror parity checks."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_files(project_root: Path = PROJECT_ROOT) -> dict[Path, Path]:
    """Collect manifest-approved Python files keyed relative to ``src/quantbt``."""

    root = project_root / "src" / "quantbt"
    files: dict[Path, Path] = {}
    for entry_name in MIRROR_ENTRIES:
        entry = root / entry_name
        if entry.is_file() and entry.suffix == ".py":
            files[Path(entry.name)] = entry
        elif entry.is_dir():
            for path in entry.rglob("*.py"):
                files[path.relative_to(root)] = path
    return files


def mirror_files(project_root: Path = PROJECT_ROOT) -> dict[Path, Path]:
    """Collect only manifest-approved root mirror files."""

    files: dict[Path, Path] = {}
    for entry_name in MIRROR_ENTRIES:
        entry = project_root / entry_name
        if entry.is_file() and entry.suffix == ".py":
            files[Path(entry.name)] = entry
        elif entry.is_dir():
            for path in entry.rglob("*.py"):
                files[path.relative_to(project_root)] = path
    return files


def compare_file_maps(
    canonical: dict[Path, Path],
    mirror: dict[Path, Path],
) -> dict[str, tuple[Path, ...]]:
    """Compare two relative-path maps without modifying either tree."""

    missing = sorted(canonical.keys() - mirror.keys())
    extra = sorted(mirror.keys() - canonical.keys())
    drift = sorted(
        relative
        for relative in canonical.keys() & mirror.keys()
        if sha256(canonical[relative]) != sha256(mirror[relative])
    )
    return {
        "missing": tuple(missing),
        "extra": tuple(extra),
        "drift": tuple(drift),
    }


def mirror_differences(project_root: Path = PROJECT_ROOT) -> dict[str, tuple[Path, ...]]:
    """Return missing, extra, and byte-drifted manifest entries."""

    return compare_file_maps(
        canonical_files(project_root),
        mirror_files(project_root),
    )


def format_differences(differences: dict[str, tuple[Path, ...]]) -> str:
    """Format mirror differences for CLI and CI output."""

    lines: list[str] = []
    for label in ("missing", "extra", "drift"):
        values = differences[label]
        if values:
            lines.append(f"{label}: " + ", ".join(str(value) for value in values))
    return "\n".join(lines) or "mirror check: PASS"
