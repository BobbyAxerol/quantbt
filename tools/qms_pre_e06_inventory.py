"""Read-only PRE-E06-01 discovery/source/test audit; never runs a strategy."""

import argparse
import ast
import inspect
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import textwrap

from tools.qms_e02_inventory import verify as verify_dispatch
from tools.qms_execution_source_guard import verify as verify_execution_source


ROOT = Path(__file__).resolve().parents[1]
ENTRY = "74879f1"
GUIDE = "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
GUIDE_SHA = "adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d"
MANIFEST = "benchmarks/optimization/meta_selection/qms_pre_e06_01_inventory.json"
DOMAIN = "src/quantbt/optimization/meta_selection/domains/"
TESTS = "tests/meta_selection/"

# These are reviewed owners, not a second capability or financial registry.
OWNERS = {
    "signal_notional": ("scalar", "native_vectorized/native_event/legacy", "test_qms03_engine.py::test_q3_t02_original_engine_labels_reconcile_and_centroid_has_own_is", "test_e03_scalar.py::test_e03_t04_omitted_off_shadow_exact_search_rng_and_continuous_account"),
    "pct_equity": ("scalar", "legacy/Numba", "test_qms06_prepared.py::test_q6_t01_pct_equity_existing_native_account_units_and_cost_parity", "test_qms05_public.py::test_q5_t08_pct_equity_fees_funding_and_boundary_authority"),
    "notional": ("scalar", "native_vectorized/native_event/legacy", "test_e03_scalar.py::test_e03_t02_independent_accepted_delta_pnl_fee_slippage_and_turnover", "test_e03_scalar.py::test_e03_t04_prepared_original_pool_selection_and_final_account_parity"),
    "unit": ("scalar", "native_vectorized/native_event/legacy", "test_g01_metric_compatibility.py::test_g01_liquidation_score_compact_audit_and_prepared_parity", "test_e03_scalar.py::test_e03_t04_prepared_original_pool_selection_and_final_account_parity"),
    "dca_ladder": ("scalar", "legacy/Numba structural high-low", "test_e03_scalar.py::test_e03_t03_ladder_limits_manual_quantity_cost_and_same_close_exit", "test_e03_scalar.py::test_e03_t03_ladder_actual_high_low_required_not_close_proxy"),
    "portfolio": ("portfolio", "native_portfolio NumPy/Numba", "test_e04_portfolio.py::test_e04_t03_every_is_and_forward_observation_uses_original_aggregate_report", "test_e04_portfolio.py::test_e04_t04_final_account_is_original_stitched_position_run_not_fold_equity"),
    "basket": ("package", "native_event frozen best-effort", "test_e05_package.py::test_e05_t03_labels_equal_original_aggregate_reports_and_leg_reconciliation", "test_e05_package.py::test_e05_t01_active_final_is_one_original_stitched_signal_account"),
    "arbitrage": ("package", "native_event bounded linear non-expiring", "test_e05_package.py::test_e05_t03_labels_equal_original_aggregate_reports_and_leg_reconciliation", "test_e05_package.py::test_e05_t02_unqualified_contracts_fail_closed"),
    "intrabar": ("execution", "explicit original intrabar Numba/reference/Rust", "test_execution_window_public.py::test_original_is_and_forward_metrics_not_proxy", "test_execution_domain_accounting.py::test_carried_intrabar_trade_keeps_original_stop_across_new_fold"),
    "event_driven": ("execution", "explicit native_event Python callback/Rust financial owner", "test_execution_window_public.py::test_original_is_and_forward_metrics_not_proxy", "test_execution_window_public.py::test_active_final_rebuild_uses_actual_fold_intent_in_one_account"),
    "order_commands": ("execution", "explicit original orders Python/Rust", "test_execution_window_public.py::test_original_is_and_forward_metrics_not_proxy", "test_execution_domain_accounting.py::test_pending_command_crosses_fold_boundary_without_reset"),
    "delivery_arbitrage": ("execution", "explicit original orders Python/Rust pre-expiry flatten", "test_execution_domain_accounting.py::test_quarterly_roll_flatten_prices_and_each_one_way_fee", "test_execution_domain_accounting.py::test_quarterly_insufficient_close_capacity_cannot_get_a_pass_receipt"),
    "reactive_reset": ("reactive", "prepared native numeric W3; inprocess/safe Linux fork", "test_local_reactive.py::test_w3_shadow_same_native_search_and_account_with_original_observations", "test_local_reactive.py::test_w3_supported_meta_actually_switches_the_applied_native_candidate"),
    "options": (None, None, "test_e02_inventory.py::test_e02_t05_actual_dispatch_and_discovery_have_registered_or_pending_adapters", "test_e02_inventory.py::test_e02_t05_future_dispatch_omitted_from_matrix_cannot_escape_conformance"),
    "nautilus_validation": (None, None, "test_e02_inventory.py::test_e02_t05_actual_dispatch_and_discovery_have_registered_or_pending_adapters", "test_e02_inventory.py::test_e02_t05_future_dispatch_omitted_from_matrix_cannot_escape_conformance"),
}
SOURCES = {
    "scalar": (DOMAIN + "scalar.py", "ScalarDomainAdapter"),
    "portfolio": (DOMAIN + "portfolio.py", "PortfolioDomainAdapter"),
    "package": (DOMAIN + "package.py", "PackageDomainAdapter"),
    "execution": (DOMAIN + "execution.py", "ExecutionDomainAdapter"),
    "reactive": (DOMAIN + "reactive.py", "ReactiveDomainAdapter"),
}
CONTRACT_FILES = (
    "src/quantbt/endpoint.py", "src/quantbt/walkforward.py", "src/quantbt/wfo_execution.py",
    "src/quantbt/metrics/performance.py", "src/quantbt/backends/native_wfo_public.py",
    "src/quantbt/optimization/meta_selection/config.py",
    "src/quantbt/optimization/meta_selection/observer.py",
    "src/quantbt/optimization/meta_selection/records.py",
    "src/quantbt/optimization/meta_selection/prepared.py",
    "src/quantbt/optimization/meta_selection/reactive.py",
    "src/quantbt/optimization/meta_selection/reactive_transport.py",
    "src/quantbt/optimization/meta_selection/domains/registry.py",
    *[DOMAIN + n + "_contract.py" for n in ("scalar", "portfolio", "package")],
    "src/quantbt/core/delivery_lifecycle.py",
)
DOCS = (
    "upgrade/implement.md", "handoff/WFO_META_CURRENT.md", "docs/meta_selection.md",
    *["docs/meta_selection/" + n + ".md" for n in (
        "PRE_E06_BASELINE", "CURRENT_ROUTE_REVIEW", "GAP_CLOSURE_STATUS",
        "DOMAIN_ADAPTER_CONTRACT", "QUALIFICATION", "RELEASE_HANDOFF")],
)
PATCH_ALLOW = frozenset((*DOCS, MANIFEST, "tools/qms_pre_e06_inventory.py",
    "tests/meta_selection/test_pre_e06_01_audit.py", "tests/meta_selection/test_e02_docs.py",
    "tests/meta_selection/test_e03_scalar.py",
    "benchmarks/optimization/meta_selection/qms_pre_e06_01_closure.json"))


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def file_hash(name):
    path = ROOT / name
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise ValueError("inventory file must be a regular repository path")
    return sha256(path.read_bytes()).hexdigest()


def hash_map(mapping):
    return sha256(json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_symbol(reference):
    name, symbol = reference.split("::")
    tree = ast.parse((ROOT / name).read_text())
    if symbol not in {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}:
        raise ValueError(f"missing inventory test/source owner: {reference}")
    return name


def check_public_text(text):
    patterns = (
        r"gh[pousr]_" + r"[A-Za-z0-9]{20,}",
        r"pypi-" + r"[A-Za-z0-9_-]{30,}",
        r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"/root/bobby/pool_alpha/" + r"(?:alphas_storage|pool_alpha|Arbops)/",
    )
    if any(re.search(p, text) for p in patterns):
        raise ValueError("private path or credential in public patch")


def check_patch_safety(names=None):
    if names is None:
        names = set(git("diff", "--name-only", ENTRY)) | set(git(
            "ls-files", "--others", "--exclude-standard"))
    if set(names) - PATCH_ALLOW:
        raise ValueError("non-phase source, artifact or private file in patch")
    for name in names:
        file_hash(name)
        if name in git("ls-files", "--", name):
            additions = "\n".join(line[1:] for line in git("diff", "--no-ext-diff",
                "--unified=0", ENTRY, "--", name) if line.startswith("+") and not line.startswith("+++"))
        else:
            additions = (ROOT / name).read_text()
        check_public_text(additions)
    return True


def protected_inventory():
    names = git("ls-tree", "-r", "--name-only", ENTRY, "--", "src", "rust")
    sealed = [n for n in git("ls-tree", "-r", "--name-only", ENTRY, "--",
        "benchmarks/optimization/meta_selection", "docs/meta_selection")
        if n.endswith(".json") or n.endswith("_REPORT.md") or n.endswith("REAL_DIAGNOSTIC.md")
        or n.endswith("QMSE03_G01_CLOSURE.md")]
    protected = [*names, *sealed, GUIDE]
    changed = git("diff", "--name-only", ENTRY, "--", *protected)
    extra = git("ls-files", "--others", "--exclude-standard", "--", "src", "rust")
    if changed or extra:
        raise ValueError("PRE-E06-01 cannot change runtime/guide/sealed evidence: " + str(changed + extra))
    if file_hash(GUIDE) != GUIDE_SHA:
        raise ValueError("original scientific guide changed")
    verify_execution_source()
    receipt = json.loads((ROOT / "benchmarks/optimization/meta_selection/qms_execution_closeout_v4.json").read_text())
    retained = receipt["retained_sha256"]
    for name, expected in retained.items():
        if file_hash(name) != expected:
            raise ValueError("retained historical artifact changed")
    return dict(entry_commit=git("rev-parse", ENTRY)[0], runtime_files=len(names),
        runtime_sha256=hash_map({n: file_hash(n) for n in names}),
        sealed_files=len(sealed), sealed_sha256=hash_map({n: file_hash(n) for n in sealed}),
        guide_sha256=GUIDE_SHA, retained_artifacts=len(retained),
        retained_sha256=hash_map(retained))


def build_inventory():
    from quantbt import QuantBTEndpoint, walkforward_support_matrix
    from quantbt.wfo_execution import EXECUTION_ROUTES
    from quantbt.optimization.meta_selection.domains.registry import CAPABILITIES, route_metadata
    from quantbt.optimization.meta_selection.observer import canonical_metric_contract

    protected = protected_inventory()
    dispatch = verify_dispatch()
    discovery = {r["target_mode"]: r for r in walkforward_support_matrix(False)}
    source = ast.parse(textwrap.dedent(inspect.getsource(QuantBTEndpoint._run_walk_forward)))
    if not any(isinstance(n, ast.Compare) and isinstance(n.left, ast.Name)
            and n.left.id == "target_mode" and any(isinstance(v, ast.Name)
                and v.id == "EXECUTION_ROUTES" for v in n.comparators) for n in ast.walk(source)):
        raise ValueError("typed execution dispatch is no longer bound to reviewed EXECUTION_ROUTES")
    if not EXECUTION_ROUTES <= discovery.keys():
        raise ValueError("typed execution dispatch missing from public discovery")
    dispatch["execution_constant_targets"] = sorted(EXECUTION_ROUTES)
    if set(OWNERS) != {c.route for c in CAPABILITIES}:
        raise ValueError("capability changed; explicit inventory review required")
    rows, bound_names = [], set(CONTRACT_FILES) | {
        "examples/wfo_meta_" + name + ".py" for name in ("execution", "scalar", "portfolio", "package")}
    for cap in CAPABILITIES:
        kind, backend, measurement, account = OWNERS[cap.route]
        owners = [TESTS + measurement, TESTS + account]
        bound_names.update(check_symbol(ref) for ref in owners)
        adapter = None if kind is None else "::".join(SOURCES[kind])
        if adapter:
            bound_names.add(check_symbol(adapter))
        rows.append(dict(route=cap.route, discovery=discovery.get(cap.route),
            meta=route_metadata(cap.route), adapter_owner=adapter, financial_backend_scope=backend,
            diagnostic_account="original_reset_flat" if cap.activated else None,
            final_account=("original_segmented_reset_flat" if cap.route == "reactive_reset"
                else "one_original_continuous_account") if cap.activated else None,
            existing_test_owners=owners,
            coverage_review="EXISTING_TEST_INVENTORY_NOT_REEXECUTED",
            next_required_gate="PRE02-MATURED-" + cap.route if cap.activated else "FUTURE_ROUTE_ADMISSION"))
    return dict(schema="quantbt-pre-e06-01-inventory-v1", phase="PRE-E06-01",
        purpose="source_contract_inventory_not_financial_or_release_certification",
        protected=protected, metric_contract_365={**asdict(canonical_metric_contract()),
            "metric_id": canonical_metric_contract().metric_id},
        source_and_test_sha256={n: file_hash(n) for n in sorted(bound_names)},
        documentation_sha256={n: file_hash(n) for n in DOCS},
        discovery_and_dispatch=dispatch, routes=rows,
        prepared_scalar_targets=["signal_notional", "notional", "unit", "pct_equity"],
        prepared_contract="close_target_v2_same_close/legacy_zero_base_v1/original_same_pass",
        method_activation="Mode 4/per_fold_causal only; C01/C05 approved implementation pending",
        empirical_promotion=False, release=False)


def verify_manifest(payload):
    expected = json.loads(json.dumps(build_inventory()))
    if payload != expected:
        raise ValueError("PRE-E06 inventory is incomplete, tampered or stale; regenerate only after review")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write a newly reviewed local inventory")
    args = parser.parse_args()
    path = ROOT / MANIFEST
    if args.write:
        path.write_text(json.dumps(build_inventory(), indent=2, sort_keys=True) + "\n")
    payload = verify_manifest(json.loads(path.read_text()))
    print(json.dumps(dict(phase=payload["phase"], routes=len(payload["routes"]),
        runtime_files=payload["protected"]["runtime_files"],
        retained_artifacts=payload["protected"]["retained_artifacts"],
        gate="PASS_INVENTORY_ONLY", financial_runs=0, release=False), sort_keys=True))


if __name__ == "__main__":
    main()
