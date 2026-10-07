"""Small reporting results; optional episode buffers are serialized only on demand."""

from dataclasses import dataclass
import math

from ..report_contracts import ReportingMetricV1


@dataclass(frozen=True, kw_only=True)
class ReportingResult:
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
        return len(self.provenance_json.encode("utf-8")) + len(self.metrics) * 1024 + (
            self.episodes.retained_bytes if self.episodes is not None else 0)

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
