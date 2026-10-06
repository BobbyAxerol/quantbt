"""Serializable opt-in policy and preflight, independent of financial engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .common import MetaRecordError
from .model import RidgeSettings
from .numerics import NumericRuntime


@dataclass(frozen=True, slots=True)
class MetaSelectionConfig:
    mode: str = "off"
    learner: str = "ridge_origin_sum_v1"
    lambda_reg: float = 10.0
    min_matured_origins: int = 12
    q_hat_floor: float = -0.10
    tie_tolerance: float = 1e-10
    native_batch_policy: str = "auto"
    label_observer: bool = False
    reporting_lag_seconds: float = 1.0
    full_ranking: bool = False
    max_folds: int = 256
    schema_version: str = "qms-public-policy-v1"

    def __post_init__(self):
        if self.mode not in {"off", "shadow", "active"}:
            raise MetaRecordError("META_CONFIG_INVALID: meta_selection.mode")
        if (
            self.learner != "ridge_origin_sum_v1"
            or self.schema_version != "qms-public-policy-v1"
        ):
            raise MetaRecordError("META_CONFIG_INVALID: learner/schema_version")
        if self.native_batch_policy not in {"auto", "require", "reference"}:
            raise MetaRecordError("META_CONFIG_INVALID: native_batch_policy")
        if any(
            type(getattr(self, k)) is not bool
            for k in ("label_observer", "full_ranking")
        ):
            raise MetaRecordError("META_CONFIG_INVALID: boolean policy required")
        import math

        if (
            not math.isfinite(self.reporting_lag_seconds)
            or self.reporting_lag_seconds < 0
            or type(self.max_folds) is not int
            or self.max_folds <= 0
        ):
            raise MetaRecordError("META_CONFIG_INVALID: lag/capacity")
        self.ridge_settings()

    def ridge_settings(self):
        return RidgeSettings(
            lambda_reg=self.lambda_reg,
            min_matured_origins=self.min_matured_origins,
            epsilon=-self.q_hat_floor,
            tie_tolerance=self.tie_tolerance,
        )


def normalize_meta_config(value):
    if value is None:
        return None
    if not isinstance(value, MetaSelectionConfig):
        if not isinstance(value, Mapping):
            raise MetaRecordError(
                "META_CONFIG_INVALID: meta_selection must be a policy mapping"
            )
        try:
            value = MetaSelectionConfig(**dict(value))
        except TypeError as exc:
            raise MetaRecordError(
                "META_CONFIG_INVALID: unknown or invalid meta_selection field"
            ) from exc
    return None if value.mode == "off" else value


def validate_meta_route(config, *, route="target_series"):
    if config.meta_selection is None:
        return
    requested = f"{config.optimization_mode}/{config.optimization_schedule}/{config.target_mode}"
    reactive = route == "reactive_reset"
    if route not in {"target_series", "reactive_reset"}:
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: unknown route")
    from .domains.scalar_contract import SCALAR_ROUTES, canonical_scalar_route
    if (
        config.optimization_mode != "mode_4_is_only_robust"
        or config.optimization_schedule != "per_fold_causal"
    ):
        raise MetaRecordError(
            f"META_METHODOLOGY_UNSUPPORTED: {requested}; supported Mode 4/per_fold_causal; disable meta for legacy behavior"
        )
    if (
        canonical_scalar_route(config.target_mode) not in (
            {"signal_notional", "pct_equity"} if reactive else SCALAR_ROUTES | {"portfolio", "basket", "arbitrage"})
        or config.scoring_backend != "endpoint"
        or config.calendar_contract != "exact_v2"
        or config.strategy_lifecycle_policy != "isolated_v1"
        or config.fold_account_policy != ("reset_flat" if reactive else "carry_position")
        or (not reactive and config.metadata.get("use_scalar_trial_scoring", True)
            and config.metadata.get("native_prepared_wfo", "off") == "off")
    ):
        raise MetaRecordError(
            f"META_ROUTE_UNSUPPORTED: {requested}; requires exact endpoint, isolated_v1 and declared {'reset_flat' if reactive else 'carry_position'} account with authoritative original-result or prepared witness"
        )
    if config.optuna_trials <= 0:
        raise MetaRecordError(
            "META_METHODOLOGY_UNSUPPORTED: meta requires optimizing param_ranges, not fixed params"
        )


@dataclass(frozen=True, slots=True)
class MetaHistoryContext:
    """Caller-owned runtime handle. Never place this object in static config.

    The clock callback, if provided, returns explicit historical-replay stage
    completion times. It receives (fold, stage, measured_elapsed_seconds).
    This route does not certify observed-live readiness or send broker orders.
    """

    history: object
    corpus_id: str
    instrument_id: str
    timeframe: str
    run_id: str
    authorized_corpora: tuple[str, ...] = ()
    outcome_origins: tuple[str, ...] = ("historical_counterfactual",)
    research_exposures: tuple[str, ...] = ("research_only",)
    clock: object = field(default=None, repr=False, compare=False)
    native_module: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        from .common import token
        from .history import MetaHistory

        if not isinstance(self.history, MetaHistory):
            raise MetaRecordError(
                "META_HISTORY_INCOMPATIBLE: MetaHistory instance required"
            )
        for k in ("corpus_id", "instrument_id", "timeframe", "run_id"):
            token(getattr(self, k), k)
        if self.clock is not None and not callable(self.clock):
            raise MetaRecordError(
                "META_CLOCK_INVALID: completion clock must be callable"
            )
        for k in ("authorized_corpora", "outcome_origins", "research_exposures"):
            values = tuple(sorted(set(getattr(self, k))))
            if k == "authorized_corpora" and not values:
                values = (self.corpus_id,)
            if not values or (
                k == "authorized_corpora" and self.corpus_id not in values
            ):
                raise MetaRecordError(
                    "META_HISTORY_INCOMPATIBLE: explicit permission set required"
                )
            for value in values:
                token(value)
            object.__setattr__(self, k, values)
        if (
            "historical_counterfactual" not in self.outcome_origins
            or "research_only" not in self.research_exposures
        ):
            raise MetaRecordError(
                "META_HISTORY_INCOMPATIBLE: public replay writes historical_counterfactual/research_only"
            )

    def numeric_runtime(self, policy):
        return NumericRuntime(native_policy=policy, native_module=self.native_module)
