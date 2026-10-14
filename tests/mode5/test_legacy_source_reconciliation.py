"""Archived guards admit only explicitly reviewed, committed snapshot bytes."""
from pathlib import Path
import subprocess

import pytest

from tools.mode5_public_source_guard import without_snapshot_reconciliation

ROOT = Path(__file__).resolve().parents[2]
NAME = "src/quantbt/metrics/reporting/snapshots.py"


def test_exact_snapshot_parent_and_current_reconcile_without_metric_changes():
    parent = subprocess.check_output(["git", "show", "a4e68e7:"+NAME], cwd=ROOT)
    assert without_snapshot_reconciliation(parent, NAME) == parent
    assert without_snapshot_reconciliation((ROOT / NAME).read_bytes(), NAME) == parent


def test_arbitrary_snapshot_change_and_other_file_are_not_whitelisted():
    with pytest.raises(AssertionError, match="unreviewed immutable"):
        without_snapshot_reconciliation((ROOT / NAME).read_bytes()+b"\n# unreviewed\n", NAME)
    assert without_snapshot_reconciliation(b"arbitrary", "other.py") == b"arbitrary"


def test_current_new_module_is_verified_through_every_later_amendment():
    from tools.mode5_public_source_guard import prior_names
    assert prior_names([NAME, "src/quantbt/mode5/__init__.py"], "6c0f877") == set()


def test_metrics_guard_preserves_exact_continuous_adapter_amendments():
    import json
    from tests.metrics.source_guard import assert_protected_bytes
    baseline = json.loads((ROOT / "docs/metrics/evidence/met01/baseline.json").read_bytes())
    for name in ("src/quantbt/endpoint.py", "src/quantbt/walkforward.py"):
        source = (ROOT / name).read_bytes()
        assert_protected_bytes(name, baseline["protected_sources"][name], source)
        with pytest.raises(AssertionError, match="unreviewed"):
            assert_protected_bytes(name, baseline["protected_sources"][name], source+b"\n# unreviewed\n")


def test_only_exact_reviewed_continuous_consumer_is_admitted():
    from tools.mode5_public_source_guard import without_continuous
    name = "src/quantbt/mode5/continuous.py"
    source = (ROOT / name).read_bytes()
    assert without_continuous(source, name) == b""
    with pytest.raises(AssertionError, match="unreviewed"):
        without_continuous(source+b"\n# unreviewed\n", name)
