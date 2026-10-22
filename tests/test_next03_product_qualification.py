from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from support.historical_assets import GitSnapshot


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def historical_identity() -> dict[str, str]:
    # The receipt/proof were committed after the frozen candidate was built.
    receipt = GitSnapshot("62b8ea1a5490fdea68940db3d40e431dcf9e7858")
    manifest = "contracts/next03_product_qualification.json"
    receipt.assert_retained(manifest)
    payload = receipt.read_json(manifest)
    snapshot = GitSnapshot(payload["candidate"]["commit"])
    identity = snapshot.source_identity()
    for field, value in identity.items():
        assert payload["candidate"][field] == value
    proof = payload["consumer_proof"]
    receipt.assert_record(proof)
    receipt.assert_retained(proof["path"])
    return identity


@pytest.fixture
def historical_qualification(monkeypatch, historical_identity):
    from tools import check_next03_product_qualification as tool

    # Adapt only the identity lookup to real Git blobs. The checker still
    # enforces ancestry, proof hashes, local-only gates and canonical layout.
    monkeypatch.setattr(tool, "capture_measurement_identity", lambda **kwargs: historical_identity)
    return tool.validate_product_qualification


def test_next03_product_qualification_matches_its_candidate_and_is_not_a_publish_certificate(
    historical_qualification,
) -> None:
    assert historical_qualification() == []
    payload = json.loads(
        (ROOT / "contracts" / "next03_product_qualification.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "LOCAL_QUALIFIED_RELEASE_VERSION_REQUIRED"
    assert payload["outcomes"]["remote_cpython_matrix"] == "PENDING_REMOTE"
    assert payload["outcomes"]["public_publish"] == "VERSION_REQUIRED"


@pytest.mark.parametrize(
    "field", ["canonical_source_sha256", "product_registry_sha256", "lifecycle_registry_sha256"]
)
def test_next03_product_qualification_rejects_stale_source_identity(
    tmp_path: Path, historical_qualification, field: str,
) -> None:

    source = ROOT / "contracts" / "next03_product_qualification.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["candidate"][field] = "0" * 64
    candidate = tmp_path / "qualification.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    assert historical_qualification(candidate) == [f"candidate {field} no longer matches the checkout"]


def test_next03_historical_qualification_does_not_certify_current_source() -> None:
    from tools.check_canonical_source_layout import validate_canonical_source_layout
    from tools.check_next03_product_qualification import validate_product_qualification
    from tools.measurement_contract import capture_measurement_identity

    assert validate_canonical_source_layout() == []
    identity = capture_measurement_identity(
        root=ROOT, warmup_procedure="NEXT-03 current source identity check"
    )
    payload = json.loads(
        (ROOT / "contracts" / "next03_product_qualification.json").read_text(encoding="utf-8")
    )
    expected = sorted(
        f"candidate {field} no longer matches the checkout"
        for field in ("canonical_source_sha256", "product_registry_sha256", "lifecycle_registry_sha256")
        if payload["candidate"][field] != identity[field]
    )
    assert validate_product_qualification() == expected
