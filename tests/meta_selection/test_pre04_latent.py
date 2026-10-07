"""Actual Optuna proposals against the independent C05 numeric/RNG contract."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import optuna
import pytest
from scipy.stats import qmc

from quantbt.optimization import SamplerConfig
from quantbt.optimization.conditional_sobol import FrozenLatentLayout, POLICY
from quantbt.optimization.continuation import ContinuationConfig, ContinuationError, ExactStudySession
from quantbt.optimization.wfo_study import WfoSamplerStudy
from tools.qms_c05_latent import LatentLayout, numeric_value

RANGES = {
    "on": {"kind": "categorical", "choices": [True, False]},
    "x": {"kind": "float", "low": .001, "high": 1., "log": True, "active_if": {"on": [True]}},
    "child": {"kind": "categorical", "choices": ["a", "b"], "active_if": {"on": [True]}},
    "y": {"kind": "integer", "low": 1, "high": 9, "step": 2},
    "s": {"kind": "float", "low": 0., "high": 1., "step": .25},
    "z": {"kind": "integer", "low": 1, "high": 19, "log": True},
    "fixed": 2,
}
BINDING = {k: k+":pre04" for k in ("market", "calendar", "accounting", "objective",
    "schedule", "meta_snapshot", "meta_basis", "meta_task")}


def cfg(**kwargs):
    return SamplerConfig(name="sobol", sobol_policy=POLICY, **kwargs)


def bridge(ranges=RANGES, **kwargs):
    return WfoSamplerStudy(cfg(**kwargs), ranges, seed=731, budget=64,
        cutoff="2024-01-01T00:00:00Z", strategy_identity="pre04", stage="is_search")


def study(b):
    return optuna.create_study(sampler=b.sampler(), direction="maximize")


def test_actual_prefix_numeric_and_independent_category_rng():
    b = bridge()
    st = study(b)
    cube = qmc.Sobol(4, seed=731, scramble=True, bits=30, optimization=None).random_base2(5)
    categories = optuna.samplers.RandomSampler(seed=731 ^ 0x9E3779B9)
    startup = optuna.samplers.RandomSampler(seed=731)
    inactive = 0
    for n in range(33):
        t = st.ask()
        requested, effective = b.suggest(t)
        row = t.user_attrs["qms_latent"]
        active = {}
        expected_draws = []
        for spec in b.space.specs:
            if not spec.active(active):
                continue
            if spec.fixed:
                active[spec.name] = spec.value
            elif spec.choices:
                d = optuna.distributions.CategoricalDistribution(spec.choices)
                value = categories.sample_independent(st, t, spec.name, d)
                active[spec.name] = value
                expected_draws.append(dict(name=spec.name, value=value))
            elif n == 0:
                d = (optuna.distributions.IntDistribution(spec.low, spec.high, log=spec.log, step=spec.step or 1)
                     if spec.kind == "integer" else optuna.distributions.FloatDistribution(
                         spec.low, spec.high, log=spec.log, step=spec.step))
                active[spec.name] = startup.sample_independent(st, t, spec.name, d)
            else:
                active[spec.name] = row["decoded_numeric"][spec.name]
        assert effective == active
        assert row["category_draws"] == expected_draws
        assert row["active_mask"] == {s.name: s.name in effective for s in b.space.specs}
        if n:
            np.testing.assert_array_equal(row["cube_point"], cube[n-1])
            expected = {s.name: numeric_value(s, float(u)) for s, u in zip(
                LatentLayout(RANGES).numeric, cube[n-1], strict=True)}
            assert row["decoded_numeric"] == expected
            assert row["qmc_index"] == n-1
            assert all(requested[k] == v for k, v in expected.items())
            inactive += "x" not in effective
        else:
            assert row["qmc_index"] is None and row["source"] == "independent"
        st.tell(t, float(n))
    assert inactive > 0
    assert b.metadata(st)["latent_stream"]["next_qmc_index"] == 32


@pytest.mark.parametrize("u", [0., .1, .25, .5, .75, .9999999999999999])
def test_transforms_independent_reference(u):
    layout = FrozenLatentLayout(RANGES)
    expected = {s.name: numeric_value(s, u) for s in LatentLayout(RANGES).numeric}
    assert layout.decode([u]*4) == expected


@pytest.mark.parametrize("point", [[1.]*4, [-.01]*4, [float("nan")]*4, [0.]*3])
def test_invalid_cube_fails(point):
    with pytest.raises(ValueError):
        FrozenLatentLayout(RANGES).decode(point)


def test_frozen_layout_identity_and_no_numeric_rejection():
    layout = FrozenLatentLayout(RANGES)
    with pytest.raises(AttributeError):
        layout.names = ()
    reordered = {"y": RANGES["y"], **{k: v for k, v in RANGES.items() if k != "y"}}
    assert layout.identity != FrozenLatentLayout(reordered).identity
    with pytest.raises(ValueError, match="numeric dimensions"):
        bridge({"switch": [True, False]}).sampler()
    with pytest.raises(ValueError, match="requires"):
        SamplerConfig(name="tpe_legacy", sobol_policy=POLICY)


def test_all_numeric_inactive_still_consumes_and_warm_is_prefix_only():
    ranges = {"on": False, "x": {"kind": "float", "low": 0., "high": 1., "active_if": {"on": [True]}}}
    b = bridge(ranges)
    st = study(b)
    b.enqueue(st, [dict(params={"on": False}, available_at="2023-01-01T00:00:00Z",
        space_identity=b.space.identity, strategy_identity=b.strategy_identity)])
    for n in range(10):
        t = st.ask()
        _, effective = b.suggest(t)
        assert effective == {"on": False}
        st.tell(t, state=optuna.trial.TrialState.FAIL if n % 2 else optuna.trial.TrialState.PRUNED)
    witness = b.metadata(st)["latent_stream"]
    assert witness["next_qmc_index"] == 8
    assert witness["records"][0]["source"] == "warm_start"
    assert witness["records"][1]["source"] == "independent"
    st.enqueue_trial({}, user_attrs={"qms_source": "warm_start"})
    with pytest.raises(ValueError, match="prefix"):
        st.ask()


def continuation_config():
    return ContinuationConfig(sampler_config=cfg(constraint_mode="post_filter"), ranges=RANGES,
        seed=731, budget=64, cutoff="2024-01-01T00:00:00Z", strategy_identity="pre04",
        result_constraints=True, duplicate_policy="prune")


def advance(session, count, batch=1):
    for _ in range(count//batch):
        proposals = [session.ask() for _ in range(batch)]
        for p in reversed(proposals):
            if p.duplicate or p.number % 7 == 3:
                session.tell(p.number, state="PRUNED")
            elif p.number % 11 == 6:
                session.tell(p.number, state="FAIL", reason="declared_failure")
            else:
                session.tell(p.number, float(p.effective["y"]), constraints=(1. if p.number % 5 == 0 else -1.,))


@pytest.mark.parametrize("split", [0, 1, 17, 39])
@pytest.mark.parametrize("batch", [1, 4])
def test_owned_continuation_all_terminal_states_and_batch(split, batch):
    split = (split//batch)*batch
    c = continuation_config()
    full, partial = (ExactStudySession(c, binding=BINDING) for _ in range(2))
    advance(full, 56, batch)
    advance(partial, split, batch)
    text, sha = partial.dumps()
    resumed = ExactStudySession.loads(text, config=c, binding=BINDING, expected_digest=sha)
    advance(resumed, 56-split, batch)
    assert full.witness() == resumed.witness()
    assert full.dumps() == resumed.dumps()
    assert full.witness()["latent_stream"]["next_qmc_index"] == 55
    assert {t.state.name for t in full.trials} == {"COMPLETE", "PRUNED", "FAIL"}


def test_warm_waiting_early_stop_and_policy_corruption():
    c = continuation_config()
    warm = dict(params={"on": False, "y": 3, "s": .25, "z": 2, "fixed": 2},
        available_at="2023-01-01T00:00:00Z", space_identity=c.bridge().space.identity,
        strategy_identity=c.strategy_identity)
    c = replace(c, warm_start=(warm,), early_stopping={"patience": 3, "min_delta": .1, "min_trials": 4})
    full = ExactStudySession(c, binding=BINDING)
    text, sha = full.dumps()
    resumed = ExactStudySession.loads(text, config=c, binding=BINDING, expected_digest=sha)
    for _ in range(4):
        for session in (full, resumed):
            p = session.ask()
            session.tell(p.number, 1.)
    assert full.stopped and full.witness() == resumed.witness()
    assert full.witness()["latent_stream"]["next_qmc_index"] == 2
    text, sha = full.dumps()
    with pytest.raises(ContinuationError):
        ExactStudySession.loads(text, config=replace(c, sampler_config=SamplerConfig(name="sobol")),
                                binding=BINDING, expected_digest=sha)
    blob = json.loads(text)
    blob["payload"]["witness"]["latent_stream"]["next_qmc_index"] += 1
    with pytest.raises(ContinuationError):
        ExactStudySession.loads(json.dumps(blob), config=c, binding=BINDING, expected_digest=sha)


def test_fresh_process_continuation(tmp_path):
    c = continuation_config()
    full, partial = (ExactStudySession(c, binding=BINDING) for _ in range(2))
    advance(full, 40)
    advance(partial, 19)
    text, sha = partial.dumps()
    journal = tmp_path/"journal.json"
    journal.write_text(text)
    output = tmp_path/"resumed.json"
    script = """from tests.meta_selection.test_pre04_latent import *
s=ExactStudySession.loads(Path(sys.argv[1]).read_text(), config=continuation_config(), binding=BINDING, expected_digest=sys.argv[2])
advance(s,21)
Path(sys.argv[3]).write_text(json.dumps(s.witness(),sort_keys=True))
"""
    subprocess.run([sys.executable, "-c", script, str(journal), sha, str(output)], check=True,
                   env={**os.environ, "PYTHONPATH": "src:."})
    assert json.loads(output.read_text()) == full.witness()


def test_old_sampler_metadata_unchanged():
    assert SamplerConfig(name="sobol").metadata() == dict(name="sobol", kwargs={},
        constraint_mode="sampler", mixed_space_policy="reject")


def test_decimal_lattice_endpoint_clamps_to_declared_high():
    layout = FrozenLatentLayout({"s": {"kind": "float", "low": .1, "high": .7, "step": .2}})
    assert layout.decode([.999999999]) == {"s": .7}


def test_decimal_adjusted_endpoint_stays_in_optuna_distribution():
    ranges = {"s": {"kind": "float", "low": .1, "high": .8, "step": .2}}
    b = bridge(ranges)
    st = study(b)
    for _ in range(16):
        t = st.ask()
        _, effective = b.suggest(t)
        assert .1 <= effective["s"] <= .7
        st.tell(t, effective["s"])
