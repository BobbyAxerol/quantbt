from __future__ import annotations

from types import ModuleType

import pytest
from hypothesis import given, settings, strategies as st

from quantbt import (
    NATIVE_EVENT_COMMAND_ABI_VERSION,
    NATIVE_EVENT_CORE_PROTOCOL_VERSION,
    TRACE_SCHEMA_VERSION,
    native_event_semantic_descriptor,
    quantize_order_value,
    semantic_descriptor_fingerprint,
)
from quantbt.backends._native_event_rust import (
    NativeEventRustBackendError,
    probe_native_event_rust_extension,
    resolve_native_event_backend,
)
from quantbt.core.product_contracts import native_runtime_product_descriptor


def test_installed_native_extension_passes_structured_semantic_handshake():
    status = probe_native_event_rust_extension()
    assert status.available and status.compatible and status.executable
    assert status.reason is None
    assert status.semantic_descriptor == native_event_semantic_descriptor()
    assert status.product_descriptor == native_runtime_product_descriptor()
    assert status.semantic_descriptor["trace_schema"] == TRACE_SCHEMA_VERSION
    assert status.semantic_descriptor["command_abi"] == NATIVE_EVENT_COMMAND_ABI_VERSION
    assert status.semantic_descriptor["core_protocol_min"] <= NATIVE_EVENT_CORE_PROTOCOL_VERSION
    assert status.semantic_descriptor["core_protocol_max"] >= NATIVE_EVENT_CORE_PROTOCOL_VERSION
    assert len(semantic_descriptor_fingerprint(status.semantic_descriptor)) == 64


def _mismatched_module() -> ModuleType:
    module = ModuleType("_quantbt_native")
    module.version = lambda: "0.4.0"
    module.api_version = lambda: "0.4"
    module.capabilities = lambda: {"reactive_session": True, "semantic_descriptor_v1": True}
    descriptor = native_event_semantic_descriptor()
    descriptor["trace_schema"] = "wrong-trace"
    module.semantic_descriptor = lambda: descriptor
    return module


def test_explicit_rust_semantic_mismatch_fails_before_execution():
    status = probe_native_event_rust_extension(module=_mismatched_module())
    assert status.available and not status.compatible and not status.executable
    assert "trace_schema" in str(status.reason)
    with pytest.raises(NativeEventRustBackendError, match="trace_schema"):
        resolve_native_event_backend("rust", extension_status=status)


def test_auto_remains_python_and_exposes_a_structured_non_probe_reason():
    selection = resolve_native_event_backend("auto")
    assert selection.resolved == "python"
    assert selection.extension.available is False
    assert "not queried" in str(selection.extension.reason)


@settings(max_examples=100, deadline=None)
@given(
    price=st.floats(min_value=0.001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    qty=st.floats(min_value=0.000001, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    tick=st.sampled_from([0.0001, 0.001, 0.01, 0.1, 1.0]),
    step=st.sampled_from([0.000001, 0.001, 0.01, 0.1, 1.0]),
    side=st.sampled_from(["buy", "sell"]),
    order_type=st.sampled_from(["market", "limit", "stop_market", "stop_limit"]),
)
def test_python_rust_quantization_vectors_exact_match(price, qty, tick, step, side, order_type):
    import _quantbt_native

    side_code = 1 if side == "buy" else -1
    order_code = {"market": 0, "limit": 1, "stop_market": 2, "stop_limit": 3}[order_type]
    python = quantize_order_value(
        side=side, order_type=order_type, price=price, qty=qty,
        tick_size=tick, qty_step=step,
    )
    rust_price, rust_qty, rust_ticks, rust_lots, rust_reject = _quantbt_native.quantize_order_value_v1(
        price, qty, tick, step, side_code, order_code, 0.0, 0.0, 0.0, 1.0,
    )
    assert rust_ticks == python.price_ticks
    assert rust_lots == python.qty_lots
    assert rust_price == python.price
    assert rust_qty == python.qty
    assert rust_reject == int(python.reject_code)
