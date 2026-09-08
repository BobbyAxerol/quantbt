"""Release evidence must not dirty the candidate under certification."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_release_evidence_is_ignored_before_clean_tree_measurement() -> None:
    """The release workflow writes evidence before measuring a clean candidate."""

    result = subprocess.run(
        ["git", "check-ignore", "-q", "native-release-evidence/phase78-public-promotion.json"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0
