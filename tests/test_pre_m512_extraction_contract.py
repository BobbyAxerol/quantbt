"""Cold extraction structural oracle and mutation controls, without execution."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tools.m5_12_extraction_contract import RULES, shape, verify_extraction


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


def test_extraction_hashes_match_original_certificate_on_every_supported_python():
    certificate = json.loads((ROOT / "docs/maintenance/evidence/pre-m512-source-amendment.json").read_bytes())
    assert verify_extraction(*sources()) == certificate["extraction_ast"]


@pytest.mark.parametrize("prefix,node_type", [("", "FunctionDef"), ("async ", "AsyncFunctionDef")])
def test_function_shape_is_fixed_to_sealed_format(prefix, node_type):
    node = ast.parse(prefix + "def f(x):\n    return x\n").body[0]
    expected = (node_type + "(name='f', args=arguments(posonlyargs=[], args=[arg(arg='x')], "
        "kwonlyargs=[], kw_defaults=[], defaults=[]), body=[Return(value=Name(id='x', ctx=Load()))], "
        "decorator_list=[], type_params=[])")
    assert shape(node) == expected
    old = deepcopy(node)
    old._fields = tuple(name for name in old._fields if name != "type_params")
    if hasattr(old, "type_params"):
        del old.type_params
    assert shape(old) == expected
    node.type_params = [ast.Name(id="T", ctx=ast.Load())]
    assert shape(node) != expected


def test_class_shape_retains_empty_lists_and_does_not_change_input():
    node = ast.parse("class C:\n    pass\n").body[0]
    fields = node._fields
    assert shape(node) == "ClassDef(name='C', bases=[], keywords=[], body=[Pass()], decorator_list=[], type_params=[])"
    assert node._fields == fields
    with pytest.raises(TypeError, match="expected AST"):
        shape("class C: pass")
