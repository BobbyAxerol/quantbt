"""Fail-closed final receipts and exact financial buffer identities."""

from dataclasses import replace

import numpy as np
import pytest

from examples.wfo_reactive_samplers import configuration, execute
from tools.qms_c03_evidence import decision_digest
from tools.qms_c03_gate import checks, qualify


@pytest.mark.parametrize("body", ["", '<testcase name="x"><failure/></testcase>',
    '<testcase name="x"><skipped/></testcase>', '<testcase name="x"/>'])
def test_c03_t08_nonpassing_or_incomplete_junit_is_not_certification(tmp_path, body):
    junit = tmp_path / "tests.xml"
    junit.write_text(f"<testsuite>{body}</testsuite>")
    with pytest.raises(ValueError, match="passing actual|missing required"):
        qualify(junit=junit, package=None, cost=None, check_proof=None)


def test_c03_t08_cannot_overwrite_archived_checks(tmp_path):
    with pytest.raises(ValueError, match="fresh C03"):
        checks(tmp_path)


def test_c03_t08_account_digest_retains_numeric_bytes():
    result = execute(config=configuration(trials=4))
    original = decision_digest(result)
    assert decision_digest(result) == original
    fold = result.fold_results[0]
    changed = fold.result.fees.copy()
    changed.iloc[-1] = np.nextafter(float(changed.iloc[-1]), np.inf)
    result.fold_results = (replace(fold, result=replace(fold.result, fees=changed)), *result.fold_results[1:])
    assert decision_digest(result) != original
