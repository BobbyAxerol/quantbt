"""Compiler repairs cannot broaden financial or historical qualification."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import m5_12_ci_rust_amendment as amendment
from tools import portfolio_repair_source_guard as guard


def test_exact_current_rust_source_keeps_historical_format_identity():
    from tools.m5_12_ci_format_amendment import MANIFEST_SHA256, SOURCE_COMMIT
    result = guard.verify_current_source()
    assert result["source_commit"] == amendment.SOURCE_COMMIT
    assert result["m5_12_ci_format_source_commit"] == amendment.BASELINE_COMMIT == SOURCE_COMMIT
    assert result["m5_12_ci_format_amendment_sha256"] == MANIFEST_SHA256
    assert result["m5_12_ci_rust_amendment_sha256"] == amendment.MANIFEST_SHA256
    assert set(result["m5_12_ci_rust_changed_sources"]) == amendment.SOURCE_PATHS
    assert result["qualified_source_count"] == 466
    assert result["historical_receipts_unchanged"] and not result["historical_guards_reexecuted"]
    assert not result["native_artifacts_qualified"] and not result["publication"]
    assert not result["financial_numeric_source_unchanged"] and not result["ci_rustfmt_only"]


@pytest.mark.parametrize("name", sorted(amendment.SOURCE_PATHS))
def test_only_exact_reviewed_blob_can_be_normalized(name):
    entry = amendment.manifest(guard)["sources"][name]
    before = guard._blob(amendment.BASELINE_COMMIT, name, entry["before_sha256"])
    after = guard._blob(amendment.SOURCE_COMMIT, name, entry["after_sha256"])
    assert amendment.without_ci_rust(after, name, guard) == before != after
    for changed in (after + b"\n", after.replace(b"0", b"1", 1), b"//unreviewed\n" + after):
        assert changed != after and amendment.without_ci_rust(changed, name, guard) == changed
    assert amendment.without_ci_rust(after, "rust/other.rs", guard) == after
    other = next(iter(amendment.SOURCE_PATHS - {name}))
    assert amendment.without_ci_rust(after, other, guard) == after


@pytest.mark.parametrize("key,value", [
    ("baseline_commit", "0" * 40), ("source_commit", "0" * 40), ("sources", {}),
    ("scopes", ["rust"]), ("previous_amendment_sha256", "wrong"),
    ("source_only", False), ("fresh_native_artifacts_required", False),
    ("publication", True), ("native_artifacts_qualified", True), ("version_bump", True),
    ("historical_financial_invariance_claim_reissued", True),
    ("financial_numeric_source_unchanged", True),
])
def test_repinned_manifest_cannot_expand_scope_or_claims(tmp_path, monkeypatch, key, value):
    changed = deepcopy(amendment.manifest(guard))
    changed[key] = value
    path = tmp_path / "manifest.json"
    payload = json.dumps(changed).encode()
    path.write_bytes(payload)
    monkeypatch.setattr(amendment, "MANIFEST_NAME", str(path))
    monkeypatch.setattr(amendment, "MANIFEST_SHA256", sha256(payload).hexdigest())
    with pytest.raises(AssertionError):
        amendment.manifest(guard)


def test_changed_manifest_cannot_reuse_digest(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_bytes((guard.ROOT / amendment.MANIFEST_NAME).read_bytes() + b"\n")
    monkeypatch.setattr(amendment, "MANIFEST_NAME", str(path))
    with pytest.raises(AssertionError, match="manifest digest"):
        amendment.manifest(guard)


@pytest.mark.parametrize("mutation", ("extra", "missing", "bytes"))
def test_current_source_inventory_drift_is_rejected(monkeypatch, mutation):
    value = amendment.manifest(guard)
    original = guard._committed_source_hashes
    before = original(amendment.BASELINE_COMMIT, value["scopes"])

    def committed(commit, scopes):
        result = original(commit, scopes)
        if commit == amendment.SOURCE_COMMIT:
            if mutation == "extra":
                result["rust/other.rs"] = "0" * 64
            elif mutation == "missing":
                result.pop("rust/native_event/src/qms_numeric.rs")
            else:
                result["rust/native_event/src/lib.rs"] = "0" * 64
        return result

    monkeypatch.setattr(guard, "_committed_source_hashes", committed)
    with pytest.raises(AssertionError):
        amendment.apply_ci_rust(guard, before, value["scopes"])


def test_installed_custody_pins_new_verifier():
    from tools.m5_12_installed_preflight import verifier_manifest
    from tools.m5_12_pct_installed import source_pins
    name = "tools/m5_12_ci_rust_amendment.py"
    assert verifier_manifest()[name] == source_pins()[name] == sha256((guard.ROOT / name).read_bytes()).hexdigest()
