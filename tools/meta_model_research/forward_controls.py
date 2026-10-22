"""Pure structural forecasts and an empirical, causal retention gate."""

from collections import defaultdict
import math

import numpy as np
import pandas as pd

from .decision_policy import choose


def structural_losses(rows):
    if not rows:
        raise ValueError("nonempty matched label rows required")
    models = set(rows[0]["predictions"])
    if models & {"Y_ZERO", "Y_IS"}:
        raise ValueError("reserved structural model name")
    origins = defaultdict(list)
    for r in rows:
        if set(r["predictions"]) != models:
            raise ValueError("exact model mask mismatch")
        if (
            not all(
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(v)
                for v in [
                    r["y"],
                    r["delta_is"],
                    r["weight"],
                    *r["predictions"].values(),
                ]
            )
            or r["weight"] <= 0
        ):
            raise ValueError("finite positive weighted matched observations required")
        origins[r["origin"]].append(r)
    result = {}
    for name in sorted(models | {"Y_ZERO", "Y_IS"}):
        by_origin = {}
        for origin, values in sorted(origins.items()):
            if not math.isclose(
                math.fsum(r["weight"] for r in values), 1, rel_tol=1e-10, abs_tol=1e-10
            ):
                raise ValueError("each complete origin must have unit weight")
            errors = []
            for r in values:
                yhat = (
                    0
                    if name == "Y_ZERO"
                    else r["delta_is"]
                    if name == "Y_IS"
                    else r["predictions"][name]
                )
                ey = yhat - r["y"]
                eq = (r["delta_is"] - yhat) - (r["delta_is"] - r["y"])
                if not math.isclose(ey, -eq, abs_tol=1e-10, rel_tol=1e-10):
                    raise ValueError("Y/Q error identity")
                errors.append((r["weight"], ey))
            by_origin[origin] = dict(
                mse=math.fsum(w * e * e for w, e in errors),
                mae=math.fsum(w * abs(e) for w, e in errors),
                labels=len(values),
            )
        result[name] = dict(
            mse=math.fsum(r["mse"] for r in by_origin.values()) / len(origins),
            mae=math.fsum(r["mae"] for r in by_origin.values()) / len(origins),
            origins=len(origins),
            labels=len(rows),
            by_origin=by_origin,
            Y_MSE_equals_Q_MSE=True,
        )
    for value in result.values():
        base = result["Y_IS"]["mse"]
        value["skill_vs_Q_ZERO"] = None if base == 0 else 1 - value["mse"] / base
    return dict(
        models=result,
        weighting="unit per origin, then equal-origin; exact common masks",
        origins=len(origins),
        labels=len(rows),
    )


def structural_choice(predictions, anchor, ranking):
    if ranking not in ("min_y", "max_q"):
        raise ValueError("structural ranking")
    scored = [p for p in predictions if p["yhat"] is not None]
    if not scored:
        return dict(status="NOT_SCORED", winner=anchor, same_anchor=True)
    ai = next(p["raw_is"] for p in scored if p["evaluation_id"] == anchor)
    values = [dict(p, yhat=p["raw_is"] - ai, qhat=0.0) for p in scored]
    selected = choose(values, anchor, "R" if ranking == "min_y" else "F")
    return dict(
        status="CHECKED",
        winner=selected["winner"],
        same_anchor=selected["winner"] == anchor,
    )


def retention_gate(rows, *, current_month, cutoff):
    current = pd.Period(current_month, freq="M")
    clock = pd.Timestamp(cutoff)
    if clock.tzinfo is None:
        raise ValueError("timezone-aware cutoff required")
    available = {}
    for r in rows:
        month = pd.Period(r["month"], freq="M")
        if month >= current:
            continue
        published = pd.Timestamp(r["available_at"])
        if published.tzinfo is None:
            raise ValueError("timezone-aware label availability required")
        if published > clock:
            continue
        if month in available:
            raise ValueError("duplicate published origin")
        available[month] = r
    if not available:
        return dict(
            accepted=False,
            reason="NO_PUBLISHED_HISTORY",
            mean_Q=None,
            count=0,
            used_months=[],
        )
    end = max(available)
    months = [end - i for i in range(11, -1, -1)]
    values = []
    for month in months:
        r = available.get(month)
        if r is None or r["status"] != "VALID":
            continue
        value = r["Q"]
        if (
            not isinstance(value, (float, int))
            or isinstance(value, bool)
            or not np.isfinite(value)
        ):
            raise ValueError("VALID retention observation must be finite")
        values.append(float(value))
    mean = math.fsum(values) / 12 if len(values) == 12 else None
    return dict(
        accepted=mean is not None and mean > 0,
        reason="ACCEPT_PAST_MEAN_POSITIVE"
        if mean is not None and mean > 0
        else "INSUFFICIENT_COMPLETE_CALENDAR"
        if mean is None
        else "NONPOSITIVE_PAST_MEAN",
        mean_Q=mean,
        count=len(values),
        used_months=[str(m) for m in months],
        window_end=str(end),
        age_months=current.ordinal - end.ordinal,
    )
