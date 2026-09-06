#!/usr/bin/env python3
"""Generate the PERF-01 public-route and performance-work traceability map.

This tool is intentionally source-only: it inventories the checked tree and
can capture a separate runtime identity file, but it never runs a strategy or
claims a benchmark result.  Later PERF phases attach measured evidence to this
map rather than replacing its route ownership records.
"""

from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_PATH = ROOT / "src" / "quantbt" / "endpoint.py"
MEASUREMENT_TOOL_PATH = ROOT / "tools" / "measurement_contract.py"
DEFAULT_MANIFEST = ROOT / "benchmarks" / "native_event" / "traceability" / "perf_01_traceability_v1.json"
DEFAULT_DOC = ROOT / "docs" / "performance" / "perf_01_traceability.md"

SCHEMA = "quantbt-perf-01-traceability-v1"


ROUTE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "id": "static_orders",
        "factories": ("orders", "native_event_lifecycle"),
        "resolved_request": "declared OrderCommand tape -> execution plan",
        "runtime_kernel": "NativeEventBackend static lifecycle executor",
        "metrics_result": "native-event ledger -> BacktestResult/report adapters",
        "export": "fills, order logs, metrics, plots, report bundle",
        "domain_contract": "event lifecycle timing, fee/funding/account contract",
        "optimization_target": "AP-04 matcher/specialization later; PERF-01 records baseline only",
        "oracle_tests": ("tests/native_event/contract/test_phase54b2_rust_first_routes.py",),
        "benchmark_fixture": "phase54b2 deterministic public static command tape",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/backends/native_event.py",
            "src/quantbt/core/native_event_promotion.py",
        ),
    },
    {
        "id": "fill_replay",
        "factories": ("fill_replay",),
        "resolved_request": "typed FillReplayTapeV2 and funding replay tape",
        "runtime_kernel": "Rust FillReplay V2 where explicitly certified; reference otherwise",
        "metrics_result": "linear accounting result -> standard metrics and audit adapters",
        "export": "fill replay result, audit, metrics",
        "domain_contract": "linear accounting, fee/funding timing, deterministic fill order",
        "optimization_target": "AP-01 retention plan; no replay replacement in PERF-01",
        "oracle_tests": ("tests/test_phase59_linear_accounting_fill_replay.py",),
        "benchmark_fixture": "phase59 linear accounting corpus",
        "anchors": ("src/quantbt/endpoint.py", "src/quantbt/core/fill_replay_v2.py"),
    },
    {
        "id": "target_signal",
        "factories": ("signal_notional",),
        "resolved_request": "signal/target matrix -> prepared target request",
        "runtime_kernel": "NativeVectorizedBackend NumPy/Numba or explicit typed Rust route",
        "metrics_result": "vectorized account result -> BacktestResult/report adapters",
        "export": "equity, positions, metrics, report",
        "domain_contract": "target sizing, one-way fee, slippage, funding, margin",
        "optimization_target": "AP-06 target specialization later",
        "oracle_tests": ("tests/test_phase66_rust_target_vectorized.py",),
        "benchmark_fixture": "phase66 same-close direct target fixture",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/backends/native_vectorized.py",
            "src/quantbt/preparation/native_execution.py",
        ),
    },
    {
        "id": "pct_equity",
        "factories": ("pct_equity",),
        "resolved_request": "legacy signed signal -> pct-equity transition request",
        "runtime_kernel": "legacy compatibility route or explicit prepared Rust transition scorer",
        "metrics_result": "endpoint-compatible account result -> BacktestResult/report adapters",
        "export": "equity, raw positions, metrics, report",
        "domain_contract": "legacy transition sizing with canonical fee/slippage provenance",
        "optimization_target": "public WFO prepared score; preserve legacy final account behavior",
        "oracle_tests": ("tests/test_phase77_2_pct_equity_native.py",),
        "benchmark_fixture": "phase77.2 pct-equity WFO fixture",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/backends/native_wfo_public.py",
            "src/quantbt/backends/native_prepared_evaluation.py",
        ),
    },
    {
        "id": "static_dca",
        "factories": ("dca_ladder", "native_event_dca_grid"),
        "resolved_request": "DCA/grid specification -> structured target/order plan",
        "runtime_kernel": "native vectorized DCA or event lifecycle route",
        "metrics_result": "account result -> standard metrics and audit adapters",
        "export": "equity, orders, fills, metrics, report",
        "domain_contract": "ladder activation, quantity constraints, margin and liquidation",
        "optimization_target": "AP-04/AP-05 high-churn work stays downstream",
        "oracle_tests": ("tests/test_phase47a_grid_adapter.py",),
        "benchmark_fixture": "Phase47 grid adapter and parity fixture",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/core/target_intents.py",
            "src/quantbt/core/structured_orders.py",
        ),
    },
    {
        "id": "reactive_event_strategy",
        "factories": ("event_driven", "native_event_strategy"),
        "resolved_request": "reactive strategy protocol -> wake schedule and staged command batch",
        "runtime_kernel": "hybrid Python strategy / Rust numeric co-runtime when eligible",
        "metrics_result": "reactive account ledger -> BacktestResult and audit adapters",
        "export": "event/fill logs, equity, metrics, report",
        "domain_contract": "wake ordering, callback state, staged command exception/cancel semantics",
        "optimization_target": "AP-03 boundary and AP-02 reset work in PERF-02/PERF-03",
        "oracle_tests": (
            "tests/test_phase62_reactive_numeric_coruntime.py",
            "tests/test_phase63_sparse_block_reactive.py",
        ),
        "benchmark_fixture": "phase62/63 low- and high-churn reactive fixtures",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/api/event_driven.py",
            "src/quantbt/strategies/reactive_protocols.py",
        ),
    },
    {
        "id": "portfolio_basket",
        "factories": ("portfolio", "basket"),
        "resolved_request": "aligned target matrix or basket plan -> shared account admission",
        "runtime_kernel": "NativePortfolioBackend; bounded Rust shared-account companion where certified",
        "metrics_result": "portfolio attribution/account result -> report adapters",
        "export": "equity, exposure, attribution, metrics, report",
        "domain_contract": "shared equity, margin, quantities, fees/funding and rebalance policy",
        "optimization_target": "AP-04 derived account snapshot and AP-09 tiling later",
        "oracle_tests": ("tests/test_phase67_rust_shared_portfolio.py",),
        "benchmark_fixture": "phase67 shared-account portfolio fixture",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/backends/native_portfolio.py",
            "src/quantbt/core/portfolio_execution_contracts.py",
        ),
    },
    {
        "id": "bounded_package_arbitrage",
        "factories": ("arbitrage",),
        "resolved_request": "arbitrage/package spec -> typed multi-leg intent package",
        "runtime_kernel": "bounded package/arbitrage executor with explicit Rust companion",
        "metrics_result": "package result, residuals and account result -> report adapters",
        "export": "leg package PnL, residuals, metrics, report",
        "domain_contract": "leg ordering, partial/residual policy, shared liquidity/account state",
        "optimization_target": "AP-04/AP-05 package admission and matcher work later",
        "oracle_tests": ("tests/test_phase68_rust_package_authority.py",),
        "benchmark_fixture": "phase68 bounded package fixture",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/backends/native_package_arbitrage.py",
            "src/quantbt/core/package_execution_v2.py",
        ),
    },
    {
        "id": "intrabar",
        "factories": ("intrabar_bracket", "intrabar_bracket_rust"),
        "resolved_request": "OHLCV tape plus compact intrabar intent/session tape",
        "runtime_kernel": "reference/Numba intrabar or explicit Rust intrabar kernel",
        "metrics_result": "intrabar account path -> standard metrics and audit adapters",
        "export": "fills, lifecycle flags, equity, metrics, audit",
        "domain_contract": "intrabar ordering, protective exits, funding clock and ambiguity policy",
        "optimization_target": "AP-06 specialization is measured before any promotion",
        "oracle_tests": ("tests/test_phase69_rust_intrabar_authority.py",),
        "benchmark_fixture": "phase69 single-symbol bracket fixture",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/backends/native_intrabar_rust.py",
            "src/quantbt/core/intrabar_kernel.py",
        ),
    },
    {
        "id": "walk_forward_mode_1",
        "factories": ("walk_forward",),
        "resolved_request": "Mode 1 candidate/fold tasks -> endpoint or prepared scalar score batch",
        "runtime_kernel": "WalkForwardEngine plus optional NativePreparedPublicWfoScorerV1",
        "metrics_result": "trial/fold metrics -> decay selector -> stitched endpoint account",
        "export": "trial ledger, fold table, candidate table, stitched metrics/report",
        "domain_contract": "declared global/per-fold schedule and mode-1 decay selection",
        "optimization_target": "AP-01 plan and AP-07/AP-08 WFO work later",
        "oracle_tests": ("tests/test_phase74_public_wfo_native.py",),
        "benchmark_fixture": "PERF-01 paired public Mode 1 observer baseline",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/walkforward.py",
            "src/quantbt/backends/native_wfo_public.py",
        ),
    },
    {
        "id": "walk_forward_mode_2",
        "factories": ("walk_forward",),
        "resolved_request": "Mode 2 return path -> stationary/bootstrap robustness selector",
        "runtime_kernel": "WalkForwardEngine statistical bootstrap path",
        "metrics_result": "bootstrap statistics -> candidate selection -> stitched endpoint account",
        "export": "trial ledger, fold table, candidate table, stitched metrics/report",
        "domain_contract": "seeded bootstrap indices and declared SBB simulation policy",
        "optimization_target": "AP-07/AP-08, no hidden top-K reduction",
        "oracle_tests": ("tests/test_walkforward_phase1.py",),
        "benchmark_fixture": "phase77.1 required mode schedule matrix",
        "anchors": ("src/quantbt/endpoint.py", "src/quantbt/walkforward.py"),
    },
    {
        "id": "walk_forward_mode_3",
        "factories": ("walk_forward",),
        "resolved_request": "Mode 3 candidate metrics and parameter coordinates -> flat-minima selector",
        "runtime_kernel": "WalkForwardEngine plateau selector",
        "metrics_result": "cluster selection -> stitched endpoint account",
        "export": "trial/candidate ledgers, selection metadata, metrics/report",
        "domain_contract": "parameter normalization, deterministic cluster/tie policy",
        "optimization_target": "AP-07/AP-08 selection DAG work later",
        "oracle_tests": ("tests/test_walkforward_phase1.py",),
        "benchmark_fixture": "phase77.1 required mode schedule matrix",
        "anchors": ("src/quantbt/endpoint.py", "src/quantbt/walkforward.py"),
    },
    {
        "id": "walk_forward_mode_4",
        "factories": ("walk_forward",),
        "resolved_request": "Mode 4 IS shard metrics and plateau coordinates -> IS-only robust selector",
        "runtime_kernel": "WalkForwardEngine temporal/plateau selection path",
        "metrics_result": "IS-only candidate selector -> stitched endpoint account",
        "export": "trial/candidate ledgers, shard metadata, metrics/report",
        "domain_contract": "IS-only selection and declared causal/global schedule semantics",
        "optimization_target": "AP-07/AP-08 and prepared public WFO score reuse",
        "oracle_tests": ("tests/test_phase49a_walkforward_schedules.py",),
        "benchmark_fixture": "phase77.1 public mode4 per-fold causal row",
        "anchors": ("src/quantbt/endpoint.py", "src/quantbt/walkforward.py", "src/quantbt/backends/native_wfo_public.py"),
    },
    {
        "id": "walk_forward_mode_5",
        "factories": ("walk_forward",),
        "resolved_request": "full declared IS candidates -> full-sample robust selector",
        "runtime_kernel": "WalkForwardEngine full-sample selection path",
        "metrics_result": "full-IS selection -> endpoint account on supplied evaluation tape",
        "export": "trial/candidate ledgers, selection metadata, metrics/report",
        "domain_contract": "full declared sample only; no implicit chronological OOS claim",
        "optimization_target": "AP-01 retention plan and AP-07 selector DAG later",
        "oracle_tests": ("tests/test_walkforward_phase1.py",),
        "benchmark_fixture": "phase77.1 required mode schedule matrix",
        "anchors": ("src/quantbt/endpoint.py", "src/quantbt/walkforward.py"),
    },
    {
        "id": "options_containment",
        "factories": ("options",),
        "resolved_request": "option chain, instruments and hedge policy -> options execution plan",
        "runtime_kernel": "Python options domain backend",
        "metrics_result": "options ledger/Greeks/margin -> option result/report adapters",
        "export": "cash, marks, Greeks, margin, fills, packages, report",
        "domain_contract": "declared European/top-of-book scope and explicit approximation labels",
        "optimization_target": "contained outside PERF native promotion scope",
        "oracle_tests": ("tests/options/test_endpoint_contract.py", "tests/options/test_result_contract.py"),
        "benchmark_fixture": "options P0 containment regression",
        "anchors": (
            "src/quantbt/endpoint.py",
            "src/quantbt/options/execution.py",
            "src/quantbt/options/authority.py",
        ),
    },
)

AP_DISPOSITIONS: tuple[dict[str, Any], ...] = (
    {"id": "AP-01", "state": "IMPLEMENTED_VERIFIED", "owner": "PERF-01", "evidence": ("src/quantbt/core/performance_contracts.py", "rust/crates/quantbt-engine/src/metrics_v2.rs", "src/quantbt/core/native_result_v2.py")},
    {"id": "AP-02", "state": "OPEN", "owner": "PERF-02", "evidence": ("src/quantbt/backends/native_prepared_evaluation.py",)},
    {
        "id": "AP-03",
        "state": "IMPLEMENTED_VERIFIED",
        "owner": "PERF-03",
        "evidence": (
            "rust/native_event/src/reactive_numeric.rs",
            "src/quantbt/backends/native_event.py",
            "tests/test_perf_03_reactive_boundary.py",
            "benchmarks/native_event/benchmark_perf03_reactive_boundary.py",
        ),
    },
    {"id": "AP-04", "state": "OPEN", "owner": "PERF-02", "evidence": ("src/quantbt/core/runtime_governance.py",)},
    {"id": "AP-05", "state": "OPEN", "owner": "PERF-04", "evidence": ("src/quantbt/backends/native_event.py",)},
    {"id": "AP-06", "state": "OPEN", "owner": "PERF-04", "evidence": ("src/quantbt/backends/native_vectorized.py",)},
    {"id": "AP-07", "state": "OPEN", "owner": "PERF-05", "evidence": ("src/quantbt/walkforward.py",)},
    {"id": "AP-08", "state": "OPEN", "owner": "PERF-05", "evidence": ("src/quantbt/walkforward.py",)},
    {"id": "AP-09", "state": "OPEN", "owner": "PERF-05", "evidence": ("src/quantbt/backends/native_prepared_evaluation.py",)},
    {"id": "AP-10", "state": "OPEN", "owner": "PERF-06", "evidence": ("src/quantbt/core/runtime_governance.py",)},
    {"id": "AP-11", "state": "IMPLEMENTED_VERIFIED", "owner": "PERF-01", "evidence": ("src/quantbt/core/performance_contracts.py", "src/quantbt/walkforward.py")},
    {"id": "AP-12", "state": "OPEN", "owner": "PERF-07", "evidence": ("rust/Cargo.toml",)},
)

_LATER_AC_OWNER = {
    **{identifier: "PERF-02" for identifier in range(5, 11)},
    **{identifier: "PERF-03" for identifier in range(11, 18)},
    **{identifier: "PERF-04" for identifier in range(18, 24)},
    **{identifier: "PERF-05" for identifier in range(24, 35)},
    **{identifier: "PERF-06" for identifier in range(35, 40)},
    **{identifier: "PERF-07" for identifier in range(40, 45)},
}

BENCHMARK_CLASSES: tuple[dict[str, str], ...] = (
    ("B-01", "no-trade short/long score/compact", "PERF-01"),
    ("B-02", "numeric every-bar strategy with repeated getters", "PERF-03"),
    ("B-03", "many commands per callback", "PERF-03"),
    ("B-04", "object-heavy Python decision", "PERF-03"),
    ("B-05", "sparse strategy with idle bars", "PERF-03"),
    ("B-06", "grid high churn resting/cancel/amend", "PERF-04"),
    ("B-07", "fresh versus reused heterogeneous trials", "PERF-02"),
    ("B-08", "target candidate/symbol shape sweep", "PERF-04"),
    ("B-09", "portfolio/package shared account", "PERF-04"),
    ("B-10", "fixed-matrix WFO across five modes", "PERF-05"),
    ("B-11", "zero/mixed/high cache reuse", "PERF-05"),
    ("B-12", "audit-full research with slow sink", "PERF-06"),
    ("B-13", "long WFO cancel/fail/retry", "PERF-05"),
    ("B-14", "held-out workload for PGO", "PERF-07"),
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _endpoint_factories() -> set[str]:
    tree = ast.parse(ENDPOINT_PATH.read_text(encoding="utf-8"), filename=str(ENDPOINT_PATH))
    endpoint_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QuantBTEndpoint"
    )
    return {
        node.name
        for node in endpoint_class.body
        if isinstance(node, ast.FunctionDef)
        and any(isinstance(item, ast.Name) and item.id == "classmethod" for item in node.decorator_list)
    }


def _source_record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    return {"path": relative, "exists": path.is_file(), "sha256": _sha(path) if path.is_file() else None}


def _load_measurement_tool():
    specification = importlib.util.spec_from_file_location("perf01_measurement_contract", MEASUREMENT_TOOL_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load measurement-contract helpers")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def capture_runtime_identity() -> dict[str, Any]:
    """Capture machine-local identity separately from the committed source map."""

    measurement = _load_measurement_tool()
    return {
        "schema": "quantbt-perf-01-runtime-identity-v1",
        "phase": "PERF-01",
        "source_identity": measurement.capture_measurement_identity(
            root=ROOT,
            warmup_procedure="workload-specific warm-up declared by the benchmark manifest",
        ),
    }


def build_manifest() -> dict[str, Any]:
    """Build a checked route/AP/AC/B map for the current source snapshot."""

    factories = _endpoint_factories()
    routes: list[dict[str, Any]] = []
    for source in ROUTE_ROWS:
        row = dict(source)
        row["factories"] = list(row["factories"])
        row["oracle_tests"] = list(row["oracle_tests"])
        row["source_records"] = [_source_record(path) for path in row.pop("anchors")]
        missing = sorted(factory for factory in row["factories"] if factory not in factories)
        if missing:
            raise ValueError(f"traceability row {row['id']} references absent endpoint factories: {missing}")
        absent = [record["path"] for record in row["source_records"] if not record["exists"]]
        if absent:
            raise ValueError(f"traceability row {row['id']} has missing source anchors: {absent}")
        missing_tests = [path for path in row["oracle_tests"] if not (ROOT / path).is_file()]
        if missing_tests:
            raise ValueError(f"traceability row {row['id']} has missing oracle tests: {missing_tests}")
        routes.append(row)

    ac_rows = []
    covered = {
        1: ("PERF-01", "tests/test_perf_01_traceability_and_computation.py::test_observation_ledger_deduplicates_per_reducer"),
        2: ("PERF-01", "tests/test_perf_01_traceability_and_computation.py::test_opaque_custom_metric_requires_conservative_full_input"),
        3: ("PERF-01", "tests/test_perf_01_traceability_and_computation.py::test_profiled_wfo_preserves_trial_checkpoint_order_and_result"),
        4: ("PERF-01", "tests/test_phase49b_wfo_performance.py::test_prepared_walkforward_context_has_content_signature_and_isolated_strategy_slice"),
        11: ("PERF-03", "tests/test_perf_03_reactive_boundary.py::test_perf03_exception_discards_unsubmitted_staged_rows_and_requires_reset"),
        12: ("PERF-03", "tests/test_perf_03_reactive_boundary.py::test_perf03_business_rejection_remains_per_command_not_callback_atomicity"),
        13: ("PERF-03", "tests/test_phase62_reactive_numeric_coruntime.py::test_r1_direct_runner_rejects_command_capacity_exhaustion_deterministically"),
        14: ("PERF-03", "tests/test_perf_03_reactive_boundary.py::test_perf03_silent_every_bar_callback_still_advances_private_state"),
        15: ("PERF-03", "tests/test_perf_03_reactive_boundary.py::test_perf03_future_ohlc_suffix_cannot_change_prior_effective_command"),
        16: ("PERF-03", "tests/test_phase63_sparse_block_reactive.py::test_r2_coalesces_fill_order_event_and_liquidation_on_one_boundary"),
        17: ("PERF-03", "tests/test_phase63_sparse_block_reactive.py::test_r3b_candidate_batch_coalesces_callbacks_and_isolates_failures"),
        42: ("PERF-01", "tests/test_perf_01_traceability_and_computation.py::test_observer_on_off_keeps_walkforward_economics_identical"),
    }
    for identifier in range(1, 45):
        if identifier in covered:
            owner, evidence = covered[identifier]
            state = f"COVERED_{owner.replace('-', '')}"
        else:
            owner, evidence = _LATER_AC_OWNER[identifier], None
            state = "OWNED_BY_LATER_PHASE"
        ac_rows.append(
            {
                "id": f"AC-{identifier:02d}",
                "state": state,
                "owner": owner,
                "evidence": evidence,
            }
        )

    measurement = _load_measurement_tool()
    return {
        "schema": SCHEMA,
        "phase": "PERF-01",
        "baseline_source": {
            "identity_mode": "content-addressed source anchors; runtime identity captured separately",
            "endpoint": _source_record("src/quantbt/endpoint.py"),
            "walkforward": _source_record("src/quantbt/walkforward.py"),
            "performance_contracts": _source_record("src/quantbt/core/performance_contracts.py"),
            "measurement_contract_tool": _source_record("tools/measurement_contract.py"),
            "native_metrics": _source_record("rust/crates/quantbt-engine/src/metrics_v2.rs"),
        },
        "runtime_identity_capture": {
            "helper": "tools.measurement_contract.capture_measurement_identity",
            "required_fields": sorted(measurement.IDENTITY_REQUIRED_FIELDS),
            "command": "PYTHONPATH=src .venv/bin/python tools/generate_perf01_traceability.py --runtime-identity /tmp/perf01-runtime-identity.json",
            "rule": "capture a clean candidate separately; do not commit credentials, private market data, or a machine-local extension path as public evidence",
        },
        "route_matrix": routes,
        "ap_dispositions": [dict(item, evidence=list(item["evidence"])) for item in AP_DISPOSITIONS],
        "ac_coverage": ac_rows,
        "benchmark_classes": [
            {"id": identifier, "workload": workload, "owner": owner, "state": "REGISTERED"}
            for identifier, workload, owner in BENCHMARK_CLASSES
        ],
        "contracts": {
            "economic_vs_performance": "economic fingerprints remain independent of kernel/cache/profile choices",
            "ownership": "prepared WFO context is run-local; strategy slices are isolated; mutable source identity is content-hashed",
            "audit": "financial retention and research retention are independent; requested audit cannot be silently dropped",
            "numeric": "no fast-math, RNG substitution, relaxed tie-break or reordered sequential optimizer decisions",
            "callback": "callback exception/re-entry/cancel/capacity work is owned by PERF-03",
        },
        "measurement_policy": {
            "timing": "exclusive stage buckets plus separate optional aggregate worker CPU time",
            "counter_null": "null means not measured by that route; zero means measured zero",
            "comparison": "paired public samples; cache reuse must be reported separately from execution throughput",
            "baseline_budget": {"warm_public_p50_regression_pct": 3.0, "warm_public_p95_regression_pct": 5.0},
        },
    }


def validate_manifest(payload: Mapping[str, Any]) -> list[str]:
    """Return deterministic structural violations without re-running workloads."""

    violations: list[str] = []
    if payload.get("schema") != SCHEMA:
        violations.append("unsupported schema")
    if payload.get("phase") != "PERF-01":
        violations.append("phase must be PERF-01")
    routes = payload.get("route_matrix")
    if not isinstance(routes, list) or len(routes) < 15:
        violations.append("route matrix is incomplete")
    else:
        ids = [row.get("id") for row in routes]
        if len(ids) != len(set(ids)):
            violations.append("route ids must be unique")
        for row in routes:
            for field in ("factories", "resolved_request", "runtime_kernel", "metrics_result", "export", "domain_contract"):
                if row.get(field) in (None, "", []):
                    violations.append(f"route {row.get('id')} missing {field}")
            for source in row.get("source_records", []):
                if not source.get("exists") or not source.get("sha256"):
                    violations.append(f"route {row.get('id')} has unavailable source anchor")
    ap_rows = payload.get("ap_dispositions")
    if not isinstance(ap_rows, list) or {row.get("id") for row in ap_rows} != {f"AP-{item:02d}" for item in range(1, 13)}:
        violations.append("AP disposition matrix must contain AP-01 through AP-12")
    ac_rows = payload.get("ac_coverage")
    if not isinstance(ac_rows, list) or {row.get("id") for row in ac_rows} != {f"AC-{item:02d}" for item in range(1, 45)}:
        violations.append("AC coverage matrix must contain AC-01 through AC-44")
    benchmark_rows = payload.get("benchmark_classes")
    if not isinstance(benchmark_rows, list) or {row.get("id") for row in benchmark_rows} != {f"B-{item:02d}" for item in range(1, 15)}:
        violations.append("benchmark matrix must contain B-01 through B-14")
    return violations


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render a compact human-readable companion to the JSON artifact."""

    lines = [
        "# PERF-01 Traceability And Computation Plan",
        "",
        "> Generated by `tools/generate_perf01_traceability.py`; edit the source map, not this output.",
        "",
        "This artifact pins source ownership and measurement obligations before later performance changes. It is not a benchmark certificate and does not promote any route.",
        "",
        "## Public Route Map",
        "",
        "| Route | Public factory | Runtime/kernel | Metrics/result |",
        "|---|---|---|---|",
    ]
    for row in payload["route_matrix"]:
        lines.append(
            f"| `{row['id']}` | {', '.join(f'`QuantBTEndpoint.{item}`' for item in row['factories'])} | {row['runtime_kernel']} | {row['metrics_result']} |"
        )
    lines.extend(("", "## AP Disposition", "", "| Proposal | State | Owner |", "|---|---|---|"))
    for row in payload["ap_dispositions"]:
        lines.append(f"| `{row['id']}` | `{row['state']}` | `{row['owner']}` |")
    lines.extend(
        (
            "",
            "## PERF-01 Contracts",
            "",
            "- `RequiredComputationPlanV1` compiles WFO objective, pruning, retention, reducer and output-sink requirements at prepare time.",
            "- Existing native `OnlineMetricReducerV2` remains the financial score authority; this phase does not create a second metric engine.",
            "- `ExclusiveWorkProfilerV1` uses non-overlapping timing buckets. Null counters mean the route did not measure that boundary; they are not synthetic zeroes.",
            "- Opaque custom metrics force conservative full-input retention and cannot use scalar-only prepared-native scoring.",
            "- Prepared context ownership, cache identity, audit compatibility, callback failure semantics and numeric/RNG/tie-break policy are locked here for downstream phases.",
            "",
            "## Runtime Identity Capture",
            "",
            "For a candidate measurement, use the existing `capture_measurement_identity(...)` helper from `tools/measurement_contract.py` with a clean tree and workload-specific typed data/intent hashes. Keep private strategy/data paths and credentials outside committed evidence.",
            "",
        )
    )
    return "\n".join(lines).rstrip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument(
        "--runtime-identity",
        type=Path,
        help="write machine-local runtime identity separately from the committed source map",
    )
    parser.add_argument("--check", action="store_true", help="validate generated content without writing")
    args = parser.parse_args(argv)
    if args.runtime_identity is not None:
        _write(args.runtime_identity, json.dumps(capture_runtime_identity(), indent=2, sort_keys=True) + "\n")
    manifest = build_manifest()
    violations = validate_manifest(manifest)
    if violations:
        raise SystemExit("PERF-01 traceability validation failed: " + "; ".join(violations))
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(manifest) + "\n"
    if args.check:
        expected_manifest = args.manifest.read_text(encoding="utf-8") if args.manifest.is_file() else ""
        expected_doc = args.doc.read_text(encoding="utf-8") if args.doc.is_file() else ""
        if expected_manifest != encoded or expected_doc != markdown:
            raise SystemExit("PERF-01 traceability artifacts are stale; rerun tools/generate_perf01_traceability.py")
    else:
        _write(args.manifest, encoded)
        _write(args.doc, markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
