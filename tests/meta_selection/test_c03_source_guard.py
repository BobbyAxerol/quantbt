"""Later adapters do not invalidate or weaken sealed scientific receipts."""

import pytest

from tools.qms_c03_source_guard import ROOT, ALLOW, validate_changes, without_c03_sampler, verify


def test_c03_t08_exact_scope():
    proof = verify()
    assert set(proof["allowed_changes"]) == ALLOW
    assert proof["financial_rust_unchanged"] and proof["shared_sampler_math_unchanged"]


@pytest.mark.parametrize("name", sorted(ALLOW))
def test_c03_t08_reviewed_adapter_cannot_hide_other_edits(name):
    source = (ROOT / name).read_bytes()
    without_c03_sampler(source, name)
    with pytest.raises(AssertionError, match="unapproved C03"):
        without_c03_sampler(source + b"\n# unreviewed calculation\n", name)


@pytest.mark.parametrize("name", ["src/quantbt/walkforward.py", "src/quantbt/optimization/samplers.py",
    "src/quantbt/optimization/meta_selection/ridge.py", "rust/native_event/src/reactive_numeric.rs"])
def test_c03_t08_scope_expansion_rejected(name):
    with pytest.raises(AssertionError, match="unapproved C03"):
        validate_changes([name])
