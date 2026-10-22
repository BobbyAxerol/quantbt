"""Cold extraction structural oracle and mutation controls, without execution."""

from pathlib import Path
import subprocess

import pytest

from tools.m5_12_extraction_contract import RULES, verify_extraction


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "7cdaadbc573435186ea7901162b9499973ec82b5"


def sources():
    before = {name:subprocess.check_output(["git", "show", BASELINE+":"+name], cwd=ROOT) for name in RULES}
    after = {name:(ROOT/name).read_bytes() for name in RULES}
    helpers = {rule["helper"]:(ROOT/rule["helper"]).read_bytes() for rule in RULES.values()}
    return before,after,helpers


def test_extraction_preserves_all_nonmoved_engine_ast_and_moved_function_ast():
    result = verify_extraction(*sources())
    assert set(result) == set(RULES)
    assert all(row["retained_engine_code_unchanged"] for row in result.values())


@pytest.mark.parametrize("name", RULES)
def test_changed_retained_facade_code_fails(name):
    before,after,helpers = sources()
    after[name] += b"\nUNREVIEWED = True\n"
    with pytest.raises(AssertionError, match="retained engine/facade code changed"):
        verify_extraction(before,after,helpers)


@pytest.mark.parametrize("helper", [rule["helper"] for rule in RULES.values()])
def test_changed_moved_function_fails(helper):
    before,after,helpers = sources()
    helpers[helper] = helpers[helper].replace(b"    return ", b"    return None  #", 1)
    with pytest.raises(AssertionError, match="extracted function changed"):
        verify_extraction(before,after,helpers)


def test_private_static_alias_removal_fails():
    before,after,helpers = sources()
    name = "src/quantbt/backends/native_portfolio.py"
    after[name] = after[name].replace(b"    _build_exposure_report = staticmethod(_portfolio_reports._build_exposure_report)\n", b"")
    with pytest.raises(AssertionError, match="extraction binding differs"):
        verify_extraction(before,after,helpers)
