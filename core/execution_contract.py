"""
Execution contract taxonomy for QuantBT backtest engines.

The contract object is deliberately small and serializable. It describes what a
backend promises to simulate; hot kernels receive integer codes compiled from
these records in later phases.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict


class SignalPhase(str, Enum):
    BAR_OPEN = "bar_open"
    BAR_CLOSE = "bar_close"


class FillPhase(str, Enum):
    SAME_OPEN = "same_open"
    SAME_CLOSE = "same_close"
    NEXT_OPEN = "next_open"
    NEXT_CLOSE = "next_close"


class MarketFillPolicy(str, Enum):
    CLOSE = "close"
    OPEN = "open"
    NEXT_OPEN = "next_open"


class StopGapPolicy(str, Enum):
    OPEN_WORSE_THAN_TRIGGER = "open_worse_than_trigger"


class TakeProfitGapPolicy(str, Enum):
    LIMIT_PRICE_CONSERVATIVE = "limit_price_conservative"
    OPEN_PRICE_IMPROVEMENT = "open_price_improvement"


class IntrabarSameBarPolicy(str, Enum):
    CONSERVATIVE = "conservative"
    STOP_FIRST = "stop_first"
    TP_FIRST = "tp_first"
    OHLC_PATH = "ohlc_path"
    OLHC_PATH = "olhc_path"
    REJECT_AMBIGUOUS = "reject_ambiguous"
    LOWER_TIMEFRAME_REQUIRED = "lower_timeframe_required"


class TrailingUpdatePhase(str, Enum):
    NONE = "none"
    NEXT_BAR = "next_bar"


class FundingPhase(str, Enum):
    POSITION_AT_EVENT = "position_at_event"
    POSITION_AT_CLOSE = "position_at_close"


class LiquidationPriority(str, Enum):
    LIQUIDATION_FIRST_AT_GAP = "liquidation_first_at_gap"
    USER_STOP_FIRST = "user_stop_first"


class AmbiguityPolicy(str, Enum):
    FLAG_AND_CONSERVATIVE = "flag_and_conservative"
    REJECT = "reject"
    LOWER_TIMEFRAME_REQUIRED = "lower_timeframe_required"


@dataclass(frozen=True)
class ExecutionContract:
    engine_id: str
    signal_phase: SignalPhase
    entry_fill_phase: FillPhase
    market_fill_policy: MarketFillPolicy
    stop_gap_policy: StopGapPolicy = StopGapPolicy.OPEN_WORSE_THAN_TRIGGER
    take_profit_gap_policy: TakeProfitGapPolicy = TakeProfitGapPolicy.LIMIT_PRICE_CONSERVATIVE
    same_bar_policy: IntrabarSameBarPolicy = IntrabarSameBarPolicy.CONSERVATIVE
    trailing_update_phase: TrailingUpdatePhase = TrailingUpdatePhase.NONE
    funding_phase: FundingPhase = FundingPhase.POSITION_AT_EVENT
    liquidation_priority: LiquidationPriority = LiquidationPriority.LIQUIDATION_FIRST_AT_GAP
    close_on_last_bar: bool = True
    ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.FLAG_AND_CONSERVATIVE
    strict_data: bool = True

    def __post_init__(self) -> None:
        if not self.engine_id:
            raise ValueError("engine_id is required")

    @classmethod
    def close_target(cls) -> "ExecutionContract":
        return cls(
            engine_id="close_target_v2",
            signal_phase=SignalPhase.BAR_CLOSE,
            entry_fill_phase=FillPhase.SAME_CLOSE,
            market_fill_policy=MarketFillPolicy.CLOSE,
            trailing_update_phase=TrailingUpdatePhase.NONE,
            close_on_last_bar=False,
        )

    @classmethod
    def next_open(cls) -> "ExecutionContract":
        return cls(
            engine_id="next_open_v1",
            signal_phase=SignalPhase.BAR_CLOSE,
            entry_fill_phase=FillPhase.NEXT_OPEN,
            market_fill_policy=MarketFillPolicy.NEXT_OPEN,
            trailing_update_phase=TrailingUpdatePhase.NONE,
        )

    @classmethod
    def intrabar_bracket(
        cls,
        *,
        same_bar_policy: IntrabarSameBarPolicy = IntrabarSameBarPolicy.CONSERVATIVE,
        trailing_update_phase: TrailingUpdatePhase = TrailingUpdatePhase.NEXT_BAR,
        take_profit_gap_policy: TakeProfitGapPolicy = TakeProfitGapPolicy.LIMIT_PRICE_CONSERVATIVE,
        close_on_last_bar: bool = True,
    ) -> "ExecutionContract":
        return cls(
            engine_id="intrabar_bracket_v1",
            signal_phase=SignalPhase.BAR_CLOSE,
            entry_fill_phase=FillPhase.NEXT_OPEN,
            market_fill_policy=MarketFillPolicy.NEXT_OPEN,
            same_bar_policy=same_bar_policy,
            trailing_update_phase=trailing_update_phase,
            take_profit_gap_policy=take_profit_gap_policy,
            close_on_last_bar=close_on_last_bar,
        )

    @classmethod
    def fill_replay(cls) -> "ExecutionContract":
        return cls(
            engine_id="fill_replay_v1",
            signal_phase=SignalPhase.BAR_CLOSE,
            entry_fill_phase=FillPhase.NEXT_OPEN,
            market_fill_policy=MarketFillPolicy.NEXT_OPEN,
        )

    @classmethod
    def event_lifecycle(cls) -> "ExecutionContract":
        return cls(
            engine_id="event_lifecycle_v2",
            signal_phase=SignalPhase.BAR_CLOSE,
            entry_fill_phase=FillPhase.NEXT_OPEN,
            market_fill_policy=MarketFillPolicy.NEXT_OPEN,
        )

    def to_metadata(self) -> Dict:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Enum):
                payload[key] = value.value
        return payload


EXECUTION_CONTRACT_REGISTRY: Dict[str, ExecutionContract] = {
    "close_target_v2": ExecutionContract.close_target(),
    "next_open_v1": ExecutionContract.next_open(),
    "intrabar_bracket_v1": ExecutionContract.intrabar_bracket(),
    "fill_replay_v1": ExecutionContract.fill_replay(),
    "event_lifecycle_v2": ExecutionContract.event_lifecycle(),
}


def get_execution_contract(engine_id: str) -> ExecutionContract:
    key = str(engine_id).lower().strip()
    if key not in EXECUTION_CONTRACT_REGISTRY:
        raise KeyError(f"unknown execution contract {engine_id!r}")
    return EXECUTION_CONTRACT_REGISTRY[key]
