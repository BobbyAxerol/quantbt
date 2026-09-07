"""Versioned contracts for causally auditable walk-forward orchestration.

The contracts in this module deliberately describe *orchestration* only.  They
do not own signal generation, matching, account accounting, or metrics.  That
separation lets the existing Python/oracle routes remain valid while native
WFO runtimes consume the same immutable provenance later.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import copy
import hashlib
import inspect
import json
from typing import Any, Iterator, Mapping, Optional, Protocol, runtime_checkable


WFO_CONTRACT_SCHEMA_V1 = "quantbt-wfo-contract-v1"


class WfoCausalityScheduleV2(str, Enum):
    """Versioned meaning of a walk-forward optimizer schedule."""

    RETROSPECTIVE_GLOBAL = "retrospective_global_v2"
    TRUSTED_STRATEGY_GLOBAL = "trusted_strategy_global_v2"
    ENGINE_ENFORCED_PER_FOLD = "engine_enforced_per_fold_v2"
    ENGINE_ENFORCED_NESTED = "engine_enforced_nested_v2"


class FoldWarmupPolicyV1(str, Enum):
    """How historical observations may initialize a fold-local strategy."""

    NONE = "none"
    PRE_TRAIN_ONLY = "pre_train_only"
    PRE_TEST_FROM_TRAIN_TAIL = "pre_test_from_train_tail"
    EXPLICIT_BARS = "explicit_bars"


class FoldAccountPolicyV1(str, Enum):
    """Account state treatment at an outer-fold boundary."""

    RESET_FLAT = "reset_flat"
    CARRY_POSITION = "carry_position"
    CLOSE_AT_BOUNDARY = "close_at_boundary"
    REPLAY_PRIOR_STATE = "replay_prior_state"


class WfoIntentKindV1(str, Enum):
    """The semantic kind of an output emitted by a WFO strategy adapter."""

    TARGET_POSITION = "target_position"
    TARGET_UNITS = "target_units"
    TARGET_NOTIONAL = "target_notional"
    TARGET_WEIGHT = "target_weight"
    SIGNAL = "signal"
    DESIRED_ORDER = "desired_order"
    POSITION = "position"


_PHASES = frozenset(
    {
        "bar_open",
        "bar_close",
        "next_bar_open",
        "next_bar_close",
        "downstream_execution",
        "strategy_defined",
    }
)


@dataclass(frozen=True, slots=True)
class WfoIntentContractV1:
    """Explicit timing and semantic declaration for a WFO strategy output.

    A raw ``Series`` does not establish whether it is a target, a desired
    order, or an already-effective held position.  New certified WFO callers
    provide this contract; the legacy adapter remains available but is marked
    non-certified in metadata rather than silently inferred.
    """

    kind: WfoIntentKindV1 = WfoIntentKindV1.TARGET_POSITION
    observation_phase: str = "strategy_defined"
    effective_phase: str = "downstream_execution"
    already_shifted: bool = False
    route_id: str = "legacy_series_adapter_v1"
    certified: bool = False

    def __post_init__(self) -> None:
        observation = str(self.observation_phase).lower().strip()
        effective = str(self.effective_phase).lower().strip()
        if observation not in _PHASES:
            raise ValueError(f"WFO observation_phase must be one of: {', '.join(sorted(_PHASES))}")
        if effective not in _PHASES:
            raise ValueError(f"WFO effective_phase must be one of: {', '.join(sorted(_PHASES))}")
        route_id = str(self.route_id).strip()
        if not route_id:
            raise ValueError("WFO intent route_id must be non-empty")
        object.__setattr__(self, "observation_phase", observation)
        object.__setattr__(self, "effective_phase", effective)
        object.__setattr__(self, "route_id", route_id)

    @classmethod
    def legacy(cls) -> "WfoIntentContractV1":
        """Return the explicit non-certified compatibility declaration."""

        return cls()

    @classmethod
    def from_value(cls, value: "WfoIntentContractV1 | Mapping[str, Any] | None") -> "WfoIntentContractV1":
        if value is None:
            return cls.legacy()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("intent_contract must be WfoIntentContractV1 or a mapping")
        payload = dict(value)
        kind = payload.pop("kind", WfoIntentKindV1.TARGET_POSITION.value)
        try:
            payload["kind"] = kind if isinstance(kind, WfoIntentKindV1) else WfoIntentKindV1(str(kind).lower().strip())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in WfoIntentKindV1)
            raise ValueError(f"WFO intent kind must be one of: {allowed}") from exc
        return cls(**payload)

    def metadata(self) -> dict[str, object]:
        return {
            "schema": WFO_CONTRACT_SCHEMA_V1,
            "kind": self.kind.value,
            "observation_phase": self.observation_phase,
            "effective_phase": self.effective_phase,
            "already_shifted": bool(self.already_shifted),
            "route_id": self.route_id,
            "certified": bool(self.certified),
        }


@runtime_checkable
class StrategyLifecycleV1(Protocol):
    """Optional lifecycle protocol for mutable WFO strategy adapters."""

    def spawn(self, *, run_id: str, candidate_id: str, fold_id: int): ...

    def reset(self, *, seed: int, market_fingerprint: str, cutoff): ...

    def state_fingerprint(self) -> str: ...

    def snapshot_state(self): ...

    def restore_state(self, snapshot): ...

    def close(self): ...


def resolve_causality_schedule_v2(
    *,
    optimization_schedule: str,
    optimization_mode: str,
    trusted_strategy_global: bool = False,
) -> WfoCausalityScheduleV2:
    """Map stable legacy aliases to their exact versioned causality meaning."""

    schedule = str(optimization_schedule).lower().strip()
    mode = str(optimization_mode).lower().strip()
    if schedule == "global":
        return (
            WfoCausalityScheduleV2.TRUSTED_STRATEGY_GLOBAL
            if bool(trusted_strategy_global)
            else WfoCausalityScheduleV2.RETROSPECTIVE_GLOBAL
        )
    if schedule == "per_fold_causal" and mode == "mode_1_decay":
        return WfoCausalityScheduleV2.ENGINE_ENFORCED_NESTED
    if schedule in {"per_fold_decay", "per_fold_causal"}:
        return WfoCausalityScheduleV2.ENGINE_ENFORCED_PER_FOLD
    raise ValueError(f"unsupported WFO optimization_schedule={optimization_schedule!r}")


def strategy_fingerprint(strategy: object) -> str:
    """Return a stable code/config identity without falling back to object id."""

    candidate = (
        strategy
        if inspect.isclass(strategy) or inspect.isfunction(strategy) or inspect.ismethod(strategy)
        else strategy.__class__
    )
    module = getattr(candidate, "__module__", type(strategy).__module__)
    qualname = getattr(candidate, "__qualname__", type(strategy).__qualname__)
    version = getattr(strategy, "strategy_version", getattr(candidate, "strategy_version", None))
    code = getattr(strategy, "__code__", None)
    if code is None:
        code = getattr(getattr(strategy, "__call__", None), "__code__", None)
    digest = hashlib.sha256()
    digest.update(str(module).encode("utf-8"))
    digest.update(str(qualname).encode("utf-8"))
    digest.update(json.dumps(version, default=str, sort_keys=True).encode("utf-8"))
    if code is not None:
        digest.update(bytes(code.co_code))
        digest.update(repr(code.co_consts).encode("utf-8"))
    return digest.hexdigest()


def derive_strategy_seed(
    *,
    base_seed: int,
    run_id: str,
    candidate_id: str,
    fold_id: int,
    cutoff_ns: int,
    purpose: str,
) -> int:
    """Derive a worker-order-independent 32-bit strategy seed."""

    payload = json.dumps(
        {
            "base_seed": int(base_seed),
            "run_id": str(run_id),
            "candidate_id": str(candidate_id),
            "fold_id": int(fold_id),
            "cutoff_ns": int(cutoff_ns),
            "purpose": str(purpose),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "little", signed=False)


@contextmanager
def isolated_strategy_instance(
    strategy: object,
    *,
    run_id: str,
    candidate_id: str,
    fold_id: int,
    seed: int,
    market_fingerprint: str,
    cutoff,
    policy: str = "isolated_v1",
) -> Iterator[tuple[object, dict[str, object]]]:
    """Yield one independently scoped strategy instance and lifecycle record.

    ``isolated_v1`` never reuses a callable object instance.  Plain functions
    are treated as stateless adapters; classes are instantiated; lifecycle
    objects receive ``spawn``/``reset``; other callable objects are deep-copied.
    If a copy cannot be produced, the run fails rather than leaking mutable
    state.  ``legacy_reuse_v1`` remains an explicit reproducibility escape
    hatch and is recorded as non-certified.
    """

    normalized_policy = str(policy).lower().strip()
    if normalized_policy not in {"isolated_v1", "legacy_reuse_v1"}:
        raise ValueError("strategy_lifecycle_policy must be isolated_v1 or legacy_reuse_v1")

    lifecycle_kind: str
    spawned = False
    reset_called = False
    instance: object
    if isinstance(strategy, type):
        instance = strategy()
        lifecycle_kind = "class_factory"
    elif hasattr(strategy, "spawn") and callable(getattr(strategy, "spawn")):
        instance = strategy.spawn(run_id=run_id, candidate_id=candidate_id, fold_id=int(fold_id))
        if instance is strategy and normalized_policy == "isolated_v1":
            raise TypeError(
                "StrategyLifecycleV1.spawn must return an isolated instance under strategy_lifecycle_policy="
                "'isolated_v1'"
            )
        lifecycle_kind = "lifecycle_spawn"
        spawned = True
    elif inspect.isfunction(strategy) or inspect.ismethod(strategy):
        instance = strategy
        lifecycle_kind = "stateless_function"
    elif normalized_policy == "legacy_reuse_v1":
        instance = strategy
        lifecycle_kind = "legacy_reuse"
    else:
        try:
            instance = copy.deepcopy(strategy)
        except Exception as exc:
            raise TypeError(
                "walk-forward isolated_v1 requires a strategy class, function, "
                "spawn/reset lifecycle, or deepcopy-safe callable instance"
            ) from exc
        lifecycle_kind = "deepcopy_isolated"

    reset = getattr(instance, "reset", None)
    if spawned and not callable(reset) and normalized_policy == "isolated_v1":
        raise TypeError(
            "StrategyLifecycleV1.spawn must return an instance implementing reset(seed=, "
            "market_fingerprint=, cutoff=) under strategy_lifecycle_policy='isolated_v1'"
        )
    if callable(reset):
        try:
            reset(seed=int(seed), market_fingerprint=str(market_fingerprint), cutoff=cutoff)
        except TypeError as exc:
            if normalized_policy != "legacy_reuse_v1":
                raise TypeError(
                    "StrategyLifecycleV1.reset must accept seed, market_fingerprint, and cutoff keyword arguments"
                ) from exc
            reset()
        reset_called = True

    state_before = None
    fingerprint_method = getattr(instance, "state_fingerprint", None)
    if callable(fingerprint_method):
        state_before = str(fingerprint_method())
    record = {
        "schema": WFO_CONTRACT_SCHEMA_V1,
        "run_id": str(run_id),
        "candidate_id": str(candidate_id),
        "fold_id": int(fold_id),
        "seed": int(seed),
        "cutoff": str(cutoff),
        "market_fingerprint": str(market_fingerprint),
        "strategy_fingerprint": strategy_fingerprint(strategy),
        "lifecycle_kind": lifecycle_kind,
        "spawned": bool(spawned),
        "reset_called": bool(reset_called),
        "policy": normalized_policy,
        "state_before": state_before,
        "certified_isolation": bool(normalized_policy == "isolated_v1" and lifecycle_kind != "legacy_reuse"),
    }
    try:
        yield instance, record
    finally:
        if callable(fingerprint_method):
            record["state_after"] = str(fingerprint_method())
        close = getattr(instance, "close", None)
        if callable(close):
            close()
            record["closed"] = True
        else:
            record["closed"] = False


__all__ = [
    "FoldAccountPolicyV1",
    "FoldWarmupPolicyV1",
    "StrategyLifecycleV1",
    "WFO_CONTRACT_SCHEMA_V1",
    "WfoCausalityScheduleV2",
    "WfoIntentContractV1",
    "WfoIntentKindV1",
    "derive_strategy_seed",
    "isolated_strategy_instance",
    "resolve_causality_schedule_v2",
    "strategy_fingerprint",
]
