"""Explicit, opt-in cold-report configuration; no execution or global cache."""

from dataclasses import dataclass, field

from ..report_contracts import ReportingContractV1


@dataclass(frozen=True, kw_only=True)
class ReportingRequest:
    account: ReportingContractV1
    result_identity: str
    backend: str = "python"
    retain_episodes: bool = False
    partial_mask: tuple[bool, ...] | None = None
    return_witness: str | None = None
    naive_timezone: str | None = None
    profile: str = "completed"
    index: object = None
    ledger: object = None
    ledger_contracts: tuple[ReportingContractV1, ...] = ()
    execution: object = None
    cache: object = None
    _partial_mask_bytes: bytes | None = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self):
        if not isinstance(self.account, ReportingContractV1) or self.account.unit != "account_period":
            raise ValueError("account-period reporting contract required")
        if not isinstance(self.result_identity, str) or not self.result_identity.strip():
            raise ValueError("explicit completed-result identity required")
        if self.backend not in {"python", "numba"}:
            raise NotImplementedError("reporting V1 supports Python/Numba, not native metric V2")
        if not isinstance(self.retain_episodes, bool):
            raise TypeError("retain_episodes must be boolean")
        if self.partial_mask is not None:
            if not isinstance(self.partial_mask, tuple) or any(type(v) is not bool for v in self.partial_mask):
                raise TypeError("partial_mask must be an immutable tuple of booleans")
            if not self.return_witness:
                raise ValueError("explicit return/partial-period witness required")
            import numpy as np
            mask = np.fromiter(self.partial_mask, dtype=np.bool_, count=len(self.partial_mask))
            object.__setattr__(self, "_partial_mask_bytes", mask.tobytes())
        if self.naive_timezone not in {None, "UTC"}:
            raise ValueError("only explicit naive_timezone='UTC' is supported")
        if not isinstance(self.ledger_contracts, tuple):
            raise TypeError("ledger_contracts must be an immutable tuple")
        units = set()
        for contract in self.ledger_contracts:
            if contract.unit not in {"closed_trade", "closed_action"} or contract.unit in units:
                raise ValueError("one contract per closed-trade/action population required")
            units.add(contract.unit)
            for field in ("scope", "currency", "baseline_equity", "baseline_time_ns", "scope_end_ns"):
                if getattr(contract, field) != getattr(self.account, field):
                    raise ValueError("ledger/account scope, baseline and currency must agree")
        if self.ledger is not None and not self.ledger_contracts:
            raise ValueError("recorded ledger requires explicit matching/grouping contracts")

    @property
    def _partial_mask_array(self):
        if self._partial_mask_bytes is None:
            return None
        import numpy as np
        return np.frombuffer(self._partial_mask_bytes, np.bool_)
