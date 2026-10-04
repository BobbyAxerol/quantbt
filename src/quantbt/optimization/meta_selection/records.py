"""Versioned task/IS/forward records; no market paths or account state retained."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping

import pandas as pd

from .common import MetaRecordError, digest, freeze, token, utc


class OutcomeStatus(str, Enum):
    VALID = "VALID"
    PENDING = "PENDING"
    OUTCOME_FAILED = "OUTCOME_FAILED"
    INCOMPLETE_WINDOW = "INCOMPLETE_WINDOW"
    CENSORED = "CENSORED"
    NO_VARIANCE = "NO_VARIANCE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True, slots=True)
class MetricContract:
    definition_id: str
    activity_definition_id: str
    trading_days: int = 365
    risk_free: float = 0.0
    sample_policy: str = "quantbt_array_daily_preferred_bar_fallback_ddof1_v1"

    def __post_init__(self):
        token(self.definition_id)
        token(self.activity_definition_id)
        if (
            type(self.trading_days) is not int
            or self.trading_days <= 0
            or not math.isfinite(self.risk_free)
        ):
            raise MetaRecordError("invalid annualization/risk-free contract")
        token(self.sample_policy)

    @property
    def metric_id(self):
        return digest({"schema": "qms-metric-v1", "contract": self})


@dataclass(frozen=True, slots=True)
class CompatibilityFamily:
    strategy_id: str
    parameter_schema_id: str
    descriptor_schema_id: str
    instrument_id: str
    timeframe: str
    window_policy_id: str
    metric_contract_id: str
    economics_id: str
    scorer_contract_id: str
    anchor_policy_id: str
    sampler_policy_id: str
    account_policy_id: str

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            token(getattr(self, name), name)

    @property
    def family_id(self):
        return digest({"schema": "qms-family-v1", "contract": self})


@dataclass(frozen=True, slots=True)
class MetricObservation:
    status: OutcomeStatus
    raw_sharpe: float | None
    activity_count: int | None
    sample_count: int
    sample_std: float | None
    metric_contract_id: str
    economics_id: str
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    input_frontier: pd.Timestamp
    initial_capital: float
    initial_mark_equity: float | None
    output_ref: str
    input_signature: str
    verification: str = "unverified"

    def __post_init__(self):
        object.__setattr__(self, "status", OutcomeStatus(self.status))
        for name in ("window_start", "window_end", "input_frontier"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if self.window_start > self.window_end or self.input_frontier > self.window_end:
            raise MetaRecordError("metric window/frontier mismatch")
        if (
            type(self.sample_count) is not int
            or self.sample_count < 0
            or self.initial_capital <= 0
            or not math.isfinite(self.initial_capital)
        ):
            raise MetaRecordError("invalid metric sample/base equity")
        if self.activity_count is not None and (
            type(self.activity_count) is not int or self.activity_count < 0
        ):
            raise MetaRecordError(
                "activity is a nonnegative count, not fills/turnover alias"
            )
        for name in ("raw_sharpe", "sample_std", "initial_mark_equity"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise MetaRecordError(f"nonfinite {name}; use a typed disposition")
        if self.sample_std is not None and self.sample_std < 0:
            raise MetaRecordError("negative variance support")
        for name in (
            "metric_contract_id",
            "economics_id",
            "output_ref",
            "input_signature",
        ):
            token(getattr(self, name), name)
        if self.verification not in {
            "original_result",
            "original_native_score",
            "unverified",
            "reviewed_import",
        }:
            raise MetaRecordError("unknown metric provenance verification")
        if self.status == OutcomeStatus.VALID and (
            self.raw_sharpe is None
            or self.sample_count < 2
            or self.sample_std is None
            or self.sample_std <= 0
            or self.initial_mark_equity is None
            or self.initial_mark_equity <= 0
            or self.verification == "unverified"
        ):
            raise MetaRecordError(
                "VALID requires authoritative finite sample/variance evidence"
            )


@dataclass(frozen=True, slots=True)
class CandidateISRecord:
    evaluation_id: str
    candidate_id: str
    native_trial_id: int
    requested_params: Mapping
    effective_params: Mapping
    objective: float
    observation: MetricObservation
    resolved_at: pd.Timestamp
    optional_is_features: Mapping

    def __post_init__(self):
        token(self.evaluation_id)
        token(self.candidate_id)
        if type(self.native_trial_id) is not int:
            raise MetaRecordError("native trial identity must be an integer")
        if not math.isfinite(self.objective):
            raise MetaRecordError("eligible IS record requires finite actual objective")
        for name in ("requested_params", "effective_params", "optional_is_features"):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        object.__setattr__(self, "resolved_at", utc(self.resolved_at))


@dataclass(frozen=True, slots=True)
class CandidateRoleRef:
    role: str
    policy_id: str
    evaluation_id: str

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            token(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class MetaTask:
    family: CompatibilityFamily
    corpus_id: str
    run_id: str
    origin: pd.Timestamp
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    forward_start: pd.Timestamp
    forward_end: pd.Timestamp
    data_cutoff: pd.Timestamp
    resolved_fold_seed: int
    candidates: tuple[CandidateISRecord, ...]
    anchor_candidate_evaluation_id: str
    roles: tuple[CandidateRoleRef, ...]
    search_completed_at: pd.Timestamp
    anchor_selected_at: pd.Timestamp
    decision_sealed_at: pd.Timestamp
    first_forward_action_at: pd.Timestamp
    wall_generated_at: pd.Timestamp
    clock_mode: str
    outcome_origin: str
    research_exposure: str
    sampling_provenance: Mapping

    def __post_init__(self):
        for name in ("corpus_id", "run_id", "outcome_origin", "research_exposure"):
            token(getattr(self, name), name)
        for name in (
            "origin",
            "is_start",
            "is_end",
            "forward_start",
            "forward_end",
            "data_cutoff",
            "search_completed_at",
            "anchor_selected_at",
            "decision_sealed_at",
            "first_forward_action_at",
            "wall_generated_at",
        ):
            object.__setattr__(self, name, utc(getattr(self, name)))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "roles", tuple(self.roles))
        object.__setattr__(
            self, "sampling_provenance", freeze(self.sampling_provenance)
        )
        if self.clock_mode not in {"historical_replay", "observed_live"}:
            raise MetaRecordError(
                "declare historical replay versus observed live clocks"
            )
        if type(self.resolved_fold_seed) is not int or self.resolved_fold_seed < 0:
            raise MetaRecordError("resolved fold seed must be a nonnegative integer")
        if not (
            self.is_start
            <= self.is_end
            <= self.data_cutoff
            < self.forward_start
            <= self.forward_end
        ):
            raise MetaRecordError("task IS/forward/cutoff ordering invalid")
        if not (
            self.data_cutoff <= self.search_completed_at <= self.decision_sealed_at
            and self.data_cutoff <= self.anchor_selected_at <= self.decision_sealed_at
            and self.decision_sealed_at
            <= self.first_forward_action_at
            <= self.forward_end
        ):
            raise MetaRecordError("completion/seal/economic-action ordering invalid")
        if self.first_forward_action_at < self.forward_start:
            raise MetaRecordError("forward economic action precedes forward window")
        if (
            self.clock_mode == "observed_live"
            and self.wall_generated_at < self.decision_sealed_at
        ):
            raise MetaRecordError("live task cannot be generated before actual sealing")
        ids = [c.evaluation_id for c in self.candidates]
        if (
            not ids
            or len(ids) != len(set(ids))
            or ids.count(self.anchor_candidate_evaluation_id) != 1
        ):
            raise MetaRecordError(
                "META_ANCHOR_INVALID: exactly one explicit anchor evaluation required"
            )
        anchor_roles = [r for r in self.roles if r.role == "native_anchor"]
        if (
            len(anchor_roles) != 1
            or anchor_roles[0].evaluation_id != self.anchor_candidate_evaluation_id
        ):
            raise MetaRecordError(
                "META_ANCHOR_INVALID: missing/duplicate native anchor role reference"
            )
        if any(r.evaluation_id not in ids for r in self.roles):
            raise MetaRecordError("role references an unknown evaluation")
        for c in self.candidates:
            m = c.observation
            if (
                m.metric_contract_id != self.family.metric_contract_id
                or m.economics_id != self.family.economics_id
                or m.window_start != self.is_start
                or m.window_end != self.is_end
                or m.input_frontier > self.data_cutoff
                or not (self.data_cutoff <= c.resolved_at <= self.decision_sealed_at)
            ):
                raise MetaRecordError(
                    "candidate IS origin/window/economics/frontier mismatch"
                )

    @property
    def task_id(self):
        return digest(
            {
                "schema": "qms-task-v1",
                "family": self.family.family_id,
                "corpus": self.corpus_id,
                "run": self.run_id,
                "origin": self.origin,
                "is": [self.is_start, self.is_end],
                "forward": [self.forward_start, self.forward_end],
                "cutoff": self.data_cutoff,
                "seed": self.resolved_fold_seed,
                "pool": sorted(c.evaluation_id for c in self.candidates),
                "anchor": self.anchor_candidate_evaluation_id,
                "sampling": self.sampling_provenance,
            }
        )

    @property
    def anchor(self):
        return next(
            c
            for c in self.candidates
            if c.evaluation_id == self.anchor_candidate_evaluation_id
        )


@dataclass(frozen=True, slots=True)
class CandidateForwardRecord:
    task_id: str
    evaluation_id: str
    observation: MetricObservation
    label_available_at: pd.Timestamp | None
    reporting_lag_seconds: float
    publication_order: int | None = None

    def __post_init__(self):
        token(self.task_id)
        token(self.evaluation_id)
        if (
            not math.isfinite(self.reporting_lag_seconds)
            or self.reporting_lag_seconds < 0
        ):
            raise MetaRecordError("invalid reporting lag")
        if self.observation.status == OutcomeStatus.PENDING:
            if self.label_available_at is not None:
                raise MetaRecordError(
                    "pending outcome has no actual label availability yet"
                )
        else:
            object.__setattr__(self, "label_available_at", utc(self.label_available_at))
        if (
            self.label_available_at is not None
            and self.label_available_at < self.nominal_maturity_at
        ):
            raise MetaRecordError("label precedes forward end/reporting lag")
        if self.publication_order is not None and (
            type(self.publication_order) is not int or self.publication_order < 0
        ):
            raise MetaRecordError("invalid publication event order")

    @property
    def nominal_maturity_at(self):
        return self.observation.window_end + pd.Timedelta(
            seconds=self.reporting_lag_seconds
        )
