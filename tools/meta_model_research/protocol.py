"""Versioned preregistration and group/clock policy, with no outcome reads."""

from dataclasses import asdict, dataclass
import math

import pandas as pd

from quantbt.optimization.meta_selection.common import digest


GRID = (0.1, 0.3, 10.0 / 12.0, 1.0, 3.0, 10.0)
GROUPS = ("A-SC", "A-HMA", "A-HASH", "A-VWAP")


@dataclass(frozen=True)
class StudyProtocol:
    version: str = "m4_shared_ridge_calibration_replay_v1"
    policies: tuple = ("P0", "P1", "P2")
    groups: tuple = GROUPS
    grid: tuple = GRID
    acquisition_folds: tuple = tuple(range(13))
    development_folds: tuple = tuple(range(13, 25))
    evaluation_folds: tuple = tuple(range(25, 57))
    min_matured_origins: int = 12
    min_inner_origins_per_training_group: int = 3
    min_training_groups: int = 3
    min_evaluation_origins_per_group: int = 12
    min_paired_days: int = 365
    loss_relative_improvement: float = 0.02
    q_noninferiority: float = 0.05
    r_noninferiority: float = 0.05
    family_confidence: float = 0.95
    block_months: int = 3
    draws: int = 16384
    seed: int = 731
    max_fits: int = 4000
    max_cpu_seconds: int = 3600
    max_admission_cpu_seconds: int = 900
    max_rss_bytes: int = 1536 * 1024**2
    max_incremental_bytes: int = 256 * 1024**2
    min_disk_free_bytes: int = 5 * 1024**3
    min_available_ram_bytes: int = 512 * 1024**2
    primary_panel: str = "sealed_feature_dependent_base_only_v1"
    sensitivity: str = "registered_union_v1"
    tie_policy: str = "largest_mean_alpha_within_one_block_SE_of_minimum_v1"
    calibration_schedule: str = "freeze_once_before_first_outer_evaluation_v1"
    inference: str = "conditional_origin_group_macro_complete_calendar_block_bootstrap_v1"
    review_status: str = "reviewed_exploratory_not_independent_oos"

    def __post_init__(self):
        if (self.groups != GROUPS or self.grid != GRID or self.min_matured_origins != 12
                or set(self.acquisition_folds) & set(self.development_folds)
                or set(self.development_folds) & set(self.evaluation_folds)
                or tuple(self.acquisition_folds + self.development_folds + self.evaluation_folds)
                != tuple(range(57))):
            raise ValueError("registered roster, support and chronology cannot drift")

    @property
    def protocol_id(self):
        return digest(asdict(self))


def training_groups(held_out, groups=GROUPS):
    if held_out not in groups:
        raise ValueError("held-out related-alpha group is not registered")
    return tuple(g for g in groups if g != held_out)


def permitted_calibration_rows(rows, held_out, cutoff, protocol=StudyProtocol()):
    """Exclude held-out group and actual unavailable labels, not nominal dates."""
    cutoff = pd.Timestamp(cutoff)
    allowed = set(training_groups(held_out, protocol.groups))
    return tuple(r for r in rows if r["group"] in allowed
                 and r["fold"] in protocol.development_folds
                 and pd.Timestamp(r["label_available_at"]) < cutoff
                 and pd.Timestamp(r["revision_available_at"]) < cutoff)


def macro_mean(rows, value="loss"):
    groups = {}
    for row in rows:
        v = row[value]
        if v is not None:
            if not math.isfinite(v):
                raise ValueError("undefined metrics require null disposition, not NaN")
            groups.setdefault(row["group"], []).append(v)
    if not groups:
        return None
    return math.fsum(math.fsum(v) / len(v) for v in groups.values()) / len(groups)


def choose_recipe(rows, held_out, cutoff, protocol=StudyProtocol()):
    """One common algorithm; never a lookup of an alpha's own winning lambda."""
    selected = permitted_calibration_rows(rows, held_out, cutoff, protocol)
    keys = [(r["group"], r["fold"], r["alpha"]) for r in selected]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate calibration origin/grid contribution")
    groups = training_groups(held_out)
    scores, support = {}, {}
    for alpha in protocol.grid:
        subset = [r for r in selected if r["alpha"] == alpha and r["loss"] is not None]
        support[alpha] = {g: len({r["fold"] for r in subset if r["group"] == g}) for g in groups}
        if any(n < protocol.min_inner_origins_per_training_group for n in support[alpha].values()):
            return dict(policy="P0", alpha=None, reason="CALIBRATION_SUPPORT_INSUFFICIENT",
                        held_out=held_out, training_groups=groups, support=support)
        scores[alpha] = macro_mean(subset)
    best = min(scores, key=lambda a: (scores[a], -a))
    # Use intact calendar blocks, not an IID candidate-row standard error.
    block_values = []
    for start in range(13, 25, protocol.block_months):
        block = [r for r in selected if r["alpha"] == best and r["loss"] is not None
                 and start <= r["fold"] < start + protocol.block_months]
        if {r["group"] for r in block} == set(groups):
            block_values.append(macro_mean(block))
    if len(block_values) < 3:
        return dict(policy="P0", alpha=None, reason="CALIBRATION_BLOCK_SUPPORT_INSUFFICIENT",
                    held_out=held_out, training_groups=groups, support=support)
    import numpy as np
    se = float(np.std(block_values, ddof=1) / math.sqrt(len(block_values)))
    chosen = max(a for a in protocol.grid if scores[a] <= scores[best] + se)
    return dict(policy="P2", alpha=chosen, reason="COMMON_GROUP_CHRONOLOGICAL_CALIBRATION",
                held_out=held_out, training_groups=groups, support=support,
                scores=scores, minimum_alpha=best, block_se=se,
                complete_blocks=len(block_values), frozen_as_of=str(cutoff))
