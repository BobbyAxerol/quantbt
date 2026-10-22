"""Archived guards admit only explicitly reviewed, committed snapshot bytes."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from tools.mode5_public_source_guard import (
    LEGACY_RECONCILIATION,
    without_snapshot_reconciliation,
)

ROOT = Path(__file__).resolve().parents[2]
NAME = "src/quantbt/metrics/reporting/snapshots.py"


@pytest.fixture(scope="module")
def historical_snapshot():
    manifest = json.loads(LEGACY_RECONCILIATION.read_bytes())
    assert manifest["path"] == NAME
    parent = subprocess.check_output(["git", "show", "a4e68e7:"+NAME], cwd=ROOT)
    admitted = subprocess.check_output(
        ["git", "show", manifest["after_commit"]+":"+NAME], cwd=ROOT
    )
    assert sha256(parent).hexdigest() == manifest["before_sha256"]
    assert sha256(admitted).hexdigest() == manifest["after_sha256"]
    assert parent != admitted
    return parent, admitted


def test_exact_historical_snapshot_parent_and_reviewed_blob_reconcile(historical_snapshot):
    parent, admitted = historical_snapshot
    assert without_snapshot_reconciliation(parent, NAME) == parent
    assert without_snapshot_reconciliation(admitted, NAME) == parent


def test_arbitrary_snapshot_change_and_other_file_are_not_whitelisted(historical_snapshot):
    for source in (*historical_snapshot, (ROOT / NAME).read_bytes()):
        with pytest.raises(AssertionError, match="unreviewed immutable"):
            without_snapshot_reconciliation(source+b"\n# unreviewed\n", NAME)
    assert without_snapshot_reconciliation(b"arbitrary", "other.py") == b"arbitrary"


def test_current_source_is_qualified_separately_from_historical_snapshot_guards():
    from tests.meta_selection.current_source_assertions import current_source_rejects_historical_certificate
    from tools.mode5_public_source_guard import prior_names

    # Source-only qualification must not reissue an old unchanged-source claim.
    current_source_rejects_historical_certificate(
        lambda: prior_names([NAME, "src/quantbt/mode5/__init__.py"], "6c0f877")
    )
    with pytest.raises(AssertionError, match="unreviewed immutable"):
        without_snapshot_reconciliation((ROOT / NAME).read_bytes(), NAME)


def test_metrics_guard_preserves_exact_continuous_adapter_amendments():
    from tests.metrics.source_guard import assert_protected_bytes
    baseline = json.loads((ROOT / "docs/metrics/evidence/met01/baseline.json").read_bytes())
    for name in ("src/quantbt/endpoint.py", "src/quantbt/walkforward.py"):
        source = (ROOT / name).read_bytes()
        assert_protected_bytes(name, baseline["protected_sources"][name], source)
        with pytest.raises(AssertionError, match="unreviewed"):
            assert_protected_bytes(name, baseline["protected_sources"][name], source+b"\n# unreviewed\n")


def test_only_exact_reviewed_continuous_consumer_is_admitted():
    from tools.mode5_public_source_guard import without_continuous
    from tools.portfolio_repair_source_guard import without_portfolio_repair

    for name in ("src/quantbt/mode5/continuous.py", "src/quantbt/mode5/continuous_retention.py"):
        source = (ROOT / name).read_bytes()
        normalized = without_portfolio_repair(source, name)
        assert normalized != source
        assert without_continuous(normalized, name) == b""
        for changed in (source, normalized):
            with pytest.raises(AssertionError, match="unreviewed"):
                without_continuous(
                    without_portfolio_repair(changed+b"\n# unreviewed\n", name), name
                )
