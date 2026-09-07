"""Optional W1/W2 strategy preparation for the public walk-forward facade.

The adapter deliberately owns only parameter-independent alpha preparation.
``WalkForwardEngine`` continues to own fold construction, Optuna sequencing,
candidate selection, and final stitched-account reconstruction.  The protocol
is opt-in because an arbitrary cached feature graph cannot be proven causal by
the engine: strict schedules require the strategy to explicitly declare the
causal cache contract before it is admitted.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import hashlib
import sys
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..core.wfo_contracts import derive_strategy_seed, isolated_strategy_instance, strategy_fingerprint


_POLICIES = frozenset({"off", "auto", "require"})
_ADAPTERS = frozenset({"auto", "w1", "w2"})
_STRICT_CAUSAL_CACHE_CONTRACT = "causal_parameter_independent_v1"


class PreparedWfoStrategyUnsupported(NotImplementedError):
    """An optional public W1/W2 strategy adapter cannot be admitted safely."""


@dataclass(slots=True)
class PreparedWfoStrategyAdapterV1:
    """Own one isolated prepared strategy instance for one WFO run.

    W1 emits one full-tape scalar signal for a candidate/fold.  W2 emits a
    ``(candidates, bars)`` batch; the normal public Optuna path preserves
    certified sequential ask/evaluate/tell, so its W2 invocation contains one
    candidate.  The explicit ``NativeWfoRuntimeV2`` remains the route for an
    opt-in throughput candidate matrix.
    """

    prepared: object
    adapter: str
    full_index: pd.DatetimeIndex
    lifecycle: AbstractContextManager
    lifecycle_record: dict[str, object]
    requested_policy: str
    cache_contract: str
    _stats: dict[str, object] = field(default_factory=dict)
    _closed: bool = False

    def generate(
        self,
        *,
        params: Mapping[str, Any],
        fold_id: int,
        expected_index: pd.DatetimeIndex,
        context: str,
    ) -> pd.Series:
        """Generate and project one full-tape signal without shifting it."""

        if self._closed:
            raise RuntimeError("prepared WFO strategy adapter is closed")
        if self.adapter == "w2":
            generated = self.prepared.generate_batch(
                params_matrix=(dict(params),),
                fold_id=int(fold_id),
            )
            values = _coerce_w2_signal(generated, bars=len(self.full_index))
            self._stats["w2_generate_batch_calls"] = int(self._stats["w2_generate_batch_calls"]) + 1
        else:
            generated = self.prepared.generate(params=dict(params), fold_id=int(fold_id))
            values = _coerce_w1_signal(generated, bars=len(self.full_index))
            self._stats["w1_generate_calls"] = int(self._stats["w1_generate_calls"]) + 1
        self._stats["generate_calls"] = int(self._stats["generate_calls"]) + 1
        contexts = self._stats["contexts"]
        assert isinstance(contexts, dict)
        contexts[str(context)] = int(contexts.get(str(context), 0)) + 1
        full = pd.Series(values, index=self.full_index, dtype=float)
        return full.reindex(expected_index)

    def metadata(self) -> dict[str, object]:
        """Return detached strategy preparation provenance."""

        return {
            "schema": "quantbt-prepared-wfo-strategy-v1",
            "requested_policy": self.requested_policy,
            "resolved_adapter": self.adapter,
            "cache_contract": self.cache_contract,
            "strategy_kind": f"{type(self.prepared).__module__}.{type(self.prepared).__qualname__}",
            "prepared_market_bars": int(len(self.full_index)),
            "closed": bool(self._closed),
            **dict(self._stats),
        }

    def close(self) -> None:
        """Close the isolated preparation lifetime exactly once."""

        if self._closed:
            return
        self.lifecycle.__exit__(None, None, None)
        self._closed = True


def prepare_public_wfo_strategy(
    *,
    strategy: object,
    data,
    datetime_index: pd.DatetimeIndex,
    folds: Sequence[object],
    config,
) -> tuple[PreparedWfoStrategyAdapterV1 | None, dict[str, object], dict[str, object] | None]:
    """Resolve and prepare the optional public W1/W2 strategy contract.

    ``auto`` falls back only when the strategy does not expose ``prepare_wfo``.
    Once a strategy opts into preparation, an invalid signature/output is a
    hard error: silently switching behavior after candidate generation would
    make an audit impossible.
    """

    metadata = dict(getattr(config, "metadata", {}) or {})
    policy = str(metadata.get("prepared_wfo_strategy", "off")).lower().strip()
    requested_adapter = str(metadata.get("prepared_wfo_strategy_adapter", "auto")).lower().strip()
    if policy not in _POLICIES:
        raise ValueError("prepared_wfo_strategy must be 'off', 'auto', or 'require'")
    if requested_adapter not in _ADAPTERS:
        raise ValueError("prepared_wfo_strategy_adapter must be 'auto', 'w1', or 'w2'")
    baseline = {
        "schema": "quantbt-prepared-wfo-strategy-v1",
        "requested_policy": policy,
        "requested_adapter": requested_adapter,
        "resolved_adapter": "w0",
        "reason": "disabled" if policy == "off" else None,
        "cache_contract": None,
        "prepare_calls": 0,
        "generate_calls": 0,
        "w1_generate_calls": 0,
        "w2_generate_batch_calls": 0,
        "contexts": {},
    }
    if policy == "off":
        return None, baseline, None

    prepare_method = getattr(strategy, "prepare_wfo", None)
    if not callable(prepare_method) and not isinstance(strategy, type):
        reason = "strategy does not expose prepare_wfo(data=..., folds=..., static_config=...)"
        if policy == "require":
            raise PreparedWfoStrategyUnsupported(reason)
        baseline["reason"] = reason
        return None, baseline, None

    index = _utc_index(datetime_index)
    run_id = hashlib.sha256(
        f"prepared-wfo:{strategy_fingerprint(strategy)}:{len(index)}:{int(index[-1].value)}".encode("utf-8")
    ).hexdigest()
    seed = derive_strategy_seed(
        base_seed=int(config.random_seed),
        run_id=run_id,
        candidate_id="prepared_wfo",
        fold_id=-1,
        cutoff_ns=int(index[-1].value),
        purpose="prepared_wfo_setup",
    )
    lifecycle = isolated_strategy_instance(
        strategy,
        run_id=run_id,
        candidate_id="prepared_wfo",
        fold_id=-1,
        seed=seed,
        market_fingerprint=_market_fingerprint(data, index),
        cutoff=index[-1],
        policy=str(config.strategy_lifecycle_policy),
    )
    instance, lifecycle_record = lifecycle.__enter__()
    try:
        prepare = getattr(instance, "prepare_wfo", None)
        if not callable(prepare):
            if policy == "auto":
                lifecycle.__exit__(None, None, None)
                baseline["reason"] = (
                    "strategy instance does not expose "
                    "prepare_wfo(data=..., folds=..., static_config=...)"
                )
                return None, baseline, None
            raise PreparedWfoStrategyUnsupported(
                "strategy instance does not expose prepare_wfo(data=..., folds=..., static_config=...)"
            )
        prepared = prepare(
            data=_copy_market_for_preparation(data),
            folds=tuple(folds),
            static_config=_static_config(config, index),
        )
        resolved_adapter = _resolve_adapter(prepared, requested_adapter)
        cache_contract = str(
            getattr(
                prepared,
                "causal_cache_contract",
                getattr(instance, "causal_cache_contract", "undeclared"),
            )
        ).lower().strip()
        if str(config.optimization_schedule) != "global" and cache_contract != _STRICT_CAUSAL_CACHE_CONTRACT:
            raise PreparedWfoStrategyUnsupported(
                "prepared WFO strategy on a per-fold schedule must declare "
                f"causal_cache_contract={_STRICT_CAUSAL_CACHE_CONTRACT!r}"
            )
        adapter = PreparedWfoStrategyAdapterV1(
            prepared=prepared,
            adapter=resolved_adapter,
            full_index=index,
            lifecycle=lifecycle,
            lifecycle_record=lifecycle_record,
            requested_policy=policy,
            cache_contract=cache_contract,
            _stats={
                "prepare_calls": 1,
                "generate_calls": 0,
                "w1_generate_calls": 0,
                "w2_generate_batch_calls": 0,
                "contexts": {},
            },
        )
    except Exception:
        lifecycle.__exit__(*sys.exc_info())
        raise
    lifecycle_record["context"] = "prepared_wfo_setup"
    lifecycle_record["prepared_adapter"] = resolved_adapter
    lifecycle_record["prepared_cache_contract"] = cache_contract
    lifecycle_record["prepared_market_bars"] = int(len(index))
    return adapter, {**baseline, **adapter.metadata(), "reason": None}, lifecycle_record


def _resolve_adapter(prepared: object, requested: str) -> str:
    generate = getattr(prepared, "generate", None)
    generate_batch = getattr(prepared, "generate_batch", None)
    if requested == "auto":
        if callable(generate_batch):
            return "w2"
        if callable(generate):
            return "w1"
    elif requested == "w2" and callable(generate_batch):
        return "w2"
    elif requested == "w1" and callable(generate):
        return "w1"
    raise PreparedWfoStrategyUnsupported(
        f"prepared WFO strategy cannot satisfy adapter={requested!r}; "
        "W1 requires generate(params=..., fold_id=...), W2 requires generate_batch(params_matrix=..., fold_id=...)"
    )


def _coerce_w1_signal(value: object, *, bars: int) -> np.ndarray:
    if isinstance(value, Mapping):
        if "signal" not in value:
            raise PreparedWfoStrategyUnsupported("W1 prepared output mapping must include 'signal'")
        value = value["signal"]
    if isinstance(value, pd.Series):
        values = value.to_numpy(dtype=np.float64)
    else:
        values = np.asarray(value, dtype=np.float64)
    values = np.ascontiguousarray(values, dtype=np.float64)
    if values.shape != (int(bars),) or not np.isfinite(values).all():
        raise PreparedWfoStrategyUnsupported(
            "W1 prepared signal must be finite and have shape (prepared_market_bars,)"
        )
    return values


def _coerce_w2_signal(value: object, *, bars: int) -> np.ndarray:
    if isinstance(value, Mapping):
        if "signal" not in value:
            raise PreparedWfoStrategyUnsupported("W2 prepared output mapping must include 'signal'")
        value = value["signal"]
    values = np.ascontiguousarray(np.asarray(value, dtype=np.float64))
    if values.shape != (1, int(bars)) or not np.isfinite(values).all():
        raise PreparedWfoStrategyUnsupported(
            "W2 prepared signal must be finite and have shape (1, prepared_market_bars) "
            "under certified_sequential_v1"
        )
    return values[0]


def _static_config(config, index: pd.DatetimeIndex) -> Mapping[str, object]:
    extra = dict(getattr(config, "metadata", {}) or {}).get("prepared_wfo_strategy_static_config", {})
    if not isinstance(extra, Mapping):
        raise TypeError("prepared_wfo_strategy_static_config must be a mapping")
    return MappingProxyType(
        {
            "schema": "quantbt-prepared-wfo-strategy-v1",
            "datetime_index": index.copy(),
            "optimization_mode": str(config.optimization_mode),
            "optimization_schedule": str(config.optimization_schedule),
            "target_mode": str(config.target_mode),
            "intent_contract": config.intent_contract.metadata(),
            "static_config": MappingProxyType(dict(extra)),
        }
    )


def _copy_market_for_preparation(data):
    if isinstance(data, (pd.DataFrame, pd.Series)):
        return data.copy(deep=True)
    if isinstance(data, Mapping):
        return {
            key: value.copy(deep=True)
            if isinstance(value, (pd.DataFrame, pd.Series))
            else value
            for key, value in data.items()
        }
    return data


def _market_fingerprint(data, index: pd.DatetimeIndex) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(index.asi8, dtype=np.int64).tobytes())
    if isinstance(data, pd.DataFrame):
        digest.update(pd.util.hash_pandas_object(data, index=True).to_numpy(dtype=np.uint64).tobytes())
    elif isinstance(data, pd.Series):
        digest.update(pd.util.hash_pandas_object(data, index=True).to_numpy(dtype=np.uint64).tobytes())
    return digest.hexdigest()


def _utc_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    normalized = pd.DatetimeIndex(index)
    if normalized.tz is None:
        normalized = normalized.tz_localize("UTC")
    else:
        normalized = normalized.tz_convert("UTC")
    if len(normalized) == 0 or not normalized.is_monotonic_increasing or normalized.has_duplicates:
        raise PreparedWfoStrategyUnsupported("prepared WFO strategy requires a non-empty unique monotonic UTC index")
    return normalized


__all__ = [
    "PreparedWfoStrategyAdapterV1",
    "PreparedWfoStrategyUnsupported",
    "prepare_public_wfo_strategy",
]
