"""Exact current-source extraction guard, distinct from old QMS certificates."""

import argparse
from hashlib import sha256
import json
import subprocess

from tools.m5_12_extraction_contract import RULES, verify_extraction


MANIFEST_NAME = "docs/maintenance/evidence/pre-m512-source-amendment.json"
MANIFEST_SHA256 = "f1d4115f7000b4c7d266157a13cb80f9cc4c26e5fca5ad474267888990ce1b24"


def manifest(guard):
    raw = (guard.ROOT/MANIFEST_NAME).read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "pre-M512 extraction manifest digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.pre_m512.source_extraction.v1"
    from tools.account_metrics_source_guard import MANIFEST_SHA256 as acc01_digest
    assert value["acc01_amendment_sha256"] == acc01_digest, "extraction ACC-01 baseline differs"
    assert value["source_only"] and not value["native_artifacts_qualified"] and not value["publication"]
    assert not value["historical_financial_invariance_claim_reissued"] and not value["version_bump"]
    assert set(value["sources"]) == set(RULES)|{rule["helper"] for rule in RULES.values()}
    return value


def without_extraction(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None or sha256(source).hexdigest() != entry["after_sha256"]:
        return source
    assert source == guard._blob(entry["after_commit"],name,entry["after_sha256"])
    return guard._blob(entry["before_commit"],name,entry["before_sha256"]) if entry["before_sha256"] else b""


def historical_names(names, entry, guard):
    """Only exact new helper modules disappear from historical source inventories."""
    result = set(names)
    value = manifest(guard)
    for name, change in value["sources"].items():
        if name not in result or change["before_sha256"] is not None:
            continue
        assert without_extraction((guard.ROOT/name).read_bytes(),name,guard) == b"", "unreviewed extracted helper"
        old = subprocess.run(["git", "cat-file", "-e", entry+":"+name], cwd=guard.ROOT, capture_output=True)
        assert old.returncode != 0, "extracted helper unexpectedly existed at historical entry"
        result.remove(name)
    return result


def apply_extraction(guard, expected, scopes):
    value = manifest(guard)
    assert scopes == value["scopes"], "extraction source scopes differ"
    before = guard._committed_source_hashes(value["baseline_commit"],scopes)
    assert before == expected, "extraction does not follow exact approved current baseline"
    after = guard._committed_source_hashes(value["source_commit"],scopes)
    changed = guard._verify_repair_delta(value,before,after,value)
    assert not any(name.startswith("rust/") for name in changed), "extraction cannot admit native changes"
    def blob(name, side):
        item = value["sources"][name]
        return guard._blob(item[side+"_commit"],name,item[side+"_sha256"])
    report = verify_extraction({name:blob(name,"before") for name in RULES},
                               {name:blob(name,"after") for name in RULES},
                               {rule["helper"]:blob(rule["helper"],"after") for rule in RULES.values()})
    assert report == value["extraction_ast"], "extraction structural proof differs"
    return value,after,changed


def verify_current_source():
    from tools import portfolio_repair_source_guard as guard
    result = guard.verify_current_source()
    assert result["pre_m512_amendment_sha256"] == MANIFEST_SHA256
    assert result["historical_receipts_unchanged"] and not result["native_artifacts_qualified"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(verify_current_source(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
