"""Pure saved-output analysis: no execution, selection, fitting or market access."""

from __future__ import annotations

import math
from datetime import datetime


def empirical_disposition(registration=None):
    """Do not turn a synthetic smoke or unspecified budget into market evidence."""
    if registration is None:
        return {
            "status": "EMPIRICAL_VALIDATION_NOT_RUN",
            "reason": "No approved alpha/BTC data, calendar and economic budget registration",
            "attempted_trials": 0,
            "matured_origins": 0,
            "development_folds": 0,
            "paired_valid_locked_folds": 0,
            "market_gain": None,
            "live_certified": False,
        }
    required = {
        "data_digest",
        "alpha_identity",
        "samplers",
        "attempted_trials_per_cutoff",
        "matured_origins",
        "development_folds",
        "locked_folds",
        "owner_decision_ref",
    }
    if set(registration) != required or any(
        not isinstance(registration[k], str) or not registration[k].strip()
        for k in ("data_digest", "alpha_identity", "owner_decision_ref")
    ):
        raise ValueError("economic registration incomplete or unapproved")
    samplers = registration["samplers"]
    if (
        not isinstance(samplers, list)
        or not 1 <= len(samplers) <= 2
        or any(
            s not in {"tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"}
            for s in samplers
        )
        or len(set(samplers)) != len(samplers)
        or any(
            type(registration[k]) is not int
            for k in (
                "attempted_trials_per_cutoff",
                "matured_origins",
                "development_folds",
                "locked_folds",
            )
        )
    ):
        raise ValueError("economic registration types/recipes invalid")
    if (
        registration["development_folds"] not in (0,)
        and registration["development_folds"] < 12
        or registration["attempted_trials_per_cutoff"] < 128
        or registration["matured_origins"] < 12
        or registration["locked_folds"] < 12
    ):
        raise ValueError("economic support/trial/fold budget insufficient")
    return {
        "status": "REGISTERED_NOT_EXECUTED",
        "registration": dict(registration),
        "market_gain": None,
        "live_certified": False,
    }


def paired_decomposition(rows):
    """Mean fold decay is not continuous-account Sharpe or an edge certificate.

    Undefined windows retain their status/calendar. Only independently valid
    native/meta pairs enter the explicitly named paired-valid estimand.
    """
    output, identities = [], set()
    for row in rows:
        if set(row) != {"fold_id", "start", "end", "native", "meta"}:
            raise ValueError("paired row schema mismatch")
        if not (
            type(row["fold_id"]) is int
            or isinstance(row["fold_id"], str)
            and row["fold_id"].strip()
        ):
            raise ValueError("invalid paired fold identity")
        try:
            start, end = (datetime.fromisoformat(row[k]) for k in ("start", "end"))
            if start >= end:
                raise ValueError("paired calendar window must have positive duration")
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid paired calendar") from exc
        if row["fold_id"] in identities:
            raise ValueError("duplicate paired fold")
        identities.add(row["fold_id"])
        values, reasons = [], []
        for arm in ("native", "meta"):
            record = row[arm]
            if set(record) != {"status", "is_sharpe", "forward_sharpe"}:
                raise ValueError("raw arm schema mismatch")
            if record["status"] == "VALID":
                pair = [record["is_sharpe"], record["forward_sharpe"]]
                if any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in pair
                ):
                    raise ValueError(
                        "VALID raw metrics require finite scalars, including genuine zero"
                    )
                values.extend(pair)
            else:
                if record["status"] not in {
                    "NO_TRADES",
                    "ZERO_VARIANCE",
                    "UNDEFINED",
                    "FAILED",
                }:
                    raise ValueError("unknown raw outcome status")
                if (
                    record["is_sharpe"] is not None
                    or record["forward_sharpe"] is not None
                ):
                    raise ValueError(
                        "undefined arm must not have fabricated scalar metrics"
                    )
                reasons.append(f"{arm}:{record['status']}")
        result = {k: row[k] for k in ("fold_id", "start", "end")}
        result.update(
            raw=row, status="UNPAIRED" if reasons else "VALID", reasons=reasons
        )
        result.update(
            r=None, q=None, is_difference=None, native_decay=None, meta_decay=None
        )
        if not reasons:
            ni, nf, mi, mf = values
            result.update(
                native_decay=ni - nf,
                meta_decay=mi - mf,
                r=(ni - nf) - (mi - mf),
                q=mf - nf,
                is_difference=ni - mi,
            )
            if not math.isclose(
                result["r"],
                result["is_difference"] + result["q"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("decay decomposition does not reconcile")
        output.append(result)
    valid = [row for row in output if row["status"] == "VALID"]
    return {
        "schema": "qms-paired-saved-output-report-v1",
        "rows": output,
        "calendar_folds": len(output),
        "paired_valid_folds": len(valid),
        "unpaired_folds": len(output) - len(valid),
        "mean_fold_r": math.fsum(row["r"] for row in valid) / len(valid)
        if valid
        else None,
        "mean_fold_q": math.fsum(row["q"] for row in valid) / len(valid)
        if valid
        else None,
        "estimand": "paired-valid mean fold decay / forward-Sharpe difference",
        "uncertainty": "NOT_ASSESSED: requires registered dependent-time inference",
        "continuous_account_sharpe": None,
        "edge_certified": False,
    }
