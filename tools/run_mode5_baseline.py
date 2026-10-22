#!/usr/bin/env python3
"""Run private M5-01 provenance checks using the invoking interpreter."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.mode5_baseline.runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
