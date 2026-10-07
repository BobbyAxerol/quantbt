"""New exact source amendment must not weaken historical seals."""

import pytest

from tools import qms_pre04_source_guard as guard


def test_pre04_scope_source_and_no_financial_or_scientific_change():
    result = guard.verify()
    assert len(result["changed_runtime"]) == 13
    assert result["accounting_or_ridge_changed"] is False
    assert result["publication"] is False


@pytest.mark.parametrize("name", sorted(guard.ALLOW))
def test_unreviewed_bytes_never_become_whole_file_exemptions(name):
    source = (guard.ROOT/name).read_bytes()
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
    result = verify()
    assert len(result["additive_module_sha256"]) == 4
