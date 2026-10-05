"""Versioned bindings, not a financial engine or a shape-based dispatcher."""

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Protocol, runtime_checkable

import pandas as pd

from ..common import MetaRecordError, digest, freeze, token, utc
from ..records import CompatibilityFamily, MetricObservation


DOMAIN_ABI = "qms-domain-evaluation-v1"


class InputKind(str, Enum):
    SCALAR_TARGET = "scalar_target"
    POSITION_MATRIX = "position_matrix"
    PACKAGE = "package"
    INTRABAR_INTENT = "intrabar_intent"
    ORDER_COMMANDS = "order_commands"
    REACTIVE_WINDOW = "reactive_window"


class EvaluationStage(str, Enum):
    CURRENT_IS = "current_is"
    POST_SEAL_FORWARD = "post_seal_counterfactual_forward"
    FINAL_OOS = "final_oos"


@dataclass(frozen=True, slots=True)
class DomainCompatibility:
    """Nominal contracts belong to a family; actual dates/data do not."""

    domain: str
    input_kind: InputKind
    universe: tuple[str, ...]
    calendar_policy: str
    instrument_contract: str
    funding_policy: str
    economics_id: str
    metric_id: str
    execution_timing: str
    diagnostic_account: str
    final_account: str
    witness_abi: str
    abi: str = DOMAIN_ABI

    def __post_init__(self):
        object.__setattr__(self, "input_kind", InputKind(self.input_kind))
        object.__setattr__(self, "universe", tuple(self.universe))
        if self.abi != DOMAIN_ABI:
            raise MetaRecordError("META_DOMAIN_ABI_UNSUPPORTED")
        if not self.universe or len(set(self.universe)) != len(self.universe):
            raise MetaRecordError("META_DOMAIN_UNIVERSE_INVALID")
        for value in self.universe:
            token(value)
        for name in ("domain", "calendar_policy", "instrument_contract", "funding_policy",
                     "economics_id", "metric_id", "execution_timing", "diagnostic_account",
                     "final_account", "witness_abi"):
            token(getattr(self, name), name)

    @property
    def compatibility_id(self):
        return digest(self)

    def bind_family(self, family: CompatibilityFamily):
        """Future adapters cannot borrow scalar families via similar inputs."""
        if family.metric_contract_id != self.metric_id or family.economics_id != self.economics_id:
            raise MetaRecordError("META_DOMAIN_FAMILY_INCOMPATIBLE")
        return replace(family, scorer_contract_id=digest({"abi": self.abi,
            "adapter": self.compatibility_id, "scorer": family.scorer_contract_id}))


@dataclass(frozen=True, slots=True)
class MarketBinding:
    run_id: str
    source_signature: str
    calendar_signature: str
    instrument_signature: str
    funding_signature: str
    compatibility: DomainCompatibility
    abi: str = DOMAIN_ABI

    def __post_init__(self):
        if self.abi != DOMAIN_ABI or not isinstance(self.compatibility, DomainCompatibility):
            raise MetaRecordError("META_DOMAIN_ABI_UNSUPPORTED")
        for name in ("run_id", "source_signature", "calendar_signature",
                     "instrument_signature", "funding_signature"):
            token(getattr(self, name), name)

    @property
    def binding_id(self):
        return digest(self)


@dataclass(frozen=True, slots=True)
class EvaluationBinding:
    domain: str
    input_kind: InputKind
    stage: EvaluationStage
    index: pd.DatetimeIndex = field(repr=False, compare=False)
    params: Mapping = field(repr=False)
    payload: object = field(repr=False, compare=False)
    input_signature: str
    information_as_of: pd.Timestamp
    decision_sealed_at: pd.Timestamp | None = None
    abi: str = DOMAIN_ABI

    def __post_init__(self):
        if self.abi != DOMAIN_ABI:
            raise MetaRecordError("META_DOMAIN_ABI_UNSUPPORTED")
        token(self.domain)
        token(self.input_signature)
        object.__setattr__(self, "input_kind", InputKind(self.input_kind))
        object.__setattr__(self, "stage", EvaluationStage(self.stage))
        index = self.index
        if (not isinstance(index, pd.DatetimeIndex) or len(index) < 2 or index.tz is None
                or not index.is_unique or not index.is_monotonic_increasing):
            raise MetaRecordError("META_DOMAIN_CALENDAR_INVALID")
        object.__setattr__(self, "params", freeze(self.params))
        cutoff = utc(self.information_as_of)
        object.__setattr__(self, "information_as_of", cutoff)
        if self.stage == EvaluationStage.CURRENT_IS:
            if utc(index[-1]) > cutoff:
                raise MetaRecordError("META_DOMAIN_FUTURE_INPUT")
        else:
            seal = utc(self.decision_sealed_at)
            object.__setattr__(self, "decision_sealed_at", seal)
            if not cutoff <= seal < utc(index[0]):
                raise MetaRecordError("META_DOMAIN_UNSEALED_FORWARD")


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    binding: EvaluationBinding
    observation: MetricObservation
    original_result: object = field(repr=False, compare=False)
    abi: str = DOMAIN_ABI

    def __post_init__(self):
        if self.abi != DOMAIN_ABI or not isinstance(self.binding, EvaluationBinding):
            raise MetaRecordError("META_DOMAIN_ABI_UNSUPPORTED")
        observation = self.observation
        if (not isinstance(observation, MetricObservation)
                or observation.input_signature != self.binding.input_signature
                or observation.window_start != utc(self.binding.index[0])
                or observation.window_end != utc(self.binding.index[-1])
                or observation.verification not in {"original_result", "original_native_score"}):
            raise MetaRecordError("META_DOMAIN_RESULT_UNBOUND")


@runtime_checkable
class DomainEvaluationAdapter(Protocol):
    """Execution is delegated to the existing owner; results are never replayed."""

    domain: str
    input_kind: InputKind

    def validate_market(self, data, index, folds): ...
    def bind_input(self, *, payload, index, params, stage, input_signature,
                   information_as_of, decision_sealed_at=None) -> EvaluationBinding: ...
    def evaluate(self, binding: EvaluationBinding, execute): ...
    def observe(self, binding: EvaluationBinding, result, *, metric_adapter,
                economics_id, prepared_witness=None) -> EvaluationEvidence: ...
    def observer_evaluator(self, data, fold, task): ...
    def finalize(self, result): ...
    def reset(self): ...
    def cancel(self): ...
    def clear(self): ...
