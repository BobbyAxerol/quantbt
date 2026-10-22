"""Support/availability and genuinely exercised periodic-update controls."""

from copy import deepcopy

import pytest

from tools.meta_model_research.family_protocol import (
    ROSTER,
    common_nominees,
    periodic_update,
)
from tools.meta_model_research.protocol import GROUPS


def rows():
    return [
        dict(
            group=g,
            fold=f,
            code=c,
            loss=10 + ROSTER.index(c),
            label_available_at=f"2023-01-{f:02d}T00:00Z",
            revision_available_at=f"2023-01-{f:02d}T00:01Z",
        )
        for g in GROUPS
        for f in range(13, 25)
        for c in ROSTER
    ]


def test_common_roster_ignores_heldout_and_future_and_keeps_complete_blocks():
    r = rows()
    first = common_nominees(r, "A-SC", "2024-01-31T23:00Z")
    assert first["nominees"] == ["B1", "H135"]
    mutated = [dict(x, loss=-1e8) if x["group"] == "A-SC" else x for x in r]
    mutated += [
        dict(
            r[0],
            label_available_at="2025-01-01T00:00Z",
            revision_available_at="2025-01-02T00:00Z",
        )
    ]
    assert common_nominees(mutated, "A-SC", "2024-01-31T23:00Z") == first
    partial = [x for x in r if x["fold"] in (13, 16, 19, 22)]
    assert common_nominees(partial, "A-SC", "2024-01-31T23:00Z")["nominees"] == []
    with pytest.raises(ValueError, match="duplicate"):
        common_nominees(r + r, "A-SC", "2024-01-31T23:00Z")


def test_update_requires_new_mature_support_and_not_current_forward():
    r = rows()
    codes = ("B1", "H200")
    assert not periodic_update(
        r, "A-SC", "2024-01-31T23:00Z", fold=25, previous="H200", permitted_codes=codes
    )["updated"]
    later = [
        dict(
            x,
            fold=f,
            label_available_at="2024-03-01T00:00Z",
            revision_available_at="2024-03-01T00:01Z",
        )
        for x in r
        if x["fold"] == 13
        for f in (25, 26, 27)
    ]
    updated = periodic_update(
        [*r, *later],
        "A-SC",
        "2024-04-01T00:00Z",
        fold=28,
        previous="H200",
        permitted_codes=codes,
    )
    assert updated["updated"] and updated["policy"] == "B1"
    future = [
        dict(
            x,
            loss=-1e12,
            fold=28,
            label_available_at="2024-05-01T00:00Z",
            revision_available_at="2024-05-01T00:00Z",
        )
        for x in later
        if x["fold"] == 25
    ]
    assert (
        periodic_update(
            [*r, *later, *future],
            "A-SC",
            "2024-04-01T00:00Z",
            fold=28,
            previous="H200",
            permitted_codes=codes,
        )
        == updated
    )
    assert not periodic_update(
        [*r, *later],
        "A-SC",
        "2024-04-01T00:00Z",
        fold=29,
        previous="H200",
        permitted_codes=codes,
    )["updated"]
    assert (
        periodic_update(
            [], "A-SC", "2024-04-01T00:00Z", fold=28, previous="P0", permitted_codes=()
        )["policy"]
        == "P0"
    )


def test_keep_simpler_recipe_and_actual_changed_allowed_past_control():
    r = rows()
    initial = common_nominees(r, "A-SC", "2024-01-31T23:00Z")
    changed = [dict(x, loss=0.0) if x["code"] == "H135" else x for x in deepcopy(r)]
    other = common_nominees(changed, "A-SC", "2024-01-31T23:00Z")
    assert initial["nominees"][0] == "B1" and other["nominees"][0] == "H135"


def test_partial_block_cannot_reverse_the_matched_nomination():
    r = [x for x in rows() if x["fold"] <= 21]
    r += [
        dict(x, fold=22, loss=0.0)
        for x in rows()
        if x["fold"] == 13 and x["code"] == "H135"
    ]
    result = common_nominees(r, "A-SC", "2024-01-31T23:00Z")
    assert result["complete_blocks"] == 3
    assert result["nominees"][0] == "B1"
    assert result["scores"]["H135"] == 11.0


def test_out_of_roster_new_origins_cannot_unlock_periodic_update():
    r = rows()
    later = [
        dict(
            x,
            fold=f,
            label_available_at="2024-03-01T00:00Z",
            revision_available_at="2024-03-01T00:01Z",
        )
        for x in r
        if x["fold"] == 13 and x["code"] == "X3"
        for f in (25, 26, 27)
    ]
    result = periodic_update(
        [*r, *later],
        "A-SC",
        "2024-04-01T00:00Z",
        fold=28,
        previous="H200",
        permitted_codes=("B1", "H200"),
    )
    assert not result["updated"]
    assert all(n == 0 for n in result["new_origins"].values())
