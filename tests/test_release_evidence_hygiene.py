"""Performance-evolution provenance gates."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVOLUTION_TOOL = ROOT / "tools" / "generate_performance_evolution.py"


def test_release_performance_evolution_resolves_committed_raw_evidence() -> None:
    result = subprocess.run(
        [sys.executable, str(EVOLUTION_TOOL), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Performance evolution evidence verified" in result.stdout
    assert (ROOT / "docs" / "assets" / "quantbt-performance-evolution.png").is_file()
