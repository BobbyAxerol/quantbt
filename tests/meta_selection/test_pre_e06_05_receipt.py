import copy
import pytest

from tools.qms_pre05_qualification import (
    cost_disposition,
    passed_cases,
    REGISTERED_NA,
    NA_REASON,
)


def cost_fixture():
    return dict(
        point_budgets=dict(p50_pct=3, p95_pct=5),
        rows=[
            dict(
                cell=str(i),
                mode="off" if i < 32 else "active",
                exact_semantic_parity=True,
                p50_change_pct=0,
                p95_change_pct=0,
                disabled_point_budget="PASS" if i < 32 else "NOT_APPLICABLE",
            )
            for i in range(76)
        ],
    )


def test_cost_point_miss_cannot_be_reported_accepted():
    value = cost_fixture()
    assert cost_disposition(value)["accepted_cost_disposition"]
    value["rows"][0].update(p95_change_pct=5.01, disabled_point_budget="NOT_MET")
    result = cost_disposition(value)
    assert not result["accepted_cost_disposition"]
    assert result["disabled_not_met"] == ["0"]
    value["rows"][0]["disabled_point_budget"] = "PASS"
    with pytest.raises(ValueError, match="misclassified"):
        cost_disposition(value)


@pytest.mark.parametrize("mutation", ("budget", "missing", "parity"))
def test_incomplete_or_changed_gate_rejected(mutation):
    value = copy.deepcopy(cost_fixture())
    if mutation == "budget":
        value["point_budgets"]["p95_pct"] = 6
    elif mutation == "missing":
        value["rows"].pop()
    else:
        value["rows"][2]["exact_semantic_parity"] = False
    with pytest.raises(ValueError):
        cost_disposition(value)


@pytest.mark.parametrize("child", ("failure", "error", "skipped"))
def test_nonpassing_junit_cannot_be_certified(tmp_path, child):
    path = tmp_path / "invalid.xml"
    path.write_text(
        f'<testsuite><testcase classname="x" name="y"><{child}/></testcase></testsuite>'
    )
    with pytest.raises(ValueError, match="without skips"):
        passed_cases(path)


@pytest.mark.parametrize("reason", (NA_REASON, "missing native capability"))
def test_registered_na_is_not_a_passing_software_case(tmp_path, reason):
    from xml.etree.ElementTree import Element, SubElement, ElementTree

    cls, name = sorted(REGISTERED_NA)[0]
    root = Element("testsuite")
    case = SubElement(root, "testcase", classname=cls, name=name)
    SubElement(case, "skipped", message=reason)
    SubElement(root, "testcase", classname="software", name="applicable")
    path = tmp_path / "na.xml"
    ElementTree(root).write(path)
    if reason != NA_REASON:
        with pytest.raises(ValueError, match="without skips"):
            passed_cases(path, admitted_na=REGISTERED_NA)
    else:
        assert set(passed_cases(path, admitted_na=REGISTERED_NA)) == {
            ("software", "applicable")
        }


def test_duplicate_na_identity_rejected(tmp_path):
    from xml.etree.ElementTree import Element, SubElement, ElementTree

    cls, name = sorted(REGISTERED_NA)[0]
    root = Element("testsuite")
    for _ in range(2):
        case = SubElement(root, "testcase", classname=cls, name=name)
        SubElement(case, "skipped", message=NA_REASON)
    path = tmp_path / "duplicates.xml"
    ElementTree(root).write(path)
    with pytest.raises(ValueError, match="duplicate"):
        passed_cases(path, admitted_na=REGISTERED_NA)


@pytest.mark.parametrize("child", ("failure", "error"))
def test_repaired_failure_not_counted_as_pass_in_old_shard(tmp_path, child):
    path = tmp_path / "failed.xml"
    path.write_text(
        f'<testsuite><testcase classname="x" name="y"><{child}/></testcase>'
        '<testcase classname="x" name="z"/></testsuite>'
    )
    assert set(passed_cases(path, repaired_by={("x", "y")})) == {("x", "z")}


@pytest.mark.parametrize("child", ("failure", "error"))
def test_failure_without_exact_passing_rerun_rejected(tmp_path, child):
    path = tmp_path / "failed.xml"
    path.write_text(
        f'<testsuite><testcase classname="x" name="y"><{child}/></testcase></testsuite>'
    )
    with pytest.raises(ValueError, match="without skips"):
        passed_cases(path, repaired_by={("different", "test")})


def test_unexpected_skip_never_repaired_as_failure(tmp_path):
    path = tmp_path / "skip.xml"
    path.write_text(
        '<testsuite><testcase classname="x" name="y"><skipped/></testcase></testsuite>'
    )
    with pytest.raises(ValueError, match="without skips"):
        passed_cases(path, repaired_by={("x", "y")})
