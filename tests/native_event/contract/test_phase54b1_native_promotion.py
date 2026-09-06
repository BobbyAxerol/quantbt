from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from quantbt.backends._native_event_rust import (
    NativeEventRustExtensionStatus,
    resolve_native_event_backend,
)
from quantbt.backends.native_event import NativeEventBackend, NativeEventConfig
from quantbt.core.native_event_promotion import (
    NativePromotionContext,
    NativePromotionError,
    resolve_native_event_promotion,
)
from quantbt.core.generated_product_contracts import (
    NATIVE_EVENT_PRODUCT_REGISTRY,
    NATIVE_EVENT_PROMOTION_POLICY,
    NATIVE_EVENT_PROMOTION_TABLE_VERSION,
)
from quantbt.core.schema import AccountConfig
from quantbt.planning import (
    BackendKind,
    BacktestRequest,
    RunProfile,
    StrategyMode,
    WorkloadClass,
    resolve_execution_plan,
)
from quantbt.planning.capabilities import CapabilitySnapshot
from tools.measurement_contract import load_measurement_contract


_STATIC_CAPABILITIES = (
    "native_event_v2_full_contract",
    "native_event_v2_multisymbol",
    "native_event_v2_funding",
    "native_event_v2_liquidation",
    "native_event_v2_cancel_all_oco",
    "native_event_v2_tif_expiry",
    "native_event_v2_relationships",
    "native_event_v2_quantity_preflight",
)


def _current_candidate_evidence() -> dict[str, object]:
    """Build fully-shaped synthetic evidence for routing-policy tests only."""

    root = Path(__file__).resolve().parents[3]
    contract = load_measurement_contract(
        root / "benchmarks" / "native_event" / "manifests" / "phase72_measurement_contract_v1.json",
        root=root,
    )
    digest = "a" * 64
    pair = next(item for item in contract["profile_pairs"] if item["id"] == "compact_to_compact_v1")
    comparator = {
        "timing_scope": pair["timing_scope"],
        "result_contract": pair["result_contract"],
        "metric_contract_id": "metric-contract-v2-365",
        "annualization_days": 365,
        "fee_contract_id": "canonical-one-way-fee-v1",
        "account_contract_id": "linear-quote-gross-cross-v1",
    }
    return {
        "status": "pass",
        "measurement_status": "current_candidate_verified",
        "identity_status": "current_candidate",
        "promotion_eligible": True,
        "end_to_end_faster_than_python": True,
        "rss_plateau": True,
        "candidate_identity": {
            "git_commit": "b" * 40,
            "git_dirty": False,
            "git_status_sha256": digest,
            "canonical_source_sha256": digest,
            "product_registry_sha256": digest,
            "lifecycle_registry_sha256": digest,
            "core_distribution": {"distribution": "quantbt-engine", "version": "1.1.0"},
            "native_distribution": {"distribution": "quantbt-native", "version": "0.4.1"},
            "native_extension": {
                "available": True,
                "module_sha256": digest,
                "version": "0.4.1",
                "api_version": "0.4",
                "capability_sha256": digest,
            },
            "python": "CPython 3.12",
            "platform": "linux-x86_64",
            "cpu_count": 4,
            "thread_environment": {},
            "data_sha256": digest,
            "intent_sha256": digest,
            "measurement_contract_sha256": digest,
            "warmup_procedure": "test warmup",
        },
        "comparator_contract": {"python": dict(comparator), "native": dict(comparator)},
        "measurement": {
            "sample_count": 9,
            "median_seconds": 0.01,
            "p95_seconds": 0.02,
            "cold_rss_mb": 100.0,
            "warm_rss_mb": 104.0,
            "parity": {"passed": True},
            "artifact_sha256": digest,
        },
    }


def _context(**updates) -> NativePromotionContext:
    values = {
        "requested_backend": "auto",
        "backend_policy": None,
        "workload_id": "event_static_tape_v2_v3",
        "execution_contract_id": "event_lifecycle_v3_next_open",
        "strategy_mode": "static_commands",
        "profile": "audit",
        "account_model": "linear_quote_settled_gross_cross",
        "bars": 10_000,
        "symbol_count": 1,
        "required_capabilities": (),
        "platform_tags": ("cpython-3.12+", "linux-x86_64-local"),
    }
    values.update(updates)
    return NativePromotionContext(**values)


def _promoted_static_registry_and_policy():
    registry = deepcopy(NATIVE_EVENT_PRODUCT_REGISTRY)
    policy = deepcopy(NATIVE_EVENT_PROMOTION_POLICY)
    registry["workloads"] = list(registry["workloads"])
    static = next(item for item in registry["workloads"] if item["id"] == "event_static_tape_v2_v3")
    static["maturity"] = "promoted"
    static["auto_promotion"] = True
    evidence = registry["performance_evidence"]["event_static_tape_v2_v3"]
    evidence.update(_current_candidate_evidence())
    evidence.update(
        {
            "status": "pass",
            "measurement_status": "current_candidate_verified",
            "identity_status": "current_candidate",
            "promotion_eligible": True,
            "end_to_end_faster_than_python": True,
            "rss_plateau": True,
        }
    )
    policy["default_stage"] = "static_ir"
    policy["rules"] = list(policy["rules"])
    next(item for item in policy["rules"] if item["id"] == "static_tape_rust_stage_b")["enabled"] = True
    return registry, policy


def _available_context(**updates) -> NativePromotionContext:
    values = {
        "native_available": True,
        "native_compatible": True,
        "native_executable": True,
        "native_capabilities": _STATIC_CAPABILITIES,
    }
    values.update(updates)
    return _context(**values)


def _request(**updates) -> BacktestRequest:
    values = {
        "endpoint_mode": "orders",
        "input_mode": "orders",
        "requested_backend": "auto",
        "execution_contract_id": "event_lifecycle_v3_next_open",
        "strategy_mode": StrategyMode.STATIC_COMMANDS,
        "workload": WorkloadClass.STATIC_COMMAND_TAPE,
        "profile": RunProfile.AUDIT,
        "report_level": "audit",
        "audit_sink": "memory",
        "symbols": ("BTCUSDT",),
        "command_count": 2,
        "bars": 10_000,
        "trace_requested": True,
    }
    values.update(updates)
    return BacktestRequest(**values)


def test_phase72_registry_is_versioned_and_holds_auto_promotion_without_current_evidence():
    decision = resolve_native_event_promotion(_context(), environment={})

    assert NATIVE_EVENT_PROMOTION_POLICY["table_version"] == NATIVE_EVENT_PROMOTION_TABLE_VERSION
    assert decision.resolved_backend == "python"
    assert decision.reason == "measurement_evidence_not_current"
    assert decision.native_probe_required is False
    assert decision.configured_stage == "static_ir"
    assert decision.effective_stage == "static_ir"
    assert decision.to_dict()["fingerprint"] == decision.fingerprint


def test_phase54b1_explicit_rust_probes_once_and_fails_closed_on_capability_gap():
    pending = resolve_native_event_promotion(
        _context(requested_backend="rust", required_capabilities=("native_event_v2_full_contract",)),
        environment={},
    )
    assert pending.native_probe_required is True
    assert pending.reason == "native_probe_required"

    accepted = resolve_native_event_promotion(
        _available_context(
            requested_backend="rust",
            required_capabilities=("native_event_v2_full_contract",),
        ),
        environment={},
    )
    assert accepted.resolved_backend == "rust"
    assert accepted.reason == "explicit_rust_certified"

    rejected = resolve_native_event_promotion(
        _available_context(
            requested_backend="rust",
            required_capabilities=("missing_capability",),
        ),
        environment={},
    )
    assert rejected.resolved_backend == "python"
    assert rejected.reason == "native_missing_capabilities"


def test_phase54b1_policy_and_emergency_controls_never_bypass_certification():
    registry, policy = _promoted_static_registry_and_policy()
    native = resolve_native_event_promotion(
        _available_context(backend_policy="prefer_native"),
        environment={},
        registry=registry,
        policy_table=policy,
    )
    assert native.resolved_backend == "rust"
    assert native.matched_rule_id == "static_tape_rust_stage_b"
    assert native.workload_maturity == "promoted"
    assert native.execution_contract_id == "event_lifecycle_v3_next_open"
    assert native.emergency_native_disabled is False

    compatibility = resolve_native_event_promotion(
        _available_context(backend_policy="prefer_compatibility"),
        environment={},
        registry=registry,
        policy_table=policy,
    )
    assert compatibility.resolved_backend == "python"
    assert compatibility.reason == "policy_prefer_compatibility"

    stage_limited = resolve_native_event_promotion(
        _available_context(),
        environment={"QUANTBT_NATIVE_PROMOTION_MAX": "explicit_only"},
        registry=registry,
        policy_table=policy,
    )
    assert stage_limited.resolved_backend == "python"
    assert stage_limited.reason == "promotion_stage_limited"

    disabled = resolve_native_event_promotion(
        _available_context(),
        environment={"QUANTBT_DISABLE_NATIVE": "1"},
        registry=registry,
        policy_table=policy,
    )
    assert disabled.resolved_backend == "python"
    assert disabled.reason == "emergency_native_disabled"
    assert disabled.emergency_native_disabled is True
    assert disabled.promotion_max_stage == "package"
    with pytest.raises(NativePromotionError, match="QUANTBT_DISABLE_NATIVE"):
        resolve_native_event_promotion(
            _available_context(requested_backend="rust"),
            environment={"QUANTBT_DISABLE_NATIVE": "true"},
            registry=registry,
            policy_table=policy,
        )


def test_phase54b1_decision_fingerprint_changes_only_with_routing_inputs():
    first = resolve_native_event_promotion(_context(), environment={})
    second = resolve_native_event_promotion(_context(), environment={})
    policy_changed = resolve_native_event_promotion(
        _context(backend_policy="prefer_compatibility"),
        environment={},
    )

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != policy_changed.fingerprint


def test_phase72_planner_does_not_probe_a_withdrawn_auto_route_and_records_provenance():
    calls = 0

    def unexpected_probe() -> CapabilitySnapshot:
        nonlocal calls
        calls += 1
        return CapabilitySnapshot(
            available=True,
            compatible=True,
            executable=True,
            capabilities=tuple((name, True) for name in _STATIC_CAPABILITIES),
            semantic_descriptor=(),
            fingerprint="native-test",
        )

    plan = resolve_execution_plan(_request(), rust_capability_loader=unexpected_probe, environment={})

    assert calls == 0
    assert plan.backend is BackendKind.PYTHON
    assert plan.promotion_reason == "measurement_evidence_not_current"
    assert plan.promotion_table_version == NATIVE_EVENT_PROMOTION_TABLE_VERSION
    assert plan.promotion_rule_id is None
    assert len(plan.promotion_fingerprint) == 64
    assert plan.to_dict()["backend_policy"] == "certified_only"


def test_phase54b1_compatibility_selector_and_backend_metadata_share_the_policy():
    status = NativeEventRustExtensionStatus(
        available=True,
        compatible=True,
        executable=True,
        version="test",
        api_version="0.4",
        capabilities={"reactive_session": True},
    )
    selection = resolve_native_event_backend("auto", extension_status=status, environment={})
    assert selection.resolved == "python"
    assert selection.promotion.reason == "auto_python_release_policy"

    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0),
            native_backend="auto",
            backend_policy="prefer_compatibility",
        )
    )
    metadata = backend._backend_selection_metadata()
    assert metadata["native_event_promotion_v1"]["backend_policy"] == "prefer_compatibility"
    assert metadata["native_event_promotion_v1"]["reason"] == "policy_prefer_compatibility"
