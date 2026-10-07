"""Recorded outcomes, not a fill matcher or an inferred strategy/action model."""

from dataclasses import asdict, dataclass, field
import math

from ..report_contracts import ReportingCoverageV1
from .inputs import identity


@dataclass(frozen=True, kw_only=True)
class RecordedOutcome:
    trade_id: str
    symbol: str
    side: str
    currency: str
    closed_at_ns: int | None
    close_sequence: int
    opened_at_ns: int | None = None
    action_id: str | None = None
    net_pnl: float | None = None
    gross_pnl: float | None = None
    allocated_fee: float | None = None
    allocated_funding_cost: float | None = None
    allocated_slippage_cost: float | None = None
    open_unrealized_pnl: float | None = None
    holding_bars: int | None = None
    initial_risk: float | None = None
    return_denominator: float | None = None
    mfe_net_pnl: float | None = None
    mae_net_pnl: float | None = None
    excursion_witness: str | None = None
    close_reason: str | None = None

    def __post_init__(self):
        for name in ("trade_id", "symbol", "currency"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"explicit {name} required")
        if self.side not in {"long", "short", "mixed"}:
            raise ValueError("recorded outcome side required")
        for name in ("closed_at_ns", "opened_at_ns", "close_sequence", "holding_bars"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or (name in {"close_sequence", "holding_bars"} and value < 0)):
                raise ValueError(f"integer {name} required")
        if self.close_sequence is None:
            raise ValueError("stable close sequence required")
        if self.closed_at_ns is not None and self.opened_at_ns is not None and self.closed_at_ns < self.opened_at_ns:
            raise ValueError("closure precedes recorded opening")
        for name in ("net_pnl", "gross_pnl", "allocated_fee", "allocated_funding_cost", "allocated_slippage_cost",
                     "open_unrealized_pnl", "initial_risk", "return_denominator", "mfe_net_pnl", "mae_net_pnl"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"finite {name} required")
        for name in ("initial_risk", "return_denominator"):
            if getattr(self, name) is not None and getattr(self, name) <= 0:
                raise ValueError(f"positive {name} required")
        if self.action_id is not None and (not isinstance(self.action_id, str) or not self.action_id):
            raise ValueError("nonempty recorded action identity required")


@dataclass(frozen=True, kw_only=True)
class ActionRoster:
    action_id: str
    outcome_ids: tuple[str, ...]
    shared_net_adjustment: float
    allocation_witness: str

    def __post_init__(self):
        object.__setattr__(self, "outcome_ids", tuple(self.outcome_ids))
        if not self.action_id or not self.outcome_ids or len(set(self.outcome_ids)) != len(self.outcome_ids):
            raise ValueError("nonempty unique authoritative action roster required")
        if not all(isinstance(value, str) and value for value in self.outcome_ids):
            raise ValueError("roster outcome identities required")
        if not self.allocation_witness or not isinstance(self.allocation_witness, str):
            raise ValueError("recorded shared-cost allocation witness required")
        if not isinstance(self.shared_net_adjustment, (int, float)) or isinstance(self.shared_net_adjustment, bool) or not math.isfinite(self.shared_net_adjustment):
            raise ValueError("finite recorded shared net adjustment required")


@dataclass(frozen=True, kw_only=True)
class LedgerObservations:
    records: tuple[RecordedOutcome, ...]
    coverage: ReportingCoverageV1
    matching: str
    rosters: tuple[ActionRoster, ...] = ()
    valuation_time_ns: int | None = None
    identity: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "rosters", tuple(self.rosters))
        if not isinstance(self.coverage, ReportingCoverageV1):
            raise ValueError("typed ledger coverage required")
        if self.matching not in {"position_episode", "average_cost", "recorded_lot"}:
            raise ValueError("explicit executed matching witness required")
        if not all(isinstance(row, RecordedOutcome) for row in self.records):
            raise ValueError("typed recorded outcomes required")
        if len({row.trade_id for row in self.records}) != len(self.records):
            raise ValueError("duplicate outcome identity")
        closures = [(r.closed_at_ns, r.close_sequence) for r in self.records if r.closed_at_ns is not None]
        if len(set(closures)) != len(closures):
            raise ValueError("closed outcomes need a unique timestamp/sequence tie-break")
        if self.coverage.ledger in {"complete", "truncated"} and self.coverage.retained_rows != len(self.records):
            raise ValueError("ledger coverage row count differs from recorded population")
        if self.coverage.ledger in {"omitted", "unsupported"} and self.records:
            raise ValueError("absent ledger cannot retain outcomes")
        if not all(isinstance(roster, ActionRoster) for roster in self.rosters):
            raise ValueError("typed action rosters required")
        if len({r.action_id for r in self.rosters}) != len(self.rosters):
            raise ValueError("duplicate action roster")
        if self.valuation_time_ns is not None and type(self.valuation_time_ns) is not int:
            raise ValueError("integer valuation timestamp required")
        if self.valuation_time_ns is not None and any(
            (row.opened_at_ns is not None and row.opened_at_ns > self.valuation_time_ns) or
            (row.closed_at_ns is not None and row.closed_at_ns > self.valuation_time_ns) for row in self.records):
            raise ValueError("recorded outcome beyond declared valuation observation")
        object.__setattr__(self, "identity", identity(dict(records=[asdict(r) for r in self.records],
                           rosters=[asdict(r) for r in self.rosters], matching=self.matching,
                           coverage=asdict(self.coverage), valuation_time_ns=self.valuation_time_ns)))
