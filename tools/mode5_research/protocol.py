"""Frozen time/data/retention boundaries for expanded Mode5 research."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from tools.mode5_diagnostics.identity import digest


@dataclass(frozen=True)
class ResearchProtocol:
    schema: str = "mode5_expanded_research_v1"
    preload_start: str = "2020-01-01"
    development_start: str = "2021-01-01"
    development_stop: str = "2024-01-01"
    forward_stop: str = "2026-01-01"
    unique_configs: int = 128
    formal_trials: int = 256
    seed: int = 731
    numeric_threads: int = 1
    financial_workers: int = 1
    pilot_timeout_seconds: int = 1800
    minimum_free_bytes: int = 5 * 1024**3
    scratch_cap_bytes: int = 1024**3
    retained_cap_bytes: int = 4 * 1024**3
    worker_rss_cap_bytes: int = 2 * 1024**3
    data_role: str = "DEVELOPMENT_REVIEWED_RETROSPECTIVE"
    continuous_within_scope: bool = True
    auto_deploy: bool = False
    publication: bool = False

    def __post_init__(self):
        dates = [datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            for value in (self.preload_start, self.development_start,
                          self.development_stop, self.forward_stop)]
        if not all(left < right for left, right in zip(dates, dates[1:])):
            raise ValueError("strict chronological preload/development/forward boundaries required")
        if (type(self.unique_configs) is not int or type(self.formal_trials) is not int
                or self.unique_configs < 128 or self.formal_trials < 256):
            raise ValueError("approved broad budgets must not be silently reduced")
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError("exact registered sampler seed required")
        if self.publication or self.auto_deploy or not self.continuous_within_scope:
            raise ValueError("research approval does not authorize publication/reset/live orders")
        if self.numeric_threads != 1 or self.financial_workers != 1:
            raise ValueError("new worker budget requires separate registration")
        for name in ("pilot_timeout_seconds", "minimum_free_bytes", "scratch_cap_bytes",
                     "retained_cap_bytes", "worker_rss_cap_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError("positive exact resource bounds required")

    @property
    def identity(self):
        return digest(asdict(self))

    @property
    def development_days(self):
        return (datetime.fromisoformat(self.development_stop)
                - datetime.fromisoformat(self.development_start)).days
