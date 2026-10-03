"""Optuna sampler factory with QuantBT compatibility checks."""

from __future__ import annotations

import inspect
import importlib.util
from typing import Any, Callable, Mapping, Optional

from .config import SamplerConfig
from .space import build_grid_search_space, search_space_info


WFO_RECIPES = {"tpe", "tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"}


def resolved_sampler_kwargs(cfg: SamplerConfig, seed: Optional[int]) -> tuple[str, dict]:
    name, kwargs = cfg.name, dict(cfg.kwargs)
    if name == "tpe_legacy":
        name = "tpe"
    elif name == "tpe_multivariate_group":
        name = "tpe"
        if kwargs.get("multivariate", True) is not True or kwargs.get("group", True) is not True:
            raise ValueError("tpe_multivariate_group requires multivariate=True and group=True")
        kwargs.update(multivariate=True, group=True)
    if name == "tpe" and kwargs.get("group", False) and not kwargs.get("multivariate", False):
        raise ValueError("group=True requires multivariate=True")
    if name == "sobol":
        if kwargs.get("qmc_type", "sobol") != "sobol":
            raise ValueError("sobol recipe requires qmc_type='sobol'")
        kwargs.setdefault("qmc_type", "sobol")
        kwargs.setdefault("scramble", True)
    if seed is not None:
        kwargs.setdefault("seed", int(seed))
    return name, kwargs


def build_sampler(
    sampler_config: SamplerConfig,
    *,
    seed: Optional[int],
    search_space: Mapping[str, Any],
    objective_count: int,
    constraints_func: Optional[Callable] = None,
):
    """Build an Optuna sampler and validate domain-agnostic compatibility."""

    try:
        import optuna
    except Exception as exc:  # pragma: no cover - dependency guard
        raise ImportError("QuantBT optimization requires optuna") from exc

    cfg = sampler_config if isinstance(sampler_config, SamplerConfig) else SamplerConfig(**dict(sampler_config))
    name, kwargs = resolved_sampler_kwargs(cfg, seed)
    if objective_count < 1:
        raise ValueError("objective_count must be positive")

    if name == "tpe":
        payload = {**kwargs}
        if seed is not None:
            payload.setdefault("seed", int(seed))
        if constraints_func is not None and _accepts(optuna.samplers.TPESampler, "constraints_func"):
            payload.setdefault("constraints_func", constraints_func)
        return optuna.samplers.TPESampler(**payload)

    if name == "random":
        if constraints_func is not None:
            raise ValueError("RandomSampler does not support formal constraints")
        payload = {**kwargs}
        if seed is not None:
            payload.setdefault("seed", int(seed))
        return optuna.samplers.RandomSampler(**payload)

    if name == "grid":
        if constraints_func is not None:
            raise ValueError("GridSampler does not support formal constraints")
        max_grid_size = int(kwargs.pop("max_grid_size", 100_000))
        grid = build_grid_search_space(search_space, max_grid_size=max_grid_size)
        payload = {**kwargs}
        if seed is not None:
            payload.setdefault("seed", int(seed))
        return optuna.samplers.GridSampler(grid, **payload)

    if name == "cmaes":
        info = search_space_info(search_space)
        from .parameter_space import NormalizedSearchSpace
        specs = NormalizedSearchSpace(search_space).specs
        if objective_count != 1:
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: CMA-ES requires one objective")
        if constraints_func is not None:
            raise ValueError("CmaEsSampler does not support formal constraints")
        if (info.has_categorical or any(spec.active_if for spec in specs)) and cfg.mixed_space_policy != "explicit_independent":
            raise ValueError("CMA-ES requires a numeric continuous/int search space; categorical params are not supported")
        if info.has_dynamic_float is False and not info.variable_names:
            raise ValueError("CMA-ES requires at least one variable numeric parameter")
        if not any(spec.variable and not spec.choices and not spec.active_if for spec in specs):
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: CMA-ES requires a static numeric dimension")
        if cfg.mixed_space_policy == "explicit_independent" and kwargs.get("warn_independent_sampling", True) is False:
            raise ValueError("explicit_independent must not suppress independent-sampling warnings")
        if importlib.util.find_spec("cmaes") is None:
            raise ImportError("CMA-ES requires cmaes==0.12.0; install quantbt-engine[optimization]")
        payload = {**kwargs}
        if seed is not None:
            payload.setdefault("seed", int(seed))
        return optuna.samplers.CmaEsSampler(**payload)

    if name == "sobol":
        from .parameter_space import NormalizedSearchSpace
        specs = NormalizedSearchSpace(search_space).specs
        if constraints_func is not None:
            raise ValueError("SAMPLER_CONSTRAINT_POLICY_REQUIRED: Sobol requires post_filter")
        if any(spec.active_if for spec in specs):
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: Sobol V1 requires a fixed relative space; conditional ranges are unsupported")
        if not any(spec.variable and not spec.choices for spec in specs):
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: Sobol requires a numeric dimension")
        return optuna.samplers.QMCSampler(**kwargs)

    if name == "nsgaii":
        payload = {**kwargs}
        if seed is not None:
            payload.setdefault("seed", int(seed))
        if constraints_func is not None and _accepts(optuna.samplers.NSGAIISampler, "constraints_func"):
            payload.setdefault("constraints_func", constraints_func)
        if objective_count < 1:
            raise ValueError("objective_count must be positive")
        return optuna.samplers.NSGAIISampler(**payload)

    raise ValueError("sampler name must be one of: tpe, tpe_legacy, tpe_multivariate_group, random, grid, cmaes, sobol, nsgaii")


def _accepts(callable_obj, parameter: str) -> bool:
    return parameter in inspect.signature(callable_obj).parameters
