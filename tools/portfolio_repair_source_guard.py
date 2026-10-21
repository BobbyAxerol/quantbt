"""Exact source reconciliation for the owner-approved portfolio repair."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/portfolio_review/evidence/repair-source-amendment.json"
MANIFEST_SHA256 = "e3ebad658e66b2b30e4ab1ba8110ca86130d50f32b7fa76a464c1ed7660b2f47"


def without_portfolio_repair(source, name, *, expected_baseline=None):
    raw = MANIFEST.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "portfolio repair manifest digest"
    manifest = json.loads(raw)
    entry = manifest["sources"].get(name)
    if entry is None:
        return source
    before = (_blob(entry["before_commit"], name, entry["before_sha256"])
              if entry["before_sha256"] is not None else b"")
    after = _blob(entry["after_commit"], name, entry["after_sha256"])
    if source == after:
        source = before
    previous = entry.get("historical_reconciliation")
    if previous is not None and source == before and previous["sha256"] == expected_baseline:
        source = _blob(previous["commit"], name, previous["sha256"])
    return source


def _blob(commit, name, digest):
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    value = subprocess.check_output(["git", "show", commit + ":" + name], cwd=ROOT)
    assert sha256(value).hexdigest() == digest, "portfolio repair committed source bytes"
    return value
