"""Exact ACC-01 source amendment layered over the retained portfolio repair."""

from hashlib import sha256
import json


MANIFEST_NAME = "docs/portfolio_review/evidence/acc01-final-source-amendment.json"
MANIFEST_SHA256 = "95af947a570cc5c10bc6655c922b7dd8497f02e6da422aa3479af0163a94e0f1"
FIRST_NAME = "docs/portfolio_review/evidence/acc01-source-amendment.json"
FIRST_SHA256 = "7a94b343bc516ec89b7e230681b5af491c9e507ce81ccdce6aaced70bd3a1187"


def first_manifest(guard):
    raw = (guard.ROOT / FIRST_NAME).read_bytes()
    assert sha256(raw).hexdigest() == FIRST_SHA256, "ACC-01 first amendment digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.acc01.source_amendment.v1"
    return value


def manifest(guard):
    raw = (guard.ROOT / MANIFEST_NAME).read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "ACC-01 amendment digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.acc01.source_amendment.v2"
    first = first_manifest(guard)
    assert value["first_acc01_manifest_sha256"] == FIRST_SHA256
    assert value["first_acc01_source_commit"] == first["source_commit"]
    assert value["prior_amendment_sha256"] == guard.MANIFEST_SHA256, "ACC-01 prior repair differs"
    assert value["prior_qualification_sha256"] == guard.QUALIFICATION_SHA256, "ACC-01 prior qualification differs"
    assert value["historical_receipts_unchanged"] and not value["version_bump"]
    return value


def without_acc01(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None:
        return source
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    if source != after:
        previous = first_manifest(guard)["sources"].get(name)
        if previous is None or source != guard._blob(previous["after_commit"], name, previous["after_sha256"]):
            return source
    if entry["before_sha256"] is None:
        return b""
    return guard._blob(entry["before_commit"], name, entry["before_sha256"])


def verify_amendment(guard, previous, expected):
    value = manifest(guard)
    assert value["baseline_commit"] == previous["source_commit"], "ACC-01 baseline differs"
    assert value["scopes"] == previous["scopes"], "ACC-01 qualification scopes differ"
    after = guard._committed_source_hashes(value["source_commit"], value["scopes"])
    changed = guard._verify_repair_delta(value, expected, after, value)
    return value, after, changed
