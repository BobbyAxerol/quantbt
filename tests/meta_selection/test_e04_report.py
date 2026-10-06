"""Public summaries cannot turn incomplete software or synthetic timings into edge."""

from copy import deepcopy

import pytest

from tools.qms_e04_report import executed_tests, validate_profile


def test_e04_report_rejects_empty_or_failed_xml(tmp_path):
    path = tmp_path / "tests.xml"
    path.write_text('<testsuites><testsuite/></testsuites>')
    with pytest.raises(ValueError, match="missing"):
        executed_tests([path])
    path.write_text('<testsuites><testsuite><testcase name="x"><failure/></testcase></testsuite></testsuites>')
    with pytest.raises(ValueError, match="failures"):
        executed_tests([path])


def test_e04_report_keeps_empirical_group_not_run_and_unique_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.qms_e04_report.ROOT", tmp_path)
    path = tmp_path / "tests.xml"
    cases = ''.join(f'<testcase classname="E04" name="test_e04_t{i:02d}_case"/>'
                    for i in (1, 2, 3, 4, 6))
    path.write_text(f'<testsuites><testsuite>{cases}</testsuite></testsuites>')
    assert executed_tests([path])["distinct_tests"] == 5
    assert executed_tests([path])["empirical_t05"] == "NOT_RUN"
    with pytest.raises(ValueError, match="duplicate"):
        executed_tests([path, path])


@pytest.mark.parametrize("mutation", ["promotion", "missing", "pool", "account", "observer"])
def test_e04_report_rejects_false_profile_claims(mutation):
    row = dict(warm_median_seconds=1., observer_failures=0,
               identity=dict(account="a", params="p", trials="t", pool="c"))
    value = dict(schema="qms-e04-public-portfolio-profile-v1", real_alpha=False,
        economic_claim=False, publication=False, exact_parity=True,
        rows={name:deepcopy(row) for name in ("off", "reference", "prepared")})
    validate_profile(value)
    if mutation == "promotion": value["real_alpha"] = True
    if mutation == "missing": value["rows"].pop("reference")
    if mutation == "pool": value["rows"]["prepared"]["identity"]["pool"] = "changed"
    if mutation == "account": value["rows"]["off"]["identity"]["account"] = "changed"
    if mutation == "observer": value["rows"]["prepared"]["observer_failures"] = 1
    with pytest.raises(ValueError): validate_profile(value)
