from dataclasses import replace

import pytest

from tools.mode5_geometry import EffectiveGeometry, OrderedConstraint
from tools.mode5_research.design import discovery_design
from tools.mode5_research.protocol import ResearchProtocol


def test_registered_horizon_and_counts_are_not_a_two_point_pilot():
    protocol = ResearchProtocol()
    assert protocol.development_days == 1095
    assert protocol.unique_configs == 128
    assert protocol.formal_trials == 256
    assert replace(protocol, seed=732).identity != protocol.identity


@pytest.mark.parametrize("changes", [dict(unique_configs=2), dict(formal_trials=2),
    dict(development_stop="2020-01-01"), dict(publication=True), dict(auto_deploy=True),
    dict(continuous_within_scope=False), dict(financial_workers=4),
    dict(worker_rss_cap_bytes=0), dict(unique_configs=128.5), dict(seed=True), dict(seed=-1)])
def test_unapproved_shortcuts_are_rejected(changes):
    with pytest.raises(ValueError):
        ResearchProtocol(**changes)


def test_conditional_balanced_branches_are_effectively_unique_and_reproducible():
    geometry = EffectiveGeometry.from_ranges(dict(branch=[False, True], x=(1, 1000),
        y=dict(kind="integer", low=2, high=1000, active_if=dict(branch=True))))
    branches = [({"branch": False}, 256), ({"branch": True}, 256)]
    design = discovery_design(geometry, branches=branches)
    replay = discovery_design(geometry, branches=branches)
    assert design.identity == replay.identity
    assert [row.point.identity for row in design.selected] == [row.point.identity for row in replay.selected]
    assert len({row.point.identity for row in design.selected}) == 128
    assert design.coverage()["branch_counts"] == {"branch:0": 64, "branch:1": 64}
    assert all("y" not in row.point.active_names for row in design.selected if not row.point.params["branch"])


def test_infeasible_points_are_retained_without_outcome_dependent_replacement():
    geometry = EffectiveGeometry.from_ranges(dict(a=(1, 1000), b=(1, 1000)),
        constraints=(OrderedConstraint(("a", "b")),))
    design = discovery_design(geometry, branches=[({}, 512)])
    assert len(design.selected) == 128
    assert any(row.status == "INFEASIBLE" for row in design.ledger.rows)
    assert all(row.point.params["a"] < row.point.params["b"] for row in design.selected)
    assert design.coverage()["raw_proposals"] == 512


def test_admission_budget_is_part_of_design_identity():
    geometry = EffectiveGeometry.from_ranges(dict(x=(1, 1000), y=(1, 1000)))
    first = discovery_design(geometry, branches=[({}, 512)], target=128)
    larger = discovery_design(geometry, branches=[({}, 512)], target=256)
    assert first.identity != larger.identity


def test_finite_domain_reports_shortfall_instead_of_counting_replays():
    geometry = EffectiveGeometry.from_ranges(dict(x=[1, 2]))
    design = discovery_design(geometry, branches=[({}, 256)])
    assert len(design.selected) == 2
    assert design.coverage()["status"] == "INSUFFICIENT_COVERAGE"
    assert sum(row.status == "COLLISION" for row in design.ledger.rows) == 254
