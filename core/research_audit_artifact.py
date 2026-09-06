"""Cold-path research artifact and manifest construction for WFO.

This module owns artifact materialization, immutable provenance manifests, and
legacy-dataframe adaptation.  The columnar codec and bounded writer remain in
`research_audit` so the hot-facing retention contract stays compact.
"""

from __future__ import annotations

from collections import OrderedDict
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .research_audit import (
    RESEARCH_AUDIT_CODEC_V1,
    RESEARCH_AUDIT_DIGEST_V1,
    RESEARCH_AUDIT_SCHEMA_V1,
    ColumnarResearchTableV1,
    ResearchAuditError,
    ResearchAuditWriterV1,
    ResearchRetentionPlanV1,
    _freeze_manifest_value,
    _logical_digest,
    _logical_record_mapping,
    _original_fill_audit_source,
    _sequence_length,
    _series_value_at,
    _timestamp_or_none,
)


class ResearchAuditArtifactV1:
    """Cold-path research product attached to a WFO result.

    The artifact retains no market tape, live account object, Python strategy,
    or mutable execution state.  It contains only immutable research chunks and
    immutable manifest dictionaries.  DataFrames are materialized on request
    and held in a bounded local LRU.
    """

    def __init__(
        self,
        *,
        plan: ResearchRetentionPlanV1,
        run_manifest: Mapping[str, Any],
        search_space_manifest: Mapping[str, Any],
        instrument_manifest: Mapping[str, Any],
        writer: ResearchAuditWriterV1,
    ) -> None:
        self.plan = plan
        self.run_manifest = _freeze_manifest_value(dict(run_manifest))
        self.search_space_manifest = _freeze_manifest_value(dict(search_space_manifest))
        self.instrument_manifest = _freeze_manifest_value(dict(instrument_manifest))
        self._writer = writer
        self._extra_tables: dict[str, tuple[ColumnarResearchTableV1, ...]] = {}
        self._materialized: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._runtime_payload: dict[str, Any] = {}
        self._financial_payload: dict[str, Any] = {
            "financial_completion": "pending_final_endpoint_result",
            "financial_retention": plan.financial_retention,
            "financial_scope": plan.financial_scope,
            "reconstructed": False,
        }

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._writer.tables) | set(self._extra_tables)))

    def chunks(self, table_name: str) -> tuple[ColumnarResearchTableV1, ...]:
        if table_name in self._extra_tables:
            return self._extra_tables[table_name]
        return self._writer.tables.get(table_name, ())

    def to_pandas(self, table_name: str) -> pd.DataFrame:
        cached = self._materialized.get(table_name)
        if cached is not None:
            self._materialized.move_to_end(table_name)
            return cached.copy(deep=True)
        chunks = self.chunks(table_name)
        if not chunks:
            frame = pd.DataFrame()
        else:
            frame = pd.concat([chunk.to_pandas() for chunk in chunks], axis=0, ignore_index=True, copy=False)
        self._materialized[table_name] = frame
        while len(self._materialized) > self.plan.max_materialized_frames:
            self._materialized.popitem(last=False)
        return frame.copy(deep=True)

    def clear_materialized(self) -> None:
        self._materialized.clear()

    def legacy_exports(self) -> dict[str, pd.DataFrame]:
        """Materialize compatible WFO tables only when a caller asks for them."""

        exports: dict[str, pd.DataFrame] = {
            "trial_table": self._legacy_trial_table("trials", "legacy_compact_row"),
            "trial_table_full": self._legacy_trial_table("trials", "legacy_full_row"),
            "candidate_table": self._legacy_trial_table("analysis", "legacy_compact_row"),
            "candidate_table_full": self._legacy_trial_table("analysis", "legacy_full_row"),
            "evaluation_table": self.to_pandas("evaluations"),
            "selection_table": self.to_pandas("selection"),
            "deployment_table": self.to_pandas("deployment"),
            "replay_table": self.to_pandas("replay"),
            "performance_table": self.to_pandas("performance"),
            "financial_table": self.to_pandas("financial"),
        }
        return exports

    def _legacy_trial_table(self, table_name: str, column_name: str) -> pd.DataFrame:
        rows = self.to_pandas(table_name)
        if rows.empty or column_name not in rows:
            return pd.DataFrame()
        return pd.DataFrame(list(rows[column_name]))

    def finalize_runtime(self, *, runtime: Mapping[str, Any] | None, performance: Mapping[str, Any] | None) -> None:
        self._runtime_payload = {
            "wfo_execution_runtime": dict(runtime or {}),
            "performance_profile": dict(performance or {}),
        }
        self._replace_records("performance", [
            {
                "performance_id": 0,
                "runtime": self._runtime_payload["wfo_execution_runtime"],
                "performance_profile": self._runtime_payload["performance_profile"],
            }
        ])

    def finalize_financial(self, result: Any) -> None:
        """Attach selected-final financial retention without replaying execution."""

        equity = getattr(result, "equity", None)
        if equity is None:
            raise ResearchAuditError("selected-final financial retention requires a result with an equity path")
        equity_values = np.asarray(equity, dtype=np.float64)
        if equity_values.ndim != 1 or len(equity_values) == 0:
            raise ResearchAuditError("selected-final financial retention requires a non-empty one-dimensional equity path")
        metadata = dict(getattr(result, "metadata", {}) or {})
        timestamps = (
            list(equity.index)
            if isinstance(equity, pd.Series)
            else list(range(int(len(equity_values))))
        )
        returns = getattr(result, "returns", None)
        fees = getattr(result, "fees", None)
        funding = getattr(result, "funding", None)
        payload: dict[str, Any] = {
            "financial_id": 0,
            "financial_retention": self.plan.financial_retention,
            "financial_scope": self.plan.financial_scope,
            "initial_equity": float(equity_values[0]),
            "final_equity": float(equity_values[-1]),
            "equity_points": int(len(equity_values)),
            "reconstructed": False,
            "result_type": f"{type(result).__module__}.{type(result).__qualname__}",
        }
        if self.plan.financial_retention == "score":
            payload["financial_completion"] = "score_complete_selected_final_account"
        elif self.plan.financial_retention == "compact":
            payload["financial_completion"] = "compact_complete_selected_final_path"
            payload["compact_path_columns"] = ["timestamp", "equity", "return"]
        else:
            original_fill_rows, fill_audit_complete = _original_fill_audit_source(result, metadata)
            if not fill_audit_complete:
                raise ResearchAuditError(
                    "financial_retention='audit' requires original selected-final fill/audit output; "
                    "an empty generic fills field alongside position/cost activity is not an audit. "
                    "Use an audit-capable execution route or request financial_retention='compact'; "
                    "QuantBT will not reconstruct fills from a target/equity path"
                )
            payload["financial_completion"] = "audit_complete_selected_final_execution"
            payload["audit_source"] = "original_selected_final_result"
        self._financial_payload = payload
        self._replace_records("financial", [payload])
        path_rows = []
        for ordinal, (timestamp, value) in enumerate(zip(timestamps, equity_values)):
            row = {
                "bar_ordinal": int(ordinal),
                "timestamp": _timestamp_or_none(timestamp),
                "equity": float(value),
                "return": _series_value_at(returns, timestamp, ordinal),
            }
            if self.plan.financial_retention == "audit":
                row["fee"] = _series_value_at(fees, timestamp, ordinal)
                row["funding"] = _series_value_at(funding, timestamp, ordinal)
            path_rows.append(row)
        if self.plan.financial_retention != "score":
            self._replace_records("financial_path", path_rows)
        if self.plan.financial_retention != "audit":
            return

        def retain_original_sequence(table_name: str, label: str, values: Any) -> int:
            if values is None:
                return 0
            if isinstance(values, pd.DataFrame):
                rows = [
                    {
                        "record_ordinal": int(ordinal),
                        "timestamp": _timestamp_or_none(index),
                        "record": dict(row),
                    }
                    for ordinal, (index, row) in enumerate(values.iterrows())
                ]
            else:
                rows = [
                    {
                        "record_ordinal": int(ordinal),
                        "record": _logical_record_mapping(item, label=label),
                    }
                    for ordinal, item in enumerate(tuple(values))
                ]
            if rows:
                self._replace_records(table_name, rows)
            return len(rows)

        payload["original_fill_count"] = retain_original_sequence("financial_fills", "fill", original_fill_rows)
        payload["original_order_count"] = retain_original_sequence(
            "financial_orders", "order", getattr(result, "orders", None)
        )
        payload["original_trade_count"] = retain_original_sequence(
            "financial_trades", "trade", getattr(result, "trades", None)
        )
        payload["original_diagnostic_count"] = retain_original_sequence(
            "financial_diagnostics", "diagnostic", getattr(result, "diagnostics", None)
        )
        payload["original_margin_row_count"] = retain_original_sequence(
            "financial_margin", "margin", getattr(result, "margin", None)
        )
        payload["original_position_row_count"] = retain_original_sequence(
            "financial_positions", "position", getattr(result, "positions", None)
        )
        self._financial_payload = payload
        self._replace_records("financial", [payload])

    def finalize_segmented_financial(self, fold_results: Sequence[Any]) -> None:
        """Attach honest reset-flat reactive financial segments without stitching them."""

        rows: list[dict[str, Any]] = []
        path_rows: list[dict[str, Any]] = []
        fill_rows: list[dict[str, Any]] = []
        order_rows: list[dict[str, Any]] = []
        trade_rows: list[dict[str, Any]] = []
        diagnostic_rows: list[dict[str, Any]] = []
        for ordinal, item in enumerate(fold_results):
            result = getattr(item, "result", item)
            equity = getattr(result, "equity", None)
            if equity is None:
                raise ResearchAuditError("segmented financial retention requires every fold result to expose equity")
            equity_values = np.asarray(equity, dtype=np.float64)
            if equity_values.ndim != 1 or len(equity_values) == 0:
                raise ResearchAuditError("segmented financial retention requires non-empty fold equity paths")
            row: dict[str, Any] = {
                "financial_id": int(ordinal),
                "fold_id": int(getattr(item, "fold_id", ordinal)),
                "financial_retention": self.plan.financial_retention,
                "financial_scope": "segmented_reset_flat_execution",
                "initial_equity": float(equity_values[0]),
                "final_equity": float(equity_values[-1]),
                "equity_points": int(len(equity_values)),
                "reconstructed": False,
                "continuous_equity_available": False,
            }
            if self.plan.financial_retention == "score":
                row["financial_completion"] = "score_complete_segmented_reset_flat"
            elif self.plan.financial_retention == "compact":
                row["financial_completion"] = "compact_complete_segmented_reset_flat"
                row["compact_path_columns"] = ["timestamp", "equity"]
            else:
                metadata = dict(getattr(result, "metadata", {}) or {})
                original_fill_rows, fill_audit_complete = _original_fill_audit_source(result, metadata)
                if not fill_audit_complete:
                    raise ResearchAuditError(
                        "financial_retention='audit' requires original reactive fold fills; "
                        "an empty generic fills field alongside position/cost activity is not an audit. "
                        "QuantBT will not reconstruct a lifecycle audit"
                    )
                row["financial_completion"] = "audit_complete_segmented_reset_flat"
                row["original_fill_count"] = int(_sequence_length(original_fill_rows) or 0)
                row["audit_source"] = "original_reactive_fold_result"
            if self.plan.financial_retention != "score":
                equity_index = (
                    list(equity.index)
                    if isinstance(equity, pd.Series)
                    else list(range(int(len(equity_values))))
                )
                returns = getattr(result, "returns", None)
                for bar_ordinal, (timestamp, value) in enumerate(zip(equity_index, equity_values)):
                    path_rows.append(
                        {
                            "fold_id": int(getattr(item, "fold_id", ordinal)),
                            "bar_ordinal": int(bar_ordinal),
                            "timestamp": _timestamp_or_none(timestamp),
                            "equity": float(value),
                            "return": _series_value_at(returns, timestamp, bar_ordinal),
                            "continuous_equity_available": False,
                        }
                    )
            if self.plan.financial_retention == "audit":
                fold_id = int(getattr(item, "fold_id", ordinal))

                def retain_segment_records(table_rows: list[dict[str, Any]], label: str, values: Any) -> None:
                    if values is None:
                        return
                    if isinstance(values, pd.DataFrame):
                        for record_ordinal, (timestamp, record) in enumerate(values.iterrows()):
                            table_rows.append(
                                {
                                    "fold_id": fold_id,
                                    "record_ordinal": int(record_ordinal),
                                    "timestamp": _timestamp_or_none(timestamp),
                                    "record": dict(record),
                                }
                            )
                        return
                    for record_ordinal, record in enumerate(tuple(values)):
                        table_rows.append(
                            {
                                "fold_id": fold_id,
                                "record_ordinal": int(record_ordinal),
                                "record": _logical_record_mapping(record, label=label),
                            }
                        )

                retain_segment_records(fill_rows, "fill", original_fill_rows)
                retain_segment_records(order_rows, "order", getattr(result, "orders", None))
                retain_segment_records(trade_rows, "trade", getattr(result, "trades", None))
                retain_segment_records(diagnostic_rows, "diagnostic", getattr(result, "diagnostics", None))
            rows.append(row)
        self._financial_payload = {
            "financial_completion": "segmented_reset_flat_complete",
            "financial_retention": self.plan.financial_retention,
            "financial_scope": "segmented_reset_flat_execution",
            "continuous_equity_available": False,
            "reconstructed": False,
        }
        self._replace_records("financial", rows)
        if self.plan.financial_retention != "score":
            self._replace_records("financial_path", path_rows)
        if self.plan.financial_retention == "audit":
            if fill_rows:
                self._replace_records("financial_fills", fill_rows)
            if order_rows:
                self._replace_records("financial_orders", order_rows)
            if trade_rows:
                self._replace_records("financial_trades", trade_rows)
            if diagnostic_rows:
                self._replace_records("financial_diagnostics", diagnostic_rows)

    def _replace_records(self, table_name: str, records: Sequence[Mapping[str, Any]]) -> None:
        chunks: list[ColumnarResearchTableV1] = []
        rows = list(records)
        for start in range(0, len(rows), self.plan.chunk_rows):
            ordinal = len(chunks)
            chunks.append(
                ColumnarResearchTableV1.from_records(
                    table_name=table_name,
                    chunk_id=f"{table_name}:extra:{ordinal:08d}",
                    records=rows[start : start + self.plan.chunk_rows],
                )
            )
        self._extra_tables[table_name] = tuple(chunks)
        self._materialized.pop(table_name, None)

    def metadata(self) -> dict[str, object]:
        writer = self._writer.metadata()
        table_metadata = {
            name: [chunk.metadata() for chunk in self.chunks(name)]
            for name in self.table_names
        }
        return {
            "schema": RESEARCH_AUDIT_SCHEMA_V1,
            "codec": RESEARCH_AUDIT_CODEC_V1,
            "digest_algorithm": RESEARCH_AUDIT_DIGEST_V1,
            "retention": self.plan.metadata(),
            "run_manifest_id": self.run_manifest.get("run_manifest_id"),
            "search_space_manifest_id": self.search_space_manifest.get("search_space_manifest_id"),
            "instrument_manifest_id": self.instrument_manifest.get("instrument_manifest_id"),
            "space_completeness": self.search_space_manifest.get("space_completeness"),
            "writer": writer,
            "financial": dict(self._financial_payload),
            "tables": table_metadata,
            "materialized_frames": list(self._materialized),
            "original_vs_reconstructed": {
                "selected_final_financial": self._financial_payload.get("financial_completion"),
                "reconstructed": False,
                "policy": "selected replay must be explicitly marked reconstructed=true; this artifact does not replay",
            },
        }


def _record_field(record: Any, name: str, default: Any = None) -> Any:
    return getattr(record, name, default)


def _record_to_rows(records: Sequence[Any], *, kind: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build trial and evaluation logical rows before chunk ownership transfer."""

    try:
        # Local import avoids a module cycle: walkforward imports this module.
        from ..walkforward import _trial_to_dict  # type: ignore
    except ImportError:  # pragma: no cover - direct module-only tests.
        _trial_to_dict = None
    trial_rows: list[dict[str, Any]] = []
    evaluation_rows: list[dict[str, Any]] = []
    for ordinal, record in enumerate(records):
        params = dict(_record_field(record, "params", {}) or {})
        metadata = dict(_record_field(record, "selection_metadata", {}) or {})
        candidate_id = _logical_digest(params)
        stage = str(metadata.get("stage", "fixed_or_post_selection_evaluation"))
        pruned = bool(_record_field(record, "pruned", False))
        status = "pruned" if pruned else "complete"
        compact = (
            _trial_to_dict(record, include_fold_metrics=False)
            if _trial_to_dict is not None
            else {
                "trial_id": int(_record_field(record, "trial_id", ordinal)),
                "params": params,
                "objective": float(_record_field(record, "objective", float("nan"))),
            }
        )
        full = (
            _trial_to_dict(record, include_fold_metrics=True)
            if _trial_to_dict is not None
            else {**compact, "fold_metrics": list(_record_field(record, "fold_metrics", []) or [])}
        )
        trial_rows.append(
            {
                "record_kind": kind,
                "record_ordinal": int(ordinal),
                "trial_id": int(_record_field(record, "trial_id", ordinal)),
                "study_id": int(metadata.get("study_id", -1)),
                "candidate_id": candidate_id,
                "stage": stage,
                "status": status,
                "pruned": pruned,
                "objective": float(_record_field(record, "objective", float("nan"))),
                "mean_is_sharpe": float(_record_field(record, "mean_is_sharpe", float("nan"))),
                "mean_oos_sharpe": float(_record_field(record, "mean_oos_sharpe", float("nan"))),
                "mean_decay": float(_record_field(record, "mean_decay", float("nan"))),
                "std_decay": float(_record_field(record, "std_decay", float("nan"))),
                "params": params,
                "selection_metadata": metadata,
                "legacy_compact_row": compact,
                "legacy_full_row": full,
            }
        )
        for metric_ordinal, metric in enumerate(list(_record_field(record, "fold_metrics", []) or [])):
            payload = dict(metric)
            evaluation_rows.append(
                {
                    "record_kind": kind,
                    "record_ordinal": int(ordinal),
                    "evaluation_ordinal": int(metric_ordinal),
                    "trial_id": int(_record_field(record, "trial_id", ordinal)),
                    "study_id": int(metadata.get("study_id", -1)),
                    "candidate_id": candidate_id,
                    "stage": stage,
                    "status": status,
                    "fold_id": int(payload.get("fold_id", -1)),
                    "fold_metric": payload,
                }
            )
    return trial_rows, evaluation_rows


def _search_space_entry(name: str, spec: Any) -> dict[str, Any]:
    if isinstance(spec, range):
        return {
            "name": str(name),
            "distribution": "categorical",
            "category_order": list(spec),
            "declared_spec": spec,
            "condition": None,
        }
    if isinstance(spec, tuple) and len(spec) in {2, 3} and all(
        isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)
        for value in spec
    ):
        integer = all(isinstance(value, (int, np.integer)) and not isinstance(value, bool) for value in spec)
        return {
            "name": str(name),
            "distribution": "int" if integer else "float",
            "low": spec[0],
            "high": spec[1],
            "step": None if len(spec) == 2 else spec[2],
            "log": False,
            "declared_spec": spec,
            "condition": None,
        }
    if isinstance(spec, (list, tuple)):
        return {
            "name": str(name),
            "distribution": "categorical",
            "category_order": list(spec),
            "declared_spec": spec,
            "condition": None,
        }
    return {
        "name": str(name),
        "distribution": "constant",
        "fixed_value": spec,
        "declared_spec": spec,
        "condition": None,
    }


def _manifest_id(payload: Mapping[str, Any]) -> str:
    return _logical_digest(dict(payload))


def _runtime_build_identity() -> dict[str, Any]:
    """Return a wheel-safe, local provenance identity without shelling out."""

    source = Path(__file__).resolve()
    try:
        installed_version = distribution_version("quantbt-engine")
    except PackageNotFoundError:
        installed_version = None
    return {
        "schema": "quantbt-research-runtime-identity-v1",
        "audit_codec_module": source.name,
        "audit_codec_module_sha256": sha256(source.read_bytes()).hexdigest(),
        "core_distribution": "quantbt-engine",
        "core_distribution_version": installed_version,
        "identity_scope": "installed_module_or_checked_source_file",
    }


def _build_manifests(
    *,
    config: Any,
    result_metadata: Mapping[str, Any],
    param_ranges: Mapping[str, Any] | None,
    selected_params: Mapping[str, Any],
    all_records: Sequence[Any],
    result_kind: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    declared = {str(name): _search_space_entry(str(name), spec) for name, spec in dict(param_ranges or {}).items()}
    observed_names = sorted({str(name) for record in all_records for name in dict(_record_field(record, "params", {}) or {})})
    declared_names = set(declared)
    completeness = "declared" if declared and set(observed_names).issubset(declared_names) else "observed_only"
    search_space = {
        "schema": "quantbt-research-search-space-v1",
        "space_completeness": completeness,
        "declared_parameters": declared,
        "observed_parameter_names": observed_names,
        "fixed_overrides": (
            dict(selected_params) if not declared else {name: entry["fixed_value"] for name, entry in declared.items() if entry["distribution"] == "constant"}
        ),
    }
    search_space["search_space_manifest_id"] = _manifest_id(search_space)
    config_metadata = dict(getattr(config, "metadata", {}) or {})
    prepared_context = result_metadata.get("prepared_wfo_context")
    # This is deliberately a contract/identity record, never a copy of the
    # market tape.  The authoritative tape remains with the execution result
    # and its content signature; retaining it here would defeat bounded audit
    # memory and make a research sidecar look like a replay engine.
    instrument = {
        "schema": "quantbt-research-instrument-contract-v1",
        "target_mode": result_metadata.get("target_mode"),
        "calendar_contract": result_metadata.get("calendar_contract"),
        "calendar_plan": result_metadata.get("calendar_plan"),
        "intent_contract": result_metadata.get("intent_contract"),
        "fold_account_policy": result_metadata.get("fold_account_policy"),
        "prepared_market_identity": prepared_context,
        "declared_instrument_constraints": config_metadata.get("instrument_constraints"),
        "declared_symbol_mapping": config_metadata.get("symbol_mapping"),
        "declared_execution_contract": config_metadata.get("execution_contract"),
    }
    instrument["instrument_manifest_id"] = _manifest_id(instrument)
    run_manifest = {
        "schema": "quantbt-research-run-manifest-v1",
        "result_kind": str(result_kind),
        "runtime_build_identity": result_metadata.get("runtime_build_identity", _runtime_build_identity()),
        "engine": result_metadata.get("engine"),
        "data_hash": result_metadata.get("data_hash"),
        "config_hash": result_metadata.get("config_hash"),
        "strategy_fingerprint": result_metadata.get("strategy_fingerprint"),
        "random_seed": result_metadata.get("random_seed"),
        "optimization_mode": result_metadata.get("optimization_mode"),
        "optimization_schedule": result_metadata.get("optimization_schedule"),
        "target_mode": result_metadata.get("target_mode"),
        "fold_account_policy": result_metadata.get("fold_account_policy"),
        "intent_contract": result_metadata.get("intent_contract"),
        "calendar_contract": result_metadata.get("calendar_contract"),
        "required_computation_plan": result_metadata.get("required_computation_plan"),
        "prepared_wfo_context": result_metadata.get("prepared_wfo_context"),
        "wfo_execution_runtime": result_metadata.get("wfo_evaluation_runtime"),
        "search_space_manifest_id": search_space["search_space_manifest_id"],
        "instrument_manifest_id": instrument["instrument_manifest_id"],
    }
    run_manifest["run_manifest_id"] = _manifest_id(run_manifest)
    return run_manifest, search_space, instrument


def build_walkforward_research_audit(
    *,
    config: Any,
    result_metadata: Mapping[str, Any],
    param_ranges: Mapping[str, Any] | None,
    trial_records: Sequence[Any],
    candidate_records: Sequence[Any],
    selected_record: Any,
    folds: Sequence[Any],
    params_by_fold: Mapping[int, Mapping[str, Any]] | None,
    result_kind: str = "signal_wfo",
    plan: ResearchRetentionPlanV1 | None = None,
) -> ResearchAuditArtifactV1:
    """Build a cold-path artifact from existing WFO records without replaying.

    ``selected_only`` deliberately retains only the selected record plus its
    deployment trail.  ``none`` has manifests and truthful retention state but
    no trial/evaluation rows.  Neither setting is reported as a full ledger.
    """

    plan = plan or ResearchRetentionPlanV1.from_config(config)
    all_records = [*trial_records, *candidate_records, selected_record]
    run_manifest, search_space_manifest, instrument_manifest = _build_manifests(
        config=config,
        result_metadata=result_metadata,
        param_ranges=param_ranges,
        selected_params=dict(_record_field(selected_record, "params", {}) or {}),
        all_records=all_records,
        result_kind=result_kind,
    )
    writer = ResearchAuditWriterV1(plan=plan)
    artifact = ResearchAuditArtifactV1(
        plan=plan,
        run_manifest=run_manifest,
        search_space_manifest=search_space_manifest,
        instrument_manifest=instrument_manifest,
        writer=writer,
    )
    if plan.research_retention != "none":
        if plan.research_retention == "selected_only":
            retained_trials = [selected_record]
            retained_candidates = [selected_record]
        else:
            retained_trials = list(trial_records)
            retained_candidates = list(candidate_records)
        trial_rows, evaluation_rows = _record_to_rows(retained_trials, kind="trial")
        analysis_rows, analysis_evaluations = _record_to_rows(retained_candidates, kind="candidate_analysis")
        writer.append_records("trials", trial_rows)
        writer.append_records("evaluations", [*evaluation_rows, *analysis_evaluations])
        writer.append_records("analysis", analysis_rows)
        selected_params = dict(_record_field(selected_record, "params", {}) or {})
        selected_metadata = dict(_record_field(selected_record, "selection_metadata", {}) or {})
        writer.append_records(
            "selection",
            [
                {
                    "selection_id": 0,
                    "selected_trial_id": int(_record_field(selected_record, "trial_id", 0)),
                    "selected_candidate_id": _logical_digest(selected_params),
                    "selected_objective": float(_record_field(selected_record, "objective", float("nan"))),
                    "selected_params": selected_params,
                    "selection_metadata": selected_metadata,
                    "allowed_data_roles": {
                        "oos_used_for_selection": bool(result_metadata.get("oos_used_for_selection", False)),
                        "validation_claim": result_metadata.get("validation_claim"),
                        "causality_claim": result_metadata.get("causality_claim"),
                    },
                    "rejected_candidate_count": int(max(0, len(candidate_records) - 1)),
                }
            ],
        )
        deployments: list[dict[str, Any]] = []
        schedule_params = {int(key): dict(value) for key, value in dict(params_by_fold or {}).items()}
        for deployment_id, fold in enumerate(folds):
            fold_id = int(getattr(fold, "fold_id", deployment_id))
            params = schedule_params.get(fold_id, selected_params)
            deployments.append(
                {
                    "deployment_id": int(deployment_id),
                    "fold_id": fold_id,
                    "params": dict(params),
                    "train_start": getattr(fold, "train_start", None),
                    "train_end": getattr(fold, "train_end", None),
                    "test_start": getattr(fold, "test_start", None),
                    "test_end": getattr(fold, "test_end", None),
                    "account_policy": getattr(fold, "account_policy", result_metadata.get("fold_account_policy")),
                    "deployment_kind": result_kind,
                    "reconstructed": False,
                }
            )
        writer.append_records("deployment", deployments)
        writer.append_records(
            "replay",
            [
                {
                    "replay_id": 0,
                    "reconstructed": False,
                    "coverage": "original_selection_records_only",
                    "reason": "no selected audit replay was requested during research artifact construction",
                }
            ],
        )
    artifact.finalize_runtime(
        runtime=result_metadata.get("wfo_evaluation_runtime"),
        performance=result_metadata.get("perf_01_profile", result_metadata.get("performance_profile", {})),
    )
    writer.close()
    return artifact


__all__ = [
    "ResearchAuditArtifactV1",
    "build_walkforward_research_audit",
]

