"""Conformance against actual public dispatch, not just a hand-maintained table."""

import ast
import inspect
import textwrap

from quantbt import QuantBTEndpoint, walkforward_support_matrix
from quantbt.optimization.meta_selection.domains import check_route_inventory


def dispatch_routes(source):
    routes = set()
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "target_mode":
            for value in node.comparators:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    routes.add(value.value)
                elif isinstance(value, (ast.Set, ast.Tuple, ast.List)):
                    routes.update(v.value for v in value.elts if isinstance(v, ast.Constant) and isinstance(v.value, str))
    # Existing alias does not bypass the public meta target-mode preflight.
    return sorted("pct_equity" if r == "%_equity" else r for r in routes)


def verify(source=None):
    rows = walkforward_support_matrix(False)
    matrix = {row["target_mode"] for row in rows}
    dispatched = set(dispatch_routes(source or inspect.getsource(QuantBTEndpoint._run_walk_forward)))
    check_route_inventory(sorted(matrix | dispatched))
    if dispatched - matrix:
        raise ValueError("public WFO dispatch missing from discovery: " + str(sorted(dispatched-matrix)))
    return dict(schema="qms-e02-public-route-inventory-v1", public_targets=sorted(matrix),
                typed_dispatch_targets=sorted(dispatched), pending_routes_not_activated=True)
