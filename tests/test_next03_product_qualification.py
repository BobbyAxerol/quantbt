from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_next03_product_qualification_is_current_and_explicitly_not_a_publish_certificate() -> None:
    from tools.check_next03_product_qualification import validate_product_qualification

    assert validate_product_qualification() == []
    payload = json.loads(
        (ROOT / "contracts" / "next03_product_qualification.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "LOCAL_QUALIFIED_RELEASE_VERSION_REQUIRED"
    assert payload["outcomes"]["remote_cpython_matrix"] == "PENDING_REMOTE"
    assert payload["outcomes"]["public_publish"] == "VERSION_REQUIRED"


def test_next03_product_qualification_rejects_stale_source_identity(tmp_path: Path) -> None:
    from tools.check_next03_product_qualification import validate_product_qualification

    source = ROOT / "contracts" / "next03_product_qualification.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["candidate"]["canonical_source_sha256"] = "0" * 64
    candidate = tmp_path / "qualification.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    assert "candidate canonical_source_sha256 no longer matches the checkout" in validate_product_qualification(
        candidate
    )
