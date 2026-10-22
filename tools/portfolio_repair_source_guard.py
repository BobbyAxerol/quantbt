"""Historical reconciliation and separate current portfolio source qualification."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/portfolio_review/evidence/repair-source-amendment.json"
MANIFEST_SHA256 = "490806eab1e5118675dab4b5013df19ea0b3a3bde633632d9e0d3c4a99253edb"
QUALIFICATION = ROOT / "docs/portfolio_review/evidence/current-source-qualification.json"
QUALIFICATION_SHA256 = "e3e557086c940971f8cd3573fcf812fce24fe862564367d417abac9887050e6c"


def without_portfolio_repair(source, name, *, expected_baseline=None):
    from tools.m5_12_source_guard import without_extraction
    from tools.public_inventory_source_amendment import without_inventory_refresh
    from tools.m5_12_pct_source_amendment import without_pct_activity
    from tools.m5_12_pct_alias_amendment import without_pct_alias
    from tools.m5_12_snapshot_amendment import without_snapshot
    from tools.m5_12_release120_amendment import without_release120
    from tools.m5_12_ci_format_amendment import without_ci_format
    from tools.m5_12_ci_rust_amendment import without_ci_rust
    import sys
    source = without_ci_rust(source, name, sys.modules[__name__])
    source = without_ci_format(source, name, sys.modules[__name__])
    source = without_release120(source, name, sys.modules[__name__])
    source = without_snapshot(source, name, sys.modules[__name__])
    source = without_pct_alias(source, name, sys.modules[__name__])
    source = without_pct_activity(source, name, sys.modules[__name__])
    source = without_extraction(source, name, sys.modules[__name__])
    source = without_inventory_refresh(source, name, sys.modules[__name__])
    raw = MANIFEST.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "portfolio repair manifest digest"
    manifest = json.loads(raw)
    from tools.account_metrics_source_guard import without_acc01
    import sys
    source = without_acc01(source, name, sys.modules[__name__])
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


def _git(*args, input=None):
    return subprocess.check_output(["git", *args], cwd=ROOT, input=input)


def _qualification_manifest():
    raw = QUALIFICATION.read_bytes()
    assert sha256(raw).hexdigest() == QUALIFICATION_SHA256, "current qualification manifest digest"
    manifest = json.loads(raw)
    assert manifest["schema"] == "quantbt.portfolio.current_source_qualification.v1"
    for key in ("baseline_commit", "source_commit"):
        commit = manifest[key]
        assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    return manifest


def _committed_source_hashes(commit, scopes):
    entries = {}
    for record in _git("ls-tree", "-r", "-z", commit, "--", *scopes).split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        assert kind == b"blob" and mode in (b"100644", b"100755"), "non-file qualified source"
        entries[path.decode()] = oid
    assert entries, "empty qualified source tree"
    # Batch committed blobs, then hash raw bytes without Git filters or normalization.
    output = _git("cat-file", "--batch", input=b"".join(oid + b"\n" for oid in entries.values()))
    cursor = 0
    result = {}
    for name, oid in entries.items():
        end = output.index(b"\n", cursor)
        actual, kind, size = output[cursor:end].split()
        assert actual == oid and kind == b"blob", "qualified committed blob differs"
        start = end + 1
        cursor = start + int(size)
        result[name] = sha256(output[start:cursor]).hexdigest()
        assert output[cursor:cursor + 1] == b"\n", "qualified blob boundary"
        cursor += 1
    assert cursor == len(output), "unexpected qualified blob data"
    return result


def _assert_current_sources(expected, scopes):
    names = {name.decode() for name in _git(
        "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *scopes
    ).split(b"\0") if name}
    assert names == set(expected), f"unreviewed/missing current source paths: {sorted(names ^ set(expected))}"
    for name, digest in expected.items():
        path = ROOT / name
        assert not path.is_symlink() and path.is_file(), f"missing/non-file current source: {name}"
        assert sha256(path.read_bytes()).hexdigest() == digest, f"unreviewed current source bytes: {name}"


def _verify_repair_delta(repair, before, after, qualification):
    for name, entry in repair["sources"].items():
        assert entry["before_commit"] == qualification["baseline_commit"], "repair baseline differs"
        assert entry["after_commit"] == qualification["source_commit"], "repair source commit differs"
        assert before.get(name) == entry["before_sha256"], f"repair baseline bytes differ: {name}"
        assert name in after and after[name] == entry["after_sha256"], f"repair approved bytes differ: {name}"
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    reviewed = {name for name, entry in repair["sources"].items()
                if entry["before_sha256"] != entry["after_sha256"]}
    assert changed == reviewed, f"unreviewed/missing committed repair changes: {sorted(changed ^ reviewed)}"
    assert changed, "qualification requires the financial repair, not the historical source"
    return sorted(changed)


def _historical_receipts(qualification):
    receipts = {}
    for key, entry in qualification["historical_receipts"].items():
        name = entry["path"]
        archived = _blob(qualification["baseline_commit"], name, entry["sha256"])
        assert (ROOT / name).read_bytes() == archived, f"historical receipt changed: {name}"
        receipts[key] = dict(path=name, sha256=entry["sha256"], claim_scope="historical_only",
                             source=json.loads(archived)[entry["source_key"]])
    return receipts


def verify_current_source():
    """Qualify exact approved bytes, without reissuing old financial-unchanged claims.

    This is a source-only gate. Historical guards/receipts are not rerun or
    rewritten, and no native artifact, runtime test or economic result is certified.
    """
    qualification = _qualification_manifest()
    raw = MANIFEST.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "portfolio repair manifest digest"
    repair = json.loads(raw)
    scopes = qualification["scopes"]
    before = _committed_source_hashes(qualification["baseline_commit"], scopes)
    after = _committed_source_hashes(qualification["source_commit"], scopes)
    changed = _verify_repair_delta(repair, before, after, qualification)
    from tools.account_metrics_source_guard import verify_amendment, MANIFEST_SHA256 as acc01_digest
    import sys
    amendment, current, acc01_changed = verify_amendment(sys.modules[__name__], qualification, after)
    from tools.public_inventory_source_amendment import current_inventory_amendment
    current, metadata_amendments = current_inventory_amendment(current, ROOT)
    from tools.m5_12_source_guard import apply_extraction, MANIFEST_SHA256 as extraction_digest
    extraction, current, extracted_sources = apply_extraction(sys.modules[__name__], current, scopes)
    from tools.m5_12_pct_source_amendment import apply_pct_activity, MANIFEST_SHA256 as pct_digest
    pct, current, pct_changed = apply_pct_activity(sys.modules[__name__], current, scopes)
    from tools.m5_12_pct_alias_amendment import apply_pct_alias, MANIFEST_SHA256 as alias_digest
    alias, current, alias_changed = apply_pct_alias(sys.modules[__name__], current, scopes)
    from tools.m5_12_snapshot_amendment import apply_snapshot, MANIFEST_SHA256 as snapshot_digest
    snapshot, current, snapshot_changed = apply_snapshot(sys.modules[__name__], current, scopes)
    from tools.m5_12_release120_amendment import apply_release120, MANIFEST_SHA256 as release120_digest
    release120, current, release120_changed = apply_release120(sys.modules[__name__], current, scopes)
    from tools.m5_12_ci_format_amendment import apply_ci_format, MANIFEST_SHA256 as ci_format_digest
    ci_format, current, ci_format_changed = apply_ci_format(sys.modules[__name__], current, scopes)
    from tools.m5_12_ci_rust_amendment import apply_ci_rust, MANIFEST_SHA256 as ci_rust_digest
    ci_rust, current, ci_rust_changed = apply_ci_rust(sys.modules[__name__], current, scopes)
    _assert_current_sources(current, scopes)
    all_changed = sorted(name for name in before.keys() | current.keys() if before.get(name) != current.get(name))
    return dict(
        schema="quantbt.portfolio.current_source_qualification.v1",
        baseline_commit=qualification["baseline_commit"], source_commit=ci_rust["source_commit"],
        qualification_sha256=QUALIFICATION_SHA256, repair_amendment_sha256=MANIFEST_SHA256,
        scopes=scopes, current_source_qualified=True, qualified_source_count=len(current),
        acc01_amendment_sha256=acc01_digest, acc01_changed_sources=acc01_changed,
        previous_source_commit=qualification["source_commit"],
        source_metadata_amendments=metadata_amendments,
        acc01_source_commit=amendment["source_commit"], pre_m512_amendment_sha256=extraction_digest,
        pre_m512_extracted_sources=extracted_sources, cold_extraction_semantics_unchanged=True,
        m5_12_pct_amendment_sha256=pct_digest, m5_12_pct_changed_sources=pct_changed,
        m5_12_pct_alias_amendment_sha256=alias_digest, m5_12_pct_alias_changed_sources=alias_changed,
        m5_12_pct_alias_source_commit=alias["source_commit"],
        m5_12_snapshot_amendment_sha256=snapshot_digest, m5_12_snapshot_changed_sources=snapshot_changed,
        m5_12_snapshot_source_commit=snapshot["source_commit"],
        m5_12_release120_amendment_sha256=release120_digest,
        m5_12_release120_changed_sources=release120_changed,
        m5_12_release120_source_commit=release120["source_commit"],
        m5_12_ci_format_amendment_sha256=ci_format_digest,
        m5_12_ci_format_changed_sources=ci_format_changed,
        m5_12_ci_format_source_commit=ci_format["source_commit"],
        m5_12_ci_rust_amendment_sha256=ci_rust_digest,
        m5_12_ci_rust_changed_sources=ci_rust_changed,
        ci_rustfmt_only=False,
        m5_12_pct_source_commit=pct["source_commit"],
        pre_m512_source_commit=extraction["source_commit"],
        financial_source_changed=True, financial_numeric_source_unchanged=False,
        financial_rust_unchanged=not any(name.startswith("rust/") for name in all_changed),
        repair_changed_sources=all_changed, historical_receipts=_historical_receipts(qualification),
        historical_receipts_unchanged=True, historical_guards_reexecuted=False,
        native_artifacts_qualified=False, publication=False,
    )
