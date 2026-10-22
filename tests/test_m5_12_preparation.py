"""Static preparation checks; no financial execution, installation or build."""

import ast
from hashlib import sha256
from pathlib import Path
import subprocess
import zipfile

import pytest

from tools import check_endpoint_compatibility as api
from tools import portfolio_repair_source_guard as guard
from tools import public_inventory_source_amendment as amendment
from tools.check_release_artifacts import inspect_artifact
from tools.generate_public_api_inventory import generated_outputs


ROOT = Path(__file__).resolve().parents[1]


def args(source):
    return ast.parse("def method(" + source + "): pass").body[0].args


@pytest.mark.parametrize("old,new", [
    ("self, x=1", "self, x=1, *, reporting=None"),
    ("cls, strategy, **kwargs", "cls, strategy, execution_endpoint=None, **kwargs"),
])
def test_additive_optional_signatures(old, new):
    assert api.breaking_changes(args(old), args(new)) == []


@pytest.mark.parametrize("new", ["self", "self, x=2", "self, y, x=1", "self, *, x=1", "self, x=1, *, required"])
def test_signature_breaks_are_detected(new):
    assert api.breaking_changes(args("self, x=1"), args(new))


@pytest.mark.parametrize("before,after", [
    ("@classmethod\ndef method(cls): pass", "def method(cls): pass"),
    ("@staticmethod\ndef method(): pass", "def method(): pass"),
    ("def method(self): pass", "async def method(self): pass"),
])
def test_method_binding_and_async_breaks_are_detected(before, after):
    assert api.method_breaking_changes(ast.parse(before).body[0], ast.parse(after).body[0])


@pytest.mark.parametrize("baseline", ["v1.1.1", "8f7df9d"])
def test_endpoint_baselines_are_additive(baseline):
    result = api.audit(baseline)
    assert not result["breaking_signature_change"]
    assert not result["removed_exports"]
    assert result["public_method_count"] == 48
    if baseline == "8f7df9d":
        assert not result["added_methods"] and not result["changed_signatures"]


def test_inventory_is_generated_and_refresh_is_metadata_only():
    for path, value in generated_outputs().items():
        assert path.read_text() == value
    result = guard.verify_current_source()
    assert result["current_source_qualified"] and not result["native_artifacts_qualified"]
    assert result["source_metadata_amendments"] == [dict(
        path=amendment.NAME, before_sha256=amendment.BEFORE_SHA256,
        after_sha256=amendment.AFTER_SHA256, financial_source_changed=False)]


def test_inventory_normalization_rejects_unknown_source():
    raw = (ROOT / amendment.NAME).read_bytes()
    original = amendment.without_inventory_refresh(raw, amendment.NAME, guard)
    assert sha256(original).hexdigest() == amendment.BEFORE_SHA256
    for name, value in [(amendment.NAME, raw+b"\n"), ("src/quantbt/__init__.py", raw)]:
        assert amendment.without_inventory_refresh(value, name, guard) == value


def test_legacy_diagnostic_export_reconciliation_is_exact():
    raw = (ROOT / amendment.EXPORT_NAME).read_bytes()
    before = amendment.without_diagnostic_root_exports(raw, amendment.EXPORT_NAME, guard)
    assert sha256(before).hexdigest() == amendment.EXPORT_PARENT_SHA256
    assert amendment.without_diagnostic_root_exports(raw+b"\n", amendment.EXPORT_NAME, guard) == raw+b"\n"
    assert amendment.without_diagnostic_root_exports(raw, "unrelated.py", guard) == raw


def test_inventory_current_admission_rejects_other_bytes(tmp_path):
    path = tmp_path / amendment.NAME
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / amendment.NAME).read_bytes()+b"\n")
    with pytest.raises(AssertionError, match="unreviewed API inventory"):
        amendment.current_inventory_amendment({amendment.NAME: amendment.BEFORE_SHA256}, tmp_path)
    with pytest.raises(AssertionError, match="baseline differs"):
        amendment.current_inventory_amendment({amendment.NAME: "0"*64}, tmp_path)


def test_stale_inventory_is_not_current_source_qualification(tmp_path):
    path = tmp_path / amendment.NAME
    path.parent.mkdir(parents=True)
    path.write_bytes(guard._blob(amendment.BASELINE_COMMIT, amendment.NAME, amendment.BEFORE_SHA256))
    with pytest.raises(AssertionError, match="unreviewed API inventory"):
        amendment.current_inventory_amendment({amendment.NAME: amendment.BEFORE_SHA256}, tmp_path)


@pytest.mark.parametrize("name", ["upgrade/alphas/local.py", "upgrade/private/x.json", "upgrade/local/run.py",
                                   "upgrade/MODE5_INVARIANT_AND_ALPHA_PROFILING_SPEC_V1.md"])
def test_private_inputs_remain_ignored_and_untracked(name):
    assert subprocess.run(["git", "check-ignore", "-q", "--no-index", name], cwd=ROOT).returncode == 0
    assert subprocess.check_output(["git", "ls-files", "--", name], cwd=ROOT) == b""


@pytest.mark.parametrize("name", ["upgrade/implement.md", "docs/mode5/PUBLIC_CALIBRATION_V1.md", "tests/test_m5_12_preparation.py"])
def test_public_plan_and_tests_are_not_hidden(name):
    assert subprocess.run(["git", "check-ignore", "-q", "--no-index", name], cwd=ROOT).returncode == 1


def test_alias_of_private_source_is_rejected_in_synthetic_artifact(tmp_path):
    payload = b"# synthetic private strategy fixture; no real strategy content\n"
    artifact = tmp_path / "quantbt_engine-1.1.2-py3-none-any.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("quantbt/renamed.py", payload)
        archive.writestr("quantbt_engine-1.1.2.dist-info/METADATA", "Name: quantbt-engine\nVersion: 1.1.2\n")
    findings = inspect_artifact(artifact, private_payload_hashes=frozenset([sha256(payload).hexdigest()]))
    assert any("private" in finding for finding in findings)


def test_sdist_manifest_explicitly_excludes_owner_inputs():
    text = (ROOT / "MANIFEST.in").read_text()
    assert "prune upgrade/alphas\n" in text
    assert "exclude upgrade/MODE5_INVARIANT_AND_ALPHA_PROFILING_SPEC_V1.md\n" in text
