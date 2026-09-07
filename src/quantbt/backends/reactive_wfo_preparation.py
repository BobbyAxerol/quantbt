"""Run-local immutable calendar preparation for reactive walk-forward runs.

Reactive WFO has the same parameter-independent calendar work as ordinary
walk-forward, but it cannot reuse static signal outputs: every candidate owns a
fresh callback strategy and a fresh account.  This module therefore owns only
validated positional windows, temporal shards, annualized trade requirements,
and nested Mode 1 causal folds.  It never owns market data, scores, strategy
instances, account state, or Optuna state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

from ..core.wfo_preparation import PreparedWfoWindowRegistryV1, PreparedWfoWindowV1
from ..walkforward import WalkForwardConfig, WalkForwardFold, _build_inner_folds, _required_trades_for_index


_IS_ONLY_MODES = frozenset({"mode_4_is_only_robust", "mode_5_full_robust"})


@dataclass(slots=True)
class ReactiveWfoPreparationV1:
    """Identity-certified calendar state for exactly one reactive WFO call.

    The opaque ``owner_token`` is intentionally not a data signature.  A task
    receives a positional fast path only when it came from this exact runtime
    and passes the same canonical ``DatetimeIndex`` object registered here.
    Equivalent indexes continue through the historical checked-indexer path.
    """

    registry: PreparedWfoWindowRegistryV1
    inner_folds_by_outer_id: dict[int, tuple[WalkForwardFold, ...]]
    owner_token: object
    _inner_fold_hits: int = 0
    _inner_fold_misses: int = 0

    @classmethod
    def prepare(
        cls,
        *,
        index: pd.DatetimeIndex,
        folds: Sequence[WalkForwardFold],
        config: WalkForwardConfig,
    ) -> "ReactiveWfoPreparationV1":
        """Build all deterministic calendar artifacts before candidate scoring."""

        registry = PreparedWfoWindowRegistryV1(index)
        inner_folds_by_outer_id: dict[int, tuple[WalkForwardFold, ...]] = {}
        mode = str(config.optimization_mode).lower().strip()
        schedule = str(config.optimization_schedule).lower().strip()

        for fold in folds:
            cls._register_fold(registry, fold, config=config, include_shards=mode in _IS_ONLY_MODES)
            if schedule == "per_fold_causal" and mode == "mode_1_decay":
                inner = tuple(_build_inner_folds(fold, config))
                inner_folds_by_outer_id[id(fold)] = inner
                for inner_fold in inner:
                    cls._register_fold(registry, inner_fold, config=config, include_shards=False)

        return cls(
            registry=registry,
            inner_folds_by_outer_id=inner_folds_by_outer_id,
            owner_token=object(),
        )

    @staticmethod
    def _register_fold(
        registry: PreparedWfoWindowRegistryV1,
        fold: WalkForwardFold,
        *,
        config: WalkForwardConfig,
        include_shards: bool,
    ) -> None:
        if registry.register(fold.train_index) is None or registry.register(fold.test_index) is None:
            raise RuntimeError("reactive WFO fold is not a contiguous canonical market window")
        if include_shards:
            registry.register_shards(fold.train_index, int(config.is_subperiods))

    def window_for(self, index: pd.DatetimeIndex) -> PreparedWfoWindowV1 | None:
        """Return an exact prepared task window, otherwise record a safe miss."""

        return self.registry.window_for(index)

    def shards_for(self, index: pd.DatetimeIndex, n_parts: int) -> tuple[pd.DatetimeIndex, ...] | None:
        """Return exact prepared temporal shards, never a value-equivalent lookup."""

        return self.registry.shards_for(index, int(n_parts))

    def required_trades_for(
        self,
        index: pd.DatetimeIndex,
        min_trades_per_year: float | None,
    ) -> float:
        """Use cached annualization only for an exact canonical view."""

        value = self.registry.required_trades_for(index, min_trades_per_year)
        if value is not None:
            return float(value)
        return float(_required_trades_for_index(index, min_trades_per_year))

    def inner_folds_for(self, fold: WalkForwardFold) -> tuple[WalkForwardFold, ...] | None:
        """Return the prebuilt causal inner folds for this exact outer fold."""

        result = self.inner_folds_by_outer_id.get(id(fold))
        if result is None:
            self._inner_fold_misses += 1
            return None
        self._inner_fold_hits += 1
        return result

    def metadata(self) -> Mapping[str, object]:
        return {
            "schema": "quantbt-reactive-wfo-preparation-v1",
            "contract": "run_local_identity_calendar_v1",
            "nested_mode1_outer_folds": int(len(self.inner_folds_by_outer_id)),
            "nested_mode1_inner_folds": int(sum(len(value) for value in self.inner_folds_by_outer_id.values())),
            "inner_fold_lookup_hits": int(self._inner_fold_hits),
            "inner_fold_lookup_misses": int(self._inner_fold_misses),
            "window_registry": dict(self.registry.metadata()),
        }


__all__ = ["ReactiveWfoPreparationV1"]
