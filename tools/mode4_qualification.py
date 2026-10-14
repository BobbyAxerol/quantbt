"""Public M5-11.6 contract only; no finance, selection or inference execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from math import fsum, isclose, isfinite


def _utc(year, month, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Mode4Protocol:
    alpha_ids: tuple[str, ...] = ("A-SC", "A-HMA", "A-HASH", "A-VWAP")
    is_start: datetime = _utc(2020, 1)
    oos_start: datetime = _utc(2022, 1)
    oos_stop: datetime = _utc(2026, 10)
    source_stop: datetime = _utc(2026, 10, 6)
    trials_per_fold: int = 128
    seed: int = 731  # Existing runner owns fold-seed derivation.

    @property
    def fold_count(self):
        return 12 * (self.oos_stop.year - self.oos_start.year) + self.oos_stop.month - self.oos_start.month

    @property
    def proposal_slots(self):
        return len(self.alpha_ids) * self.fold_count * self.trials_per_fold


PROTOCOL = Mode4Protocol()


@dataclass(frozen=True)
class FoldWindow:
    fold_id: str
    role: str
    is_start: datetime
    is_stop: datetime
    oos_start: datetime
    oos_stop: datetime

    @property
    def information_as_of(self):
        return self.is_stop


def build_windows():
    """Half-open UTC windows; cutoff is not a seal/effective/publication clock."""
    windows, start = [], PROTOCOL.oos_start
    while start < PROTOCOL.oos_stop:
        stop = _utc(start.year + (start.month == 12), start.month % 12 + 1)
        role = "history" if start < _utc(2023, 2) else "development" if start < _utc(2024, 2) else "evaluation"
        windows.append(FoldWindow(start.strftime("%Y-%m"), role, PROTOCOL.is_start, start, start, stop))
        start = stop
    return tuple(windows)


def _finite(value):
    return type(value) in (int, float) and isfinite(value)


def _raw(observation):
    if observation is None:
        return None, "MISSING"
    if not isinstance(observation, Mapping):
        return None, "INVALID_OBSERVATION"
    status = observation.get("status")
    if status != "VALID":
        return None, status if status in {"NO_VARIANCE", "INSUFFICIENT_SAMPLE", "INCOMPLETE_WINDOW", "OUTCOME_FAILED", "CENSORED"} else "INVALID_STATUS"
    value, std, count = (observation.get(k) for k in ("raw_sharpe", "sample_std", "sample_count"))
    if not _finite(value) or not _finite(std) or type(count) is not int or count < 2 or std <= 0:
        return None, "UNDEFINED_OR_INVALID_RAW_SHARPE"
    if not all(isinstance(observation.get(k), str) and observation[k] for k in ("metric_contract_id", "economics_id")):
        return None, "MISSING_METRIC_IDENTITY"
    return value, None


def measure_pair(alpha_id, fold_id, observations):
    """Reduce independently obtained original raw metrics, never objectives/returns."""
    windows = {w.fold_id: w for w in build_windows()}
    if alpha_id not in PROTOCOL.alpha_ids or fold_id not in windows:
        raise ValueError("registered alpha and monthly fold required")
    names = ("native_is", "native_forward", "meta_is", "meta_forward")
    if not isinstance(observations, Mapping) or set(observations) - set(names):
        raise ValueError("expected four named original metric observations")
    values = [_raw(observations.get(name)) for name in names]
    reasons = [f"{name}:{reason}" for name, (_, reason) in zip(names, values) if reason]
    if not reasons and len({(o["metric_contract_id"], o["economics_id"]) for o in observations.values()}) != 1:
        reasons.append("INCOMPATIBLE_METRIC_OR_ECONOMICS")
    metrics = dict.fromkeys(("D_native", "D_meta", "IS_effect", "R", "Q", "identity_residual"))
    flags = []
    if not reasons:
        ni, nf, mi, mf = (v for v, _ in values)
        dn, dm, effect, q = ni - nf, mi - mf, ni - mi, mf - nf
        r = dn - dm
        if not all(_finite(v) for v in (dn, dm, effect, q, r, effect + q, r - (effect + q))):
            reasons.append("NONFINITE_CONTRAST")
        elif not isclose(r, effect + q, rel_tol=1e-12, abs_tol=1e-12):
            reasons.append("RQ_IDENTITY_MISMATCH")
        else:
            metrics.update(D_native=dn, D_meta=dm, IS_effect=effect, R=r, Q=q, identity_residual=r - (effect + q))
            if r > 0 and q <= 0:
                flags.append("LOWER_IS_ONLY" if q == 0 else "LOWER_IS_DESPITE_WORSE_FORWARD")
    status = "MISSING" if any(reason == "MISSING" for _, reason in values) else "INVALID" if reasons else "PAIRED_VALID"
    return dict(alpha_id=alpha_id, fold_id=fold_id, role=windows[fold_id].role, status=status,
                reasons=reasons, **metrics, flags=flags, economic_winner_claim=False)


def paired_report(alpha_id, folds):
    """Keep calendar gaps; descriptive evaluation means are not account Sharpe/CI."""
    if set(folds) - {w.fold_id for w in build_windows()}:
        raise ValueError("unregistered fold")
    rows = [measure_pair(alpha_id, w.fold_id, folds.get(w.fold_id, {})) for w in build_windows()]
    evaluation = [r for r in rows if r["role"] == "evaluation"]
    valid = [r for r in evaluation if r["status"] == "PAIRED_VALID"]
    return dict(rows=rows, counts={s: sum(r["status"] == s for r in rows) for s in ("PAIRED_VALID", "MISSING", "INVALID")},
                evaluation_pair_mask=[r["status"] == "PAIRED_VALID" for r in evaluation],
                evaluation_means={k: fsum(r[k] / len(valid) for r in valid) if valid else None for k in ("R", "Q", "IS_effect")},
                evaluation_support_limited=len(valid) < 12, inference="NOT_COMPUTED", economic_winner_claim=False)


def _pin(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def phase_registration(*, route_witnesses=None, budget=None):
    """Check externally verified receipts, not issue route/economic certification.

    Generic correctness PASS cannot replace actual inventory-carry witnesses or
    earliest/middle/latest horizon measurements for every registered alpha.
    """
    routes, b, blockers = route_witnesses or {}, budget or {}, []
    for alpha in PROTOCOL.alpha_ids:
        witness = routes.get(alpha, {})
        if not (witness.get("status") == "PASS"
                and all(_pin(witness.get(k)) for k in ("binding_identity", "diagnostic_reset_witness", "continuous_carry_witness"))
                and type(witness.get("carried_inventory_boundaries")) is int and witness["carried_inventory_boundaries"] > 0
                and all(witness.get(k) is True for k in ("actual_route", "strategy_state_preserved", "pending_orders_preserved", "event_clock_preserved"))
                and witness.get("forced_flatten") is False):
            blockers.append(f"{alpha}:ACTUAL_ROUTE_CARRY_NOT_QUALIFIED")
    horizons = ("2022-01", "2024-01", "2026-09")
    pilots = b.get("horizon_witnesses", {})
    if not all(all(_pin(pilots.get(a, {}).get(h)) for h in horizons) for a in PROTOCOL.alpha_ids):
        blockers.append("FOUR_ALPHA_HORIZON_MEASUREMENTS_REQUIRED")
    timings = ("p50_seconds", "p95_seconds", "forecast_seconds", "wall_limit_seconds")
    sizes = ("measured_peak_rss_bytes", "forecast_peak_rss_bytes", "rss_limit_bytes", "available_ram_bytes",
             "measured_peak_disk_bytes", "forecast_scratch_bytes", "forecast_retained_bytes", "free_disk_bytes", "thread_limit")
    measured = (b.get("status") == "MEASURED" and _pin(b.get("measurement_identity"))
                and type(b.get("workers")) is int and b["workers"] == 1
                and type(b.get("proposal_slots")) is int and b["proposal_slots"] == PROTOCOL.proposal_slots
                and b.get("includes_auxiliary_work") is True
                and all(_finite(b.get(k)) and b[k] > 0 for k in timings)
                and all(type(b.get(k)) is int and b[k] > 0 for k in sizes))
    if not measured:
        blockers.append("MEASURED_WHOLE_RUN_BUDGET_REQUIRED")
    elif not (b["p50_seconds"] <= b["p95_seconds"] <= b["forecast_seconds"] <= b["wall_limit_seconds"]
              and b["measured_peak_rss_bytes"] <= b["forecast_peak_rss_bytes"] <= b["rss_limit_bytes"] <= min(2 * 1024**3, b["available_ram_bytes"])
              and b["measured_peak_disk_bytes"] <= b["forecast_scratch_bytes"] + b["forecast_retained_bytes"]
              and b["forecast_scratch_bytes"] <= 256 * 1024**2 and b["forecast_retained_bytes"] <= 1024**3
              and b["free_disk_bytes"] >= 5 * 1024**3 + b["forecast_scratch_bytes"] + b["forecast_retained_bytes"]):
        blockers.append("RESOURCE_ENVELOPE_EXCEEDED")
    return dict(phase="M5-11.6", proposal_slots=PROTOCOL.proposal_slots,
                long_launch_admitted=not blockers, blockers=blockers, economic_winner_claim=False)
