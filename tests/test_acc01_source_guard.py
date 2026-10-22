"""An approved source amendment admits exact committed bytes, never drift."""

from hashlib import sha256
import json

import pytest

from tools import account_metrics_source_guard as amendment
from tools import portfolio_repair_source_guard as guard


DATA = amendment.manifest(guard)


@pytest.mark.parametrize("name", sorted(DATA["sources"]))
def test_acc01_exact_committed_blob_normalization_and_tamper_rejection(name):
    entry = DATA["sources"][name]
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    expected = guard._blob(entry["before_commit"], name, entry["before_sha256"]) if entry["before_sha256"] else b""
    assert amendment.without_acc01(after, name, guard) == expected
    mutated = after + b"\n# unreviewed change\n"
    assert amendment.without_acc01(mutated, name, guard) == mutated


def test_acc01_amendment_is_locked_and_preserves_old_receipts(tmp_path, monkeypatch):
    assert sha256((guard.ROOT/amendment.MANIFEST_NAME).read_bytes()).hexdigest() == amendment.MANIFEST_SHA256
    assert DATA["baseline_commit"] == json.loads(guard.QUALIFICATION.read_text())["source_commit"]
    assert DATA["scopes"] == json.loads(guard.QUALIFICATION.read_text())["scopes"]
    path = tmp_path/amendment.MANIFEST_NAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(DATA)+"\n")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    with pytest.raises(AssertionError, match="ACC-01 amendment digest"):
        amendment.manifest(guard)


def test_acc01_current_source_never_reissues_historical_financial_claims():
    source = guard.verify_current_source()
    assert source["current_source_qualified"]
    assert source["historical_receipts_unchanged"]
    assert not source["financial_numeric_source_unchanged"]
    assert not source["financial_rust_unchanged"]
    assert not source["native_artifacts_qualified"]
    assert not source["historical_guards_reexecuted"]


@pytest.mark.parametrize("name", sorted(amendment.first_manifest(guard)["sources"]))
def test_acc01_first_receipt_blobs_remain_exact_historical_admissions(name):
    entry = amendment.first_manifest(guard)["sources"][name]
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    before = guard._blob(entry["before_commit"], name, entry["before_sha256"]) if entry["before_sha256"] else b""
    assert amendment.without_acc01(after, name, guard) == before
    assert amendment.without_acc01(after + b"\n# unknown\n", name, guard) == after + b"\n# unknown\n"
