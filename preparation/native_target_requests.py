"""Typed direct-target request builders for the prepared native cache.

This module owns normalization and immutable request construction for the two
close-target Rust workloads.  ``NativeExecutionPreparationCache`` remains the
sole owner of cache tiers, native handles, and ingress diagnostics; these
helpers deliberately receive that cache rather than introducing a second
cache or execution state machine.
"""

from __future__ import annotations

from typing import Any

import numpy as np


_DIRECT_TARGET_KIND_CODES = {
    "units": 0,
    "target_units": 0,
    "notional": 1,
    "target_notional": 1,
    "weight": 2,
    "target_weight": 2,
    "equity_fraction": 3,
    # Historical direct-request spelling remains the per-bar fraction route;
    # the legacy endpoint contract is deliberately explicit below.
    "pct_equity": 3,
    "pct_equity_transition": 4,
    "legacy_pct_equity_transition": 4,
}
_DIRECT_TARGET_TIMING_CODES = {
    "close_target_v2_same_close": 0,
    "close_target_v2": 0,
    "same_close": 0,
    "next_open_v1": 1,
    "next_open": 1,
    "event_lifecycle_v3_next_open": 1,
    "next_close": 2,
    "event_lifecycle_v2_next_bar_close": 2,
}
_DIRECT_TARGET_INVALID_POLICY_CODES = {
    "reject_run": 0,
    "hold_prior": 1,
    "flatten": 2,
    "skip_bar": 3,
}
_SHARED_PORTFOLIO_ADMISSION_POLICY_CODES = {
    "sequential_legacy": 0,
    "sequential": 0,
    "reduce_first_then_increase": 1,
    "reduce_first": 1,
    "pro_rata_to_available_margin": 2,
    "pro_rata": 2,
    "all_or_none_rebalance": 3,
    "all_or_none": 3,
}


def _resolve_code(value: object, codes: dict[str, int], *, name: str) -> int:
    if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
        code = int(value)
        if code in codes.values():
            return code
    else:
        code = codes.get(str(value).strip().lower())
        if code is not None:
            return int(code)
    supported = ", ".join(sorted(codes))
    raise ValueError(f"unsupported native direct target {name}={value!r}; supported: {supported}")


def _build_target_request(
    cache: Any,
    template: Any,
    *,
    targets: object,
    target_kind: str | int,
    timing: str | int,
    invalid_target_policy: str | int,
    tradable: object | None,
    stale: object | None,
    qty_step: object | None,
    min_qty: object | None,
    min_notional: object | None,
    equity_fraction: object | None,
    output_profile: int,
    admission_policy: str | int | None,
):
    """Build one cached target request without owning any cache state.

    The import is intentionally deferred: ``native_execution`` imports these
    helpers to expose stable cache methods, while this builder needs its
    immutable record type and canonical normalization/signature utilities.
    Calls happen after that module has finished initialization, avoiding a
    module-init cycle while retaining one implementation of those contracts.
    """

    from .native_execution import (  # Local import preserves one cache authority.
        NativePreparedRequest,
        _PREPARATION_SCHEMA,
        _REQUEST_SCHEMA,
        _digest,
        _normalise_array,
    )

    target_array, target_copies, target_bytes = _normalise_array(
        targets, dtype=np.dtype(np.float64), ndim=2, name="targets"
    )
    expected_shape = (int(template.core.bars), int(template.core.symbols))
    if target_array.shape != expected_shape:
        prefix = "shared portfolio" if admission_policy is not None else "native direct"
        raise ValueError(f"{prefix} target values must match template bars and symbols")

    def matrix_or_default(value: object | None, *, default: bool, name: str):
        if value is None:
            return np.full(expected_shape, default, dtype=np.bool_), 0, 0
        return _normalise_array(value, dtype=np.dtype(np.bool_), ndim=2, name=name)

    def vector_or_default(value: object | None, *, default: float, name: str):
        if value is None:
            return np.full(expected_shape[1], default, dtype=np.float64), 0, 0
        array, copies, copied_bytes = _normalise_array(
            value, dtype=np.dtype(np.float64), ndim=1, name=name
        )
        if array.shape != (expected_shape[1],):
            raise ValueError(f"{name} length must match native direct target symbols")
        return array, copies, copied_bytes

    tradable_array, tradable_copies, tradable_bytes = matrix_or_default(
        tradable, default=True, name="tradable"
    )
    stale_array, stale_copies, stale_bytes = matrix_or_default(
        stale, default=False, name="stale"
    )
    if tradable_array.shape != expected_shape or stale_array.shape != expected_shape:
        raise ValueError("native direct target tradable/stale masks must match target shape")
    qty_step_array, qty_step_copies, qty_step_bytes = vector_or_default(
        qty_step, default=0.0, name="qty_step"
    )
    min_qty_array, min_qty_copies, min_qty_bytes = vector_or_default(
        min_qty, default=0.0, name="min_qty"
    )
    min_notional_array, min_notional_copies, min_notional_bytes = vector_or_default(
        min_notional, default=0.0, name="min_notional"
    )
    equity_fraction_array, equity_fraction_copies, equity_fraction_bytes = vector_or_default(
        equity_fraction, default=1.0, name="equity_fraction"
    )
    kind_code = _resolve_code(target_kind, _DIRECT_TARGET_KIND_CODES, name="target_kind")
    timing_code = _resolve_code(timing, _DIRECT_TARGET_TIMING_CODES, name="timing")
    if timing_code != 0:
        route = "shared portfolio target" if admission_policy is not None else "native direct target"
        raise NotImplementedError(
            f"{route} certifies only 'close_target_v2_same_close'; "
            "next-open and next-close target clocks remain separate, unpromoted contracts"
        )
    invalid_code = _resolve_code(
        invalid_target_policy,
        _DIRECT_TARGET_INVALID_POLICY_CODES,
        name="invalid_target_policy",
    )
    admission_code = None
    if admission_policy is not None:
        admission_code = _resolve_code(
            admission_policy,
            _SHARED_PORTFOLIO_ADMISSION_POLICY_CODES,
            name="admission_policy",
        )
    profile = int(output_profile)
    if profile not in {0, 1, 2}:
        raise ValueError("native direct target output_profile must be 0 (score), 1 (compact), or 2 (audit)")

    workload = "shared_portfolio_target_v1" if admission_code is not None else "direct_target_v1"
    signature = _digest(
        _REQUEST_SCHEMA,
        _PREPARATION_SCHEMA,
        template.signature,
        workload,
        kind_code,
        admission_code,
        timing_code,
        invalid_code,
        profile,
        target_array,
        tradable_array,
        stale_array,
        qty_step_array,
        min_qty_array,
        min_notional_array,
        equity_fraction_array,
    )
    key = (_REQUEST_SCHEMA, signature)
    with cache._lock:
        cached = cache._request_cache.get(key)
        if cached is not None:
            return cached
        native = cache._native()
        if admission_code is None:
            if not hasattr(native, "NativeTargetExecutionRequestCore"):
                raise RuntimeError(
                    "installed quantbt-native extension lacks NativeTargetExecutionRequestCore; "
                    "install a wheel that supports direct target execution"
                )
            core = native.NativeTargetExecutionRequestCore.from_template(
                template.core,
                target_array,
                target_kind=kind_code,
                timing=timing_code,
                invalid_target_policy=invalid_code,
                tradable=tradable_array,
                stale=stale_array,
                qty_step=qty_step_array,
                min_qty=min_qty_array,
                min_notional=min_notional_array,
                equity_fraction=equity_fraction_array,
                output_profile=profile,
            )
        else:
            if not hasattr(native, "NativeSharedPortfolioTargetRequestCore"):
                raise RuntimeError(
                    "installed quantbt-native extension lacks NativeSharedPortfolioTargetRequestCore; "
                    "install a wheel that supports Rust shared-account portfolio targets"
                )
            core = native.NativeSharedPortfolioTargetRequestCore.from_template(
                template.core,
                target_array,
                target_kind=kind_code,
                admission_policy=admission_code,
                timing=timing_code,
                invalid_target_policy=invalid_code,
                tradable=tradable_array,
                stale=stale_array,
                qty_step=qty_step_array,
                min_qty=min_qty_array,
                min_notional=min_notional_array,
                equity_fraction=equity_fraction_array,
                output_profile=profile,
            )
        request_bytes = int(
            target_array.nbytes
            + tradable_array.nbytes
            + stale_array.nbytes
            + qty_step_array.nbytes
            + min_qty_array.nbytes
            + min_notional_array.nbytes
            + equity_fraction_array.nbytes
        )
        record = NativePreparedRequest(
            core=core,
            template=template,
            signature=str(core.fingerprint),
            workload=workload,
            request_bytes=request_bytes,
            market_signature=template.market.signature,
        )
        cache._request_cache.put(key, record, size_bytes=request_bytes)
        cache._ingress_copy_count += (
            target_copies
            + tradable_copies
            + stale_copies
            + qty_step_copies
            + min_qty_copies
            + min_notional_copies
            + equity_fraction_copies
        )
        cache._ingress_copied_bytes += (
            target_bytes
            + tradable_bytes
            + stale_bytes
            + qty_step_bytes
            + min_qty_bytes
            + min_notional_bytes
            + equity_fraction_bytes
        )
        return record


def prepare_direct_target_request(cache: Any, template: Any, **kwargs: object):
    """Prepare/reuse a direct target request through the owning cache."""

    return _build_target_request(cache, template, admission_policy=None, **kwargs)


def prepare_shared_portfolio_target_request(
    cache: Any,
    template: Any,
    *,
    admission_policy: str | int = "sequential_legacy",
    **kwargs: object,
):
    """Prepare/reuse a shared-account target request through the owning cache."""

    return _build_target_request(cache, template, admission_policy=admission_policy, **kwargs)


__all__ = ["prepare_direct_target_request", "prepare_shared_portfolio_target_request"]
