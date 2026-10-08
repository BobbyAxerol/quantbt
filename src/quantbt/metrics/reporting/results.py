"""Small reporting results; optional episode buffers are serialized only on demand."""

from dataclasses import dataclass, fields, is_dataclass
import math
import sys

from ..report_contracts import ReportingMetricV1
from .snapshots import SnapshotValue


@dataclass(frozen=True, kw_only=True)
class ReportingResult(SnapshotValue):
    contract_identity: str
    input_identity: str
    metrics: tuple[ReportingMetricV1, ...]
    provenance_json: str
    episodes: object = None

    def metric(self, name):
        key = name if name.startswith("reporting.") else "reporting." + name
        return next(metric for metric in self.metrics if metric.metric_id == key)

    @property
    def retained_bytes(self):
        seen = set()
        def size(value):
            if id(value) in seen:
                return 0
            seen.add(id(value))
            total = sys.getsizeof(value)
            if is_dataclass(value):
                total += sys.getsizeof(value.__dict__) if hasattr(value, "__dict__") else 0
                return total + sum(size(getattr(value, f.name)) for f in fields(value))
            if isinstance(value, (tuple, list)):
                return total + sum(size(item) for item in value)
            if hasattr(value, "nbytes"):
                return total + int(value.nbytes)
            return total
        return size(self)

    def to_metadata(self):
        import json
        result = dict(contract_identity=self.contract_identity, input_identity=self.input_identity,
                      metrics=[metric.to_metadata() for metric in self.metrics],
                      provenance=json.loads(self.provenance_json))
        if self.episodes is not None:
            result["drawdown_episodes"] = self.episodes.to_rows()
        return result


class MetricBuilder:
    def __init__(self, contract, coverage):
        self.contract = contract
        self.coverage = coverage
        self.contract_identity = contract.identity
        self.metrics = []

    def add(self, name, value=None, *, unit="ratio", count=0, status=None, reason=None):
        if status is None:
            status = "valid" if value is not None and math.isfinite(value) else "undefined"
        if status == "valid" and (value is None or not math.isfinite(value)):
            status, value, reason = "invalid", None, "numeric overflow"
        if status != "valid":
            value = None
            reason = reason or "undefined for the declared observation population"
        self.metrics.append(ReportingMetricV1(metric_id="reporting." + name,
                            contract_identity=self.contract_identity, unit=unit, status=status,
                            value=float(value) if value is not None else None,
                            sample_count=int(count), coverage=self.coverage, reason=reason))

    def ratio(self, name, numerator, denominator, *, count, unit="ratio"):
        if denominator > 0:
            self.add(name, numerator / denominator, unit=unit, count=count)
        else:
            self.add(name, unit=unit, count=count,
                     status="no_loss" if numerator > 0 else "undefined",
                     reason="zero loss/downside denominator" if numerator > 0 else "zero denominator")
