"""Cold adapters for completed outputs. No simulation, inferred lots or replay."""

import numpy as np

from ..report_contracts import ReportingCoverageV1
from .inputs import (AccountObservations, derived_returns, frozen_array,
                     validate_account_path, validate_account_scope)
from .ledger_inputs import LedgerObservations, RecordedOutcome


def _utc_index(index, *, naive_timezone=None):
    import pandas as pd
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("explicit DatetimeIndex required; range indices are not execution clocks")
    if index.hasnans:
        raise ValueError("missing NaT timestamp is not an execution clock")
    if index.tz is None:
        if naive_timezone != "UTC":
            raise ValueError("naive timestamps require explicit naive_timezone='UTC'")
        index = index.tz_localize("UTC")
    # asi8 follows the index resolution; the reporting contract always uses ns.
    index = index.tz_convert("UTC")
    return index if index.unit == "ns" else index.as_unit("ns")


def account_from_completed(result, contract, *, result_identity, profile="completed",
                           index=None, naive_timezone=None, partial_mask=None, return_witness=None):
    if hasattr(result, "to_pandas") and hasattr(result, "profile"):
        if result.profile == "score":
            raise LookupError("score output omitted account paths; no implicit simulation rerun")
        if index is None:
            raise ValueError("native market clock must be supplied explicitly")
        frame = result.to_pandas(index=index)
        equity = frame["equity"]
        profile = result.profile
    elif hasattr(result, "accounting"):
        import pandas as pd
        equity = pd.Series(result.accounting.equity, index=result.accounting.datetime_index)
    else:
        equity = getattr(result, "equity", None)
        if equity is None:
            raise LookupError("completed output has no retained account path")
    times = _utc_index(equity.index, naive_timezone=naive_timezone)
    selected = (times.asi8 >= contract.baseline_time_ns) & (times.asi8 <= contract.scope_end_ns)
    coverage = ReportingCoverageV1(result_identity=result_identity, producer="completed account path",
        profile=profile, ledger="unsupported", retained_rows=0, dropped_rows=0,
        reason="account path cannot certify executed outcome/action ledger completeness")
    # A complete scope needs one immutable snapshot, not a boolean-index copy first.
    timestamps, marks = times.asi8, equity.to_numpy()
    if not selected.all():
        timestamps, marks = timestamps[selected], marks[selected]
    timestamps = frozen_array(timestamps, np.int64, integer=True)
    marks = frozen_array(marks, np.float64)
    validate_account_path(timestamps, marks)
    validate_account_scope(timestamps, contract)
    returns = None
    if partial_mask is not None:
        if not return_witness:
            raise ValueError("return/partial-period producer witness required")
        returns = derived_returns(timestamps, marks, contract, partial_mask=partial_mask, witness=return_witness)
    observations = AccountObservations(times_ns=timestamps, equity=marks, coverage=coverage, returns=returns)
    observations.validate_contract(contract)
    return observations


def trades_from_completed(result, *, coverage, matching, currency, pnl_basis,
                          close_sequences, rosters=(), valuation_time_ns=None, naive_timezone=None):
    """Caller supplies completeness/matching/net-cost witnesses absent from Trade.

    Only `reporting_outcome_v1` metadata is admitted for cost/risk attribution.
    Trade.realized_pnl alone does not prove whether funding/fees were included.
    """
    if pnl_basis not in {"authoritative_net", "recorded_gross"}:
        raise ValueError("explicit executed PnL basis required")
    trades = tuple(getattr(result, "trades", ()))
    if len(trades) != len(close_sequences):
        raise ValueError("recorded close sequence required for each outcome")
    records = []
    for trade, sequence in zip(trades, close_sequences):
        if not trade.trade_id:
            raise LookupError("recorded trade identity missing; cannot manufacture identity from row number")
        import pandas as pd
        def timestamp(value):
            if value is None:
                return None
            return int(_utc_index(pd.DatetimeIndex([value]), naive_timezone=naive_timezone).asi8[0])
        attributes = dict(trade.metadata.get("reporting_outcome_v1", {}))
        allowed = {"action_id", "allocated_fee", "allocated_funding_cost", "allocated_slippage_cost",
                   "open_unrealized_pnl", "holding_bars", "initial_risk", "return_denominator",
                   "mfe_net_pnl", "mae_net_pnl", "excursion_witness", "close_reason"}
        if set(attributes) - allowed:
            raise ValueError("unknown recorded reporting attribution field")
        records.append(RecordedOutcome(trade_id=trade.trade_id, symbol=trade.symbol,
            side="long" if trade.side.sign > 0 else "short", currency=currency,
            opened_at_ns=timestamp(trade.opened_at), closed_at_ns=timestamp(trade.closed_at),
            close_sequence=sequence, **attributes,
            **{"net_pnl" if pnl_basis == "authoritative_net" else "gross_pnl": trade.realized_pnl}))
    return LedgerObservations(records=records, coverage=coverage, matching=matching,
                              rosters=rosters, valuation_time_ns=valuation_time_ns)
