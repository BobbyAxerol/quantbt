"""
Reporting scope helpers.

Walk-forward and train/test split runs store a full stitched timeline, but the
natural performance report is the OOS/test portion only.  These helpers keep
endpoint-level and result-level metrics/plots consistent.
"""

from __future__ import annotations

import pandas as pd

from .results import BacktestResultV2
from .types import BacktestResult


def scoped_result(result, scope: str = "auto"):
    """
    Return `result` or an OOS/test-sliced copy for reporting.

    `auto` means OOS/test for walk-forward artifacts and full result for normal
    backtests.  Use `full` to audit the complete stitched timeline.
    """
    normalized = str(scope or "auto").lower().strip()
    if normalized == "auto":
        normalized = "oos" if "walk_forward" in result.metadata else "full"
    if normalized == "full":
        return result
    if normalized in {"test", "oos"}:
        return _slice_result_to_walk_forward_oos(result, scope=normalized)
    raise ValueError("scope must be auto, full, test, or oos")


def _slice_result_to_walk_forward_oos(result, scope: str):
    wf_meta = result.metadata.get("walk_forward")
    if not wf_meta:
        raise ValueError(f"scope={scope!r} is only available for walk_forward/train_test_split results")
    fold_table = wf_meta.get("fold_table")
    if fold_table is None or len(fold_table) == 0:
        raise ValueError("walk-forward result does not contain a fold_table")

    idx = result.equity.index
    mask = pd.Series(False, index=idx)
    for _, row in fold_table.iterrows():
        start = pd.Timestamp(row["test_start"])
        end = pd.Timestamp(row["test_end"])
        mask |= (idx >= start) & (idx <= end)
    if not bool(mask.any()):
        raise ValueError("walk-forward OOS/test scope contains no bars in result index")

    sliced_metadata = dict(result.metadata)
    sliced_wf_meta = dict(wf_meta)
    sliced_wf_meta["report_scope"] = scope
    sliced_metadata["walk_forward"] = sliced_wf_meta

    if isinstance(result, BacktestResultV2):
        return BacktestResultV2(
            equity=result.equity.loc[mask].copy(),
            returns=result.returns.loc[mask].copy(),
            positions=result.positions.loc[mask].copy(),
            closes=result.closes.loc[mask].copy(),
            symbols=list(result.symbols),
            initial_capital=float(result.initial_capital),
            leverage=float(result.leverage),
            liquidated=bool(result.liquidated),
            liquidation_bar=int(result.liquidation_bar),
            orders=getattr(result, "orders", ()),
            fills=getattr(result, "fills", ()),
            trades=getattr(result, "trades", ()),
            fees=_slice_indexed_like(result.fees, mask),
            funding=_slice_indexed_like(result.funding, mask),
            margin=_slice_indexed_like(result.margin, mask),
            diagnostics=_slice_indexed_like(result.diagnostics, mask),
            metadata=sliced_metadata,
        )

    return BacktestResult(
        equity=result.equity.loc[mask].copy(),
        returns=result.returns.loc[mask].copy(),
        positions=result.positions.loc[mask].copy(),
        closes=result.closes.loc[mask].copy(),
        symbols=list(result.symbols),
        initial_capital=float(result.initial_capital),
        leverage=float(result.leverage),
        liquidated=bool(result.liquidated),
        liquidation_bar=int(result.liquidation_bar),
        metadata=sliced_metadata,
    )


def _slice_indexed_like(obj, mask: pd.Series):
    if obj is None:
        return obj
    if isinstance(obj, (pd.Series, pd.DataFrame)) and obj.index.equals(mask.index):
        return obj.loc[mask].copy()
    return obj
