"""Lazy Python compatibility adapter for native result V2 envelopes.

The Rust execution core owns the authoritative score/compact/audit SoA result.
This module deliberately owns no execution or accounting code: it reads that
payload, exposes scalar provenance immediately, and materializes pandas only
when a caller explicitly asks for a tabular report.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional

import numpy as np


def _value(payload: object, key: str, default: object = None) -> object:
    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _required(payload: object, key: str) -> object:
    value = _value(payload, key, None)
    if value is None:
        raise ValueError(f"native result V2 payload is missing {key!r}")
    return value


@dataclass(frozen=True, slots=True)
class NativeResultHeaderV2:
    """Immutable provenance attached to one authoritative native result."""

    result_version: int
    run_id: int
    request_fingerprint: str
    template_fingerprint: str
    contract_bundle_hash: str
    terminal_fingerprint: str
    workload_kind: str
    runtime_class: str
    account_authority: str
    execution_model_id: str
    metric_contract_version: int
    output_profile: str
    detail_truncated: bool
    retained_rows: int
    dropped_rows: int

    @classmethod
    def from_payload(cls, payload: object) -> "NativeResultHeaderV2":
        """Parse either a legacy mapping or a typed PyO3 output object."""

        return cls(
            result_version=int(_required(payload, "native_result_version")),
            run_id=int(
                _value(
                    payload,
                    "native_execution_generation",
                    _value(payload, "execution_generation", 0),
                )
            ),
            request_fingerprint=str(
                _value(payload, "native_execution_request_fingerprint", _value(payload, "fingerprint", ""))
            ),
            template_fingerprint=str(
                _value(
                    payload,
                    "native_execution_template_fingerprint",
                    _value(payload, "template_fingerprint", ""),
                )
            ),
            contract_bundle_hash=str(_required(payload, "native_execution_contract_bundle_hash") if isinstance(payload, Mapping) else _required(payload, "contract_bundle_hash")),
            terminal_fingerprint=str(_required(payload, "native_execution_terminal_fingerprint") if isinstance(payload, Mapping) else _required(payload, "terminal_fingerprint")),
            workload_kind=str(_value(payload, "native_execution_workload", _value(payload, "workload_kind", ""))),
            runtime_class=str(
                _value(
                    payload,
                    "native_execution_runtime_class",
                    _value(payload, "runtime_class", "whole_run_native"),
                )
            ),
            account_authority=str(
                _value(
                    payload,
                    "native_execution_account_authority",
                    _value(payload, "account_authority", "linear_account_v1"),
                )
            ),
            execution_model_id=str(_value(payload, "native_execution_model_id", _value(payload, "execution_model_id", ""))),
            metric_contract_version=int(
                _value(
                    payload,
                    "native_metric_contract_version",
                    _value(payload, "metric_contract_version", 0),
                )
            ),
            output_profile=str(_value(payload, "native_execution_output_profile", _value(payload, "output_profile", ""))),
            detail_truncated=bool(_value(payload, "native_execution_detail_truncated", _value(payload, "detail_truncated", False))),
            retained_rows=int(_value(payload, "native_execution_retained_rows", _value(payload, "retained_rows", 0))),
            dropped_rows=int(_value(payload, "native_execution_dropped_rows", _value(payload, "dropped_rows", 0))),
        )


class NativeResultV2Adapter:
    """Cold-path convenience surface over native score/compact/audit buffers.

    ``metrics`` is scalar-only. ``to_pandas()``, ``fills_dataframe()``,
    ``orders_dataframe()``, and ``audit_events()`` are lazy and retained in a
    bounded LRU cache. None of these methods reruns or replays execution.
    """

    _METRIC_KEYS = (
        "native_metric_contract_version",
        "native_metric_return_frequency",
        "native_metric_annualization_factor",
        "native_metric_risk_free_rate",
        "native_metric_variance_ddof",
        "native_metric_zero_variance_policy",
        "native_metric_short_run_policy",
        "native_metric_trade_count_definition",
        "native_metric_total_return",
        "native_metric_cagr",
        "native_metric_mean_return",
        "native_metric_variance",
        "native_metric_sharpe",
        "native_metric_sortino",
        "native_metric_max_drawdown",
        "native_metric_calmar",
        "native_metric_omega",
        "native_metric_average_gross_exposure",
        "native_metric_final_equity",
        "native_metric_turnover",
        "native_metric_total_fee",
        "native_metric_total_funding",
        "native_metric_fill_count",
        "native_metric_event_count",
        "native_metric_rejected_count",
        "native_metric_canceled_count",
        "native_metric_sample_count",
        "native_metric_liquidated",
    )

    def __init__(self, payload: object, *, max_cached_frames: int = 3) -> None:
        if max_cached_frames <= 0:
            raise ValueError("max_cached_frames must be > 0")
        self._payload = payload
        self.header = NativeResultHeaderV2.from_payload(payload)
        if self.header.result_version != 2:
            raise ValueError(
                "NativeResultV2Adapter requires native_result_version=2; "
                f"received {self.header.result_version}"
            )
        self._max_cached_frames = int(max_cached_frames)
        self._frames: OrderedDict[str, object] = OrderedDict()
        self._metrics: Optional[Mapping[str, object]] = None

    @property
    def profile(self) -> str:
        return self.header.output_profile

    @property
    def metrics(self) -> Mapping[str, object]:
        """Return standard native metrics without materializing pandas."""

        if self._metrics is None:
            source = _value(self._payload, "metrics", None)
            if isinstance(source, Mapping):
                values = {
                    str(key).removeprefix("native_metric_"): value
                    for key, value in source.items()
                }
            else:
                values = {
                    key.removeprefix("native_metric_"): _value(self._payload, key)
                    for key in self._METRIC_KEYS
                    if _value(self._payload, key, None) is not None
                }
            self._metrics = MappingProxyType(values)
        return self._metrics

    @property
    def materialized_frames(self) -> tuple[str, ...]:
        """Names of currently cached cold-path DataFrames."""

        return tuple(self._frames)

    def clear_materialized(self) -> None:
        """Release every locally materialized DataFrame without touching SoA."""

        self._frames.clear()

    def _cached(self, key: str, build):
        existing = self._frames.get(key)
        if existing is not None:
            self._frames.move_to_end(key)
            return existing
        value = build()
        self._frames[key] = value
        while len(self._frames) > self._max_cached_frames:
            self._frames.popitem(last=False)
        return value

    def _array(self, key: str) -> np.ndarray:
        value = _required(self._payload, key)
        return np.asarray(value)

    def to_pandas(self, *, index=None):
        """Materialize compact account paths on demand.

        ``index`` is optional because the native envelope intentionally keeps
        market ownership separate from result ownership. Passing a DatetimeIndex
        is the report layer's responsibility, not a reason to copy the market
        tape into every score result.
        """

        if self.profile == "score":
            raise ValueError("score profile has no compact path; rerun with profile='compact' or 'audit'")
        if index is not None:
            return self._build_paths_dataframe(index=index)
        return self._cached("paths", lambda: self._build_paths_dataframe(index=None))

    def _build_paths_dataframe(self, *, index):
        import pandas as pd

        equity = self._array("equity")
        columns = {
            "equity": equity,
            "fees": self._array("fees"),
            "turnover": self._array("turnover"),
            "funding": self._array("funding"),
            "initial_margin": self._array("initial_margin"),
            "maintenance_margin": self._array("maintenance_margin"),
        }
        if index is not None and len(index) != len(equity):
            raise ValueError("index length must match native compact path")
        return pd.DataFrame(columns, index=index)

    def fills_dataframe(self):
        """Materialize audit fill SoA only on demand."""

        if self.profile != "audit":
            raise ValueError("fills require profile='audit'")
        return self._cached("fills", self._build_fills_dataframe)

    def _build_fills_dataframe(self):
        import pandas as pd

        return pd.DataFrame(
            {
                "bar": self._array("fill_bar"),
                "order_id": self._array("fill_order_id"),
                "symbol": self._array("fill_symbol"),
                "side": self._array("fill_side"),
                "qty": self._array("fill_qty"),
                "price": self._array("fill_price"),
                "fee": self._array("fill_fee"),
                "reason": self._array("fill_reason"),
                "ambiguity": self._array("fill_ambiguity"),
            }
        )

    def audit_events(self):
        """Materialize audit lifecycle-event SoA only on demand."""

        if self.profile != "audit":
            raise ValueError("audit events require profile='audit'")
        return self._cached("events", self._build_events_dataframe)

    def orders_dataframe(self):
        """Compatibility alias for the retained lifecycle order-event table."""

        return self.audit_events()

    def _build_events_dataframe(self):
        import pandas as pd

        return pd.DataFrame(
            {
                "bar": self._array("event_bar"),
                "kind": self._array("event_kind"),
                "status": self._array("event_status"),
                "order_id": self._array("event_order_id"),
                "target_id": self._array("event_target_id"),
                "symbol": self._array("event_symbol"),
                "reject_code": self._array("event_reject_code"),
            }
        )


__all__ = ["NativeResultHeaderV2", "NativeResultV2Adapter"]
