"""Observe original financial results after selection; never select or replay."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from time import perf_counter

import numpy as np
import pandas as pd

from .common import MetaRecordError, digest, utc
from .records import (
    CandidateForwardRecord,
    MetricContract,
    MetricObservation,
    OutcomeStatus,
)


def canonical_metric_contract(*, trading_days=365):
    from ...metrics import performance
    import inspect

    source = "\n".join(
        inspect.getsource(f)
        for f in (
            performance.full_report,
            performance.compute_performance_metrics,
            performance._array_sharpe,
            performance._array_returns_for_stats,
            performance._array_daily_equity,
            performance._array_finite_returns,
            performance._array_annualization_periods,
        )
    )
    return MetricContract(
        hashlib.sha256(source.encode()).hexdigest(),
        digest(inspect.getsource(performance._array_number_of_trades)),
        trading_days,
    )


def _economic_payload(payload, constraints):
    contract = {
        key: payload[key] for key in ("account", "execution", "sizing", "funding")
    }
    contract["funding"] = dict(contract["funding"])
    rate = contract["funding"]["funding_rate"]
    if isinstance(rate, dict) and rate.get("type") == "Series":
        contract["funding"]["funding_rate"] = {"source": "aligned_series"}
    contract["fees"] = {
        "canonical_one_way_fee_rate": payload["fees"]["canonical_one_way_fee_rate"]
    }
    contract["domain"] = {
        key: payload[key]
        for key in ("mode", "asset_type", "execution_contract", "portfolio_mode")
    }
    contract["quantity_constraints"] = constraints
    return contract


def economics_identity(config, *, symbols=None):
    """Canonical execution economics, not reporting/backend implementation IDs."""
    from ...endpoint import _endpoint_run_config_payload
    from ...core.constraints import build_quantity_constraints

    payload = _endpoint_run_config_payload(config)
    constraints = build_quantity_constraints(
        symbols or config.symbols or ["DEFAULT"],
        instruments=config.instruments,
        qty_step=config.qty_step,
        lot_size=config.lot_size,
        slot_size=config.slot_size,
        min_qty=config.min_qty,
        min_notional=config.min_notional,
    )
    contract = _economic_payload(payload, constraints.as_dict())
    return digest(contract)


def market_signature(frame, index, *, config=None):
    if not isinstance(frame, pd.DataFrame):
        raise NotImplementedError(
            "QMS-03 metric witnesses require DataFrame market tapes"
        )
    prefix = frame.loc[: index[-1]]
    sha = hashlib.sha256()
    sha.update(
        digest(
            {"columns": list(prefix.columns), "dtypes": [str(d) for d in prefix.dtypes]}
        ).encode()
    )
    sha.update(pd.util.hash_pandas_object(prefix, index=True).to_numpy().tobytes())
    if config is not None and isinstance(config.funding_rate, pd.Series):
        rates = config.funding_rate.reindex(index)
        sha.update(pd.util.hash_pandas_object(rates, index=True).to_numpy().tobytes())
    return sha.hexdigest()


class ResultMetricAdapter:
    """Reuse QuantBT's reducer and sample definition; support is not a new Sharpe."""

    def __init__(self, contract: MetricContract):
        canonical = canonical_metric_contract(trading_days=contract.trading_days)
        if contract != canonical:
            raise MetaRecordError("unsupported/changed raw metric contract")
        self.contract = contract

    def observe(
        self,
        result,
        *,
        expected_index,
        economics_id,
        input_signature,
        report=None,
        execution_config=None,
    ):
        from ...core.types import BacktestResult
        from ...core.results import BacktestResultV2
        from ...metrics.performance import _array_returns_for_stats

        if isinstance(result, BacktestResultV2):
            result = result.to_legacy()
        if not isinstance(result, BacktestResult):
            raise MetaRecordError(
                "META_METRIC_SUPPORT_MISSING: original financial result required"
            )
        actual_config = result.metadata.get("run_config")
        if actual_config is None and execution_config is not None:
            from ...endpoint import _endpoint_run_config_payload

            actual_config = _endpoint_run_config_payload(execution_config)
        constraints = result.metadata.get("quantity_constraints")
        actual_id = (
            digest(_economic_payload(actual_config, constraints))
            if actual_config is not None and constraints is not None
            else None
        )
        if actual_id != economics_id:
            raise MetaRecordError(
                "original result lacks matching execution economics evidence"
            )
        expected_index = pd.DatetimeIndex(expected_index)
        if (
            len(expected_index) < 1
            or not expected_index.is_monotonic_increasing
            or not expected_index.is_unique
        ):
            raise MetaRecordError("invalid expected diagnostic index")
        start, end = utc(expected_index[0]), utc(expected_index[-1])
        if report is None:
            report = result.full_report(
                trading_days=self.contract.trading_days, scope="full"
            )
        sample = _array_returns_for_stats(
            result.equity.index,
            result.equity.to_numpy(dtype=float),
            result.returns.to_numpy(dtype=float),
        )
        count = len(sample)
        std = float(np.std(sample, ddof=1)) if count > 1 else None
        raw = float(report["sharpe"])
        if not result.equity.index.equals(expected_index):
            status = OutcomeStatus.INCOMPLETE_WINDOW
        elif not np.isfinite(result.equity.to_numpy(dtype=float)).all():
            status = OutcomeStatus.OUTCOME_FAILED
        elif result.liquidated:
            status = OutcomeStatus.CENSORED
        elif count < 2:
            status = OutcomeStatus.INSUFFICIENT_SAMPLE
        elif std is None or not np.isfinite(std) or std <= 0:
            status = OutcomeStatus.NO_VARIANCE
        elif not np.isfinite(raw):
            status = OutcomeStatus.OUTCOME_FAILED
        else:
            status = OutcomeStatus.VALID
        # Bind witness to the original result, including first mark and account.
        witness = hashlib.sha256(
            digest(
                {
                    "index": [utc(t).isoformat() for t in result.equity.index],
                    "initial_capital": result.initial_capital,
                    "economics": economics_id,
                    "metric": self.contract.metric_id,
                    "input": input_signature,
                }
            ).encode()
        )
        for values in (result.equity, result.returns, result.positions):
            array = np.ascontiguousarray(values.to_numpy(dtype=np.float64))
            witness.update(digest({"shape": array.shape, "dtype": "float64"}).encode())
            witness.update(array.tobytes())
        return MetricObservation(
            status,
            raw if np.isfinite(raw) else None,
            int(report["num_trades"]),
            count,
            std if std is not None and np.isfinite(std) else None,
            self.contract.metric_id,
            economics_id,
            start,
            end,
            end,
            float(result.initial_capital),
            float(result.equity.iloc[0])
            if np.isfinite(result.equity.iloc[0])
            else None,
            witness.hexdigest(),
            input_signature,
            "original_result",
        )


class PostDecisionObserver:
    """Fresh-account evaluation callable is supplied by the existing owner."""

    def __init__(self, adapter: ResultMetricAdapter):
        self.adapter = adapter
        self.attempts = 0
        self.failures = 0
        self.elapsed_seconds = 0.0

    def observe(
        self,
        *,
        task,
        panel,
        evaluate,
        expected_index,
        label_available_at,
        reporting_lag_seconds=0.0,
        publication_order=None,
    ):
        expected_index = pd.DatetimeIndex(expected_index)
        if (
            len(expected_index) == 0
            or panel.task_id != task.task_id
            or not (
                task.decision_sealed_at
                <= panel.sealed_at
                <= task.first_forward_action_at
            )
            or self.adapter.contract.metric_id != task.family.metric_contract_id
            or not set(panel.members).issubset(c.evaluation_id for c in task.candidates)
            or task.anchor_candidate_evaluation_id not in panel.members
            or utc(expected_index[0]) != task.forward_start
            or utc(expected_index[-1]) != task.forward_end
        ):
            raise MetaRecordError(
                "observer requires the sealed task's exact forward window"
            )
        label_available_at = utc(label_available_at)
        if label_available_at < task.forward_end + pd.Timedelta(
            seconds=reporting_lag_seconds
        ):
            raise MetaRecordError("observer label is not mature")
        candidates = {c.evaluation_id: c for c in task.candidates}
        outcomes = []
        for eid in panel.members:
            candidate = candidates[eid]
            started = perf_counter()
            self.attempts += 1
            try:
                # The evaluator owns fresh/reset account and strategy/RNG state.
                result, input_signature = evaluate(candidate)
                observation = self.adapter.observe(
                    result,
                    expected_index=expected_index,
                    economics_id=task.family.economics_id,
                    input_signature=input_signature,
                )
            except MetaRecordError:
                raise
            except Exception:
                self.failures += 1
                previous = candidate.observation
                observation = replace(
                    previous,
                    status=OutcomeStatus.OUTCOME_FAILED,
                    raw_sharpe=None,
                    activity_count=None,
                    sample_count=0,
                    sample_std=None,
                    initial_mark_equity=None,
                    window_start=task.forward_start,
                    window_end=task.forward_end,
                    input_frontier=task.forward_end,
                    output_ref=digest({"failed": eid, "task": task.task_id}),
                    input_signature=digest(
                        {"forward": [task.forward_start, task.forward_end]}
                    ),
                )
            finally:
                self.elapsed_seconds += perf_counter() - started
            outcomes.append(
                CandidateForwardRecord(
                    task.task_id,
                    eid,
                    observation,
                    label_available_at,
                    reporting_lag_seconds,
                    publication_order,
                )
            )
        return tuple(outcomes)
