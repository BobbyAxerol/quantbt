"""Prepared W3 contracts for causally auditable reactive walk-forward runs.

Reactive strategies own a command/lifecycle state machine, not a vectorized
``pos_weight`` series.  This module therefore keeps their WFO preparation and
candidate construction separate from the older W1/W2 signal protocol.  The
generic :mod:`quantbt.walkforward` engine still owns folds, Optuna sequencing,
and candidate-selection mathematics; this contract only makes the strategy
boundary explicit and lifecycle-safe.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import sys
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable
from weakref import WeakValueDictionary

import pandas as pd

from ..core.wfo_contracts import derive_strategy_seed, isolated_strategy_instance, strategy_fingerprint


REACTIVE_WFO_SCHEMA_V1 = "quantbt-reactive-wfo-v1"
STRICT_CAUSAL_CACHE_CONTRACT_V1 = "causal_parameter_independent_v1"


class PreparedReactiveWfoUnsupported(NotImplementedError):
    """Raised before a reactive WFO run when its strategy contract is unsafe."""


@dataclass(frozen=True, slots=True)
class ReactiveWfoTaskV1:
    """One immutable candidate/fold/window binding.

    ``start_bar`` and ``end_bar`` are absolute indices into the single prepared
    market tape.  A score always starts from a fresh flat account at
    ``start_bar``.  ``history_end_bar`` is causal feature provenance only: a
    strategy can consult parameter-independent prepared features through that
    point, but QuantBT never carries order/account state into the score.
    """

    run_id: str
    candidate_id: str
    fold_id: int
    stage: str
    start_bar: int
    end_bar: int
    history_start_bar: int
    history_end_bar: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    seed: int
    market_signature: str

    def __post_init__(self) -> None:
        if not 0 <= int(self.history_start_bar) <= int(self.start_bar) < int(self.end_bar):
            raise ValueError("reactive WFO task bars must satisfy history_start <= start < end")
        if int(self.history_end_bar) < int(self.start_bar) or int(self.history_end_bar) >= int(self.end_bar):
            raise ValueError("reactive WFO task history_end_bar must lie inside its execution window")
        if not str(self.stage).strip():
            raise ValueError("reactive WFO task stage must be non-empty")

    @property
    def bars(self) -> int:
        return int(self.end_bar - self.start_bar)

    def metadata(self) -> dict[str, object]:
        return {
            "schema": REACTIVE_WFO_SCHEMA_V1,
            "candidate_id": self.candidate_id,
            "fold_id": int(self.fold_id),
            "stage": self.stage,
            "start_bar": int(self.start_bar),
            "end_bar": int(self.end_bar),
            "history_start_bar": int(self.history_start_bar),
            "history_end_bar": int(self.history_end_bar),
            "seed": int(self.seed),
            "market_signature": self.market_signature,
        }


@runtime_checkable
class PreparedReactiveWfoStrategyV1(Protocol):
    """Parameter-independent W3 preparation plus per-task strategy creation."""

    causal_cache_contract: str

    def build_strategy(self, *, params: Mapping[str, Any], task: ReactiveWfoTaskV1) -> object:
        """Return one fresh R1/R2/R3 strategy object for ``task``."""

    def build_candidate_batch(
        self,
        *,
        params_matrix: Sequence[Mapping[str, Any]],
        tasks: Sequence[ReactiveWfoTaskV1],
    ) -> object:
        """Optional R3B strategy for one same-window fixed candidate batch."""


@runtime_checkable
class ReactiveWfoPreparationV1(Protocol):
    """Optional public strategy factory protocol for reactive WFO."""

    def prepare_reactive_wfo(
        self,
        *,
        data,
        folds: Sequence[object],
        static_config: Mapping[str, Any],
    ) -> PreparedReactiveWfoStrategyV1:
        """Build a parameter-independent causal feature/cache owner once."""


@dataclass(slots=True)
class PreparedReactiveWfoStrategyAdapterV1:
    """Run-local owner for one prepared W3 strategy factory.

    The adapter never shares a mutable returned strategy across tasks.  A
    callable returned twice is only admitted if it expressly declares itself
    stateless; otherwise a repeated identity is treated as a state-leak risk.
    """

    prepared: PreparedReactiveWfoStrategyV1
    lifecycle: AbstractContextManager
    lifecycle_record: dict[str, object]
    full_index: pd.DatetimeIndex
    market_signature: str
    run_id: str
    _stats: dict[str, object] = field(default_factory=dict)
    _live_mutable_by_id: WeakValueDictionary[int, object] = field(default_factory=WeakValueDictionary)
    _closed: bool = False

    def task(
        self,
        *,
        params: Mapping[str, Any],
        fold,
        evaluation_index: pd.DatetimeIndex,
        stage: str,
    ) -> ReactiveWfoTaskV1:
        if self._closed:
            raise RuntimeError("prepared reactive WFO strategy adapter is closed")
        if not len(evaluation_index):
            raise ValueError("reactive WFO evaluation index must be non-empty")
        start = int(self.full_index.get_indexer([evaluation_index[0]])[0])
        end_last = int(self.full_index.get_indexer([evaluation_index[-1]])[0])
        if start < 0 or end_last < start:
            raise ValueError("reactive WFO evaluation index is not contained by the prepared market clock")
        # The normal WFO calendar builds contiguous bars.  A dynamic command
        # strategy cannot silently bridge a temporal gap with missing state.
        if not self.full_index[start : end_last + 1].equals(evaluation_index):
            raise ValueError("reactive WFO evaluation windows must be contiguous prepared-market bars")
        candidate_id = _candidate_id(params)
        task = ReactiveWfoTaskV1(
            run_id=self.run_id,
            candidate_id=candidate_id,
            fold_id=int(fold.fold_id),
            stage=str(stage),
            start_bar=start,
            end_bar=end_last + 1,
            history_start_bar=int(self.full_index.get_indexer([fold.train_index[0]])[0]),
            # The strategy obtains only causal history.  For IS scoring this
            # is the evaluation end; for OOS it is likewise the task cutoff.
            history_end_bar=end_last,
            train_start=pd.Timestamp(fold.train_start),
            train_end=pd.Timestamp(fold.train_end),
            test_start=pd.Timestamp(fold.test_start),
            test_end=pd.Timestamp(fold.test_end),
            seed=derive_strategy_seed(
                base_seed=int(self._stats["base_seed"]),
                run_id=self.run_id,
                candidate_id=candidate_id,
                fold_id=int(fold.fold_id),
                cutoff_ns=int(evaluation_index[-1].value),
                purpose=f"reactive_wfo:{stage}",
            ),
            market_signature=self.market_signature,
        )
        self._stats["tasks_created"] = int(self._stats["tasks_created"]) + 1
        return task

    def build_strategy(self, *, params: Mapping[str, Any], task: ReactiveWfoTaskV1) -> object:
        if self._closed:
            raise RuntimeError("prepared reactive WFO strategy adapter is closed")
        build = getattr(self.prepared, "build_strategy", None)
        if not callable(build):
            raise PreparedReactiveWfoUnsupported(
                "prepared reactive WFO strategy must implement build_strategy(params=..., task=...)"
            )
        strategy = build(params=MappingProxyType(dict(params)), task=task)
        if strategy is None:
            raise PreparedReactiveWfoUnsupported("reactive WFO build_strategy returned None")
        if not _is_stateless_callable(strategy):
            identity = id(strategy)
            # ``id()`` alone is not an identity contract: CPython can reuse the
            # address immediately after a prior candidate becomes unreachable.
            # A weak live-object table catches an actually retained/reused
            # mutable strategy without retaining every candidate strategy for
            # the life of a long Optuna study.
            try:
                existing = self._live_mutable_by_id.get(identity)
                if existing is strategy:
                    raise PreparedReactiveWfoUnsupported(
                        "reactive WFO build_strategy reused one mutable strategy object across tasks; "
                        "return a fresh object or explicitly declare quantbt_stateless_reactive_v1=True"
                    )
                self._live_mutable_by_id[identity] = strategy
            except TypeError:
                # A non-weak-referenceable strategy must explicitly identify
                # itself as stateless to bypass this guard.  There is no safe
                # unbounded strong-reference fallback for a long WFO search.
                raise PreparedReactiveWfoUnsupported(
                    "reactive WFO mutable strategy instances must support weak references; "
                    "return a regular fresh object or declare quantbt_stateless_reactive_v1=True"
                ) from None
        reset = getattr(strategy, "reset", None)
        if callable(reset):
            reset(seed=int(task.seed), task=task)
        self._stats["strategy_builds"] = int(self._stats["strategy_builds"]) + 1
        return strategy

    def build_candidate_batch(
        self,
        *,
        params_matrix: Sequence[Mapping[str, Any]],
        tasks: Sequence[ReactiveWfoTaskV1],
    ) -> object:
        """Build one opt-in R3B callback for same-window independent states."""

        if self._closed:
            raise RuntimeError("prepared reactive WFO strategy adapter is closed")
        if not params_matrix or len(params_matrix) != len(tasks):
            raise ValueError("reactive WFO candidate batch requires matching non-empty params/tasks")
        windows = {(int(task.fold_id), int(task.start_bar), int(task.end_bar), str(task.stage)) for task in tasks}
        if len(windows) != 1:
            raise ValueError("reactive WFO candidate batch requires one fold/stage/absolute window")
        build = getattr(self.prepared, "build_candidate_batch", None)
        if not callable(build):
            raise PreparedReactiveWfoUnsupported(
                "throughput_batch_v1 requires prepared strategy support for "
                "build_candidate_batch(params_matrix=..., tasks=...)"
            )
        strategy = build(
            params_matrix=tuple(MappingProxyType(dict(params)) for params in params_matrix),
            tasks=tuple(tasks),
        )
        if strategy is None or not callable(getattr(strategy, "on_wake_batch", None)):
            raise PreparedReactiveWfoUnsupported(
                "reactive candidate batch builder must return an object with "
                "on_wake_batch(context_batch, out_batch)"
            )
        if not bool(getattr(strategy, "quantbt_reactive_candidate_batch_v1", False)):
            raise PreparedReactiveWfoUnsupported(
                "reactive candidate batch strategy must declare quantbt_reactive_candidate_batch_v1=True"
            )
        self._stats["candidate_batch_builds"] = int(self._stats.get("candidate_batch_builds", 0)) + 1
        return strategy

    def metadata(self) -> dict[str, object]:
        return {
            "schema": REACTIVE_WFO_SCHEMA_V1,
            "cache_contract": STRICT_CAUSAL_CACHE_CONTRACT_V1,
            "strategy_kind": f"{type(self.prepared).__module__}.{type(self.prepared).__qualname__}",
            "prepared_market_bars": int(len(self.full_index)),
            "closed": bool(self._closed),
            **dict(self._stats),
        }

    def close(self) -> None:
        if self._closed:
            return
        close = getattr(self.prepared, "close", None)
        try:
            if callable(close):
                close()
        finally:
            self.lifecycle.__exit__(None, None, None)
            self._closed = True


def prepare_reactive_wfo_strategy(
    *,
    strategy_factory: object,
    data,
    datetime_index: pd.DatetimeIndex,
    folds: Sequence[object],
    random_seed: int,
    static_config: Mapping[str, Any],
) -> PreparedReactiveWfoStrategyAdapterV1:
    """Prepare one isolated W3 factory and require its causal-cache promise."""

    prepare_method = getattr(strategy_factory, "prepare_reactive_wfo", None)
    if not callable(prepare_method) and not inspect.isclass(strategy_factory):
        raise PreparedReactiveWfoUnsupported(
            "reactive WFO strategy_factory must expose "
            "prepare_reactive_wfo(data=..., folds=..., static_config=...)"
        )
    index = _utc_index(datetime_index)
    market_signature = _market_signature(data, index)
    run_id = hashlib.sha256(
        f"reactive-wfo:{strategy_fingerprint(strategy_factory)}:{market_signature}".encode("utf-8")
    ).hexdigest()
    seed = derive_strategy_seed(
        base_seed=int(random_seed),
        run_id=run_id,
        candidate_id="reactive_wfo_prepare",
        fold_id=-1,
        cutoff_ns=int(index[-1].value),
        purpose="reactive_wfo_prepare",
    )
    lifecycle = isolated_strategy_instance(
        strategy_factory,
        run_id=run_id,
        candidate_id="reactive_wfo_prepare",
        fold_id=-1,
        seed=seed,
        market_fingerprint=market_signature,
        cutoff=index[-1],
        policy="isolated_v1",
    )
    instance, lifecycle_record = lifecycle.__enter__()
    try:
        prepare = getattr(instance, "prepare_reactive_wfo", None)
        if not callable(prepare):
            raise PreparedReactiveWfoUnsupported(
                "reactive WFO strategy instance must expose "
                "prepare_reactive_wfo(data=..., folds=..., static_config=...)"
            )
        prepared = prepare(
            data=_copy_market_for_preparation(data),
            folds=tuple(folds),
            static_config=MappingProxyType(dict(static_config)),
        )
        if prepared is None:
            raise PreparedReactiveWfoUnsupported("prepare_reactive_wfo returned None")
        contract = str(getattr(prepared, "causal_cache_contract", "")).lower().strip()
        if contract != STRICT_CAUSAL_CACHE_CONTRACT_V1:
            raise PreparedReactiveWfoUnsupported(
                "prepared reactive WFO must declare "
                f"causal_cache_contract={STRICT_CAUSAL_CACHE_CONTRACT_V1!r}"
            )
        if not callable(getattr(prepared, "build_strategy", None)):
            raise PreparedReactiveWfoUnsupported(
                "prepared reactive WFO must implement build_strategy(params=..., task=...)"
            )
    except Exception:
        lifecycle.__exit__(*sys.exc_info())
        raise
    lifecycle_record.update(
        {
            "context": "prepared_reactive_wfo_setup",
            "reactive_wfo_schema": REACTIVE_WFO_SCHEMA_V1,
            "prepared_cache_contract": STRICT_CAUSAL_CACHE_CONTRACT_V1,
            "prepared_market_bars": int(len(index)),
        }
    )
    return PreparedReactiveWfoStrategyAdapterV1(
        prepared=prepared,
        lifecycle=lifecycle,
        lifecycle_record=lifecycle_record,
        full_index=index,
        market_signature=market_signature,
        run_id=run_id,
        _stats={
            "base_seed": int(random_seed),
            "tasks_created": 0,
            "strategy_builds": 0,
            "candidate_batch_builds": 0,
        },
    )


def reactive_wfo_candidate_id(params: Mapping[str, Any]) -> str:
    """Return the stable candidate identity shared by tasks and batch ledgers."""

    payload = json.dumps(dict(params), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


# Keep the former private spelling inside this module while exposing a named
# cross-module contract for R3B failure attribution.
_candidate_id = reactive_wfo_candidate_id


def _is_stateless_callable(value: object) -> bool:
    return bool(getattr(value, "quantbt_stateless_reactive_v1", False)) or inspect.isfunction(value)


def _utc_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(index)
    if result.tz is None:
        result = result.tz_localize("UTC")
    else:
        result = result.tz_convert("UTC")
    if not result.is_monotonic_increasing or result.has_duplicates:
        raise ValueError("reactive WFO requires a unique monotonic UTC market clock")
    return result


def _copy_market_for_preparation(data):
    if isinstance(data, pd.DataFrame):
        return data.copy(deep=True)
    if isinstance(data, Mapping):
        return {key: value.copy(deep=True) if isinstance(value, pd.DataFrame) else value for key, value in data.items()}
    return data


def _market_signature(data, index: pd.DatetimeIndex) -> str:
    digest = hashlib.sha256()
    digest.update(index.asi8.tobytes())
    if isinstance(data, pd.DataFrame):
        digest.update("|".join(str(column) for column in data.columns).encode("utf-8"))
        for column in data.columns:
            values = data[column].to_numpy(copy=False)
            digest.update(str(values.dtype).encode("ascii", errors="ignore"))
            digest.update(values.tobytes())
    else:
        digest.update(repr(type(data)).encode("utf-8"))
    return digest.hexdigest()


__all__ = [
    "PreparedReactiveWfoStrategyAdapterV1",
    "PreparedReactiveWfoStrategyV1",
    "PreparedReactiveWfoUnsupported",
    "REACTIVE_WFO_SCHEMA_V1",
    "ReactiveWfoPreparationV1",
    "ReactiveWfoTaskV1",
    "STRICT_CAUSAL_CACHE_CONTRACT_V1",
    "prepare_reactive_wfo_strategy",
    "reactive_wfo_candidate_id",
]
