"""Registered quarterly raw-metric contrasts, not financial outputs or selectors.

Inputs are caller-qualified original MetricObservations. Missing observations
stay missing; no account, equity, metric, label or selection is manufactured.
The primary estimand is the equal-quarter mean over all 19 registered quarters.
Available-pair and fitted-meta summaries are explicitly descriptive, not an
alternate estimand for a failed complete-family inference.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isclose, isfinite
from types import MappingProxyType

import numpy as np
import pandas as pd

from quantbt.optimization.meta_selection.common import token
from quantbt.optimization.meta_selection.records import MetricObservation, OutcomeStatus

from .contracts import quarterly_calendar


PRIMARY_ALPHAS = ("A-SC", "A-HMA", "A-HASH", "A-VWAP")
COORDINATES = tuple((alpha, name) for alpha in PRIMARY_ALPHAS for name in ("R", "Q"))
BLOCK_QUARTERS = 2
BOOTSTRAP_DRAWS = 16_384
BOOTSTRAP_SEED = 731
FAMILY_CONFIDENCE = .95
MARGINAL_CONFIDENCE = 1. - (1. - FAMILY_CONFIDENCE) / len(COORDINATES)
MIN_PAIRED_QUARTERS = 12
MIN_PAIRED_CALENDAR_DAYS = 365
_FOLDS = quarterly_calendar()
_BY_ID = {fold.fold_id: fold for fold in _FOLDS}
_OBSERVATIONS = ("reference_is", "reference_forward", "policy_is", "policy_forward")
_METRICS = ("D_reference", "D_policy", "IS_effect", "R", "Q", "identity_residual")
_HOUR = pd.Timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ContrastScope:
    """A caller-registered policy comparison; different anchors never pool.

    ``primary_recipe`` means the registered challenger sampler/native selector,
    meta OFF, against legacy/native. Other factorial or meta comparisons must
    use ``descriptive`` or ``mature_meta``. Policy IDs are immutable caller
    identities including the appropriate sampler/anchor/version, not outcomes.
    """

    contrast_id: str
    reference_kind: str
    reference_policy_id: str
    policy_id: str
    analysis_role: str = "descriptive"

    def __post_init__(self):
        for name in ("contrast_id", "reference_policy_id", "policy_id"):
            token(getattr(self, name), name)
        if self.reference_kind not in {"own_anchor", "legacy_reference"}:
            raise ValueError("reference_kind must be own_anchor or legacy_reference")
        if self.analysis_role not in {"primary_recipe", "descriptive", "mature_meta"}:
            raise ValueError("unknown registered analysis role")
        if self.analysis_role == "primary_recipe" and self.reference_kind != "legacy_reference":
            raise ValueError("primary recipe requires the legacy_reference, not an own_anchor")


@dataclass(frozen=True, slots=True)
class QuarterlyContrast:
    alpha_id: str
    fold_id: str
    fold_identity: str
    scope: ContrastScope
    observations: Mapping[str, MetricObservation | None]
    status: str
    reasons: tuple[str, ...]
    metrics: Mapping[str, float | None]
    flags: tuple[str, ...]
    meta_fitted: bool
    matured_origins: int | None

    @property
    def contrast_labels(self):
        suffix = "meta" if self.scope.reference_kind == "own_anchor" else "ref"
        return MappingProxyType({"R": f"R_{suffix}", "Q": f"Q_{suffix}"})


def measure_quarter(alpha_id: str, fold_id: str,
                    observations: Mapping[str, MetricObservation | None], *,
                    scope: ContrastScope, meta_fitted: bool = False,
                    matured_origins: int | None = None) -> QuarterlyContrast:
    """Compute R=(Iref-Oref)-(Ipolicy-Opolicy)=IS_effect+Q.

    Observation bounds are actual inclusive 1h bar endpoints, while the
    registered fold calendar has exclusive ends. IS/FWD input frontiers must
    reach those endpoints; same-role arms must witness the same market input.
    No claim is made to re-verify the original financial paths from scalars.
    """
    token(alpha_id, "alpha_id")
    if fold_id not in _BY_ID or not isinstance(scope, ContrastScope):
        raise ValueError("registered quarter and typed ContrastScope required")
    if not isinstance(observations, Mapping) or set(observations) - set(_OBSERVATIONS):
        raise ValueError("expected four named original metric observations")
    if type(meta_fitted) is not bool:
        raise TypeError("meta_fitted must be a boolean")
    position = next(i for i, fold in enumerate(_FOLDS) if fold.fold_id == fold_id)
    # Fresh 2022 histories and the registered publication lag exclude the
    # just-finished origin at the next decision: first possible fit is 2025Q2.
    if matured_origins is not None and (type(matured_origins) is not int
            or not 0 <= matured_origins <= max(0, position - 1)):
        raise ValueError("matured origins exceed the registered quarterly history frontier")
    if meta_fitted and (matured_origins is None or matured_origins < 12):
        raise ValueError("fitted meta requires twelve genuinely matured prior origins")
    if scope.analysis_role == "primary_recipe" and (meta_fitted or matured_origins is not None):
        raise ValueError("primary recipe is meta OFF; meta cohorts are descriptive")
    obs = {name: observations.get(name) for name in _OBSERVATIONS}
    if any(o is not None and not isinstance(o, MetricObservation) for o in obs.values()):
        raise TypeError("qualified MetricObservation inputs required, not financial dictionaries")
    fold = _BY_ID[fold_id]
    reasons, incompatibilities = [], []
    for name, o in obs.items():
        if o is None:
            reasons.append(f"{name}:MISSING")
            continue
        if o.status != OutcomeStatus.VALID:
            reasons.append(f"{name}:{o.status.value}")
        start, end = ((fold.is_start, fold.is_end) if name.endswith("_is")
                      else (fold.oos_start, fold.oos_end))
        if (o.window_start != pd.Timestamp(start) or o.window_end != pd.Timestamp(end) - _HOUR
                or o.input_frontier != o.window_end):
            incompatibilities.append(f"{name}:WINDOW_OR_FRONTIER_MISMATCH")
    present = [o for o in obs.values() if o is not None]
    for field in ("metric_contract_id", "economics_id", "initial_capital"):
        if len({getattr(o, field) for o in present}) > 1:
            incompatibilities.append(f"INCOMPATIBLE_{field.upper()}")
    for role in ("is", "forward"):
        a, b = obs[f"reference_{role}"], obs[f"policy_{role}"]
        if a is not None and b is not None and a.input_signature != b.input_signature:
            incompatibilities.append(f"{role}:MARKET_INPUT_MISMATCH")
    reasons.extend(incompatibilities)
    metrics, flags = dict.fromkeys(_METRICS), []
    if not reasons:
        iref, oref, ipolicy, opolicy = (obs[name].raw_sharpe for name in _OBSERVATIONS)
        dref, dpolicy = iref - oref, ipolicy - opolicy
        effect, q, r = iref - ipolicy, opolicy - oref, dref - dpolicy
        residual = r - (effect + q)
        values = (dref, dpolicy, effect, r, q, residual)
        if not all(isfinite(v) for v in (*values, effect + q)):
            reasons.append("NONFINITE_CONTRAST")
        elif not isclose(r, effect + q, rel_tol=1e-12, abs_tol=1e-12):
            reasons.append("RQ_IDENTITY_MISMATCH")
        else:
            metrics.update(zip(_METRICS, values, strict=True))
            if effect > 0:
                flags.append("LOWER_IS_CONTRIBUTION")
            if r > 0 and q <= 0:
                flags.append("LOWER_IS_ONLY" if q == 0 else "LOWER_IS_DESPITE_WORSE_FORWARD")
    status = ("MISSING" if any(o is None for o in obs.values()) else
              "INCOMPATIBLE" if incompatibilities else "UNSUPPORTED" if reasons else "PAIRED_VALID")
    return QuarterlyContrast(alpha_id, fold_id, fold.identity, scope, MappingProxyType(obs),
        status, tuple(reasons), MappingProxyType(metrics), tuple(flags), meta_fitted, matured_origins)


def _mean(rows, name):
    if not rows:
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        value = float(np.mean([row.metrics[name] for row in rows]))
    return value if isfinite(value) else None


def summarize_quarters(alpha_id: str, contrasts: Iterable[QuarterlyContrast]) -> dict:
    """Keep all 19 slots and original dispositions; available means descriptive.

    Gaps are not compressed for inference. A missing entire alpha is supported
    as an all-missing report, not a coordinate removed from the family.
    """
    token(alpha_id, "alpha_id")
    by_id = {}
    for row in contrasts:
        if not isinstance(row, QuarterlyContrast):
            raise TypeError("per-quarter QuarterlyContrast observations required")
        if row.alpha_id != alpha_id or row.fold_id not in _BY_ID:
            raise ValueError("contrast alpha/quarter does not match the registered slots")
        if row.fold_id in by_id:
            raise ValueError("duplicate quarterly contrast")
        # Re-reduce immutable source observations, not caller-invented metrics.
        checked = measure_quarter(alpha_id, row.fold_id, row.observations, scope=row.scope,
            meta_fitted=row.meta_fitted, matured_origins=row.matured_origins)
        if checked != row:
            raise ValueError("contrast differs from its original metric observations")
        by_id[row.fold_id] = row
    rows = tuple(by_id.get(fold.fold_id) for fold in _FOLDS)
    valid = [row for row in rows if row is not None and row.status == "PAIRED_VALID"]
    reasons = []
    scopes = {row.scope for row in by_id.values()}
    if len(scopes) > 1:
        reasons.append("MIXED_CONTRAST_OR_ANCHOR_SCOPE")
    identities = {(o.metric_contract_id, o.economics_id, o.initial_capital)
                  for row in by_id.values() for o in row.observations.values() if o is not None}
    if len(identities) > 1:
        reasons.append("METRIC_OR_ECONOMICS_CHANGED_ACROSS_QUARTERS")
    days = sum((_BY_ID[row.fold_id].oos_end - _BY_ID[row.fold_id].oos_start).days for row in valid)
    means = {name: _mean(valid, name) for name in _METRICS}
    if valid and any(value is None for value in means.values()):
        reasons.append("NONFINITE_CONTRAST_MEAN")
    if reasons:
        means = dict.fromkeys(_METRICS)
    mature = [row for row in valid if row.meta_fitted and row.matured_origins >= 12]
    return dict(alpha_id=alpha_id, slots=tuple(f.fold_id for f in _FOLDS), windows=_FOLDS, rows=rows,
        observation_window_convention="inclusive_hourly_bar_endpoints",
        slot_status=tuple(row.status if row is not None else "MISSING" for row in rows),
        paired_mask=tuple(row is not None and row.status == "PAIRED_VALID" for row in rows),
        paired_quarters=len(valid), paired_calendar_days=days,
        minimum_support_met=len(valid) >= MIN_PAIRED_QUARTERS and days >= MIN_PAIRED_CALENDAR_DAYS,
        complete_all_quarters=len(valid) == len(_FOLDS), reasons=tuple(reasons),
        available_pair_means_descriptive=means,
        all_quarter_means=means if len(valid) == len(_FOLDS) and not reasons else None,
        mature_meta=dict(fold_ids=tuple(row.fold_id for row in mature), quarters=len(mature),
            means={name: _mean(mature, name) if not reasons else None for name in _METRICS},
            descriptive_only=True, twelve_mature_evaluation_quarters=False,
            promotion_claim=False))


def infer_primary_family(contrasts: Mapping[str, Iterable[QuarterlyContrast]]) -> dict:
    """Joint percentile MBB over the fixed 19x8 matrix, no gap/column removal.

    Twelve paired quarters and 365 paired days are necessary support floors,
    not permission to replace the registered all-19 estimand with available
    cases. Any incomplete/incompatible family stays INCONCLUSIVE. Other scopes
    receive their descriptive reports but never primary intervals or gates.
    Bounds condition on observed selection; no pipeline/seed robustness claim.
    """
    if not isinstance(contrasts, Mapping) or set(contrasts) - set(PRIMARY_ALPHAS):
        raise ValueError("primary family has exactly four registered alphas; RSI is reference-only")
    reports = {alpha: summarize_quarters(alpha, contrasts.get(alpha, ())) for alpha in PRIMARY_ALPHAS}
    reasons = []
    for alpha, report in reports.items():
        reasons.extend(f"{alpha}:{reason}" for reason in report["reasons"])
        if not report["minimum_support_met"]:
            reasons.append(f"{alpha}:INSUFFICIENT_PAIRED_QUARTERS_OR_CALENDAR")
        if not report["complete_all_quarters"]:
            reasons.append(f"{alpha}:INCOMPLETE_19_QUARTER_FAMILY_PATTERN")
        if any(row is not None and row.scope.analysis_role != "primary_recipe"
               for row in report["rows"]):
            reasons.append(f"{alpha}:DESCRIPTIVE_SCOPE_NOT_PRIMARY")
    identities = {(o.metric_contract_id, o.economics_id, o.initial_capital)
                  for summary in reports.values() for row in summary["rows"] if row is not None
                  for o in row.observations.values() if o is not None}
    if len(identities) > 1:
        reasons.append("INCOMPATIBLE_FAMILY_METRIC_OR_ECONOMICS")
    coordinates = [dict(alpha_id=alpha, metric=name,
        mean=reports[alpha]["all_quarter_means"][name] if reports[alpha]["all_quarter_means"] else None,
        available_pair_mean_descriptive=reports[alpha]["available_pair_means_descriptive"][name],
        lower=None, upper=None, status="INCONCLUSIVE") for alpha, name in COORDINATES]
    report = dict(schema="m51161.quarterly-rq-family.v1", status="INCONCLUSIVE",
        reasons=tuple(reasons), alphas=reports, coordinates=coordinates,
        directional_gates={alpha: None for alpha in PRIMARY_ALPHAS},
        registration=dict(calendar_slots=tuple(f.fold_id for f in _FOLDS),
            estimand="equal_quarter_mean_over_all_19", coordinates=COORDINATES,
            minimum_paired_quarters=MIN_PAIRED_QUARTERS,
            minimum_paired_calendar_days=MIN_PAIRED_CALENDAR_DAYS,
            bootstrap_owner="arch.bootstrap.MovingBlockBootstrap", block_quarters=BLOCK_QUARTERS,
            draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED, method="percentile", tail="two",
            family_confidence=FAMILY_CONFIDENCE, family_size=len(COORDINATES),
            marginal_confidence=MARGINAL_CONFIDENCE, missing_policy="no_imputation_or_coordinate_removal"),
        inference_scope="conditional_on_observed_selection_not_pipeline_or_sampler_seed_robustness",
        economic_promotion=False, mature_meta_promotion=False)
    if reasons:
        return report
    values = np.array([[reports[alpha]["rows"][i].metrics[name] for alpha, name in COORDINATES]
                       for i in range(len(_FOLDS))], dtype=np.float64)
    try:
        from arch import __version__ as arch_version
        from arch.bootstrap import MovingBlockBootstrap
    except ImportError:
        report["reasons"] = ("BOOTSTRAP_OWNER_UNAVAILABLE",)
        return report
    report["registration"]["bootstrap_owner_version"] = arch_version
    try:
        with np.errstate(over="raise", invalid="raise"):
            bounds = MovingBlockBootstrap(BLOCK_QUARTERS, values, seed=BOOTSTRAP_SEED).conf_int(
                lambda a: a.mean(axis=0), reps=BOOTSTRAP_DRAWS,
                method="percentile", size=MARGINAL_CONFIDENCE, tail="two")
    except (ValueError, FloatingPointError, OverflowError) as error:
        report["reasons"] = (f"BOOTSTRAP_NUMERICAL_FAILURE:{type(error).__name__}",)
        return report
    if (bounds.shape != (2, len(COORDINATES)) or not np.isfinite(bounds).all()
            or np.any(bounds[0] > bounds[1])):
        report["reasons"] = ("BOOTSTRAP_BOUNDS_INVALID",)
        return report
    for column, coordinate in enumerate(coordinates):
        coordinate.update(lower=float(bounds[0, column]), upper=float(bounds[1, column]),
                          status="INTERVALS_COMPUTED")
    report["status"] = "INTERVALS_COMPUTED"
    report["directional_gates"] = {alpha: bool(bounds[0, 2 * i] > 0 and bounds[0, 2 * i + 1] >= 0)
                                  for i, alpha in enumerate(PRIMARY_ALPHAS)}
    return report
