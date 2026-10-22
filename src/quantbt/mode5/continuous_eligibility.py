"""Versioned whole-account eligibility; annual measurements remain unaltered."""
from dataclasses import dataclass
import math

from .dossier.records import Record


@dataclass(frozen=True)
class WholeAccountEligibility:
    """An opt-in researcher mandate, not an objective or metric estimator."""

    @staticmethod
    def metadata():
        return dict(schema="quantbt.mode5.whole_account_eligibility.v1",
            quality_scope="whole_account", risk_scope="whole_and_each_environment",
            support_scope="each_environment", require_finite_whole_sharpe=True,
            quality_floor_comparison="greater_or_equal_v1")

    @classmethod
    def read(cls, record):
        value = record.data if isinstance(record, Record) else record
        if not isinstance(value, dict) or value != cls.metadata() or type(value.get("require_finite_whole_sharpe")) is not bool:
            raise ValueError("complete frozen whole-account eligibility policy required")
        return cls()

    def project(self, whole, observations):
        observations = tuple(observations)
        if not observations or any(type(whole[k]) is not bool for k in ("quality_pass", "risk_pass", "support_pass")):
            raise ValueError("original typed whole/annual observations required")
        value = whole["raw_sharpe"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("finite original whole Sharpe or explicit undefined required")
        quality = whole["quality_pass"] and whole["utility"]["status"] == "VALID" and value is not None
        rows = []
        for observation in observations:
            if any(type(observation[k]) is not bool for k in ("quality_pass", "risk_pass", "support_pass")):
                raise ValueError("explicit annual qualification flags required")
            rows.append({**observation, "environment_quality_diagnostic": observation["quality_pass"],
                "quality_pass": quality, "risk_pass": whole["risk_pass"] and observation["risk_pass"],
                "support_pass": whole["support_pass"] and observation["support_pass"],
                "quality_pass_basis": self.metadata()["schema"]})
        return tuple(rows)

    def eligible(self, whole, observations):
        rows = self.project(whole, observations)
        return all(all(row[k] for k in ("quality_pass", "risk_pass", "support_pass"))
                   and row["utility"]["status"] == "VALID" for row in rows)
