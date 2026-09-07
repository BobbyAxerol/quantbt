from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_next03_canonical_source_layout_has_no_root_mirror_and_keeps_identity() -> None:
    from tools.check_canonical_source_layout import (  # noqa: PLC0415
        _canonical_import_probe,
        root_mirror_regrowth,
        validate_canonical_source_layout,
    )

    assert root_mirror_regrowth() == []
    assert _canonical_import_probe() == str((ROOT / "src" / "quantbt" / "__init__.py").resolve())
    assert validate_canonical_source_layout() == []
