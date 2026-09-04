#!/usr/bin/env python3
"""Generate the checked Rust-primary V1.1 baseline inventory and corpus.

This is deliberately a repository evidence tool, not an execution tool.  It
does not import ``quantbt`` or run a backtest.  It reads the public factory
surface, governed product registry, and archived evidence to freeze the exact
starting point for the Rust-primary program.
"""

from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tomllib
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_SOURCE = ROOT / "src" / "quantbt" / "endpoint.py"
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"
PUBLIC_API_INVENTORY = ROOT / "contracts" / "generated_public_api_inventory.json"
GUIDE = ROOT / "upgrade" / "QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md"
MEASUREMENT_MODULE = ROOT / "src" / "quantbt" / "benchmarks" / "v1_1_measurement.py"

INVENTORY_JSON = ROOT / "benchmarks" / "baselines" / "v1_1_endpoint_inventory.json"
INVENTORY_DOC = ROOT / "docs" / "generated" / "v1_1_endpoint_inventory.md"
CORPUS_JSON = ROOT / "benchmarks" / "baselines" / "v1_1_corpus_manifest.json"
CORPUS_DOC = ROOT / "docs" / "generated" / "v1_1_corpus_manifest.md"
MEASUREMENT_JSON = ROOT / "contracts" / "v1_1_measurement_contract.json"
MEASUREMENT_DOC = ROOT / "docs" / "generated" / "v1_1_measurement_contract.md"

AUTHORITY_FIELDS = (
    "strategy",
    "control_flow",
    "execution",
    "accounting",
    "metrics",
    "result",
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path.relative_to(ROOT)}")
    return payload


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _source_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required baseline source is missing: {_relative(path)}")
    return {
        "path": _relative(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _endpoint_factories() -> tuple[str, ...]:
    tree = ast.parse(ENDPOINT_SOURCE.read_text(encoding="utf-8"), filename=str(ENDPOINT_SOURCE))
    endpoint_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "QuantBTEndpoint"
        ),
        None,
    )
    if endpoint_class is None:
        raise ValueError("QuantBTEndpoint class is missing from endpoint.py")
    factories: list[str] = []
    for node in endpoint_class.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(isinstance(decorator, ast.Name) and decorator.id == "classmethod" for decorator in node.decorator_list):
            factories.append(node.name)
    if len(factories) != len(set(factories)):
        raise ValueError("QuantBTEndpoint contains duplicate classmethod names")
    return tuple(sorted(factories))


def _load_measurement_module() -> Any:
    specification = importlib.util.spec_from_file_location("quantbt_v1_1_measurement", MEASUREMENT_MODULE)
    if specification is None or specification.loader is None:
        raise ValueError("could not load V1.1 measurement contract module")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _authority(
    strategy: str,
    control_flow: str,
    execution: str,
    accounting: str,
    metrics: str,
    result: str,
) -> dict[str, str]:
    value = {
        "strategy": strategy,
        "control_flow": control_flow,
        "execution": execution,
        "accounting": accounting,
        "metrics": metrics,
        "result": result,
    }
    if tuple(value) != AUTHORITY_FIELDS or any(not item.strip() for item in value.values()):
        raise ValueError("authority rows must declare every non-empty authority dimension")
    return value


PYTHON_VECTOR_AUTHORITY = _authority(
    "external Python strategy or supplied signal",
    "Python endpoint facade",
    "Python/NumPy/Numba vectorized route",
    "Python/NumPy/Numba vectorized route",
    "Python metrics layer",
    "Python BacktestResult/report adapters",
)

PYTHON_EVENT_AUTHORITY = _authority(
    "external Python strategy or supplied command tape",
    "Python event lifecycle planner",
    "Python native-event lifecycle backend",
    "Python native-event ledger",
    "Python metrics layer",
    "Python BacktestResult/event artifacts",
)

RUST_GATED_EVENT_AUTHORITY = _authority(
    "external Python strategy or precomputed typed intent",
    "Python facade plus capability resolver",
    "Rust only for an eligible governed workload; Python otherwise",
    "Rust only for an eligible governed workload; Python otherwise",
    "Rust compact metrics for eligible score/compact routes; Python otherwise",
    "Rust buffers adapted by Python on the cold path",
)

INTRABAR_AUTHORITY = _authority(
    "external Python strategy or compact intent arrays",
    "Python contract validation and session policy",
    "Python reference or Numba intrabar kernel by endpoint",
    "Python reference or Numba intrabar accounting by endpoint",
    "Python metrics layer",
    "Python IntrabarReferenceResult/BacktestResult adapters",
)

PORTFOLIO_AUTHORITY = _authority(
    "external Python strategy/planner target matrix",
    "Python portfolio target planner",
    "Python/NumPy/Numba native-portfolio backend",
    "Python/NumPy/Numba native-portfolio ledger",
    "Python portfolio metrics/attribution",
    "Python portfolio result/report adapters",
)

NAUTILUS_AUTHORITY = _authority(
    "external Python signal/intent adapter",
    "Python adapter compiles declared intent",
    "NautilusTrader external validation engine",
    "NautilusTrader account/fill accounting",
    "QuantBT adaptation over Nautilus artifacts",
    "Python report bundle adapted from Nautilus artifacts",
)

PREPARATION_V2_AUTHORITY = _authority(
    "caller-owned market data and instrument specification",
    "Python V2 preparation and compatibility validation",
    "not applicable; immutable request preparation only",
    "not applicable; no account state is created",
    "not applicable; no metrics are calculated",
    "immutable V2 market, instrument, or execution-plan handle",
)


BASELINE_ENDPOINT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "prepare_market_v2",
        "factory": "prepare_market",
        "input_mode": "single_or_multi_symbol_ohlcv_to_canonical_calendar",
        "profiles": ("prepare",),
        "requested_backends": ("python_preparation",),
        "resolved_backend_baseline": "CalendarPlanV2 and PreparedMarketHandleV2",
        "authority": PREPARATION_V2_AUTHORITY,
        "runtime_class": "PreparedData",
        "maturity": "v1_1_certified_preparation",
        "fallback": {"auto": "not applicable", "explicit": "unsupported calendar/missing policies fail during preparation"},
        "notes": ("Exact is the certified default; legacy row-count relabel is never selected here.",),
    },
    {
        "id": "prepare_instruments_v2",
        "factory": "prepare_instruments",
        "input_mode": "instrument_specs_or_legacy_constraint_fields_to_registry",
        "profiles": ("prepare",),
        "requested_backends": ("python_preparation",),
        "resolved_backend_baseline": "InstrumentRegistryV2 with immutable normalized rule rows",
        "authority": PREPARATION_V2_AUTHORITY,
        "runtime_class": "PreparedData",
        "maturity": "v1_1_certified_preparation",
        "fallback": {"auto": "not applicable", "explicit": "invalid venue constraints fail during preparation"},
        "notes": ("Multiplier, leverage, fee, and quantity rules have one canonical V2 source.",),
    },
    {
        "id": "prepare_execution_plan_v2",
        "factory": "prepare_execution_plan",
        "input_mode": "matching_prepared_market_and_instrument_registry",
        "profiles": ("prepare",),
        "requested_backends": ("python_preparation",),
        "resolved_backend_baseline": "PreparedExecutionPlanV2 compatibility and provenance binder",
        "authority": PREPARATION_V2_AUTHORITY,
        "runtime_class": "PreparedData",
        "maturity": "v1_1_certified_preparation",
        "fallback": {"auto": "not applicable", "explicit": "symbol/fingerprint mismatch fails before execution"},
        "notes": ("The plan binds V2 handles; it is not a second execution engine.",),
    },
    {
        "id": "pct_equity_legacy_signal",
        "factory": "pct_equity",
        "input_mode": "signed_signal_or_target_weight",
        "profiles": ("research", "audit"),
        "requested_backends": ("legacy",),
        "resolved_backend_baseline": "legacy pct_equity route",
        "authority": PYTHON_VECTOR_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_compatibility",
        "fallback": {"auto": "not applicable", "explicit": "legacy is the declared route"},
        "notes": ("Legacy fee compatibility remains explicit at the endpoint boundary.",),
    },
    {
        "id": "signal_notional_vectorized",
        "factory": "signal_notional",
        "input_mode": "signed_signal_or_target_notional",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("native_vectorized",),
        "resolved_backend_baseline": "native_vectorized",
        "authority": PYTHON_VECTOR_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable",
        "fallback": {"auto": "not applicable", "explicit": "native_vectorized is the declared default"},
        "notes": ("Signal changes freeze units until the next declared transition.",),
    },
    {
        "id": "signal_notional_event",
        "factory": "signal_notional",
        "input_mode": "signed_signal_to_market_rebalance",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("native_event", "rust"),
        "resolved_backend_baseline": "native_event Python lifecycle unless an explicit governed product route applies",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_explicit_event",
        "fallback": {"auto": "not applicable", "explicit": "unsupported Rust request fails closed"},
        "notes": ("The generic signal-to-order adapter is not a blanket Rust promotion.",),
    },
    {
        "id": "intrabar_reference",
        "factory": "intrabar_bracket_reference",
        "input_mode": "compact_entry_exit_stop_take_profit_trailing_intent",
        "profiles": ("reference", "audit"),
        "requested_backends": ("intrabar_reference",),
        "resolved_backend_baseline": "readable Python intrabar oracle",
        "authority": INTRABAR_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "truth_model",
        "fallback": {"auto": "not applicable", "explicit": "reference endpoint is selected directly"},
        "notes": ("This is the causal oracle for the fast intrabar contract.",),
    },
    {
        "id": "intrabar_fast_numba",
        "factory": "intrabar_bracket",
        "input_mode": "compact_entry_exit_stop_take_profit_trailing_intent",
        "profiles": ("minimal", "standard", "audit"),
        "requested_backends": ("native_intrabar",),
        "resolved_backend_baseline": "Numba intrabar kernel",
        "authority": INTRABAR_AUTHORITY,
        "runtime_class": "WholeRunNative",
        "maturity": "certified_numba",
        "fallback": {"auto": "not applicable", "explicit": "fast intrabar endpoint is selected directly"},
        "notes": ("Audit materialization is a bounded sparse second pass, not an execution replay.",),
    },
    {
        "id": "fill_replay_accounting",
        "factory": "fill_replay",
        "input_mode": "explicit_fill_tape",
        "profiles": ("minimal", "standard", "audit"),
        "requested_backends": ("native_intrabar",),
        "resolved_backend_baseline": "Numba fill-replay accounting kernel",
        "authority": INTRABAR_AUTHORITY,
        "runtime_class": "WholeRunNative",
        "maturity": "certified_accounting_replay",
        "fallback": {"auto": "not applicable", "explicit": "fill replay is selected directly"},
        "notes": ("It certifies accounting from supplied fills, not fill generation.",),
    },
    {
        "id": "dca_ladder_legacy",
        "factory": "dca_ladder",
        "input_mode": "structural_grid_level",
        "profiles": ("research", "audit"),
        "requested_backends": ("legacy",),
        "resolved_backend_baseline": "legacy DCA/grid simulator",
        "authority": PYTHON_VECTOR_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_compatibility",
        "fallback": {"auto": "not applicable", "explicit": "legacy route is selected directly"},
        "notes": ("This is distinct from the reactive callback/Grid protocol.",),
    },
    {
        "id": "orders_event_lifecycle",
        "factory": "orders",
        "input_mode": "explicit_order_intents",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("native_event", "nautilus"),
        "resolved_backend_baseline": "selected external or Python event lifecycle backend",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable",
        "fallback": {"auto": "not applicable", "explicit": "backend is user-selected"},
        "notes": ("The public constructor is backend-neutral; authority follows the selected backend.",),
    },
    {
        "id": "event_driven_orders",
        "factory": "event_driven",
        "input_mode": "canonical_order_command_tape",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("auto", "python", "rust"),
        "resolved_backend_baseline": "capability-gated Rust static tape at declared thresholds; Python otherwise",
        "authority": RUST_GATED_EVENT_AUTHORITY,
        "runtime_class": "WholeRunNative",
        "maturity": "promoted_bounded_static",
        "fallback": {
            "auto": "Python with a recorded resolver reason outside the governed static-tape capability",
            "explicit": "Rust fails closed outside the exact certified capability",
        },
        "notes": ("Only product-registry static V2/V3 tape rows are auto eligible.",),
    },
    {
        "id": "event_driven_strategy",
        "factory": "event_driven",
        "input_mode": "stateful_python_reactive_strategy",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("auto", "python", "rust"),
        "resolved_backend_baseline": "Python reactive lifecycle",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_python_reactive",
        "fallback": {
            "auto": "Python remains the default authority for arbitrary callbacks",
            "explicit": "unsupported Rust callback capability fails closed",
        },
        "notes": ("Reactive Python is first-class and not represented as fully native.",),
    },
    {
        "id": "native_event_lifecycle",
        "factory": "native_event_lifecycle",
        "input_mode": "canonical_order_command_tape",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("auto", "python", "rust"),
        "resolved_backend_baseline": "same governed lifecycle resolver as event_driven(input_mode='orders')",
        "authority": RUST_GATED_EVENT_AUTHORITY,
        "runtime_class": "WholeRunNative",
        "maturity": "promoted_bounded_static",
        "fallback": {
            "auto": "Python with an observable resolver reason outside a certified static row",
            "explicit": "Rust fails closed outside the exact certified capability",
        },
        "notes": ("Advanced lifecycle controls retain their declared contract identifiers.",),
    },
    {
        "id": "native_event_strategy",
        "factory": "native_event_strategy",
        "input_mode": "stateful_python_reactive_strategy",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("auto", "python", "rust"),
        "resolved_backend_baseline": "Python reactive lifecycle",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_python_reactive",
        "fallback": {
            "auto": "Python remains the default authority for arbitrary callbacks",
            "explicit": "unsupported Rust callback capability fails closed",
        },
        "notes": ("No generic Python callback becomes Rust-authoritative in this baseline.",),
    },
    {
        "id": "options_native_option",
        "factory": "options",
        "input_mode": "canonical_option_chain_and_package_intents",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("native_option",),
        "resolved_backend_baseline": "native_option Python domain backend",
        "authority": _authority(
            "external option strategy/package planner",
            "Python option package planner",
            "Python native option backend",
            "Python multi-currency option ledger",
            "Python option metrics/Greeks reports",
            "Python OptionBacktestResult adapters",
        ),
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_controlled_research",
        "fallback": {"auto": "not applicable", "explicit": "native_option is the only accepted backend"},
        "notes": ("Options remain contained until a dedicated native contract exists.",),
    },
    {
        "id": "nautilus_dca_grid_validation",
        "factory": "nautilus_dca_grid",
        "input_mode": "DcaGridSpec",
        "profiles": ("validation", "audit"),
        "requested_backends": ("nautilus",),
        "resolved_backend_baseline": "Nautilus structured-order validation adapter",
        "authority": NAUTILUS_AUTHORITY,
        "runtime_class": "ExternalValidator",
        "maturity": "third_party_validation",
        "fallback": {"auto": "not applicable", "explicit": "requires the Nautilus adapter/runtime"},
        "notes": ("Dynamic state remains preflight mediated, not an in-strategy Nautilus state machine.",),
    },
    {
        "id": "nautilus_bracket_validation",
        "factory": "nautilus_bracket_orders",
        "input_mode": "BracketOrderSpec",
        "profiles": ("validation", "audit"),
        "requested_backends": ("nautilus",),
        "resolved_backend_baseline": "Nautilus bracket/OCO validation adapter",
        "authority": NAUTILUS_AUTHORITY,
        "runtime_class": "ExternalValidator",
        "maturity": "third_party_validation",
        "fallback": {"auto": "not applicable", "explicit": "requires the Nautilus adapter/runtime"},
        "notes": ("Sibling cancellation is adapter/package semantics, not venue-native order-list proof.",),
    },
    {
        "id": "native_event_dca_grid",
        "factory": "native_event_dca_grid",
        "input_mode": "DcaGridSpec_to_order_commands",
        "profiles": ("research", "audit"),
        "requested_backends": ("native_event", "rust"),
        "resolved_backend_baseline": "Python native-event structured-order route",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "controlled_research",
        "fallback": {"auto": "not applicable", "explicit": "generic structured grid is not auto Rust-promoted"},
        "notes": ("No dynamic Grid/DCA Rust state machine is claimed.",),
    },
    {
        "id": "native_event_bracket_orders",
        "factory": "native_event_bracket_orders",
        "input_mode": "BracketOrderSpec_to_order_commands",
        "profiles": ("research", "audit"),
        "requested_backends": ("native_event", "rust"),
        "resolved_backend_baseline": "Python native-event structured-order route",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "controlled_research",
        "fallback": {"auto": "not applicable", "explicit": "generic bracket package is not auto Rust-promoted"},
        "notes": ("The lifecycle contract remains explicit and auditable.",),
    },
    {
        "id": "basket_pair",
        "factory": "basket",
        "input_mode": "BasketSpec_and_scalar_entry_exit_signal",
        "profiles": ("research", "audit"),
        "requested_backends": ("native_event", "native_vectorized", "nautilus"),
        "resolved_backend_baseline": "selected Python or external package route",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_controlled_research",
        "fallback": {"auto": "not applicable", "explicit": "backend is user-selected"},
        "notes": ("Frozen hedge-ratio basket semantics are distinct from generic portfolio allocation.",),
    },
    {
        "id": "arbitrage_package",
        "factory": "arbitrage",
        "input_mode": "typed_arbitrage_spec_and_package_intents",
        "profiles": ("research", "audit"),
        "requested_backends": ("native_event", "native_vectorized", "nautilus"),
        "resolved_backend_baseline": "selected Python or external specialized package route",
        "authority": PYTHON_EVENT_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "controlled_research_by_spec",
        "fallback": {"auto": "not applicable", "explicit": "schema-only specs are rejected before execution"},
        "notes": ("Cross-exchange, triangular, and venue-specific contracts remain specialized future engines.",),
    },
    {
        "id": "portfolio_generic",
        "factory": "portfolio",
        "input_mode": "multi_symbol_target_matrix",
        "profiles": ("minimal", "standard", "audit"),
        "requested_backends": ("native_portfolio",),
        "resolved_backend_baseline": "Python/NumPy/Numba native_portfolio backend",
        "authority": PORTFOLIO_AUTHORITY,
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_default",
        "fallback": {"auto": "not applicable", "explicit": "generic portfolio is not a Rust auto route"},
        "notes": ("Risk parity and cross-margin remain governed by the current Python portfolio contract.",),
    },
    {
        "id": "nautilus_validation",
        "factory": "nautilus_validation",
        "input_mode": "signal_or_order_adapter_to_Nautilus",
        "profiles": ("validation", "audit"),
        "requested_backends": ("nautilus",),
        "resolved_backend_baseline": "NautilusTrader third-party validation adapter",
        "authority": NAUTILUS_AUTHORITY,
        "runtime_class": "ExternalValidator",
        "maturity": "third_party_validation",
        "fallback": {"auto": "not applicable", "explicit": "requires installed Nautilus dependencies"},
        "notes": ("Adapter fidelity is bounded by the supplied bar/depth data and venue instrument model.",),
    },
    {
        "id": "walk_forward",
        "factory": "walk_forward",
        "input_mode": "strategy_callback_or_prepared_signal_with_fold_schedule",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("target_backend_selected_by_endpoint",),
        "resolved_backend_baseline": "Python WalkForwardEngine controls folds, optimizer, and stitching",
        "authority": _authority(
            "external Python strategy per declared cutoff",
            "Python WalkForwardEngine schedule/optimizer/fold lifecycle",
            "selected endpoint scorer/backend",
            "selected endpoint account backend",
            "Python WFO score and stitched metrics",
            "Python WalkForwardResult and endpoint adaptation",
        ),
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_causal_schedule_contract",
        "fallback": {"auto": "backend-specific", "explicit": "unsupported schedule/backend combinations raise"},
        "notes": ("Global, per-fold decay, causal, and nested schedules retain distinct provenance claims.",),
    },
    {
        "id": "train_test_split",
        "factory": "train_test_split",
        "input_mode": "strategy_callback_or_prepared_signal_with_one_holdout",
        "profiles": ("research", "optimize", "audit"),
        "requested_backends": ("target_backend_selected_by_endpoint",),
        "resolved_backend_baseline": "Python train/test wrapper over the WFO scoring stack",
        "authority": _authority(
            "external Python strategy on the declared train and holdout windows",
            "Python split schedule and optimizer control",
            "selected endpoint scorer/backend",
            "selected endpoint account backend",
            "Python holdout metrics",
            "Python BacktestResult with WFO metadata",
        ),
        "runtime_class": "PythonCompatibility",
        "maturity": "stable_holdout_contract",
        "fallback": {"auto": "backend-specific", "explicit": "unsupported target/backend combinations raise"},
        "notes": ("The external holdout is not selection input under an IS-only configuration.",),
    },
)


CORPUS_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "static_v2_v3_orders",
        "route": "event_static_tape_v2_v3",
        "status": "baseline_available",
        "runtime_class": "WholeRunNative",
        "requested_backend": "auto",
        "resolved_backend": "rust_when_capability_gate_passes",
        "config_contract": {"execution_contracts": ["event_lifecycle_v2_next_bar_close", "event_lifecycle_v3_next_open"], "input": "canonical_order_command_tape"},
        "artifacts": (
            "tests/corpus/native_event/phase54a5_full_session.json",
            "benchmarks/native_event/results/phase54a5/exit_gate.json",
            "benchmarks/native_event/results/phase54b2/public_routes.json",
        ),
        "metrics": ("final_equity", "fees", "funding", "margin", "terminal_fingerprint"),
        "trace": "canonical_trace_artifact_available",
        "known_deviations": (),
    },
    {
        "id": "reactive_grid_mrs_like",
        "route": "event_driven(input_mode='strategy')",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "auto",
        "resolved_backend": "python",
        "config_contract": {"input": "stateful_python_callback", "wake_policy": "strategy_declared", "account": "single_symbol_linear"},
        "artifacts": (
            "benchmarks/native_event/reactive_session_baseline.json",
            "benchmarks/native_event/results/phase47c/python_audit_long_short.json",
            "benchmarks/native_event/results/phase47c/rust_audit_long_short.json",
        ),
        "metrics": ("final_equity", "fill_count", "event_count", "peak_rss_mb"),
        "trace": "route_specific_audit_artifacts",
        "known_deviations": ("Generic callback/reactive strategy is not Rust-primary in the V1.1 baseline.",),
    },
    {
        "id": "signal_notional",
        "route": "QuantBTEndpoint.signal_notional",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "native_vectorized",
        "resolved_backend": "native_vectorized",
        "config_contract": {"input": "signed_signal", "sizing": "signal_notional", "unit_policy": "frozen_between_signal_transitions"},
        "artifacts": (
            "benchmarks/phase16_performance_debt.json",
            "benchmarks/results/optimization_overhead.json",
            "tests/corpus/p0_baseline/market_single_symbol.json",
        ),
        "metrics": ("final_equity", "positions", "objective", "prepared_context_parity"),
        "trace": "not_recorded_in_historical_artifact",
        "known_deviations": (),
    },
    {
        "id": "pct_equity",
        "route": "QuantBTEndpoint.pct_equity",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "legacy",
        "resolved_backend": "legacy",
        "config_contract": {"input": "signed_signal", "sizing": "pct_equity", "fee_contract": "compatibility_layer_to_canonical_one_way_fee"},
        "artifacts": (
            "benchmarks/pct_equity_nautilus_smoke.json",
            "tests/corpus/p0_baseline/market_single_symbol.json",
        ),
        "metrics": ("final_equity", "total_return_pct", "num_trades", "transition_count"),
        "trace": "adapter_transition_report_available",
        "known_deviations": ("Nautilus venue fees/slippage can differ from endpoint custom settings by adapter contract.",),
    },
    {
        "id": "portfolio",
        "route": "QuantBTEndpoint.portfolio",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "native_portfolio",
        "resolved_backend": "native_portfolio",
        "config_contract": {"input": "multi_symbol_target_matrix", "account": "shared_linear_quote_settled", "report_levels": ["minimal", "standard", "audit"]},
        "artifacts": (
            "benchmarks/portfolio_real_parity_report.json",
            "benchmarks/native_event/results/phase54b3/portfolio_package.json",
            "benchmarks/phase16_performance_debt.json",
        ),
        "metrics": ("equity", "positions", "fees", "funding", "margin", "turnover", "attribution"),
        "trace": "portfolio_audit_artifact_available",
        "known_deviations": ("Generic portfolio is not a Rust auto route in this baseline.",),
    },
    {
        "id": "wfo_global",
        "route": "QuantBTEndpoint.walk_forward",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "endpoint_selected",
        "resolved_backend": "Python WalkForwardEngine global schedule",
        "config_contract": {"optimization_schedule": "retrospective_global", "selection": "mode_specific", "fold_account": "declared_endpoint_policy"},
        "artifacts": (
            "benchmarks/phase49b_wfo_performance.json",
            "benchmarks/phase13_wfo_cache.json",
        ),
        "metrics": ("trial_table", "candidate_table", "selected_params", "stitched_equity", "fold_metrics"),
        "trace": "fold_metadata_and_terminal_metrics",
        "known_deviations": ("Global schedule has retrospective provenance and is not a per-fold causal claim.",),
    },
    {
        "id": "wfo_per_fold_decay",
        "route": "QuantBTEndpoint.walk_forward",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "endpoint_selected",
        "resolved_backend": "Python WalkForwardEngine per_fold_decay schedule",
        "config_contract": {"optimization_schedule": "per_fold_decay", "selection": "IS optimization with OOS decay measurement", "fold_account": "declared_endpoint_policy"},
        "artifacts": (
            "benchmarks/phase49b_wfo_performance.json",
            "docs/walkforward_causal.md",
        ),
        "metrics": ("fold_trial_table", "fold_selected_params", "fold_oos_metrics", "stitched_equity"),
        "trace": "fold_metadata_and_causal_cutoff",
        "known_deviations": ("OOS is evaluation for fold decay, never a direct Optuna parameter input.",),
    },
    {
        "id": "wfo_per_fold_causal",
        "route": "QuantBTEndpoint.walk_forward",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "endpoint_selected",
        "resolved_backend": "Python WalkForwardEngine per_fold_causal schedule",
        "config_contract": {"optimization_schedule": "per_fold_causal", "selection": "IS-only", "fold_account": "declared_endpoint_policy"},
        "artifacts": (
            "benchmarks/phase49b_wfo_performance.json",
            "docs/walkforward_causal.md",
        ),
        "metrics": ("fold_trial_table", "fold_selected_params", "fold_oos_metrics", "stitched_equity"),
        "trace": "fold_metadata_and_causal_cutoff",
        "known_deviations": ("Selection must not inspect later fold observations.",),
    },
    {
        "id": "wfo_engine_enforced_nested",
        "route": "QuantBTEndpoint.walk_forward",
        "status": "unsupported_baseline",
        "runtime_class": "not_applicable",
        "requested_backend": "endpoint_selected",
        "resolved_backend": "not implemented as a current public schedule",
        "config_contract": {"optimization_schedule": "engine_enforced_nested", "selection": "future native/WFO contract"},
        "artifacts": ("upgrade/QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md",),
        "metrics": (),
        "trace": "not_available",
        "known_deviations": ("Included to prevent a future schedule from being mistaken for an existing capability.",),
    },
    {
        "id": "intrabar_bracket",
        "route": "QuantBTEndpoint.intrabar_bracket",
        "status": "baseline_available",
        "runtime_class": "WholeRunNative",
        "requested_backend": "native_intrabar",
        "resolved_backend": "Numba intrabar kernel",
        "config_contract": {"execution_contract": "intrabar_bracket_v1", "input": "compact intent columns", "profiles": ["minimal", "standard", "audit"]},
        "artifacts": ("benchmarks/phase31_intrabar_benchmark.json", "docs/contracts/phase51b_certification.json"),
        "metrics": ("final_equity", "fills", "terminal_fingerprint", "trace_replay", "bars_per_second"),
        "trace": "canonical_trace_and_replay_evidence",
        "known_deviations": ("Scope is single-symbol intrabar, not shared cross-margin portfolio execution.",),
    },
    {
        "id": "fill_replay",
        "route": "QuantBTEndpoint.fill_replay",
        "status": "baseline_available",
        "runtime_class": "WholeRunNative",
        "requested_backend": "native_intrabar",
        "resolved_backend": "Numba fill-replay accounting kernel",
        "config_contract": {"execution_contract": "fill_replay_v1", "input": "explicit fill tape", "claim": "accounting_only"},
        "artifacts": ("benchmarks/phase31_intrabar_benchmark.json", "tests/corpus/regressions/phase51b/reversal_and_atomic_rollback.json"),
        "metrics": ("final_equity", "fees", "funding", "terminal_position", "trace_replay"),
        "trace": "replay_artifact_available",
        "known_deviations": ("It does not validate order matching or market fill generation.",),
    },
    {
        "id": "atomic_package",
        "route": "run_atomic_package_market",
        "status": "baseline_available",
        "runtime_class": "WholeRunNative",
        "requested_backend": "rust_explicit",
        "resolved_backend": "Rust bounded package helper when explicitly selected",
        "config_contract": {"package_policy": "same_bar_atomic_market", "account": "linear_quote_settled_gross_cross", "scope": "all_or_none"},
        "artifacts": ("benchmarks/native_event/results/phase54b3/portfolio_package.json", "tests/corpus/regressions/phase51b/reversal_and_atomic_rollback.json"),
        "metrics": ("final_equity", "fill_count", "fees", "funding", "package_status"),
        "trace": "package_transaction_artifact_available",
        "known_deviations": ("Generic arbitrage/package endpoints remain Python by default.",),
    },
    {
        "id": "options_basic_european",
        "route": "QuantBTEndpoint.options",
        "status": "baseline_available",
        "runtime_class": "PythonCompatibility",
        "requested_backend": "native_option",
        "resolved_backend": "native_option Python domain backend",
        "config_contract": {"instrument_scope": "basic European options", "execution": "top_of_book", "margin": "standard_venue_approx"},
        "artifacts": ("benchmarks/options_phase10_baseline.json",),
        "metrics": ("final_equity", "fills", "packages", "cash", "marks", "greeks", "margin"),
        "trace": "deterministic_replay_manifest",
        "known_deviations": ("Venue-exact margin and a dedicated Rust options engine are not claimed.",),
    },
)


def _package_versions(product: Mapping[str, Any]) -> dict[str, Any]:
    versions = product["versions"]
    return {
        "quantbt_engine": str(versions["core_package"]["version"]),
        "quantbt_native": str(versions["native_package"]["version"]),
        "native_protocol": dict(versions["native_protocol"]),
        "command_abi": str(versions["command_abi"]["current"]),
        "result_abi": str(versions["result_abi"]["current"]),
    }


def _endpoint_rows(product: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    factories = set(_endpoint_factories())
    coverage: dict[str, list[str]] = {factory: [] for factory in sorted(factories)}
    package_versions = _package_versions(product)
    rows: list[dict[str, Any]] = []
    for spec in BASELINE_ENDPOINT_SPECS:
        factory = str(spec["factory"])
        if factory not in factories:
            raise ValueError(f"baseline inventory references absent endpoint factory: {factory}")
        row = {
            "id": str(spec["id"]),
            "surface_type": "public_endpoint",
            "endpoint": f"QuantBTEndpoint.{factory}",
            "factory": factory,
            "input_mode": str(spec["input_mode"]),
            "profiles": list(spec["profiles"]),
            "requested_backends": list(spec["requested_backends"]),
            "resolved_backend_baseline": str(spec["resolved_backend_baseline"]),
            "authority": dict(spec["authority"]),
            "runtime_class": str(spec["runtime_class"]),
            "fallback": dict(spec["fallback"]),
            "maturity": str(spec["maturity"]),
            "package_versions": dict(package_versions),
            "source_anchors": [f"src/quantbt/endpoint.py#QuantBTEndpoint.{factory}"],
            "notes": list(spec["notes"]),
        }
        if tuple(row["authority"]) != AUTHORITY_FIELDS:
            raise ValueError(f"endpoint inventory row has incomplete authority: {row['id']}")
        coverage[factory].append(row["id"])
        rows.append(row)
    missing = sorted(factory for factory, row_ids in coverage.items() if not row_ids)
    if missing:
        raise ValueError(f"every public endpoint factory needs a V1.1 baseline row: {missing}")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("endpoint baseline row ids must be unique")
    return sorted(rows, key=lambda row: row["id"]), coverage


def _workload_rows(product: Mapping[str, Any]) -> list[dict[str, Any]]:
    package_versions = _package_versions(product)
    rows: list[dict[str, Any]] = []
    for workload in sorted(product["workloads"], key=lambda item: str(item["id"])):
        workload_id = str(workload["id"])
        strategy_modes = tuple(str(item) for item in workload["strategy_modes"])
        maturity = str(workload["maturity"])
        auto = bool(workload["auto_promotion"])
        if workload_id in {"event_static_tape_v2_v3", "native_strategy_ir_v1"}:
            authority = RUST_GATED_EVENT_AUTHORITY
            runtime_class = "WholeRunNative"
            resolved = "rust when exact wheel, capability, timing, account, and threshold gates pass; Python otherwise"
        elif workload_id in {"portfolio_target_market_v1", "package_atomic_market_v1"}:
            authority = RUST_GATED_EVENT_AUTHORITY
            runtime_class = "WholeRunNative"
            resolved = "Rust explicit helper only; generic endpoint remains Python"
        else:
            authority = PYTHON_EVENT_AUTHORITY
            runtime_class = "PythonCompatibility"
            resolved = "Python baseline; no auto Rust authority"
        rows.append(
            {
                "id": f"native_workload::{workload_id}",
                "surface_type": "governed_native_workload",
                "endpoint": "native product capability registry",
                "factory": None,
                "input_mode": ",".join(strategy_modes),
                "profiles": list(workload["profiles"]),
                "requested_backends": ["auto", "python", "rust"],
                "resolved_backend_baseline": resolved,
                "authority": dict(authority),
                "runtime_class": runtime_class,
                "fallback": {
                    "auto": "Python with a resolver reason when no enabled rule matches",
                    "explicit": "Rust fails closed when the exact workload contract is not certified",
                },
                "maturity": maturity,
                "auto_promotion": auto,
                "package_versions": dict(package_versions),
                "source_anchors": ["contracts/native_event_product_registry.json#workloads"],
                "notes": [
                    f"Declared strategy modes: {', '.join(strategy_modes)}.",
                    "This is a governed capability row, not blanket endpoint promotion.",
                ],
            }
        )
    return rows


def build_endpoint_inventory() -> dict[str, Any]:
    product = _read_json(PRODUCT_REGISTRY)
    lifecycle = _read_json(LIFECYCLE_REGISTRY)
    public_api = _read_json(PUBLIC_API_INVENTORY)
    rows, coverage = _endpoint_rows(product)
    rows.extend(_workload_rows(product))
    rows = sorted(rows, key=lambda row: row["id"])
    return {
        "schema": "quantbt-rust-primary-v1_1-endpoint-inventory-v1",
        "baseline_id": "rust_primary_v1_1_phase0",
        "source_fingerprints": {
            "endpoint": _source_record(ENDPOINT_SOURCE),
            "product_registry": _source_record(PRODUCT_REGISTRY),
            "lifecycle_registry": _source_record(LIFECYCLE_REGISTRY),
            "public_api_inventory": _source_record(PUBLIC_API_INVENTORY),
            "guide": _source_record(GUIDE),
        },
        "package_versions": _package_versions(product),
        "endpoint_factory_coverage": coverage,
        "lifecycle_contract_ids": sorted(str(item["contract_id"]) for item in lifecycle["contracts"]),
        "public_root_exports": sorted(str(item) for item in public_api["exports"]),
        "rows": rows,
        "interpretation": {
            "authority": "current baseline authority by declared route, not a future promotion target",
            "fallback": "auto fallback must be observable; explicit Rust requests fail closed outside certified scope",
            "runtime_class": "describes current decision/execution ownership and must not be inferred from a single native entry",
        },
    }


def _artifact_records(paths: tuple[str, ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in paths:
        path = ROOT / relative
        records.append(_source_record(path))
    return records


def build_corpus_manifest() -> dict[str, Any]:
    measurement = _load_measurement_module()
    product = _read_json(PRODUCT_REGISTRY)
    cases: list[dict[str, Any]] = []
    for spec in CORPUS_SPECS:
        artifact_records = _artifact_records(tuple(spec["artifacts"]))
        status = str(spec["status"])
        measurement_status = "historical_artifact" if status == "baseline_available" else "not_applicable"
        record = measurement.build_measurement_record_v1(
            workload_id=str(spec["id"]),
            route_id=str(spec["route"]),
            profile="baseline_snapshot",
            requested_backend=str(spec["requested_backend"]),
            resolved_backend=str(spec["resolved_backend"]),
            runtime_class=str(spec["runtime_class"]),
            measurement_status=measurement_status,
            artifact_refs=[item["path"] for item in artifact_records],
            notes=[
                "Historical evidence is normalized into the V1.1 field shape.",
                "Null counter/timing/RSS values are unmeasured, not zero.",
            ],
        )
        cases.append(
            {
                "id": str(spec["id"]),
                "route": str(spec["route"]),
                "status": status,
                "config_contract": dict(spec["config_contract"]),
                "required_metrics": list(spec["metrics"]),
                "canonical_trace": str(spec["trace"]),
                "artifacts": artifact_records,
                "known_deviations": list(spec["known_deviations"]),
                "measurement": record,
            }
        )
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("baseline corpus case ids must be unique")
    return {
        "schema": "quantbt-rust-primary-v1_1-corpus-manifest-v1",
        "baseline_id": "rust_primary_v1_1_phase0",
        "package_versions": _package_versions(product),
        "source_fingerprints": {
            "guide": _source_record(GUIDE),
            "measurement_contract_module": _source_record(MEASUREMENT_MODULE),
            "product_registry": _source_record(PRODUCT_REGISTRY),
        },
        "measurement_null_semantics": "null means not measured by the referenced historical artifact; zero means measured zero",
        "cases": sorted(cases, key=lambda case: case["id"]),
    }


def _render_inventory_docs(payload: Mapping[str, Any]) -> str:
    rows = list(payload["rows"])
    public_rows = [row for row in rows if row["surface_type"] == "public_endpoint"]
    workload_rows = [row for row in rows if row["surface_type"] == "governed_native_workload"]
    lines = [
        "# Rust-Primary V1.1 Endpoint Inventory",
        "",
        "> Generated by `tools/generate_v1_1_baseline.py`; do not edit by hand.",
        "",
        "This is a current-state authority inventory. It does not turn a future",
        "Rust-primary target into a current auto-promotion claim. The machine-readable",
        "artifact is [`v1_1_endpoint_inventory.json`](../../benchmarks/baselines/v1_1_endpoint_inventory.json).",
        "",
        "## Public Endpoint Routes",
        "",
        "| Route | Input | Baseline resolution | Runtime class | Maturity |",
        "|---|---|---|---|---|",
    ]
    for row in public_rows:
        lines.append(
            f"| `{row['endpoint']}` ({row['id']}) | {row['input_mode']} | {row['resolved_backend_baseline']} | `{row['runtime_class']}` | `{row['maturity']}` |"
        )
    lines.extend(("", "## Governed Native Workloads", "", "| Workload | Auto route | Baseline resolution | Runtime class | Maturity |", "|---|---:|---|---|---|"))
    for row in workload_rows:
        auto = "yes" if row.get("auto_promotion") else "no"
        lines.append(
            f"| `{row['id'].removeprefix('native_workload::')}` | {auto} | {row['resolved_backend_baseline']} | `{row['runtime_class']}` | `{row['maturity']}` |"
        )
    lines.extend(
        (
            "",
            "## Reading The Inventory",
            "",
            "- Each JSON row declares strategy, control-flow, execution, accounting, metrics, and result authority separately.",
            "- `WholeRunNative` only applies to a bounded current workload when its exact resolver gate passes. It is not a project-wide claim.",
            "- `PythonCompatibility` includes supported, production Python/NumPy/Numba routes; it is not a maturity downgrade.",
            "- `ExternalValidator` means the third-party engine owns matching/accounting while QuantBT owns adapter provenance and report adaptation.",
            "- `backend=\"auto\"` must report why it selected Python. An explicit Rust request must fail rather than silently change semantics.",
            "",
        )
    )
    return "\n".join(lines)


def _render_corpus_docs(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Rust-Primary V1.1 Baseline Corpus",
        "",
        "> Generated by `tools/generate_v1_1_baseline.py`; do not edit by hand.",
        "",
        "The corpus freezes current fixture/evidence hashes before semantics or authority change.",
        "The machine-readable artifact is [`v1_1_corpus_manifest.json`](../../benchmarks/baselines/v1_1_corpus_manifest.json).",
        "",
        "| Case | Status | Route | Trace evidence | Artifact count |",
        "|---|---|---|---|---:|",
    ]
    for case in payload["cases"]:
        lines.append(
            f"| `{case['id']}` | `{case['status']}` | `{case['route']}` | {case['canonical_trace']} | {len(case['artifacts'])} |"
        )
    lines.extend(
        (
            "",
            "## Measurement Semantics",
            "",
            "Each case carries a complete V1.1 diagnostics record. Historical artifacts are normalized into the same key set, but missing measurements remain `null`; `null` never means a measured zero. Future benchmark writers must emit the shared schema directly.",
            "",
            "`wfo_engine_enforced_nested` is intentionally recorded as unsupported in the baseline. This prevents later work from claiming an existing public causal schedule by accident.",
            "",
        )
    )
    return "\n".join(lines)


def _render_measurement_docs(payload: Mapping[str, Any]) -> str:
    def rendered(values: list[str]) -> str:
        return "\n".join(f"- `{value}`" for value in values)

    return "\n".join(
        (
            "# Rust-Primary V1.1 Measurement Contract",
            "",
            "> Generated by `tools/generate_v1_1_baseline.py`; do not edit by hand.",
            "",
            "The JSON schema is [`v1_1_measurement_contract.json`](../../contracts/v1_1_measurement_contract.json). It is intentionally independent of pandas, reporting, engine imports, and the optional native wheel.",
            "",
            "## Status Values",
            "",
            rendered(list(payload["measurement_statuses"])),
            "",
            "## Phase Timings",
            "",
            rendered(list(payload["phase_timings_ns"])),
            "",
            "## Boundary Counters",
            "",
            rendered(list(payload["boundary_counters"])),
            "",
            "## Memory Fields",
            "",
            rendered(list(payload["memory_bytes"])),
            "",
            f"**Null semantics:** {payload['null_semantics']}.",
            "",
        )
    )


def generated_outputs() -> dict[Path, str]:
    inventory = build_endpoint_inventory()
    corpus = build_corpus_manifest()
    measurement = _load_measurement_module().measurement_contract_definition_v1()
    return {
        INVENTORY_JSON: _canonical_json(inventory),
        INVENTORY_DOC: _render_inventory_docs(inventory),
        CORPUS_JSON: _canonical_json(corpus),
        CORPUS_DOC: _render_corpus_docs(corpus),
        MEASUREMENT_JSON: _canonical_json(measurement),
        MEASUREMENT_DOC: _render_measurement_docs(measurement),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when generated artifacts differ")
    args = parser.parse_args(argv)
    try:
        outputs = generated_outputs()
    except (OSError, SyntaxError, TypeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"V1.1 baseline generation failed: {exc}", file=sys.stderr)
        return 1
    stale = [path for path, content in outputs.items() if not path.is_file() or path.read_text(encoding="utf-8") != content]
    if args.check:
        if stale:
            print("stale V1.1 baseline artifacts:", file=sys.stderr)
            print("\n".join(_relative(path) for path in stale), file=sys.stderr)
            return 1
        print("V1.1 baseline artifact check: PASS")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print("generated V1.1 baseline artifacts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
