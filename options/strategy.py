"""Option strategy adapters.

Adapters live above the option execution engine. They convert observable
option-chain snapshots into package intents and audit tables. They do not own
fills, premium accounting, margin, settlement, or PnL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.schema import OrderSide
from .hedging import OptionHedgeConfig
from .packages import OptionPackageIntent, OptionPackageLeg
from .schema import OptionInstrumentRegistry


@dataclass(frozen=True)
class OptionStrategyRun:
    """Package-level strategy output consumed by `QuantBTEndpoint.options`."""

    packages: tuple[OptionPackageIntent, ...]
    hedge_policy: Optional[OptionHedgeConfig] = None
    selected_contracts: pd.DataFrame = field(default_factory=pd.DataFrame)
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class GammaScalpingConfig:
    """Configuration for a simple ATM straddle gamma-scalping adapter."""

    side: str = "long"
    quantity: float = 1.0
    min_dte_days: float = 2.0
    max_dte_days: float = 45.0
    roll_dte_days: float = 2.0
    max_spread_bps: Optional[float] = None
    min_bid_size: float = 0.0
    min_ask_size: float = 0.0
    min_volume: float = 0.0
    min_open_interest: float = 0.0
    hedge_policy: Optional[OptionHedgeConfig] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        side = str(self.side).lower().strip()
        if side not in {"long", "short"}:
            raise ValueError("GammaScalpingConfig.side must be long or short")
        object.__setattr__(self, "side", side)
        if self.quantity <= 0.0:
            raise ValueError("GammaScalpingConfig.quantity must be > 0")
        if self.min_dte_days < 0.0 or self.max_dte_days <= 0.0:
            raise ValueError("DTE bounds must be non-negative and max_dte_days > 0")
        if self.min_dte_days > self.max_dte_days:
            raise ValueError("min_dte_days must be <= max_dte_days")
        if self.roll_dte_days < 0.0:
            raise ValueError("roll_dte_days must be >= 0")
        for name in ("min_bid_size", "min_ask_size", "min_volume", "min_open_interest"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be >= 0")
        if self.max_spread_bps is not None and self.max_spread_bps < 0.0:
            raise ValueError("max_spread_bps must be >= 0")


def build_gamma_scalping_strategy_run(
    chain: pd.DataFrame,
    instruments: OptionInstrumentRegistry,
    config: Optional[GammaScalpingConfig] = None,
) -> OptionStrategyRun:
    """
    Build open/roll/close straddle packages from observable chain snapshots.

    Selection is snapshot-local: at each decision timestamp, the adapter only
    inspects rows with that exact `timestamp_ns`. The selected pair is the
    valid same-expiry same-strike call/put closest to the observed index price.
    """
    cfg = config or GammaScalpingConfig()
    frame = _canonical_strategy_frame(chain)
    valid_symbols = set(instruments.symbols)
    frame = frame[frame["instrument_id"].isin(valid_symbols)].copy()
    if frame.empty:
        raise ValueError("gamma scalping adapter found no chain rows matching instrument registry")

    timestamps = [int(ts) for ts in sorted(frame["timestamp_ns"].unique())]
    packages: list[OptionPackageIntent] = []
    selected_rows: list[dict] = []
    active: Optional[dict] = None

    for ts in timestamps:
        is_last = ts == timestamps[-1]
        if active is not None:
            dte = (int(active["expiry_ns"]) - ts) / _DAY_NS
            if dte <= cfg.roll_dte_days or is_last:
                if _has_quotes(frame, ts, (active["call_id"], active["put_id"])):
                    packages.append(_straddle_package(ts, active, cfg, action="close"))
                    selected_rows.append({**active, "timestamp_ns": ts, "action": "close", "dte_days": float(dte)})
                active = None
                if is_last:
                    break

        if active is None and not is_last:
            selection = _select_atm_pair(frame, ts, cfg)
            if selection is None:
                continue
            packages.append(_straddle_package(ts, selection, cfg, action="open"))
            dte = (int(selection["expiry_ns"]) - ts) / _DAY_NS
            selected_rows.append({**selection, "timestamp_ns": ts, "action": "open", "dte_days": float(dte)})
            active = selection

    if active is not None:
        ts = timestamps[-1]
        if _has_quotes(frame, ts, (active["call_id"], active["put_id"])):
            packages.append(_straddle_package(ts, active, cfg, action="close"))
            selected_rows.append(
                {
                    **active,
                    "timestamp_ns": ts,
                    "action": "close",
                    "dte_days": float((int(active["expiry_ns"]) - ts) / _DAY_NS),
                }
            )

    selected = pd.DataFrame(selected_rows)
    return OptionStrategyRun(
        packages=tuple(packages),
        hedge_policy=cfg.hedge_policy,
        selected_contracts=selected,
        metadata={
            "strategy": "gamma_scalping",
            "side": cfg.side,
            "quantity": float(cfg.quantity),
            "package_count": len(packages),
            "selection_count": len(selected),
            **cfg.metadata,
        },
    )


def _canonical_strategy_frame(chain: pd.DataFrame) -> pd.DataFrame:
    required = {
        "timestamp_ns",
        "instrument_id",
        "expiry_ns",
        "strike",
        "option_kind",
        "bid_price",
        "ask_price",
        "bid_size",
        "ask_size",
        "index_price",
    }
    missing = sorted(required.difference(chain.columns))
    if missing:
        raise ValueError(f"gamma scalping chain missing columns: {missing}")
    frame = chain.copy()
    for column in ("timestamp_ns", "expiry_ns"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    for column in ("strike", "bid_price", "ask_price", "bid_size", "ask_size", "index_price"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
    if "volume" not in frame:
        frame["volume"] = 0.0
    if "open_interest" not in frame:
        frame["open_interest"] = 0.0
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0).astype("float64")
    frame["open_interest"] = pd.to_numeric(frame["open_interest"], errors="coerce").fillna(0.0).astype("float64")
    frame["option_kind"] = frame["option_kind"].astype(str).str.lower().str.strip()
    return frame.sort_values(["timestamp_ns", "expiry_ns", "strike", "option_kind", "instrument_id"]).reset_index(drop=True)


def _select_atm_pair(frame: pd.DataFrame, timestamp_ns: int, cfg: GammaScalpingConfig) -> Optional[dict]:
    snap = frame[frame["timestamp_ns"] == int(timestamp_ns)].copy()
    if snap.empty:
        return None
    snap = snap[(snap["bid_price"] > 0.0) & (snap["ask_price"] > 0.0) & (snap["ask_price"] >= snap["bid_price"])]
    snap = snap[(snap["bid_size"] >= cfg.min_bid_size) & (snap["ask_size"] >= cfg.min_ask_size)]
    snap = snap[(snap["volume"] >= cfg.min_volume) & (snap["open_interest"] >= cfg.min_open_interest)]
    dte = (snap["expiry_ns"] - int(timestamp_ns)) / _DAY_NS
    snap = snap[(dte >= cfg.min_dte_days) & (dte <= cfg.max_dte_days)]
    if cfg.max_spread_bps is not None:
        mid = 0.5 * (snap["bid_price"] + snap["ask_price"])
        spread_bps = np.where(mid > 0.0, (snap["ask_price"] - snap["bid_price"]) / mid * 10_000.0, np.inf)
        snap = snap[spread_bps <= float(cfg.max_spread_bps)]
    if snap.empty:
        return None

    spot = float(snap["index_price"].median())
    pair_groups = snap.groupby(["expiry_ns", "strike"])
    candidates = []
    for (expiry_ns, strike), group in pair_groups:
        kinds = set(group["option_kind"])
        if kinds != {"call", "put"}:
            continue
        call = group[group["option_kind"] == "call"].iloc[0]
        put = group[group["option_kind"] == "put"].iloc[0]
        candidates.append(
            {
                "expiry_ns": int(expiry_ns),
                "strike": float(strike),
                "spot": spot,
                "call_id": str(call["instrument_id"]),
                "put_id": str(put["instrument_id"]),
                "call_delta": float(call.get("delta", np.nan)),
                "put_delta": float(put.get("delta", np.nan)),
                "distance": abs(float(strike) - spot),
                "dte_days": float((int(expiry_ns) - int(timestamp_ns)) / _DAY_NS),
            }
        )
    if not candidates:
        return None
    return min(candidates, key=lambda row: (row["distance"], row["dte_days"]))


def _straddle_package(timestamp_ns: int, selection: dict, cfg: GammaScalpingConfig, *, action: str) -> OptionPackageIntent:
    if action == "open":
        side = OrderSide.BUY if cfg.side == "long" else OrderSide.SELL
    elif action == "close":
        side = OrderSide.SELL if cfg.side == "long" else OrderSide.BUY
    else:
        raise ValueError("action must be open or close")
    return OptionPackageIntent(
        timestamp_ns=int(timestamp_ns),
        package_id=f"gamma-{action}:{selection['call_id']}:{selection['put_id']}:{timestamp_ns}",
        legs=(
            OptionPackageLeg(selection["call_id"], side, 1.0, role=f"{action}_call"),
            OptionPackageLeg(selection["put_id"], side, 1.0, role=f"{action}_put"),
        ),
        quantity=float(cfg.quantity),
        tag=f"gamma_scalping_{action}",
        metadata={
            "strategy": "gamma_scalping",
            "action": action,
            "side": cfg.side,
            "strike": float(selection["strike"]),
            "expiry_ns": int(selection["expiry_ns"]),
            "spot": float(selection["spot"]),
        },
    )


def _has_quotes(frame: pd.DataFrame, timestamp_ns: int, symbols: Sequence[str]) -> bool:
    snap_symbols = set(frame.loc[frame["timestamp_ns"] == int(timestamp_ns), "instrument_id"])
    return all(symbol in snap_symbols for symbol in symbols)


_DAY_NS = 24 * 60 * 60 * 1_000_000_000
