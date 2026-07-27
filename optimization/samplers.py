"""Optuna sampler factory with QuantBT compatibility checks."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Mapping, Optional

from .config import SamplerConfig
from .space import build_grid_search_space, search_space_info


def build_sampler(
    sampler_config: SamplerConfig,
    *,
    seed: int,
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
    name = cfg.name
    kwargs = dict(cfg.kwargs)
    info = search_space_info(search_space)

    if name == "tpe":
        payload = {"seed": int(seed), **kwargs}
        if constraints_func is not None and _accepts(optuna.samplers.TPESampler, "constraints_func"):
            payload.setdefault("constraints_func", constraints_func)
        return optuna.samplers.TPESampler(**payload)

    if name == "random":
        if constraints_func is not None:
            raise ValueError("RandomSampler does not support formal constraints")
        return optuna.samplers.RandomSampler(seed=int(seed), **kwargs)

    if name == "grid":
        if constraints_func is not None:
            raise ValueError("GridSampler does not support formal constraints")
        max_grid_size = int(kwargs.pop("max_grid_size", 100_000))
        grid = build_grid_search_space(search_space, max_grid_size=max_grid_size)
        return optuna.samplers.GridSampler(grid, seed=int(seed), **kwargs)

    if name == "cmaes":
        if constraints_func is not None:
            raise ValueError("CmaEsSampler does not support formal constraints")
        if info.has_categorical:
            raise ValueError("CMA-ES requires a numeric continuous/int search space; categorical params are not supported")
        if info.has_dynamic_float is False and not info.variable_names:
            raise ValueError("CMA-ES requires at least one variable numeric parameter")
        return optuna.samplers.CmaEsSampler(seed=int(seed), **kwargs)

    if name == "nsgaii":
        payload = {"seed": int(seed), **kwargs}
        if constraints_func is not None and _accepts(optuna.samplers.NSGAIISampler, "constraints_func"):
            payload.setdefault("constraints_func", constraints_func)
        if objective_count < 1:
            raise ValueError("objective_count must be positive")
        return optuna.samplers.NSGAIISampler(**payload)

    raise ValueError("sampler name must be one of: tpe, random, grid, cmaes, nsgaii")


def _accepts(callable_obj, parameter: str) -> bool:
    return parameter in inspect.signature(callable_obj).parameters
