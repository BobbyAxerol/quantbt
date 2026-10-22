"""Closed model roster and causal common-policy screening, without outcome IO."""

from dataclasses import asdict, dataclass
import math

import numpy as np

from quantbt.optimization.meta_selection.common import digest, utc
from .protocol import macro_mean, training_groups


ROSTER = ("B1", "H135", "H200", "X2", "X3")
COMPLEXITY = {code: i for i, code in enumerate(ROSTER)}


@dataclass(frozen=True, slots=True)
class FamilyProtocol:
    version: str = "m4-ml-bounded-family-screen-v1"
    roster: tuple = ROSTER
    primary_panel: str = "base"
    max_fits: int = 2000
    max_cpu_seconds: int = 5400
    maximum_nominees: int = 2
    periodic_months: int = 3
    periodic_min_new_origins_per_group: int = 3
    periodic_relative_hysteresis: float = 0.02
    adaptivity: str = (
        "conditional_on_qualified_nominee_and_complete_calibration_support"
    )

    def __post_init__(self):
        if self.version != "m4-ml-bounded-family-screen-v1" or self.roster != ROSTER:
            raise ValueError("model protocol version/roster is closed")
        if (
            self.max_fits != 2000
            or self.max_cpu_seconds != 5400
            or self.maximum_nominees != 2
            or self.periodic_months != 3
            or self.periodic_min_new_origins_per_group != 3
            or self.periodic_relative_hysteresis != 0.02
        ):
            raise ValueError("registered work/support/adaptation policy cannot drift")

    @property
    def protocol_id(self):
        return digest(asdict(self))


def common_nominees(
    rows, held_out, cutoff, *, permitted_codes=ROSTER, development_only=True
):
    """Rank procedures, not alpha names; require intact shared-calendar support."""
    groups = training_groups(held_out)
    frontier = utc(cutoff)
    permitted = tuple(c for c in ROSTER if c in permitted_codes)
    if not permitted or set(permitted_codes) - set(ROSTER):
        raise ValueError("closed model roster required")
    selected = [
        r
        for r in rows
        if r["group"] in groups
        and r["code"] in permitted
        and r["fold"] >= 13
        and (not development_only or r["fold"] < 25)
        and utc(r["label_available_at"]) < frontier
        and utc(r["revision_available_at"]) < frontier
    ]
    keys = [(r["group"], r["fold"], r["code"]) for r in selected]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate model calibration contribution")
    valid = [r for r in selected if r["loss"] is not None]
    if any(not math.isfinite(r["loss"]) for r in valid):
        raise ValueError("undefined model loss must retain a null disposition")
    support = {
        code: {
            g: len({r["fold"] for r in valid if r["code"] == code and r["group"] == g})
            for g in groups
        }
        for code in permitted
    }
    if any(n < 3 for item in support.values() for n in item.values()):
        return dict(
            policy="P0",
            nominees=[],
            reason="FAMILY_CALIBRATION_ORIGIN_SUPPORT_INSUFFICIENT",
            support=support,
        )
    max_fold = max((r["fold"] for r in selected), default=12)
    blocks = []
    for start in range(13, max_fold + 1, 3):
        required = {
            (g, f, code)
            for g in groups
            for f in range(start, start + 3)
            for code in permitted
        }
        block = [r for r in valid if start <= r["fold"] < start + 3]
        if {(r["group"], r["fold"], r["code"]) for r in block} == required:
            blocks.append(block)
    if len(blocks) < 3:
        return dict(
            policy="P0",
            nominees=[],
            reason="FAMILY_CALIBRATION_COMPLETE_BLOCKS_INSUFFICIENT",
            complete_blocks=len(blocks),
            support=support,
        )
    matched = [r for block in blocks for r in block]
    scores = {
        code: macro_mean([r for r in matched if r["code"] == code])
        for code in permitted
    }
    best = min(scores, key=lambda c: (scores[c], COMPLEXITY[c]))
    block_scores = [
        macro_mean([r for r in block if r["code"] == best]) for block in blocks
    ]
    se = float(np.std(block_scores, ddof=1) / np.sqrt(len(block_scores)))
    near = [c for c in permitted if scores[c] <= scores[best] + se]
    first = min(near, key=lambda c: COMPLEXITY[c])
    other = sorted(
        (c for c in permitted if c != first), key=lambda c: (scores[c], COMPLEXITY[c])
    )
    return dict(
        policy="RESEARCH_NOMINEES",
        nominees=[first, *other[:1]],
        reason="SUPPORTED_GROUP_CHRONOLOGICAL_DEVELOPMENT_SCREEN",
        held_out=held_out,
        training_groups=groups,
        support=support,
        scores=scores,
        block_se=se,
        complete_blocks=len(blocks),
        frozen_as_of=frontier.isoformat(),
        economic_promotion=False,
    )


def periodic_update(
    rows, held_out, cutoff, *, fold, previous, permitted_codes, last_update_fold=24
):
    """Optional quarterly recipe update; fresh causal beta refits are a different role."""
    config = FamilyProtocol()
    if not permitted_codes:
        return dict(policy="P0", reason="NO_SUPPORTED_RESEARCH_NOMINEE", updated=False)
    if (
        len(permitted_codes) > 2
        or set(permitted_codes) - set(ROSTER)
        or previous not in permitted_codes
    ):
        raise ValueError(
            "periodic research requires at most two admitted nominees and its initial recipe"
        )
    if fold < 25 or (fold - 25) % config.periodic_months:
        return dict(
            policy=previous, reason="NOT_PERIODIC_RECIPE_BOUNDARY", updated=False
        )
    groups = training_groups(held_out)
    frontier = utc(cutoff)
    mature = {
        (r["group"], r["fold"], r["code"])
        for r in rows
        if r["group"] in groups
        and r["code"] in permitted_codes
        and r["loss"] is not None
        and r["fold"] > last_update_fold
        and utc(r["revision_available_at"]) < frontier
        and utc(r["label_available_at"]) < frontier
    }
    counts = {
        g: len(
            {
                f
                for group, f, _ in mature
                if group == g
                and all((g, f, code) in mature for code in permitted_codes)
            }
        )
        for g in groups
    }
    if any(n < config.periodic_min_new_origins_per_group for n in counts.values()):
        return dict(
            policy=previous,
            reason="PERIODIC_NEW_SUPPORT_INSUFFICIENT",
            updated=False,
            new_origins=counts,
        )
    chosen = common_nominees(
        rows,
        held_out,
        frontier,
        permitted_codes=permitted_codes,
        development_only=False,
    )
    if not chosen["nominees"]:
        return dict(
            policy=previous, reason=chosen["reason"], updated=False, calibration=chosen
        )
    winner = chosen["nominees"][0]
    if previous in chosen["scores"] and chosen["scores"][winner] >= chosen["scores"][
        previous
    ] * (1 - config.periodic_relative_hysteresis):
        return dict(
            policy=previous,
            reason="PERIODIC_HYSTERESIS_KEEP",
            updated=False,
            calibration=chosen,
        )
    return dict(
        policy=winner,
        reason="PERMITTED_PAST_PERIODIC_UPDATE",
        updated=winner != previous,
        last_update_fold=fold,
        calibration=chosen,
    )
