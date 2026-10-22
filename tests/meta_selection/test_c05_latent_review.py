"""C05-T01/T02: independent transform/consumption specs; activation stays off."""

from dataclasses import replace

import numpy as np
import pytest
from scipy.stats import qmc

from tools.qms_c05_latent import Attempt, LatentLayout, consumption, sequence_declaration


SPACE = {
    "filter": {"kind": "boolean"},
    "length": {"kind": "integer", "low": 2, "high": 10, "step": 2,
               "active_if": {"filter": True}},
    "rate": {"kind": "float", "low": 1, "high": 100, "log": True},
    "method": {"kind": "categorical", "choices": ["slow", "fast"],
               "active_if": {"filter": True}},
    "threshold": {"kind": "float", "low": 0, "high": 1,
                  "active_if": {"method": "fast"}},
    "degree": 2,
}


def test_c05_t01_layout_reserves_inactive_numeric_dimensions():
    layout = LatentLayout(SPACE)
    assert layout.names == ("length", "rate", "threshold")
    requested, effective = layout.project([0.5, 0.5, 0.75], {"filter": False})
    assert requested["length"] == 6 and requested["threshold"] == 0.75
    assert effective == {"filter": False, "rate": pytest.approx(10), "degree": 2}
    _requested, active = layout.project([0.5, 0.5, 0.75], {"filter": True, "method": "fast"})
    assert active["length"] == 6 and active["threshold"] == 0.75
    assert active["rate"] == effective["rate"]


@pytest.mark.parametrize("method,has_threshold", [("slow", False), ("fast", True)])
def test_c05_t01_nested_category_activity(method, has_threshold):
    _, effective = LatentLayout(SPACE).project([0.4, 0.4, 0.4], {"filter": True, "method": method})
    assert ("threshold" in effective) is has_threshold


@pytest.mark.parametrize("spec,point,expected", [
    ({"kind": "float", "low": -2, "high": 6}, 0.25, 0.0),
    ({"kind": "float", "low": 1, "high": 100, "log": True}, 0.5, 10.0),
    ({"kind": "integer", "low": 2, "high": 10, "step": 2}, 0.0, 2),
    ({"kind": "integer", "low": 2, "high": 10, "step": 2}, 0.4, 6),
    ({"kind": "integer", "low": 2, "high": 10, "step": 2}, 0.2, 2),
    ({"kind": "integer", "low": 2, "high": 10, "step": 2}, 0.6, 6),
    ({"kind": "integer", "low": 2, "high": 10, "step": 2}, 0.8, 10),
    ({"kind": "integer", "low": 2, "high": 9, "step": 2}, 0.999, 8),
    ({"kind": "float", "low": 1, "high": 2, "step": 0.5}, 0.5, 1.5),
    ({"kind": "float", "low": 1, "high": 2.2, "step": 0.5}, 0.999, 2.0),
    ({"kind": "integer", "low": 1, "high": 8, "log": True}, 0.0, 1),
    ({"kind": "integer", "low": 1, "high": 8, "log": True}, 0.5, 2),
    ({"kind": "integer", "low": 1, "high": 8, "log": True}, 0.999, 8),
])
def test_c05_t01_hand_calculated_transforms(spec, point, expected):
    _, actual = LatentLayout({"x": spec}).project([point], {})
    assert actual["x"] == pytest.approx(expected, abs=1e-12)
    assert type(actual["x"]) is (int if spec["kind"] == "integer" else float)


def test_c05_t01_fixed_and_singleton_are_identity_not_coordinates():
    ranges = {"x": (0, 1), "degree": 2,
              "only": {"kind": "categorical", "choices": [None]},
              "constant": {"kind": "integer", "low": 4, "high": 4},
              "blocked": {"kind": "integer", "low": 2, "high": 6,
                          "active_if": {"degree": 3}}}
    layout = LatentLayout(ranges)
    assert layout.names == ("x", "blocked")
    _, effective = layout.project([0.2, 0.4], {})
    assert effective == {"x": 0, "degree": 2, "only": None, "constant": 4}
    _, other = layout.project([0.2, 0.9], {})
    assert layout.space.candidate_key(effective, strategy_identity="fixture") == layout.space.candidate_key(other, strategy_identity="fixture")


def test_c05_t01_effective_duplicates_keep_distinct_requested_values():
    layout = LatentLayout(SPACE)
    a, ea = layout.project([0.0, 0.5, 0.0], {"filter": False})
    b, eb = layout.project([0.9, 0.5, 0.9], {"filter": False})
    assert a != b and ea == eb
    assert layout.space.candidate_key(a, strategy_identity="fixture") == layout.space.candidate_key(b, strategy_identity="fixture")


def test_c05_t01_layout_and_schema_cannot_be_mutated_after_identity_freeze():
    from copy import deepcopy
    ranges = deepcopy(SPACE)
    layout = LatentLayout(ranges)
    identity = layout.identity
    ranges["length"]["high"] = 500
    assert layout.space.by_name["length"].high == 10 and layout.identity == identity
    with pytest.raises(AttributeError):
        layout.names = ("rate",)
    with pytest.raises(AttributeError):
        layout.space.specs = ()
    with pytest.raises(TypeError):
        layout.space.by_name["length"] = None


@pytest.mark.parametrize("kind", ["float", "integer"])
def test_c05_t01_seeded_cube_maps_entire_valid_lattice_and_bounds(kind):
    ranges = {"x": {"kind": kind, "low": 2, "high": 10, "step": 2},
              "log": {"kind": "float", "low": 1e-6, "high": 1, "log": True}}
    layout = LatentLayout(ranges)
    values = set()
    for cube in qmc.Sobol(d=2, scramble=True, bits=30, rng=731).random_base2(7):
        _, effective = layout.project(cube, {})
        assert 1e-6 <= effective["log"] < 1
        values.add(effective["x"])
    assert values == {2, 4, 6, 8, 10}


@pytest.mark.parametrize("point", [[0.1], [0.1, 0.2, 0.3, 0.4], [1, 0, 0],
                                  [-0.1, 0, 0], [np.nan, 0, 0], [np.inf, 0, 0]])
def test_c05_t01_invalid_cube_points_fail(point):
    with pytest.raises(ValueError, match="cube point"):
        LatentLayout(SPACE).project(point, {"filter": False})


@pytest.mark.parametrize("categories", [{}, {"filter": "yes"},
                                       {"filter": True}, {"filter": True, "method": "unknown"},
                                       {"filter": False, "invented": 1}])
def test_c05_t01_category_validation(categories):
    with pytest.raises(ValueError):
        LatentLayout(SPACE).project([0.2, 0.3, 0.4], categories)


@pytest.mark.parametrize("ranges", [{"x": [True, False]}, {"x": 2},
    {"x": {"kind": "float", "low": 0.1, "high": 1, "step": 0.1, "log": True}},
    {"x": {"kind": "integer", "low": 1, "high": 9, "step": 2, "log": True}}])
def test_c05_t01_invalid_layout_and_log_step(ranges):
    with pytest.raises(ValueError):
        LatentLayout(ranges)


@pytest.mark.parametrize("mutation", ["order", "branch", "fixed", "vocabulary", "bounds"])
def test_c05_t02_layout_identity_pins_full_schema(mutation):
    from copy import deepcopy
    altered = deepcopy(SPACE)
    if mutation == "order":
        altered = {"rate": altered.pop("rate"), **altered}
    elif mutation == "branch":
        altered["length"]["active_if"] = {"filter": False}
    elif mutation == "fixed":
        altered["degree"] = 3
    elif mutation == "vocabulary":
        altered["method"]["choices"].reverse()
    else:
        altered["rate"]["high"] = 200
    assert LatentLayout(altered).identity != LatentLayout(SPACE).identity


def test_c05_t02_explicit_unscrambled_sobol_prefix_expected_values():
    points = qmc.Sobol(d=2, scramble=False, bits=30).random_base2(3)
    np.testing.assert_array_equal(points, [
        [0, 0], [0.5, 0.5], [0.75, 0.25], [0.25, 0.75],
        [0.375, 0.375], [0.875, 0.875], [0.625, 0.125], [0.125, 0.625]])
    # Diagnostic engine fixture only; the proposed production policy is scrambled.


@pytest.mark.parametrize("seed", [0, 731, 2**32 - 1])
def test_c05_t02_scrambled_prefix_continues_without_padding_or_skipping(seed):
    declared = sequence_declaration(LatentLayout(SPACE), seed=seed)
    assert declared["seed"] == seed and declared["dimensions"] == ("length", "rate", "threshold")
    assert declared["scramble"] is True and declared["activation"] is False
    assert declared["scipy_version"] and declared["optuna_version"] == "4.8.0"
    whole = qmc.Sobol(d=3, scramble=True, bits=30, rng=seed).random_base2(3)
    engine = qmc.Sobol(d=3, scramble=True, bits=30, rng=seed)
    prefix = np.vstack([engine.random(1)[0] for _ in range(8)])
    np.testing.assert_array_equal(whole, prefix)
    assert engine.num_generated == 8
    alternate = qmc.Sobol(d=3, scramble=True, bits=30, rng=(seed + 1) % 2**32).random_base2(3)
    assert not np.array_equal(whole, alternate)


@pytest.mark.parametrize("seed", [None, True, -1, 2**32, 1.0])
def test_c05_t02_proposed_exact_seed_contract_has_no_entropy_fallback(seed):
    with pytest.raises(ValueError, match="uint32 seed"):
        sequence_declaration(LatentLayout(SPACE), seed=seed)


def ledger():
    return [Attempt("warm", "COMPLETE", "seed"),
            Attempt("independent", "FAIL", "startup"),
            Attempt("qmc", "PRUNED", "seed", 0, True),
            Attempt("qmc", "PRUNED", "infeasible", 1),
            Attempt("qmc", "FAIL", "failed", 2),
            Attempt("qmc", "COMPLETE", "winner", 3)]


def test_c05_t02_each_terminal_outcome_consumes_its_original_point():
    expected = consumption(ledger(), budget=8)
    assert expected == dict(schema="qms-conditional-numeric-latent-v1-proposed",
        attempted=6, budget=8, unspent=2, first_independent=1, warm_attempts=1,
        qmc_points=4, next_qmc_index=4, unique_effective_candidates=5,
        duplicate_attempts=1, runtime_telemetry=False, activation=False)


def test_c05_t02_no_qmc_or_retry_before_declared_independent_startup():
    with pytest.raises(ValueError, match="after startup"):
        consumption([Attempt("qmc", "COMPLETE", "point", 0)], budget=2)


def test_c05_t02_128_budget_is_not_128_qmc_points():
    events = [Attempt("warm", "COMPLETE", f"warm{i}") for i in range(2)]
    events += [Attempt("independent", "PRUNED", "startup")]
    events += [Attempt("qmc", "COMPLETE", f"q{i}", i) for i in range(125)]
    assert consumption(events, budget=128)["qmc_points"] == 125


@pytest.mark.parametrize("events", [[], [Attempt("warm", "FAIL", "warm")],
                                    [Attempt("independent", "PRUNED", "startup")]])
def test_c05_t02_early_stop_has_only_real_consumption(events):
    actual = consumption(events, budget=128)
    assert actual["unspent"] == 128 - len(events) and actual["qmc_points"] == 0


@pytest.mark.parametrize("mutation", ["skip", "reuse", "bool_index", "warm_late",
    "double_startup", "running", "unknown_source", "duplicate_complete", "over_budget"])
def test_c05_t02_invalid_consumption_is_not_silently_repaired(mutation):
    events = ledger()
    budget = 8
    if mutation in {"skip", "reuse", "bool_index"}:
        events[3] = replace(events[3], qmc_index={"skip": 2, "reuse": 0, "bool_index": True}[mutation])
    elif mutation == "warm_late":
        events.append(Attempt("warm", "COMPLETE", "late"))
    elif mutation == "double_startup":
        events.append(Attempt("independent", "COMPLETE", "twice"))
    elif mutation == "running":
        events[4] = replace(events[4], state="RUNNING")
    elif mutation == "unknown_source":
        events[4] = replace(events[4], source="retry")
    elif mutation == "duplicate_complete":
        events[2] = replace(events[2], state="COMPLETE")
    else:
        budget = 5
    with pytest.raises(ValueError):
        consumption(events, budget=budget)
