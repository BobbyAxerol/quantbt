"""Frozen support/inference contracts and immutable original daily observations."""
from dataclasses import asdict, dataclass
import math

import numpy as np

from quantbt.mode5.diagnostics.identity import digest

DAY_NS = 86_400_000_000_000


@dataclass(frozen=True)
class EconomicProtocol:
    protocol_id: str
    development_days: int = 365
    forward_days: int = 365
    minimum_fills: int = 30
    minimum_campaigns: int = 20
    minimum_origins: int = 3
    block_days: int = 7
    draws: int = 1024
    seed: int = 731
    family_size: int = 5
    family_confidence: float = .99
    mean_hurdle_daily: float = .00005
    annual_periods: float = 365.
    version: str = "mode5.economic_protocol.v1"

    def __post_init__(self):
        if not self.protocol_id or self.version != "mode5.economic_protocol.v1":
            raise ValueError("explicit versioned economic registration required")
        for name in ("development_days", "forward_days", "minimum_fills", "minimum_campaigns",
                     "minimum_origins", "block_days", "draws", "family_size"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("positive integral support and inference requirements")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("frozen nonnegative seed required")
        if (not math.isfinite(self.family_confidence) or not 0 < self.family_confidence < 1
                or not math.isfinite(self.mean_hurdle_daily) or self.mean_hurdle_daily < 0
                or not math.isfinite(self.annual_periods) or self.annual_periods <= 0):
            raise ValueError("finite preferences and valid confidence/frequency required")

    @property
    def marginal_confidence(self):
        return 1 - (1 - self.family_confidence) / self.family_size

    @property
    def identity(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class DailyAccount:
    """Byte-owned snapshot survives deepcopy/pickle without writable stale hashes."""
    execution_id: str
    economic_contract: str
    params_digest: str
    times_bytes: bytes
    return_bytes: bytes
    fills: int | None
    campaigns: int | None
    accounting_verified: bool
    terminal_policy: str
    role: str

    def __post_init__(self):
        if any(not isinstance(getattr(self, name), str) or not getattr(self, name)
               for name in ("execution_id", "economic_contract", "params_digest", "terminal_policy", "role")):
            raise ValueError("original execution/parameter/economic/data-role provenance required")
        if (type(self.times_bytes) is not bytes or type(self.return_bytes) is not bytes
                or len(self.times_bytes) != len(self.return_bytes) or len(self.times_bytes) % 8):
            raise ValueError("immutable equal-length float64/int64 buffers required")
        times = self.times
        if (not len(times) or np.any(times % DAY_NS) or np.any(np.diff(times) != DAY_NS)):
            raise ValueError("complete contiguous UTC daily calendar required; no silent alignment")
        for name in ("fills", "campaigns"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("integral measured event support or explicit unavailable required")
        if type(self.accounting_verified) is not bool:
            raise ValueError("explicit original accounting verification required")

    @classmethod
    def from_arrays(cls, times, returns, **provenance):
        times, returns = np.asarray(times), np.asarray(returns, dtype=np.float64)
        if times.dtype.kind not in "iu" or times.ndim != 1 or returns.ndim != 1 or times.shape != returns.shape:
            raise ValueError("exact integral daily times aligned to original returns required")
        return cls(times_bytes=np.asarray(times, dtype="<i8").tobytes(),
                   return_bytes=np.asarray(returns, dtype="<f8").tobytes(), **provenance)

    @property
    def times(self):
        return np.frombuffer(self.times_bytes, dtype="<i8")

    @property
    def returns(self):
        return np.frombuffer(self.return_bytes, dtype="<f8")

    @property
    def identity(self):
        from hashlib import sha256
        return digest({**{k: v for k, v in asdict(self).items() if k not in {"times_bytes", "return_bytes"}},
                       "times": sha256(self.times_bytes).hexdigest(), "returns": sha256(self.return_bytes).hexdigest()})
