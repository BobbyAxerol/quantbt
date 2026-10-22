"""Opt-in research views; no trading, financial state or regime switching."""

from .manifests import AnchorManifest, EnvironmentRegistry, match_calendar
from .labels import FeatureTape, LabelTape, PartitionSnapshot, VintageStore, fit_partition
from .rights import ChronologyPlan, KnownArtifact, ScopeUse, require_known, independent_scope
from .attribution import daily_path, attribute_days, attribute_campaigns
from .support import overlap_support

__all__ = ["AnchorManifest", "EnvironmentRegistry", "match_calendar", "FeatureTape",
    "LabelTape", "PartitionSnapshot", "VintageStore", "fit_partition", "ChronologyPlan",
    "KnownArtifact", "ScopeUse", "require_known", "independent_scope", "daily_path",
    "attribute_days", "attribute_campaigns", "overlap_support"]
