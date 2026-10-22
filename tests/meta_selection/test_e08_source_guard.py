"""Approved telemetry is not permission to ignore later financial byte changes."""

import pytest

from tools import qms_e08_source_guard as guard
from tools.qms_pre05_source_guard import without_pre05, prior_names


@pytest.mark.parametrize("name", sorted(guard.ALLOW | {guard.RUNTIME}))
def test_e08_exact_amendment_and_extra_mutation(name):
    # Exercise the exact historical amendment, not today's repaired accounting.
    source = guard.baseline(name, "d0cd95a")
    expected = guard.baseline(name, guard.E07_ENTRY if name == guard.RUNTIME else guard.ENTRY)
    assert guard.without_e07_e08(source, name) == expected
    assert without_pre05(source, name) == expected
    with pytest.raises(AssertionError, match="unreviewed"):
        without_pre05(source+b"\n# unapproved accounting change\n", name)


def test_e08_whole_source_guard_and_historical_scope():
    from current_source_assertions import current_source_rejects_historical_certificate
    current_source_rejects_historical_certificate(guard.verify)
    with pytest.raises(AssertionError, match="unreviewed"):
        prior_names(guard.ALLOW | {guard.RUNTIME}, "d0cd95a")


def test_e08_normalizer_never_exempts_other_files():
    assert guard.without_e07_e08(b"unreviewed", "src/quantbt/core/accounting.py") == b"unreviewed"
