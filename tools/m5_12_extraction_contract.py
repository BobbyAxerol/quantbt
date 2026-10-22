"""Independent AST contract for the approved cold backend helper extraction."""

import ast
from copy import deepcopy
from hashlib import sha256


RULES = {
    "src/quantbt/backends/native_portfolio.py": dict(
        helper="src/quantbt/backends/portfolio_reports.py", class_name="NativePortfolioBackend",
        functions=("_build_symbol_pnl_report", "_build_exposure_report", "_build_rebalance_report", "_build_reconciliation_report"),
        import_nodes=("from . import portfolio_reports as _portfolio_reports",),
        alias_nodes=tuple(f"{name} = staticmethod(_portfolio_reports.{name})" for name in
                          ("_build_symbol_pnl_report", "_build_exposure_report", "_build_rebalance_report", "_build_reconciliation_report"))),
    "src/quantbt/backends/native_option.py": dict(
        helper="src/quantbt/backends/option_validation.py", class_name=None,
        functions=("_validate_generic_option_configuration", "_normalize_registry", "_validate_option_requests", "_validate_tape_coverage"),
        import_nodes=("from . import option_validation as _option_validation",
                      "from .option_validation import _normalize_registry as _normalize_registry, "
                      "_validate_generic_option_configuration as _validate_generic_option_configuration, "
                      "_validate_option_requests as _validate_option_requests, _validate_tape_coverage as _validate_tape_coverage"),
        alias_nodes=("_option_validation.OptionSettlementEvent = OptionSettlementEvent",)),
}


def shape(node):
    """Preserve the sealed Python 3.12 AST format on every supported interpreter."""
    def encode(value):
        if isinstance(value, ast.AST):
            fields = list(value._fields)
            # 3.11 lacks this field; 3.13's ast.dump omits empty lists.
            if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and "type_params" not in fields:
                fields.append("type_params")
            parts = []
            for name in fields:
                if name == "type_params" and name not in value._fields:
                    item = getattr(value, name, [])
                else:
                    if not hasattr(value, name):
                        continue
                    item = getattr(value, name)
                if item is None and getattr(type(value), name, ...) is None:
                    continue
                parts.append(name + "=" + encode(item))
            return type(value).__name__ + "(" + ", ".join(parts) + ")"
        if isinstance(value, list):
            return "[" + ", ".join(encode(item) for item in value) + "]"
        return repr(value)

    if not isinstance(node, ast.AST):
        raise TypeError("expected AST")
    return encode(node)


def verify_extraction(before, after, helpers):
    """Reject changed functions, bindings or retained engine code, not just size drift."""
    reports = {}
    for name, rule in RULES.items():
        old, current = ast.parse(before[name]), ast.parse(after[name])
        helper = ast.parse(helpers[rule["helper"]])
        body = old.body if rule["class_name"] is None else next(
            node.body for node in old.body if isinstance(node, ast.ClassDef) and node.name == rule["class_name"])
        original = {node.name:node for node in body if isinstance(node, ast.FunctionDef) and node.name in rule["functions"]}
        moved = {node.name:node for node in helper.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
        assert set(original) == set(moved) == set(rule["functions"]), f"extraction function set differs: {name}"
        hashes = {}
        for key, value in original.items():
            value = deepcopy(value)
            if rule["class_name"]:
                assert [shape(item) for item in value.decorator_list] == [shape(ast.Name(id="staticmethod", ctx=ast.Load()))]
                value.decorator_list = []
            assert shape(value) == shape(moved[key]), f"extracted function changed: {name}:{key}"
            hashes[key] = sha256(shape(value).encode()).hexdigest()
        imports = {shape(ast.parse(value).body[0]) for value in rule["import_nodes"]}
        aliases = {shape(ast.parse(value).body[0]) for value in rule["alias_nodes"]}
        observed_imports, observed_aliases = set(), set()
        def stripped(tree, *, old_side):
            result = deepcopy(tree)
            if rule["class_name"]:
                cls = next(node for node in result.body if isinstance(node, ast.ClassDef) and node.name == rule["class_name"])
                kept = []
                for node in cls.body:
                    if old_side and isinstance(node, ast.FunctionDef) and node.name in original:
                        continue
                    if not old_side and shape(node) in aliases:
                        observed_aliases.add(shape(node))
                        continue
                    kept.append(node)
                cls.body = kept
            kept = []
            for node in result.body:
                if old_side and rule["class_name"] is None and isinstance(node, ast.FunctionDef) and node.name in original:
                    continue
                if not old_side and shape(node) in imports:
                    observed_imports.add(shape(node))
                    continue
                if not old_side and rule["class_name"] is None and shape(node) in aliases:
                    observed_aliases.add(shape(node))
                    continue
                kept.append(node)
            result.body = kept
            return shape(result)
        left, right = stripped(old, old_side=True), stripped(current, old_side=False)
        assert observed_imports == imports and observed_aliases == aliases, f"extraction binding differs: {name}"
        assert left == right, f"retained engine/facade code changed: {name}"
        reports[name] = dict(helper=rule["helper"], function_ast_sha256=hashes,
                             retained_module_ast_sha256=sha256(left.encode()).hexdigest(),
                             retained_engine_code_unchanged=True)
    return reports
