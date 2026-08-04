from __future__ import annotations

import hashlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = PROJECT_ROOT / "src" / "quantbt"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase45a_root_and_src_python_trees_are_identical_during_migration() -> None:
    """Prevent editable/root imports from drifting away from wheel source."""
    canonical_files = sorted(CANONICAL_ROOT.rglob("*.py"))
    assert canonical_files, "src/quantbt must contain the canonical Python package"

    for canonical in canonical_files:
        relative = canonical.relative_to(CANONICAL_ROOT)
        compatibility_mirror = PROJECT_ROOT / relative
        assert compatibility_mirror.is_file(), f"root compatibility mirror missing: {relative}"
        assert _sha256(canonical) == _sha256(compatibility_mirror), f"root/src source drift: {relative}"
