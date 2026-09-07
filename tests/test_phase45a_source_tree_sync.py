from __future__ import annotations

from pathlib import Path

from tools.check_canonical_source_layout import validate_canonical_source_layout

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_phase45a_root_and_src_python_trees_have_one_canonical_origin() -> None:
    """NEXT-03 supersedes mirror parity with a canonical-only source gate."""

    assert validate_canonical_source_layout(PROJECT_ROOT) == []
