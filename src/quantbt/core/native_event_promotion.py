"""Deterministic native-event backend promotion policy.

The policy is intentionally separate from execution.  It answers one narrow
question before preparation: whether a particular workload is eligible to use
the optional Rust runtime.  Import success alone is never a promotion signal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import os
import platform
import sys
from typing import Mapping

from .generated_product_contracts import (
    NATIVE_EVENT_PRODUCT_REGISTRY,
    NATIVE_EVENT_PROMOTION_POLICY,
    PRODUCT_CONTRACT_REGISTRY_FINGERPRINT,
)


class NativePromotionError(RuntimeError):
    """Raised when a native backend policy request is invalid or unsafe."""


class NativeBackendPolicy(str, Enum):
    """User intent for automatic native-event backend selection."""

    CERTIFIED_ONLY = "certified_only"
    PREFER_NATIVE = "prefer_native"
    PREFER_COMPATIBILITY = "prefer_compatibility"


class NativePromotionStage(str, Enum):
    """Ordered scope of automatic Rust promotion."""

    EXPLICIT_ONLY = "explicit_only"
    STATIC_IR = "static_ir"
    PORTFOLIO = "portfolio"
    PACKAGE = "package"


_BACKENDS = frozenset({"auto", "python", "rust", "replay_certified"})
_STAGE_ORDER = {
    NativePromotionStage.EXPLICIT_ONLY.value: 0,
    NativePromotionStage.STATIC_IR.value: 1,
    NativePromotionStage.PORTFOLIO.value: 2,
    NativePromotionStage.PACKAGE.value: 3,
}
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})


@dataclass(frozen=True, slots=True)
class NativePromotionContext:
    """All inputs that are allowed to influence a promotion decision."""

    requested_backend: str
    backend_policy: str | NativeBackendPolicy | None
    workload_id: str
    execution_contract_id: str
    strategy_mode: str
    profile: str
    account_model: str
    bars: int = 0
    symbol_count: int = 1
    required_capabilities: tuple[str, ...] = ()
    native_available: bool | None = None
    native_compatible: bool | None = None
    native_executable: bool | None = None
    native_capabilities: tuple[str, ...] = ()
    native_reason: str | None = None
    native_version: str | None = None
    native_api_version: str | None = None
    native_capability_fingerprint: str | None = None
    platform_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if str(self.requested_backend).lower().strip() not in _BACKENDS:
            raise NativePromotionError(
                "requested backend must be auto, python, replay_certified, or rust"
            )
        if not str(self.workload_id).strip():
            raise NativePromotionError("workload_id cannot be empty")
        if not str(self.execution_contract_id).strip():
            raise NativePromotionError("execution_contract_id cannot be empty")
        if self.bars < 0:
            raise NativePromotionError("bars must be >= 0")
        if self.symbol_count <= 0:
            raise NativePromotionError("symbol_count must be > 0")


@dataclass(frozen=True, slots=True)
class NativePromotionDecision:
    """Serializable routing decision retained with every planned execution."""

    requested_backend: str
    backend_policy: str
    resolved_backend: str
    reason: str
    workload_id: str
    workload_maturity: str
    execution_contract_id: str
    product_registry_fingerprint: str
    promotion_table_version: str
    configured_stage: str
    effective_stage: str
    promotion_max_stage: str
    emergency_native_disabled: bool
    matched_rule_id: str | None
    minimum_bars: int
    native_probe_required: bool
    native_available: bool | None
    native_compatible: bool | None
    native_executable: bool | None
    native_reason: str | None
    native_version: str | None
    native_api_version: str | None
    native_capability_fingerprint: str | None

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["fingerprint"] = self.fingerprint
        return payload


def current_native_platform_tags() -> tuple[str, ...]:
    """Return deterministic host tags used by the generated promotion table."""

    implementation = sys.implementation.name.lower()
    major, minor = sys.version_info[:2]
    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower().replace("amd64", "x86_64") or "unknown"
    return tuple(
        sorted(
            {
                "any",
                f"{implementation}-{major}.{minor}+",
                f"{system}-{machine}",
                f"{system}-{machine}-local",
            }
        )
    )


def native_event_workload_id(*, workload: str, strategy_mode: str) -> str:
    """Map planner-level workload/mode values to one registry descriptor."""

    key = (str(workload), str(strategy_mode))
    mapping = {
        ("static_command_tape", "static_commands"): "event_static_tape_v2_v3",
        ("python_callback", "python_callback_compat"): "event_python_callback_v2_v3",
        ("signal_tape", "signal"): "native_strategy_ir_v1",
        ("signal_tape", "ir_v1"): "native_strategy_ir_v1",
        ("portfolio_target", "portfolio"): "portfolio_target_preflight_v1",
        ("package_transaction", "package"): "package_transaction_preflight_v1",
    }
    try:
        return mapping[key]
    except KeyError as exc:
        raise NativePromotionError(
            f"no native promotion workload is registered for workload={key[0]!r}, "
            f"strategy_mode={key[1]!r}"
        ) from exc


def promotion_policy_snapshot() -> dict[str, object]:
    """Return a defensive, JSON-safe copy of the generated promotion policy."""

    return json.loads(json.dumps(NATIVE_EVENT_PROMOTION_POLICY, sort_keys=True))


def _normalized_backend(value: str) -> str:
    selected = str(value or "auto").lower().strip()
    if selected not in _BACKENDS:
        raise NativePromotionError(
            "requested backend must be auto, python, replay_certified, or rust"
        )
    return selected


def _normalized_policy(
    value: str | NativeBackendPolicy | None,
    policy_table: Mapping[str, object],
) -> NativeBackendPolicy:
    selected = policy_table["default_backend_policy"] if value is None else value
    try:
        return NativeBackendPolicy(str(selected).lower().strip())
    except ValueError as exc:
        valid = ", ".join(item.value for item in NativeBackendPolicy)
        raise NativePromotionError(f"backend_policy must be one of: {valid}") from exc


def _parse_disable_native(environment: Mapping[str, str]) -> bool:
    raw = environment.get("QUANTBT_DISABLE_NATIVE", "0")
    value = str(raw).lower().strip()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise NativePromotionError("QUANTBT_DISABLE_NATIVE must be one of 0/1/false/true/no/yes/off/on")


def _effective_stage(policy_table: Mapping[str, object], environment: Mapping[str, str]) -> tuple[str, str, str]:
    configured = str(policy_table["default_stage"])
    if configured not in _STAGE_ORDER:
        raise NativePromotionError(f"unsupported configured promotion stage: {configured}")
    requested_max = str(environment.get("QUANTBT_NATIVE_PROMOTION_MAX", "package")).lower().strip()
    if requested_max not in _STAGE_ORDER:
        valid = ", ".join(_STAGE_ORDER)
        raise NativePromotionError(f"QUANTBT_NATIVE_PROMOTION_MAX must be one of: {valid}")
    effective = min(configured, requested_max, key=lambda item: _STAGE_ORDER[item])
    return configured, requested_max, effective


def _workload_descriptor(workload_id: str, registry: Mapping[str, object]) -> Mapping[str, object]:
    for item in registry["workloads"]:
        if str(item["id"]) == workload_id:
            return item
    raise NativePromotionError(f"unknown native promotion workload: {workload_id}")


def _platform_matches(required: tuple[str, ...], available: tuple[str, ...]) -> bool:
    available_set = set(available)
    for requirement in required:
        if requirement in available_set:
            continue
        if requirement.startswith("cpython-") and requirement.endswith("+"):
            minimum = requirement.removeprefix("cpython-").removesuffix("+")
            try:
                min_major, min_minor = (int(item) for item in minimum.split(".", maxsplit=1))
            except ValueError:
                return False
            matching = []
            for tag in available_set:
                if not tag.startswith("cpython-") or not tag.endswith("+"):
                    continue
                try:
                    major, minor = (
                        int(item)
                        for item in tag.removeprefix("cpython-").removesuffix("+").split(".", maxsplit=1)
                    )
                except ValueError:
                    continue
                matching.append((major, minor))
            if any(version >= (min_major, min_minor) for version in matching):
                continue
        return False
    return True


def _matches_workload_shape(
    workload: Mapping[str, object],
    context: NativePromotionContext,
    platform_tags: tuple[str, ...],
) -> bool:
    max_symbols = workload["max_symbols"]
    return (
        context.execution_contract_id in set(workload["contracts"])
        and context.strategy_mode in set(workload["strategy_modes"])
        and context.profile in set(workload["profiles"])
        and context.account_model in set(workload["account_models"])
        and (max_symbols is None or context.symbol_count <= int(max_symbols))
        and _platform_matches(tuple(str(item) for item in workload["platforms"]), platform_tags)
    )


def _decision(
    context: NativePromotionContext,
    *,
    workload: Mapping[str, object],
    policy: NativeBackendPolicy,
    resolved: str,
    reason: str,
    policy_table: Mapping[str, object],
    configured_stage: str,
    effective_stage: str,
    promotion_max_stage: str,
    emergency_native_disabled: bool = False,
    matched_rule_id: str | None = None,
    minimum_bars: int = 0,
    probe_required: bool = False,
) -> NativePromotionDecision:
    return NativePromotionDecision(
        requested_backend=_normalized_backend(context.requested_backend),
        backend_policy=policy.value,
        resolved_backend=resolved,
        reason=reason,
        workload_id=context.workload_id,
        workload_maturity=str(workload["maturity"]),
        execution_contract_id=context.execution_contract_id,
        product_registry_fingerprint=PRODUCT_CONTRACT_REGISTRY_FINGERPRINT,
        promotion_table_version=str(policy_table["table_version"]),
        configured_stage=configured_stage,
        effective_stage=effective_stage,
        promotion_max_stage=promotion_max_stage,
        emergency_native_disabled=emergency_native_disabled,
        matched_rule_id=matched_rule_id,
        minimum_bars=int(minimum_bars),
        native_probe_required=probe_required,
        native_available=context.native_available,
        native_compatible=context.native_compatible,
        native_executable=context.native_executable,
        native_reason=context.native_reason,
        native_version=context.native_version,
        native_api_version=context.native_api_version,
        native_capability_fingerprint=context.native_capability_fingerprint,
    )


def _native_status_decision(
    context: NativePromotionContext,
    *,
    workload: Mapping[str, object],
    policy: NativeBackendPolicy,
    policy_table: Mapping[str, object],
    configured_stage: str,
    effective_stage: str,
    promotion_max_stage: str,
    matched_rule_id: str | None,
    minimum_bars: int = 0,
    required_capabilities: tuple[str, ...],
) -> NativePromotionDecision:
    if context.native_available is None:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="native_probe_required",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            matched_rule_id=matched_rule_id,
            minimum_bars=minimum_bars,
            probe_required=True,
        )
    if not context.native_available:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="native_unavailable",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            matched_rule_id=matched_rule_id,
            minimum_bars=minimum_bars,
        )
    if not context.native_compatible:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="native_incompatible",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            matched_rule_id=matched_rule_id,
            minimum_bars=minimum_bars,
        )
    if not context.native_executable:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="native_not_executable",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            matched_rule_id=matched_rule_id,
            minimum_bars=minimum_bars,
        )
    missing = sorted(set(required_capabilities) - set(context.native_capabilities))
    if missing:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="native_missing_capabilities",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            matched_rule_id=matched_rule_id,
            minimum_bars=minimum_bars,
        )
    return _decision(
        context,
        workload=workload,
        policy=policy,
        resolved="rust",
        reason="explicit_rust_certified" if _normalized_backend(context.requested_backend) == "rust" else "auto_rust_certified",
        policy_table=policy_table,
        configured_stage=configured_stage,
        effective_stage=effective_stage,
        promotion_max_stage=promotion_max_stage,
        matched_rule_id=matched_rule_id,
        minimum_bars=minimum_bars,
    )


def resolve_native_event_promotion(
    context: NativePromotionContext,
    *,
    environment: Mapping[str, str] | None = None,
    registry: Mapping[str, object] | None = None,
    policy_table: Mapping[str, object] | None = None,
) -> NativePromotionDecision:
    """Resolve one native-event backend decision without touching market data.

    If native capability information is omitted for a route that could use
    Rust, the returned decision sets ``native_probe_required=True``.  Callers
    probe once and resolve again with that immutable capability snapshot.
    """

    environment = os.environ if environment is None else environment
    registry = NATIVE_EVENT_PRODUCT_REGISTRY if registry is None else registry
    policy_table = NATIVE_EVENT_PROMOTION_POLICY if policy_table is None else policy_table
    workload = _workload_descriptor(context.workload_id, registry)
    selected = _normalized_backend(context.requested_backend)
    policy = _normalized_policy(context.backend_policy, policy_table)
    configured_stage, promotion_max_stage, effective_stage = _effective_stage(policy_table, environment)

    if _parse_disable_native(environment):
        if selected == "rust":
            raise NativePromotionError("native backend is disabled by QUANTBT_DISABLE_NATIVE=1")
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="replay_certified" if selected == "replay_certified" else "python",
            reason="emergency_native_disabled",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            emergency_native_disabled=True,
        )
    if selected == "python":
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="explicit_python",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
        )
    if selected == "replay_certified":
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="replay_certified",
            reason="replay_certified_compatibility",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
        )

    required = tuple(sorted(set(context.required_capabilities)))
    if selected == "rust":
        return _native_status_decision(
            context,
            workload=workload,
            policy=policy,
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            matched_rule_id=None,
            required_capabilities=required,
        )

    if policy is NativeBackendPolicy.PREFER_COMPATIBILITY:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="policy_prefer_compatibility",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
        )

    platform_tags = context.platform_tags or current_native_platform_tags()
    if not _matches_workload_shape(workload, context, platform_tags):
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="workload_shape_not_certified",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
        )

    matching_rules = [
        item
        for item in policy_table["rules"]
        if str(item["workload_id"]) == context.workload_id
    ]
    enabled_rules = [item for item in matching_rules if bool(item["enabled"])]
    if not enabled_rules:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="auto_python_release_policy",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
        )
    eligible_rules = [
        item
        for item in enabled_rules
        if _STAGE_ORDER[str(item["stage"])] <= _STAGE_ORDER[effective_stage]
    ]
    if not eligible_rules:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="promotion_stage_limited",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
        )
    if str(workload["maturity"]) != "promoted" or not bool(workload["auto_promotion"]):
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="workload_not_promoted",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
        )
    rule = eligible_rules[0]
    minimum_bars = int(rule["min_bars"])
    if context.bars < minimum_bars:
        return _decision(
            context,
            workload=workload,
            policy=policy,
            resolved="python",
            reason="below_promotion_min_bars",
            policy_table=policy_table,
            configured_stage=configured_stage,
            effective_stage=effective_stage,
            promotion_max_stage=promotion_max_stage,
            matched_rule_id=str(rule["id"]),
            minimum_bars=minimum_bars,
        )
    required = tuple(sorted(set(required) | {str(item) for item in rule["required_capabilities"]}))
    return _native_status_decision(
        context,
        workload=workload,
        policy=policy,
        policy_table=policy_table,
        configured_stage=configured_stage,
        effective_stage=effective_stage,
        promotion_max_stage=promotion_max_stage,
        matched_rule_id=str(rule["id"]),
        minimum_bars=minimum_bars,
        required_capabilities=required,
    )


__all__ = [
    "NativeBackendPolicy",
    "NativePromotionContext",
    "NativePromotionDecision",
    "NativePromotionError",
    "NativePromotionStage",
    "current_native_platform_tags",
    "native_event_workload_id",
    "promotion_policy_snapshot",
    "resolve_native_event_promotion",
]
