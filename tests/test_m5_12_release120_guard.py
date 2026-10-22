"""Current release amendment cannot normalize unknown source or native changes."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import m5_12_release120_amendment as amendment
from tools import portfolio_repair_source_guard as guard


def test_current_release120_source_is_separate_from_historical_snapshots():
    value = amendment.manifest(guard)
    result = guard.verify_current_source()
    from tools.m5_12_ci_rust_amendment import SOURCE_COMMIT
    assert result["source_commit"] == SOURCE_COMMIT != amendment.SOURCE_COMMIT
    assert result["m5_12_release120_source_commit"] == value["source_commit"] == amendment.SOURCE_COMMIT
    assert result["m5_12_snapshot_source_commit"] == amendment.BASELINE_COMMIT
    assert result["qualified_source_count"] == 466
    assert set(result["m5_12_release120_changed_sources"]) == amendment.SOURCE_PATHS
    assert result["historical_receipts_unchanged"] and not result["native_artifacts_qualified"]
    assert result["financial_source_changed"] and not result["financial_numeric_source_unchanged"]
    assert not result["publication"]


@pytest.mark.parametrize("name", sorted(amendment.SOURCE_PATHS))
def test_release120_exact_bytes_only_normalize_to_historical_parent(name):
    entry = amendment.manifest(guard)["sources"][name]
    before = guard._blob(amendment.BASELINE_COMMIT,name,entry["before_sha256"])
    after = guard._blob(amendment.SOURCE_COMMIT,name,entry["after_sha256"])
    assert amendment.without_release120(after,name,guard) == before
    assert amendment.without_release120(before,name,guard) == before
    for unknown in (after+b"\n", b"# unknown\n"+after):
        assert amendment.without_release120(unknown,name,guard) == unknown
    assert amendment.without_release120(after,"src/unreviewed.py",guard) == after


def test_release120_manifest_is_immutable_and_unsealed_state_fails_closed(tmp_path,monkeypatch):
    original = guard.ROOT/amendment.MANIFEST_NAME
    changed = tmp_path/"manifest.json"
    changed.write_bytes(original.read_bytes()+b"\n")
    monkeypatch.setattr(amendment,"MANIFEST_NAME",str(changed))
    with pytest.raises(AssertionError,match="manifest digest"):
        amendment.manifest(guard)
    monkeypatch.setattr(amendment,"MANIFEST_SHA256","PENDING")
    with pytest.raises(AssertionError,match="must be sealed"):
        amendment.manifest(guard)


@pytest.mark.parametrize("field", ("core","native","source_only","financial_kernel_changed",
                                 "metric_formulas_changed","native_artifacts_qualified","publication"))
def test_repinned_manifest_cannot_expand_version_or_authority(tmp_path,monkeypatch,field):
    value = deepcopy(amendment.manifest(guard))
    value[field] = "wrong" if field in {"core","native"} else not value[field]
    path = tmp_path/"manifest.json"
    raw = json.dumps(value,sort_keys=True).encode()
    path.write_bytes(raw)
    monkeypatch.setattr(amendment,"MANIFEST_NAME",str(path))
    monkeypatch.setattr(amendment,"MANIFEST_SHA256",sha256(raw).hexdigest())
    with pytest.raises(AssertionError):
        amendment.manifest(guard)


@pytest.mark.parametrize("name", sorted(amendment.REPORT_PATHS))
def test_reporting_optimization_cannot_change_other_functions(name):
    entry = amendment.manifest(guard)["sources"][name]
    before = guard._blob(amendment.BASELINE_COMMIT,name,entry["before_sha256"])
    after = guard._blob(amendment.SOURCE_COMMIT,name,entry["after_sha256"])
    amendment._report_scope(before,after,name)
    with pytest.raises(AssertionError,match="reporting scope drift"):
        amendment._report_scope(before,after+b"\ndef unreviewed():\n    return 0\n",name)


def test_installed_verifier_custody_includes_new_release_guard():
    from tools.m5_12_installed_preflight import verifier_manifest
    from tools.m5_12_pct_installed import source_pins
    name = "tools/m5_12_release120_amendment.py"
    assert verifier_manifest()[name] == source_pins()[name] == sha256((guard.ROOT/name).read_bytes()).hexdigest()
