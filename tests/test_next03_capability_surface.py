"""NEXT-03 capability-resolution provenance locks."""

from __future__ import annotations

import pytest

from quantbt.core.product_contracts import native_product_registry, workload_capabilities
from quantbt.planning import (
    BacktestRequest,
    BackendKind,
    PlanningError,
    RunProfile,
    StrategyMode,
    WorkloadClass,
    resolve_execution_plan,
)
from quantbt.planning.capabilities import CapabilitySnapshot


def _callback_request(*, backend: str, required_capabilities: tuple[str, ...] = ()) -> BacktestRequest:
    return BacktestRequest(
        endpoint_mode="event_driven",
        input_mode="strategy",
        requested_backend=backend,
        execution_contract_id="event_lifecycle_v2_next_bar_close",
        strategy_mode=StrategyMode.PYTHON_CALLBACK_COMPAT,
        workload=WorkloadClass.PYTHON_CALLBACK,
        profile=RunProfile.MINIMAL,
        report_level="minimal",
        audit_sink="none",
        symbols=("BTC",),
        bars=32,
        required_capabilities=required_capabilities,
    )


def test_next03_generated_capability_tables_are_defensive_and_have_one_public_origin() -> None:
    registry = native_product_registry()
    capabilities = workload_capabilities()

    assert registry["registry_id"] == "quantbt-native-event-product-v1"
    assert capabilities
    assert {row["id"] for row in capabilities} == {
        row["id"] for row in registry["workloads"]
    }

    registry["workloads"][0]["id"] = "mutated"
    capabilities[0]["id"] = "mutated"
    assert native_product_registry()["workloads"][0]["id"] != "mutated"
    assert workload_capabilities()[0]["id"] != "mutated"


def test_next03_auto_callback_uses_the_governed_python_route_without_a_native_probe() -> None:
    probe_calls = 0

    def unexpected_probe() -> CapabilitySnapshot:
        nonlocal probe_calls
        probe_calls += 1
        raise AssertionError("unpromoted callback auto route must resolve before a native probe")

    plan = resolve_execution_plan(_callback_request(backend="auto"), rust_capability_loader=unexpected_probe)

    assert plan.backend is BackendKind.PYTHON
    assert plan.promotion_reason in {"workload_not_promoted", "auto_python_release_policy"}
    assert probe_calls == 0


def test_next03_explicit_missing_capability_fails_before_preparation_without_python_fallback() -> None:
    probe_calls = 0

    def unavailable_capability_probe() -> CapabilitySnapshot:
        nonlocal probe_calls
        probe_calls += 1
        return CapabilitySnapshot(
            available=True,
            compatible=True,
            executable=True,
            capabilities=(),
            semantic_descriptor=(),
            fingerprint="next03-test-native-descriptor",
            version="test",
            api_version="0.4",
        )

    with pytest.raises(PlanningError, match="failed before preparation.*next03_intentionally_unsupported_capability"):
        resolve_execution_plan(
            _callback_request(
                backend="rust",
                required_capabilities=("next03_intentionally_unsupported_capability",),
            ),
            rust_capability_loader=unavailable_capability_probe,
        )

    assert probe_calls == 1
