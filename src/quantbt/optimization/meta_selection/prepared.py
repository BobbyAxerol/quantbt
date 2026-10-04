"""Raw metric evidence from the original prepared pass, never a replay."""

from __future__ import annotations

import math

import pandas as pd

from .common import MetaRecordError, digest
from .records import MetricObservation, OutcomeStatus


PREPARED_WITNESS_ABI = "same-pass-ddof1-daily-first-mark-v1"


def observe_prepared_score(
    result,
    row,
    *,
    index,
    contract,
    economics_id,
    input_signature,
    initial_capital,
    request_signature,
):
    support = result.metric_support
    if support is None:
        raise MetaRecordError("META_METRIC_SUPPORT_MISSING: original prepared witness")
    index = pd.DatetimeIndex(index)
    if (
        len(index) < 2
        or not index.is_unique
        or not index.is_monotonic_increasing
        or index.tz is None
        or int(result.status[row]) != 0
    ):
        raise MetaRecordError("META_METRIC_SUPPORT_INVALID: prepared window/status")
    if (
        int(support["contract_version"][row]) != 2
        or float(support["annualization_factor"][row]) != contract.trading_days
        or contract.trading_days != 365
    ):
        raise MetaRecordError("META_METRIC_SUPPORT_INVALID: reducer contract")
    count = int(support["sample_count"][row])
    variance = float(support["sample_variance"][row])
    mark = float(support["initial_mark_equity"][row])
    raw = float(result.sharpe[row])
    liquidated = bool(support["liquidated"][row])
    expected_count = len(index.normalize().unique()) - 1
    if not liquidated and count != expected_count:
        raise MetaRecordError("META_METRIC_SUPPORT_INVALID: daily sample coverage")
    status = (
        OutcomeStatus.CENSORED
        if liquidated
        else OutcomeStatus.OUTCOME_FAILED
        if not all(map(math.isfinite, (raw, variance, mark)))
        or variance < 0
        or mark <= 0
        else OutcomeStatus.INSUFFICIENT_SAMPLE
        if count < 2
        else OutcomeStatus.NO_VARIANCE
        if variance == 0
        else OutcomeStatus.VALID
    )
    evidence = {
        "abi": PREPARED_WITNESS_ABI,
        "request": request_signature,
        "input": input_signature,
        "metric": contract.metric_id,
        "economics": economics_id,
        "count": count,
        "variance": variance if math.isfinite(variance) else None,
        "first_mark": mark if math.isfinite(mark) else None,
        "sharpe": raw if math.isfinite(raw) else None,
        "liquidated": liquidated,
        "activity": int(result.report_trade_count[row]),
    }
    return MetricObservation(
        status,
        evidence["sharpe"],
        evidence["activity"],
        count,
        math.sqrt(variance) if math.isfinite(variance) and variance >= 0 else None,
        contract.metric_id,
        economics_id,
        index[0],
        index[-1],
        index[-1],
        float(initial_capital),
        evidence["first_mark"],
        digest(evidence),
        input_signature,
        "original_native_score",
    )
