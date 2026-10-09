import numpy as np
import optuna
import pytest

from quantbt.optimization.config import SamplerConfig
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from quantbt.optimization.samplers import build_sampler
from quantbt.optimization.wfo_study import ObservedSampler


@pytest.mark.parametrize("recipe",["tpe_legacy","tpe_multivariate_group","sobol","cmaes"])
def test_battery_telemetry_preserves_shared_factory_proposals_and_global_rng(recipe):
    ranges={"window":(24,40),"rvol":(1.,3.)}
    space=NormalizedSearchSpace(ranges)
    config=SamplerConfig(name=recipe,kwargs={"n_startup_trials":2} if recipe.startswith("tpe") else {})
    state=np.random.get_state()
    paths=[]
    previous=optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        for observed in (False,True):
            sampler=build_sampler(config,seed=731,search_space=ranges,objective_count=1)
            if observed:
                sampler=ObservedSampler(sampler)
            study=optuna.create_study(direction="maximize",sampler=sampler)
            params=[]
            for _ in range(8):
                trial=study.ask()
                p=space.suggest(trial)
                study.tell(trial,-(p["window"]-32.)**2-(p["rvol"]-1.6)**2)
                params.append(p)
            paths.append(params)
            if observed:
                assert len(sampler.events)==16
        assert paths[0]==paths[1]
        after=np.random.get_state()
        assert state[0]==after[0] and state[2:]==after[2:]
        np.testing.assert_array_equal(state[1],after[1])
    finally:
        optuna.logging.set_verbosity(previous)
