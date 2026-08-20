"""Content-addressed preparation for the experimental ABI-0.5 Rust boundary.

This module is intentionally a preparation-side helper rather than a public
endpoint.  It owns no account, order, fill, or result state: native execution
remains inside ``NativeExecutionRunnerCore``.  Its only job is to reuse
immutable market/template/request handles safely across static, strategy-IR,
fold, and service-loop workloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from threading import RLock
from typing import Any, Optional, Sequence

import numpy as np

from .cache import CachePolicy, PreparedObjectCache


_PREPARATION_SCHEMA = "native-execution-preparation-v1"
_MARKET_SCHEMA = "native-prepared-market-v1"
_TEMPLATE_SCHEMA = "native-execution-template-v1"
_REQUEST_SCHEMA = "native-execution-request-cache-v1"


def _digest(namespace: str, *parts: object) -> str:
    """Hash exact normalized content; never use Python object identity."""

    digest = hashlib.sha256()
    digest.update(namespace.encode("ascii"))
    for part in parts:
        if isinstance(part, np.ndarray):
            array = np.ascontiguousarray(part)
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(str(array.shape).encode("ascii"))
            digest.update(array.tobytes())
            continue
        digest.update(
            json.dumps(part, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        )
    return digest.hexdigest()


def _normalise_array(
    value: object,
    *,
    dtype: np.dtype,
    ndim: int,
    name: str,
) -> tuple[np.ndarray, int, int]:
    """Return an exact contiguous input and observable ingress-copy stats."""

    raw = np.asarray(value)
    result = np.ascontiguousarray(raw, dtype=dtype)
    if result.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    copied = int(
        not isinstance(value, np.ndarray)
        or raw.dtype != np.dtype(dtype)
        or not raw.flags.c_contiguous
    )
    return result, copied, int(result.nbytes) if copied else 0


def _normalise_market(
    *,
    timestamps_ns: object,
    opens: object,
    highs: object,
    lows: object,
    closes: object,
    volumes: object,
    funding: object,
    funding_mask: object,
) -> tuple[tuple[np.ndarray, ...], int, int]:
    fields = (
        ("timestamps_ns", timestamps_ns, np.dtype(np.int64), 1),
        ("opens", opens, np.dtype(np.float64), 2),
        ("highs", highs, np.dtype(np.float64), 2),
        ("lows", lows, np.dtype(np.float64), 2),
        ("closes", closes, np.dtype(np.float64), 2),
        ("volumes", volumes, np.dtype(np.float64), 2),
        ("funding", funding, np.dtype(np.float64), 2),
        ("funding_mask", funding_mask, np.dtype(np.bool_), 1),
    )
    arrays: list[np.ndarray] = []
    copies = 0
    copied_bytes = 0
    for name, value, dtype, ndim in fields:
        array, count, byte_count = _normalise_array(value, dtype=dtype, ndim=ndim, name=name)
        arrays.append(array)
        copies += count
        copied_bytes += byte_count

    timestamps, *ohlcvf, mask = arrays
    closes_array = ohlcvf[3]
    if len(timestamps) == 0:
        raise ValueError("prepared native market requires at least one bar")
    if closes_array.shape[0] != len(timestamps):
        raise ValueError("timestamps_ns length must match market bar count")
    if mask.shape != (len(timestamps),):
        raise ValueError("funding_mask must have one value per market bar")
    if any(array.shape != closes_array.shape for array in ohlcvf):
        raise ValueError("OHLCV/funding arrays must share shape (n_bars, n_symbols)")
    if closes_array.shape[1] == 0:
        raise ValueError("prepared native market requires at least one symbol")
    return tuple(arrays), copies, copied_bytes


def _tier_policy(policy: CachePolicy, numerator: int, denominator: int = 100) -> CachePolicy:
    return CachePolicy(
        max_bytes=(int(policy.max_bytes) * numerator) // denominator,
        max_entries=int(policy.max_entries),
        eviction=policy.eviction,
        pin_during_run=policy.pin_during_run,
        weak_result_owners=policy.weak_result_owners,
    )


@dataclass(frozen=True, slots=True)
class NativePreparedMarket:
    """One immutable Rust market owner and its complete content signature."""

    core: Any
    signature: str
    symbols: tuple[str, ...]
    prepared_bytes: int
    ingress_copy_count: int
    ingress_copied_bytes: int


@dataclass(frozen=True, slots=True)
class NativePreparedTemplate:
    """Output-independent native market/instrument/account preparation."""

    core: Any
    market: NativePreparedMarket
    signature: str
    model_bytes: int


@dataclass(frozen=True, slots=True)
class NativePreparedRequest:
    """Immutable workload request whose execution state is always separate."""

    core: Any
    template: NativePreparedTemplate
    signature: str
    workload: str
    request_bytes: int


class NativeExecutionPreparationCache:
    """Bounded L2-L4 cache for typed native execution handles.

    The tiers are deliberately budgeted independently: market (60%), template
    (15%), and immutable request tape (25%).  The total direct cache budget is
    therefore bounded by ``CachePolicy.max_bytes``. External Python references
    may outlive eviction by design, but typed output arrays never retain a
    cache entry or native session.
    """

    def __init__(
        self,
        policy: CachePolicy = CachePolicy(),
        *,
        module: Optional[Any] = None,
    ) -> None:
        self.policy = policy
        self._module = module
        self._lock = RLock()
        self._market_cache = PreparedObjectCache(_tier_policy(policy, 60))
        self._template_cache = PreparedObjectCache(_tier_policy(policy, 15))
        self._request_cache = PreparedObjectCache(_tier_policy(policy, 25))
        self._generation = 0
        self._ingress_copy_count = 0
        self._ingress_copied_bytes = 0

    def _native(self) -> Any:
        if self._module is None:
            self._module = importlib.import_module("_quantbt_native")
        required = (
            "FullPreparedMarketCore",
            "NativeExecutionTemplateCore",
            "NativeExecutionRequestCore",
        )
        missing = [name for name in required if not hasattr(self._module, name)]
        if missing:
            raise RuntimeError(
                "installed quantbt-native extension lacks ABI-0.5 prepared execution handles: "
                + ", ".join(missing)
            )
        return self._module

    @staticmethod
    def _symbols(symbols: Optional[Sequence[str]], n_symbols: int) -> tuple[str, ...]:
        resolved = tuple(str(symbol) for symbol in (symbols or tuple(str(index) for index in range(n_symbols))))
        if len(resolved) != n_symbols or len(set(resolved)) != n_symbols:
            raise ValueError("symbols must be unique and match the native market column count")
        return resolved

    def prepare_market(
        self,
        *,
        timestamps_ns: object,
        opens: object,
        highs: object,
        lows: object,
        closes: object,
        volumes: object,
        funding: object,
        funding_mask: object,
        symbols: Optional[Sequence[str]] = None,
    ) -> NativePreparedMarket:
        """Prepare/reuse an L2 market owner keyed by all result-affecting data."""

        arrays, copies, copied_bytes = _normalise_market(
            timestamps_ns=timestamps_ns,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            funding=funding,
            funding_mask=funding_mask,
        )
        timestamps, open_array, high_array, low_array, close_array, volume_array, funding_array, mask = arrays
        resolved_symbols = self._symbols(symbols, close_array.shape[1])
        signature = _digest(
            _MARKET_SCHEMA,
            _PREPARATION_SCHEMA,
            resolved_symbols,
            timestamps,
            open_array,
            high_array,
            low_array,
            close_array,
            volume_array,
            funding_array,
            mask,
        )
        key = (_MARKET_SCHEMA, signature)
        with self._lock:
            cached = self._market_cache.get(key)
            if cached is not None:
                return cached
            native = self._native()
            core = native.FullPreparedMarketCore(
                timestamps,
                open_array,
                high_array,
                low_array,
                close_array,
                volume_array,
                funding_array,
                mask,
            )
            record = NativePreparedMarket(
                core=core,
                signature=signature,
                symbols=resolved_symbols,
                prepared_bytes=int(getattr(core, "prepared_bytes", sum(array.nbytes for array in arrays))),
                ingress_copy_count=copies,
                ingress_copied_bytes=copied_bytes,
            )
            self._market_cache.put(key, record, size_bytes=record.prepared_bytes)
            self._ingress_copy_count += copies
            self._ingress_copied_bytes += copied_bytes
            return record

    def prepare_template(
        self,
        market: NativePreparedMarket,
        *,
        contract_sizes: object,
        leverages: object,
        fee_rates: object,
        initial_capital: float,
        maintenance_ratio: float,
        slippage_rate: float,
        use_funding: bool,
        event_contract_code: int = 2,
    ) -> NativePreparedTemplate:
        """Prepare/reuse an output-independent L3 native template."""

        arrays: list[np.ndarray] = []
        copies = 0
        copied_bytes = 0
        for name, value in (
            ("contract_sizes", contract_sizes),
            ("leverages", leverages),
            ("fee_rates", fee_rates),
        ):
            array, count, byte_count = _normalise_array(
                value,
                dtype=np.dtype(np.float64),
                ndim=1,
                name=name,
            )
            if len(array) != len(market.symbols):
                raise ValueError(f"{name} length must match prepared market symbols")
            arrays.append(array)
            copies += count
            copied_bytes += byte_count
        contract_size_array, leverage_array, fee_rate_array = arrays
        signature = _digest(
            _TEMPLATE_SCHEMA,
            _PREPARATION_SCHEMA,
            market.signature,
            contract_size_array,
            leverage_array,
            fee_rate_array,
            float(initial_capital),
            float(maintenance_ratio),
            float(slippage_rate),
            bool(use_funding),
            int(event_contract_code),
        )
        key = (_TEMPLATE_SCHEMA, signature)
        with self._lock:
            cached = self._template_cache.get(key)
            if cached is not None:
                return cached
            native = self._native()
            core = native.NativeExecutionTemplateCore.from_prepared(
                market.core,
                contract_size_array,
                leverage_array,
                fee_rate_array,
                float(initial_capital),
                float(maintenance_ratio),
                float(slippage_rate),
                bool(use_funding),
                event_contract_code=int(event_contract_code),
            )
            record = NativePreparedTemplate(
                core=core,
                market=market,
                signature=str(core.fingerprint),
                model_bytes=int(sum(array.nbytes for array in arrays)),
            )
            self._template_cache.put(key, record, size_bytes=record.model_bytes)
            self._ingress_copy_count += copies
            self._ingress_copied_bytes += copied_bytes
            return record

    def window_template(
        self,
        template: NativePreparedTemplate,
        *,
        start: int,
        end: int,
    ) -> NativePreparedTemplate:
        """Return/reuse a zero-copy local market window for one causal fold."""

        start = int(start)
        end = int(end)
        key = ("native-execution-template-window-v1", template.signature, str(start), str(end))
        with self._lock:
            cached = self._template_cache.get(key)
            if cached is not None:
                return cached
            core = template.core.window(start, end)
            record = NativePreparedTemplate(
                core=core,
                market=template.market,
                signature=str(core.fingerprint),
                model_bytes=0,
            )
            self._template_cache.put(key, record, size_bytes=0)
            return record

    def command_request(
        self,
        template: NativePreparedTemplate,
        *,
        command_ptr: object,
        command_codes: object,
        command_values: object,
        command_expiry: object,
        output_profile: int = 0,
    ) -> NativePreparedRequest:
        """Prepare/reuse an L4 static command request with no mutable state."""

        ptr, ptr_copies, ptr_bytes = _normalise_array(
            command_ptr, dtype=np.dtype(np.int64), ndim=1, name="command_ptr"
        )
        codes, codes_copies, codes_bytes = _normalise_array(
            command_codes, dtype=np.dtype(np.int64), ndim=2, name="command_codes"
        )
        values, values_copies, values_bytes = _normalise_array(
            command_values, dtype=np.dtype(np.float64), ndim=2, name="command_values"
        )
        expiry, expiry_copies, expiry_bytes = _normalise_array(
            command_expiry, dtype=np.dtype(np.int64), ndim=1, name="command_expiry"
        )
        if len(ptr) != int(template.core.bars) + 1:
            raise ValueError("command_ptr length must equal template bars + 1")
        signature = _digest(
            _REQUEST_SCHEMA,
            _PREPARATION_SCHEMA,
            template.signature,
            "command_tape_v5",
            int(output_profile),
            ptr,
            codes,
            values,
            expiry,
        )
        key = (_REQUEST_SCHEMA, signature)
        with self._lock:
            cached = self._request_cache.get(key)
            if cached is not None:
                return cached
            native = self._native()
            core = native.NativeExecutionRequestCore.from_template_command_tape(
                template.core,
                ptr,
                codes,
                values,
                expiry,
                output_profile=int(output_profile),
            )
            request_bytes = int(ptr.nbytes + codes.nbytes + values.nbytes + expiry.nbytes)
            record = NativePreparedRequest(
                core=core,
                template=template,
                signature=str(core.fingerprint),
                workload="command_tape_v5",
                request_bytes=request_bytes,
            )
            self._request_cache.put(key, record, size_bytes=request_bytes)
            self._ingress_copy_count += ptr_copies + codes_copies + values_copies + expiry_copies
            self._ingress_copied_bytes += ptr_bytes + codes_bytes + values_bytes + expiry_bytes
            return record

    def strategy_ir_request(
        self,
        template: NativePreparedTemplate,
        *,
        program: Any,
        signal: object,
        parameters: object | None = None,
        output_profile: int = 0,
    ) -> NativePreparedRequest:
        """Prepare/reuse a native strategy-IR request over the same template."""

        signal_array, signal_copies, signal_bytes = _normalise_array(
            signal, dtype=np.dtype(np.float64), ndim=1, name="signal"
        )
        if len(signal_array) != int(template.core.bars):
            raise ValueError("signal length must match template bars")
        parameter_array: np.ndarray | None = None
        parameter_copies = 0
        parameter_bytes = 0
        if parameters is not None:
            parameter_array, parameter_copies, parameter_bytes = _normalise_array(
                parameters,
                dtype=np.dtype(np.float64),
                ndim=1,
                name="parameters",
            )
        program_fingerprint = str(getattr(program, "fingerprint", ""))
        if not program_fingerprint:
            raise ValueError("strategy IR program must expose a stable fingerprint")
        signature = _digest(
            _REQUEST_SCHEMA,
            _PREPARATION_SCHEMA,
            template.signature,
            "strategy_ir_v1",
            program_fingerprint,
            int(output_profile),
            signal_array,
            parameter_array if parameter_array is not None else ("no-parameters",),
        )
        key = (_REQUEST_SCHEMA, signature)
        with self._lock:
            cached = self._request_cache.get(key)
            if cached is not None:
                return cached
            native = self._native()
            core = native.NativeExecutionRequestCore.from_template_strategy_ir(
                template.core,
                program,
                signal_array,
                parameters=parameter_array,
                output_profile=int(output_profile),
            )
            request_bytes = int(signal_array.nbytes + (0 if parameter_array is None else parameter_array.nbytes))
            record = NativePreparedRequest(
                core=core,
                template=template,
                signature=str(core.fingerprint),
                workload="strategy_ir_v1",
                request_bytes=request_bytes,
            )
            self._request_cache.put(key, record, size_bytes=request_bytes)
            self._ingress_copy_count += signal_copies + parameter_copies
            self._ingress_copied_bytes += signal_bytes + parameter_bytes
            return record

    def new_runner(self, request: NativePreparedRequest) -> Any:
        """Create a fresh mutable runner from one immutable cached request."""

        return request.core.new_runner()

    def clear(self, *, force: bool = False) -> dict[str, object]:
        """Clear cache-owned references without invalidating detached outputs."""

        with self._lock:
            released = {
                "requests": self._request_cache.clear(force=force),
                "templates": self._template_cache.clear(force=force),
                "markets": self._market_cache.clear(force=force),
            }
            self._generation += 1
            return {"generation": self._generation, "released": released}

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return cold-path cache/boundary diagnostics with tier budgets."""

        with self._lock:
            market = self._market_cache.diagnostics
            template = self._template_cache.diagnostics
            request = self._request_cache.diagnostics
            return {
                "schema": _PREPARATION_SCHEMA,
                "generation": int(self._generation),
                "cache_hit": int(market["cache_hit"] + template["cache_hit"] + request["cache_hit"]),
                "cache_miss": int(market["cache_miss"] + template["cache_miss"] + request["cache_miss"]),
                "resident_bytes": int(market["resident_bytes"] + template["resident_bytes"] + request["resident_bytes"]),
                "entry_count": int(market["entry_count"] + template["entry_count"] + request["entry_count"]),
                "eviction_count": int(market["eviction_count"] + template["eviction_count"] + request["eviction_count"]),
                "reuse_count": int(market["reuse_count"] + template["reuse_count"] + request["reuse_count"]),
                "ingress_copy_count": int(self._ingress_copy_count),
                "ingress_copied_bytes": int(self._ingress_copied_bytes),
                "tier_budgets": {
                    "market": int(self._market_cache.policy.max_bytes),
                    "template": int(self._template_cache.policy.max_bytes),
                    "request": int(self._request_cache.policy.max_bytes),
                },
                "tiers": {"market": market, "template": template, "request": request},
            }


__all__ = [
    "NativeExecutionPreparationCache",
    "NativePreparedMarket",
    "NativePreparedRequest",
    "NativePreparedTemplate",
]
