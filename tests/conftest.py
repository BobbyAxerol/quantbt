from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"

# Tests must exercise the source layout under review, never a stale wheel that
# happens to be installed in the developer virtualenv. Repository root remains
# available for test-only ``tools`` imports; ``src/quantbt`` is the sole
# production package and is inserted first.
for path in (REPOSITORY_ROOT, SOURCE_ROOT):
    path_text = str(path)
    if path_text in sys.path:
        sys.path.remove(path_text)
    sys.path.insert(0, path_text)
