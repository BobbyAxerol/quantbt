"""E01 independent negative evidence checks, with no invented financial run."""

import pytest

from tools.qms_e01_audit import compare
from tools.qms_e01_gate import check_tests, check_package
from tools.qms01_baseline import ROUTES


def identities():
    return dict(guide_sha256="guide", historical_receipts={"receipt": "historical"},
        lanes=[dict(mode=m, schedule=s, identity="account-search", rng="rng", off_exact=True,
                    oos_used_for_selection=False) for m, s in ROUTES])


@pytest.mark.parametrize("change", ["account", "rng", "history", "guide", "matrix"])
def test_e01_t02_before_after_parity_cannot_hide_non_reporting_change(change):
    old, new = identities(), identities()
    if change == "account": new["lanes"][0]["identity"] = "changed"
    elif change == "rng": new["lanes"][0]["rng"] = "changed"
    elif change == "history": new["historical_receipts"]["receipt"] = "changed"
    elif change == "guide": new["guide_sha256"] = "changed"
    elif change == "matrix": new["lanes"].pop()
    with pytest.raises(AssertionError):
        compare(old, new)


def test_e01_t02_only_declared_reporting_difference_is_permitted():
    old, new = identities(), identities()
    new["lanes"][3]["oos_used_for_selection"] = True
    assert compare(old, new)


@pytest.mark.parametrize("bad", ["missing_group", "skip", "failure", "error", "empty"])
def test_e01_t05_gate_requires_all_executed_local_groups(tmp_path, bad):
    cases = [f'<testcase classname="E01" name="test_e01_t{i:02}_fixture"/>' for i in range(1, 6)]
    if bad == "missing_group": cases.pop()
    elif bad == "empty": cases.clear()
    else: cases[0] = cases[0].replace("/>", f"><{'skipped' if bad == 'skip' else bad}/></testcase>")
    path = tmp_path / "junit.xml"
    path.write_text('<testsuites><testsuite>' + "".join(cases) + '</testsuite></testsuites>')
    with pytest.raises(ValueError):
        check_tests([path])


@pytest.mark.parametrize("bad", ["schema", "pair", "lane", "publication", "economic", "artifact"])
def test_e01_t05_gate_rejects_missing_or_mislabelled_actual_package_evidence(bad):
    package = dict(schema="qms-e01-installed-source-pair-v1", core="1.1.2", native="0.4.3",
                   publication=False, economic_claim=False, consumers={"wheel": {}, "sdist": {}}, artifact_refs=[])
    if bad == "schema": package["schema"] = "invented-pass"
    elif bad == "pair": package["native"] = "0.4.2"
    elif bad == "lane": package["consumers"].pop("sdist")
    elif bad == "publication": package["publication"] = True
    elif bad == "economic": package["economic_claim"] = True
    with pytest.raises(ValueError):
        check_package(package)
