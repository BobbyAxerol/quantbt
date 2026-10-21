"""Exact repair admission never authorizes unknown or mutated source bytes."""

from hashlib import sha256
import json
import subprocess

import pytest

from tools.portfolio_repair_source_guard import MANIFEST, MANIFEST_SHA256, ROOT, without_portfolio_repair


MANIFEST_DATA = json.loads(MANIFEST.read_text())


def blob(commit, name):
    return subprocess.check_output(["git", "show", commit + ":" + name], cwd=ROOT)


def test_repair_manifest_is_hash_bound_and_retains_original_receipts():
    assert sha256(MANIFEST.read_bytes()).hexdigest() == MANIFEST_SHA256
    assert MANIFEST_DATA["schema"] == "quantbt.portfolio.repair_source_amendment.v1"
    assert "cross-endpoint" in MANIFEST_DATA["authorization"]


@pytest.mark.parametrize("name", sorted(MANIFEST_DATA["sources"]))
def test_only_exact_committed_repair_bytes_map_to_review_baseline(name):
    entry = MANIFEST_DATA["sources"][name]
    current = blob(entry["after_commit"], name)
    before = blob(entry["before_commit"], name) if entry["before_sha256"] is not None else b""
    assert without_portfolio_repair(current, name) == before
    assert without_portfolio_repair(current + b"\n# unrelated mutation\n", name) != before
    assert without_portfolio_repair(b"unregistered replacement", name) == b"unregistered replacement"


@pytest.mark.parametrize("name", [
    name for name, entry in MANIFEST_DATA["sources"].items() if "historical_reconciliation" in entry
])
def test_historical_reconciliation_requires_the_exact_matching_old_digest(name):
    entry = MANIFEST_DATA["sources"][name]
    current = blob(entry["after_commit"], name)
    old = entry["historical_reconciliation"]
    assert without_portfolio_repair(current, name, expected_baseline=old["sha256"]) == blob(old["commit"], name)
    before = blob(entry["before_commit"], name)
    assert without_portfolio_repair(current, name, expected_baseline="0" * 64) == before
