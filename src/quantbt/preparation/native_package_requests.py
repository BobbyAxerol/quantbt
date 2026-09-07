"""Typed bounded-package request builders for the prepared native cache.

The functions here own only array normalization, content signatures, and the
immutable V2 request boundary.  ``NativeExecutionPreparationCache`` remains
the sole owner of cache tiers and immutable market/template handles; Rust's
``FullSession`` remains the sole owner of account/order/fill state.
"""

from __future__ import annotations

from typing import Any

import numpy as np


_EXECUTION_POLICY_CODES = {
    "atomic_bar_simulation": 0,
    "atomic": 0,
    "sequential": 1,
    "best_effort": 2,
    "hedge_after_primary": 3,
}
_RESIDUAL_POLICY_CODES = {
    "record": 0,
    "unwind_package": 1,
    "unwind": 1,
}
_QUANTITY_SOURCE_CODES = {
    "fixed": 0,
    "proportion_of_requested": 1,
    "proportion_of_actual_fill": 2,
    "consume_previous_output": 3,
}
_PACKAGE_FIELD_NAMES = (
    "command_bars",
    "package_ids",
    "package_leg_offsets",
    "execution_policies",
    "residual_policies",
    "max_staleness_ns",
    "order_ids",
    "symbol_ids",
    "signed_qty",
    "quantity_sources",
    "source_legs",
    "quantity_ratios",
    "fill_fractions",
    "qty_step",
    "min_qty",
    "min_notional",
    "source_age_ns",
    "venue_codes",
    "venue_sequence",
)


def _code_array(value: object, *, codes: dict[str, int], name: str) -> object:
    """Resolve a scalar/string vector to its compact typed ABI code array."""

    raw = np.asarray(value)
    if raw.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if raw.dtype.kind in {"U", "S", "O"}:
        resolved = []
        for item in raw.tolist():
            key = str(item).strip().lower()
            if key not in codes:
                supported = ", ".join(sorted(codes))
                raise ValueError(f"unsupported native package {name}={item!r}; supported: {supported}")
            resolved.append(codes[key])
        return np.asarray(resolved, dtype=np.uint8)
    numeric = np.asarray(raw, dtype=np.int64)
    if np.any((numeric < 0) | (numeric > max(codes.values()))):
        raise ValueError(f"native package {name} contains an unsupported code")
    return np.asarray(numeric, dtype=np.uint8)


def _unsigned_input(value: object, *, name: str) -> object:
    raw = np.asarray(value)
    if raw.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if raw.dtype.kind in {"i", "f"} and np.any(raw < 0):
        raise ValueError(f"{name} cannot contain negative values")
    return value


def _normalise_package_market_v2_arrays(
    *,
    command_bars: object,
    package_ids: object,
    package_leg_offsets: object,
    execution_policies: object,
    residual_policies: object,
    max_staleness_ns: object,
    order_ids: object,
    symbol_ids: object,
    signed_qty: object,
    quantity_sources: object,
    source_legs: object,
    quantity_ratios: object,
    fill_fractions: object,
    qty_step: object,
    min_qty: object,
    min_notional: object,
    source_age_ns: object,
    venue_codes: object,
    venue_sequence: object,
) -> tuple[dict[str, np.ndarray], int, int]:
    """Normalize and validate the immutable V2 package tape once.

    Both one-package-request and native scenario-batch ingress call this
    function.  Keeping their field conversion and cache signature material in
    one place prevents a batch from accepting a tape the single-run authority
    would reject.
    """

    from .native_execution import _normalise_array  # noqa: PLC0415

    execution_policies = _code_array(
        execution_policies, codes=_EXECUTION_POLICY_CODES, name="execution_policies"
    )
    residual_policies = _code_array(
        residual_policies, codes=_RESIDUAL_POLICY_CODES, name="residual_policies"
    )
    quantity_sources = _code_array(
        quantity_sources, codes=_QUANTITY_SOURCE_CODES, name="quantity_sources"
    )
    fields = (
        ("command_bars", _unsigned_input(command_bars, name="command_bars"), np.dtype(np.uint64)),
        ("package_ids", _unsigned_input(package_ids, name="package_ids"), np.dtype(np.uint64)),
        (
            "package_leg_offsets",
            _unsigned_input(package_leg_offsets, name="package_leg_offsets"),
            np.dtype(np.uint64),
        ),
        ("execution_policies", execution_policies, np.dtype(np.uint8)),
        ("residual_policies", residual_policies, np.dtype(np.uint8)),
        ("max_staleness_ns", max_staleness_ns, np.dtype(np.int64)),
        ("order_ids", order_ids, np.dtype(np.int64)),
        ("symbol_ids", _unsigned_input(symbol_ids, name="symbol_ids"), np.dtype(np.uint32)),
        ("signed_qty", signed_qty, np.dtype(np.float64)),
        ("quantity_sources", quantity_sources, np.dtype(np.uint8)),
        ("source_legs", source_legs, np.dtype(np.int64)),
        ("quantity_ratios", quantity_ratios, np.dtype(np.float64)),
        ("fill_fractions", fill_fractions, np.dtype(np.float64)),
        ("qty_step", qty_step, np.dtype(np.float64)),
        ("min_qty", min_qty, np.dtype(np.float64)),
        ("min_notional", min_notional, np.dtype(np.float64)),
        ("source_age_ns", source_age_ns, np.dtype(np.int64)),
        ("venue_codes", _unsigned_input(venue_codes, name="venue_codes"), np.dtype(np.uint16)),
        (
            "venue_sequence",
            _unsigned_input(venue_sequence, name="venue_sequence"),
            np.dtype(np.uint32),
        ),
    )
    arrays: dict[str, np.ndarray] = {}
    copy_count = 0
    copied_bytes = 0
    for name, value, dtype in fields:
        array, copied, byte_count = _normalise_array(value, dtype=dtype, ndim=1, name=name)
        arrays[name] = array
        copy_count += copied
        copied_bytes += byte_count

    package_count = len(arrays["package_ids"])
    if (
        package_count == 0
        or any(
            len(arrays[name]) != package_count
            for name in ("command_bars", "execution_policies", "residual_policies", "max_staleness_ns")
        )
        or len(arrays["package_leg_offsets"]) != package_count + 1
        or arrays["package_leg_offsets"][0] != 0
    ):
        raise ValueError("native package V2 package arrays have an invalid shape")
    leg_count = len(arrays["order_ids"])
    if (
        arrays["package_leg_offsets"][-1] != leg_count
        or np.any(np.diff(arrays["package_leg_offsets"]) <= 0)
        or any(
            len(arrays[name]) != leg_count
            for name in (
                "symbol_ids",
                "signed_qty",
                "quantity_sources",
                "source_legs",
                "quantity_ratios",
                "fill_fractions",
                "qty_step",
                "min_qty",
                "min_notional",
                "source_age_ns",
                "venue_codes",
                "venue_sequence",
            )
        )
    ):
        raise ValueError("native package V2 leg arrays must match declared package offsets")
    if np.any(arrays["order_ids"] < 0) or len(np.unique(arrays["order_ids"])) != leg_count:
        raise ValueError("native package V2 order_ids must be unique non-negative values")
    if len(np.unique(arrays["package_ids"])) != package_count:
        raise ValueError("native package V2 package_ids must be unique")
    if np.any(arrays["package_ids"] > np.uint64(np.iinfo(np.int64).max)):
        raise ValueError("native package V2 package_ids must fit canonical group IDs")
    return arrays, copy_count, copied_bytes


def prepare_package_market_v2_request(
    cache: Any,
    template: Any,
    *,
    command_bars: object,
    package_ids: object,
    package_leg_offsets: object,
    execution_policies: object,
    residual_policies: object,
    max_staleness_ns: object,
    order_ids: object,
    symbol_ids: object,
    signed_qty: object,
    quantity_sources: object,
    source_legs: object,
    quantity_ratios: object,
    fill_fractions: object,
    qty_step: object,
    min_qty: object,
    min_notional: object,
    source_age_ns: object,
    venue_codes: object,
    venue_sequence: object,
    output_profile: int = 2,
):
    """Prepare/reuse a bounded package V2 request over one native template.

    A package is represented by one row in the package arrays and a contiguous
    leg range in ``package_leg_offsets``.  This is intentionally a narrow
    same-account linear contract.  Cross-venue/currency flow and generic
    arbitrage planning must stay above this request boundary.
    """

    # Deferred import keeps one cache authority without a module-init cycle.
    from .native_execution import (  # noqa: PLC0415
        NativePreparedRequest,
        _PREPARATION_SCHEMA,
        _REQUEST_SCHEMA,
        _digest,
    )

    arrays, copy_count, copied_bytes = _normalise_package_market_v2_arrays(
        command_bars=command_bars,
        package_ids=package_ids,
        package_leg_offsets=package_leg_offsets,
        execution_policies=execution_policies,
        residual_policies=residual_policies,
        max_staleness_ns=max_staleness_ns,
        order_ids=order_ids,
        symbol_ids=symbol_ids,
        signed_qty=signed_qty,
        quantity_sources=quantity_sources,
        source_legs=source_legs,
        quantity_ratios=quantity_ratios,
        fill_fractions=fill_fractions,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
        source_age_ns=source_age_ns,
        venue_codes=venue_codes,
        venue_sequence=venue_sequence,
    )
    if int(output_profile) not in {0, 1, 2}:
        raise ValueError("native package output_profile must be 0 (score), 1 (compact), or 2 (audit)")

    signature = _digest(
        _REQUEST_SCHEMA,
        _PREPARATION_SCHEMA,
        template.signature,
        "package_market_v2",
        int(output_profile),
        *(arrays[name] for name in _PACKAGE_FIELD_NAMES),
    )
    key = (_REQUEST_SCHEMA, signature)
    with cache._lock:
        cached = cache._request_cache.get(key)
        if cached is not None:
            return cached
        native = cache._native()
        core_type = getattr(native, "NativeExecutionRequestCore", None)
        if core_type is None or not hasattr(core_type, "from_template_package_market_v2"):
            raise RuntimeError(
                "installed quantbt-native extension lacks package_market_v2; "
                "install a wheel that supports bounded Rust package execution"
            )
        core = core_type.from_template_package_market_v2(
            template.core,
            command_bars=arrays["command_bars"],
            package_ids=arrays["package_ids"],
            package_leg_offsets=arrays["package_leg_offsets"],
            execution_policies=arrays["execution_policies"],
            residual_policies=arrays["residual_policies"],
            max_staleness_ns=arrays["max_staleness_ns"],
            order_ids=arrays["order_ids"],
            symbol_ids=arrays["symbol_ids"],
            signed_qty=arrays["signed_qty"],
            quantity_sources=arrays["quantity_sources"],
            source_legs=arrays["source_legs"],
            quantity_ratios=arrays["quantity_ratios"],
            fill_fractions=arrays["fill_fractions"],
            qty_step=arrays["qty_step"],
            min_qty=arrays["min_qty"],
            min_notional=arrays["min_notional"],
            source_age_ns=arrays["source_age_ns"],
            venue_codes=arrays["venue_codes"],
            venue_sequence=arrays["venue_sequence"],
            output_profile=int(output_profile),
        )
        request_bytes = int(sum(array.nbytes for array in arrays.values()))
        record = NativePreparedRequest(
            core=core,
            template=template,
            signature=str(core.fingerprint),
            workload="package_market_v2",
            request_bytes=request_bytes,
            market_signature=template.market.signature,
        )
        cache._request_cache.put(key, record, size_bytes=request_bytes)
        cache._ingress_copy_count += copy_count
        cache._ingress_copied_bytes += copied_bytes
        return record


def prepare_package_market_v2_scenario_batch(
    cache: Any,
    template: Any,
    *,
    scenario_package_offsets: object,
    command_bars: object,
    package_ids: object,
    package_leg_offsets: object,
    execution_policies: object,
    residual_policies: object,
    max_staleness_ns: object,
    order_ids: object,
    symbol_ids: object,
    signed_qty: object,
    quantity_sources: object,
    source_legs: object,
    quantity_ratios: object,
    fill_fractions: object,
    qty_step: object,
    min_qty: object,
    min_notional: object,
    source_age_ns: object,
    venue_codes: object,
    venue_sequence: object,
):
    """Prepare a one-boundary scalar batch of isolated package scenarios.

    ``scenario_package_offsets`` groups contiguous package rows into independent
    scenarios.  The batch shares only ``template``; Rust resets the shared
    session before every row, so account, position, order, and reservation
    state cannot leak between candidates or folds. Detailed audit remains a
    selected-scenario rerun through :func:`prepare_package_market_v2_request`.
    """

    from .native_execution import (  # noqa: PLC0415
        NativePreparedRequest,
        _PREPARATION_SCHEMA,
        _REQUEST_SCHEMA,
        _digest,
        _normalise_array,
    )

    arrays, copy_count, copied_bytes = _normalise_package_market_v2_arrays(
        command_bars=command_bars,
        package_ids=package_ids,
        package_leg_offsets=package_leg_offsets,
        execution_policies=execution_policies,
        residual_policies=residual_policies,
        max_staleness_ns=max_staleness_ns,
        order_ids=order_ids,
        symbol_ids=symbol_ids,
        signed_qty=signed_qty,
        quantity_sources=quantity_sources,
        source_legs=source_legs,
        quantity_ratios=quantity_ratios,
        fill_fractions=fill_fractions,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
        source_age_ns=source_age_ns,
        venue_codes=venue_codes,
        venue_sequence=venue_sequence,
    )
    scenario_offsets, copied, byte_count = _normalise_array(
        _unsigned_input(scenario_package_offsets, name="scenario_package_offsets"),
        dtype=np.dtype(np.uint64),
        ndim=1,
        name="scenario_package_offsets",
    )
    copy_count += copied
    copied_bytes += byte_count
    package_count = len(arrays["package_ids"])
    if (
        len(scenario_offsets) < 2
        or scenario_offsets[0] != 0
        or scenario_offsets[-1] != package_count
        or np.any(np.diff(scenario_offsets) <= 0)
    ):
        raise ValueError(
            "native package V2 scenario_package_offsets must select non-empty package ranges"
        )

    signature = _digest(
        _REQUEST_SCHEMA,
        _PREPARATION_SCHEMA,
        template.signature,
        "package_market_v2_scenario_batch",
        scenario_offsets,
        *(arrays[name] for name in _PACKAGE_FIELD_NAMES),
    )
    key = (_REQUEST_SCHEMA, signature)
    with cache._lock:
        cached = cache._request_cache.get(key)
        if cached is not None:
            return cached
        native = cache._native()
        core_type = getattr(native, "NativePackageScenarioBatchCore", None)
        if core_type is None or not hasattr(core_type, "from_template_v2"):
            raise RuntimeError(
                "installed quantbt-native extension lacks package_market_v2_scenario_batch; "
                "install a wheel that supports bounded Rust package scenario scoring"
            )
        core = core_type.from_template_v2(
            template.core,
            scenario_package_offsets=scenario_offsets,
            command_bars=arrays["command_bars"],
            package_ids=arrays["package_ids"],
            package_leg_offsets=arrays["package_leg_offsets"],
            execution_policies=arrays["execution_policies"],
            residual_policies=arrays["residual_policies"],
            max_staleness_ns=arrays["max_staleness_ns"],
            order_ids=arrays["order_ids"],
            symbol_ids=arrays["symbol_ids"],
            signed_qty=arrays["signed_qty"],
            quantity_sources=arrays["quantity_sources"],
            source_legs=arrays["source_legs"],
            quantity_ratios=arrays["quantity_ratios"],
            fill_fractions=arrays["fill_fractions"],
            qty_step=arrays["qty_step"],
            min_qty=arrays["min_qty"],
            min_notional=arrays["min_notional"],
            source_age_ns=arrays["source_age_ns"],
            venue_codes=arrays["venue_codes"],
            venue_sequence=arrays["venue_sequence"],
        )
        request_bytes = int(scenario_offsets.nbytes + sum(array.nbytes for array in arrays.values()))
        record = NativePreparedRequest(
            core=core,
            template=template,
            signature=signature,
            workload="package_market_v2_scenario_batch",
            request_bytes=request_bytes,
            market_signature=template.market.signature,
        )
        cache._request_cache.put(key, record, size_bytes=request_bytes)
        cache._ingress_copy_count += copy_count
        cache._ingress_copied_bytes += copied_bytes
        return record


__all__ = [
    "prepare_package_market_v2_request",
    "prepare_package_market_v2_scenario_batch",
]
