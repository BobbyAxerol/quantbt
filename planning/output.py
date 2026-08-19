"""Compile one output projection for a resolved execution plan."""

from __future__ import annotations

from .models import (
    AttributionMask,
    DetailLevel,
    MetricMask,
    OutputRequirements,
    PathMask,
    PositionProjection,
    RunProfile,
    SnapshotSchedule,
)


def compile_output_requirements(
    *,
    profile: RunProfile | str,
    public_result: bool = True,
    declared_strategy_requirements: bool = True,
) -> OutputRequirements:
    profile = profile if isinstance(profile, RunProfile) else RunProfile(str(profile).lower().strip())

    if profile is RunProfile.SCORE:
        return OutputRequirements(
            scalar_metrics=MetricMask.ALL,
            dense_paths=PathMask.NONE,
            fill_detail=DetailLevel.COUNT,
            event_detail=DetailLevel.COUNT,
            active_order_detail=DetailLevel.NONE,
            final_positions=PositionProjection.FINAL,
            per_bar_positions=PositionProjection.NONE,
            account_snapshots=SnapshotSchedule.FINAL,
            attribution=AttributionMask.NONE,
            public_result=False,
            materialize_pandas=False,
        )

    conservative = not declared_strategy_requirements
    if profile is RunProfile.MINIMAL:
        return OutputRequirements(
            scalar_metrics=MetricMask.ALL,
            dense_paths=PathMask.PUBLIC_DEFAULT,
            fill_detail=DetailLevel.COMPACT,
            event_detail=DetailLevel.COUNT,
            active_order_detail=DetailLevel.NONE,
            final_positions=PositionProjection.FINAL,
            per_bar_positions=PositionProjection.PER_BAR,
            account_snapshots=SnapshotSchedule.PER_BAR,
            attribution=AttributionMask.NONE,
            public_result=public_result,
            materialize_pandas=public_result,
        )
    if profile is RunProfile.STANDARD:
        return OutputRequirements(
            scalar_metrics=MetricMask.ALL,
            dense_paths=PathMask.PUBLIC_DEFAULT,
            fill_detail=DetailLevel.FULL,
            event_detail=DetailLevel.COMPACT if conservative else DetailLevel.COUNT,
            active_order_detail=DetailLevel.COMPACT if conservative else DetailLevel.NONE,
            final_positions=PositionProjection.FINAL,
            per_bar_positions=PositionProjection.PER_BAR,
            account_snapshots=SnapshotSchedule.PER_BAR,
            attribution=AttributionMask.SYMBOL,
            public_result=public_result,
            materialize_pandas=public_result,
        )
    return OutputRequirements(
        scalar_metrics=MetricMask.ALL,
        dense_paths=PathMask.PUBLIC_DEFAULT,
        fill_detail=DetailLevel.FULL,
        event_detail=DetailLevel.FULL,
        active_order_detail=DetailLevel.FULL,
        final_positions=PositionProjection.FINAL,
        per_bar_positions=PositionProjection.PER_BAR,
        account_snapshots=SnapshotSchedule.PER_BAR,
        attribution=AttributionMask.SYMBOL | AttributionMask.LIQUIDATION,
        public_result=public_result,
        materialize_pandas=public_result,
    )


__all__ = ["compile_output_requirements"]
