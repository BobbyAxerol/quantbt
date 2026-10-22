"""Small reporting results; optional episode buffers are serialized only on demand."""

from dataclasses import dataclass, fields, is_dataclass
import math
import sys

from ..report_contracts import ReportingMetricV1
from .snapshots import SnapshotValue


def serialize_provenance(metadata):
    """Keep finite fields exact and disclose nonrepresentable aggregate paths."""
    import json
    issues = {}

    def safe(value, path):
        if isinstance(value, float) and not math.isfinite(value):
            issues[path] = dict(status="invalid", reason="numeric overflow")
            return None
        if isinstance(value, dict):
            return {key: safe(item, f"{path}.{key}" if path else str(key)) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
        return value

    result = safe(metadata, "")
    if issues:
        result["numeric_issues"] = issues
    return json.dumps(result, sort_keys=True, allow_nan=False)


@dataclass(frozen=True, kw_only=True)
class ReportingResult(SnapshotValue):
    contract_identity: str
    input_identity: str
    metrics: tuple[ReportingMetricV1, ...]
    provenance_json: str
    episodes: object = None

    def __post_init__(self):
        self._seal_arrays()

    def metric(self, name):
        self.validate_snapshot()
        key = name if name.startswith("reporting.") else "reporting." + name
        return next(metric for metric in self.metrics if metric.metric_id == key)

    @property
    def retained_bytes(self):
        self.validate_snapshot()
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
        self.validate_snapshot()
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
            status = "valid" if value is not None else "undefined"
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
        if denominator == 0 and numerator > 0:
            self.add(name, unit=unit, count=count, status="no_loss", reason="zero loss/downside denominator")
        elif not math.isfinite(numerator) or not math.isfinite(denominator):
            self.add(name, unit=unit, count=count, status="invalid", reason="numeric overflow")
        elif denominator > 0:
            self.add(name, numerator / denominator, unit=unit, count=count)
        else:
            self.add(name, unit=unit, count=count,
                     status="no_loss" if numerator > 0 else "undefined",
                     reason="zero loss/downside denominator" if numerator > 0 else "zero denominator")
