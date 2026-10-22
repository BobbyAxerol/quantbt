"""Current exact extraction proof, old receipts and fail-closed source drift."""

from hashlib import sha256
import json

import pytest

from tools import m5_12_source_guard as current
from tools import portfolio_repair_source_guard as guard


DATA = current.manifest(guard)


def test_current_source_qualifies_extraction_without_reissuing_old_qms_claims():
    result = current.verify_current_source()
    assert result["pre_m512_source_commit"] == DATA["source_commit"]
    from tools.m5_12_pct_source_amendment import manifest
    assert result["source_commit"] == manifest(guard)["source_commit"]
    assert result["acc01_source_commit"] == DATA["acc01_source_commit"]
    assert result["pre_m512_amendment_sha256"] == current.MANIFEST_SHA256
    assert result["financial_source_changed"] and not result["financial_numeric_source_unchanged"]
    assert not result["financial_rust_unchanged"]
    assert result["cold_extraction_semantics_unchanged"]
    assert result["historical_receipts_unchanged"] and not result["historical_guards_reexecuted"]
    assert not result["native_artifacts_qualified"] and not result["publication"]


@pytest.mark.parametrize("name", DATA["sources"])
def test_exact_committed_extraction_and_its_unknown_suffix_have_distinct_admission(name):
    entry = DATA["sources"][name]
    after = guard._blob(entry["after_commit"],name,entry["after_sha256"])
    before = guard._blob(entry["before_commit"],name,entry["before_sha256"]) if entry["before_sha256"] else b""
    assert current.without_extraction(after,name,guard) == before
    unknown = after+b"\n# unknown drift\n"
    assert current.without_extraction(unknown,name,guard) == unknown


def test_unreviewed_path_cannot_claim_extraction():
    raw = b"not an approved helper\n"
    assert current.without_extraction(raw,"src/quantbt/unreviewed.py",guard) == raw


def test_manifest_mutation_is_not_a_new_certificate(tmp_path,monkeypatch):
    path = tmp_path/current.MANIFEST_NAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(DATA)+"\n")
    monkeypatch.setattr(guard,"ROOT",tmp_path)
    with pytest.raises(AssertionError,match="extraction manifest digest"):
        current.manifest(guard)


def test_exact_before_tree_is_required_for_source_amendment():
    from tools.public_inventory_source_amendment import current_inventory_amendment
    expected = guard._committed_source_hashes(DATA["acc01_source_commit"],DATA["scopes"])
    expected,_ = current_inventory_amendment(expected,guard.ROOT)
    assert current.apply_extraction(guard,expected,DATA["scopes"])[0] == DATA
    expected["src/quantbt/endpoint.py"] = "0"*64
    with pytest.raises(AssertionError,match="exact approved current baseline"):
        current.apply_extraction(guard,expected,DATA["scopes"])


def test_historical_helper_inventory_cannot_hide_newer_unreviewed_bytes(tmp_path,monkeypatch):
    name = "src/quantbt/backends/portfolio_reports.py"
    path = tmp_path/name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unknown helper\n")
    monkeypatch.setattr(current,"manifest",lambda _:DATA)
    monkeypatch.setattr(guard,"ROOT",tmp_path)
    with pytest.raises(AssertionError,match="unreviewed extracted helper"):
        current.historical_names({name},DATA["baseline_commit"],guard)


def test_manifest_digest_is_a_separate_immutable_receipt():
    assert sha256((guard.ROOT/current.MANIFEST_NAME).read_bytes()).hexdigest() == current.MANIFEST_SHA256
    assert DATA["native_artifacts_qualified"] is False
    assert DATA["historical_financial_invariance_claim_reissued"] is False
