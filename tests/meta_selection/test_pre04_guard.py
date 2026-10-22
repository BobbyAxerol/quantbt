"""New exact source amendment must not weaken historical seals."""

import pytest

from tools import qms_pre04_source_guard as guard


def test_pre04_scope_source_and_no_financial_or_scientific_change():
    from current_source_assertions import current_source_rejects_historical_certificate
    current_source_rejects_historical_certificate(guard.verify)
    assert len(guard.ALLOW) == 13


@pytest.mark.parametrize("name", sorted(guard.ALLOW))
def test_unreviewed_bytes_never_become_whole_file_exemptions(name):
    source = (guard.ROOT/name).read_bytes()
    if name == "src/quantbt/optimization/meta_selection/runtime.py":
        import json
        import subprocess
        from hashlib import sha256
        from tools.qms_e08_source_guard import E07_ENTRY
        # This positive control is the sealed PRE04 module, not later reporting.
        source = subprocess.check_output(["git", "show", f"{E07_ENTRY}:{name}"], cwd=guard.ROOT)
        assert sha256(source).hexdigest() == json.loads(guard.MANIFEST.read_text())["source_sha256"][name]
    assert guard.without_pre04(source, name) == guard.baseline(name)
    with pytest.raises(AssertionError, match="unreviewed"):
        guard.without_pre04(source+b"\n# unreviewed mutation\n", name)


def test_original_pre03_receipt_and_source_manifest_are_immutable():
    import subprocess
    names = ["benchmarks/optimization/meta_selection/qms_pre_e06_03_"+s+".json"
             for s in ("reviewed_source", "closure", "cost")]
    for name in names:
        archived = subprocess.check_output(["git", "show", f"{guard.ENTRY}:{name}"], cwd=guard.ROOT)
        assert (guard.ROOT/name).read_bytes() == archived


def test_existing_c04_original_receipt_normalization():
    from tools.qms_c04_source_guard import verify
    from current_source_assertions import current_source_rejects_historical_certificate
    from tools.qms_c04_source_guard import ALLOW
    current_source_rejects_historical_certificate(verify)
    assert len(ALLOW) == 4
