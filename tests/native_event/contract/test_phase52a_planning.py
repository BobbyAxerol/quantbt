from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from quantbt.planning import (
    BackendKind,
    BacktestRequest,
    DetailLevel,
    PathMask,
    PlanningError,
    RunProfile,
    StrategyMode,
    WorkloadClass,
    compile_output_requirements,
    resolve_execution_plan,
)
from quantbt.planning.capabilities import CapabilitySnapshot


def _request(**updates):
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
        "symbols": ("BTC",),
        "command_count": 3,
        "trace_requested": True,
    }
    values.update(updates)
    return BacktestRequest(**values)


def test_execution_plan_is_frozen_serializable_and_deterministic():
    request = _request()
    first = resolve_execution_plan(request)
    second = resolve_execution_plan(request)

    assert first == second
    assert first.backend is BackendKind.PYTHON
    assert first.plan_fingerprint == second.plan_fingerprint
    assert len(first.plan_fingerprint) == 64
    assert dict(first.resolution_counts) == {
        "backend": 1,
        "capability": 1,
        "contract": 1,
        "output": 1,
        "profile": 1,
    }
    assert json.loads(json.dumps(first.to_dict()))["contract_id"] == request.execution_contract_id
    with pytest.raises(FrozenInstanceError):
        first.contract_id = "changed"


def test_auto_does_not_probe_rust_and_explicit_rust_fails_before_preparation():
    calls = 0

    def unavailable():
        nonlocal calls
        calls += 1
        return CapabilitySnapshot(
            available=False,
            compatible=False,
            executable=False,
            capabilities=(),
            semantic_descriptor=(),
            fingerprint="unavailable",
            reason="missing test extension",
        )

    auto = resolve_execution_plan(_request(), rust_capability_loader=unavailable)
    assert auto.backend is BackendKind.PYTHON
    assert calls == 0

    with pytest.raises(PlanningError, match="before preparation"):
        resolve_execution_plan(
            _request(requested_backend="rust"),
            rust_capability_loader=unavailable,
        )
    assert calls == 1


def test_output_projection_compiles_once_for_score_and_audit():
    score = compile_output_requirements(profile="score", public_result=False)
    public_score = compile_output_requirements(profile="score", public_result=True)
    audit = compile_output_requirements(profile="audit")

    assert score.dense_paths is PathMask.NONE
    assert score.fill_detail is DetailLevel.COUNT
    assert score.event_detail is DetailLevel.COUNT
    assert score.materialize_pandas is False
    assert public_score.dense_paths & PathMask.EQUITY
    assert public_score.fill_detail is DetailLevel.COUNT
    assert public_score.event_detail is DetailLevel.COUNT
    assert public_score.materialize_pandas is True
    assert audit.dense_paths & PathMask.EQUITY
    assert audit.fill_detail is DetailLevel.FULL
    assert audit.event_detail is DetailLevel.FULL
    assert audit.materialize_pandas is True
    assert score.fingerprint != audit.fingerprint


def test_plan_fingerprint_changes_with_contract_backend_or_projection():
    base = resolve_execution_plan(_request())
    contract = resolve_execution_plan(
        _request(execution_contract_id="event_lifecycle_v2_next_bar_close")
    )
    score = resolve_execution_plan(
        _request(profile=RunProfile.SCORE, report_level="score", trace_requested=False)
    )

    assert len({base.plan_fingerprint, contract.plan_fingerprint, score.plan_fingerprint}) == 3
