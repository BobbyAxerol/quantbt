from __future__ import annotations

from pathlib import Path

from tools.source_mirror_manifest import canonical_files, mirror_differences

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_phase45a_root_and_src_python_trees_are_identical_during_migration() -> None:
    """Keep the explicitly approved compatibility mirror byte-identical.

    ``src/quantbt`` also contains package-only helpers such as benchmark
    measurement code.  Only entries in the manifest are local-root import
    compatibility surfaces, so unlisted package helpers must not create an
    accidental second source tree requirement.
    """

    assert canonical_files(PROJECT_ROOT), "src/quantbt must contain mirrored package modules"
    differences = mirror_differences(PROJECT_ROOT)
    assert not any(differences.values()), differences
