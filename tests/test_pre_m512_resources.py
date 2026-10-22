"""Byte-budget tests, not a build/installation or performance benchmark."""

import pytest

from tools.m5_12_resources import GIB, MIB, LocalQualificationBudget


def test_plan_counts_peak_in_addition_to_reserve_not_only_free_disk():
    budget = LocalQualificationBudget()
    assert budget.peak_incremental_bytes == 896*MIB
    result = budget.assess(available_bytes=5*GIB,available_memory_bytes=4*GIB)
    assert not result["resource_budget_fits"]
    assert not result["full_m5_12_launch_authorized"]


def test_exact_registered_headroom_is_admissible_without_claiming_phase_permission():
    budget = LocalQualificationBudget()
    result = budget.assess(available_bytes=5*GIB+896*MIB,available_memory_bytes=512*MIB+640*MIB)
    assert result["resource_budget_fits"] and not result["full_m5_12_launch_authorized"]


def test_ram_is_a_separate_guard():
    result = LocalQualificationBudget().assess(available_bytes=10*GIB,available_memory_bytes=512*MIB)
    assert result["disk_fits"] and not result["memory_fits"] and not result["resource_budget_fits"]


@pytest.mark.parametrize("change", [{"max_owned_consumers":2},{"fresh_native_build":True},
                                    {"disk_reserve_bytes":4*GIB},{"consumer_environment_bytes":0},
                                    {"fixture_and_jit_bytes":True}])
def test_unregistered_or_weakened_plan_does_not_inherit_admission(change):
    with pytest.raises(ValueError):
        LocalQualificationBudget(**change)
