"""Search-space parsing shared by QuantBT optimization surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Mapping, Optional

import numpy as np


@dataclass(frozen=True)
class SearchSpaceInfo:
    """Static facts used by sampler compatibility checks."""

    has_categorical: bool
    has_continuous: bool
    has_dynamic_float: bool
    variable_names: tuple[str, ...]
    grid_size: Optional[int]


def suggest_parameter(trial, name: str, spec: Any) -> Any:
    """Suggest one parameter from a QuantBT param range spec.

    Supported specs are intentionally compatible with existing alpha notebooks:
    numeric tuples, categorical lists/tuples, ranges, bool choices, and scalar
    constants.
    """

    if _is_bool_choice(spec):
        return trial.suggest_categorical(name, [True, False])
    if isinstance(spec, tuple) and len(spec) in (2, 3) and all(_is_number(value) for value in spec):
        low, high = spec[0], spec[1]
        step = spec[2] if len(spec) == 3 else None
        if _looks_int(low) and _looks_int(high) and (step is None or _looks_int(step)):
            return trial.suggest_int(name, int(low), int(high), step=1 if step is None else int(step))
        if step is None:
            return trial.suggest_float(name, float(low), float(high))
        return trial.suggest_float(name, float(low), float(high), step=float(step))
    if isinstance(spec, range):
        values = list(spec)
        if not values:
            raise ValueError(f"param_ranges[{name!r}] is empty")
        return trial.suggest_categorical(name, values)
    if isinstance(spec, (list, tuple)):
        if not spec:
            raise ValueError(f"param_ranges[{name!r}] is empty")
        return trial.suggest_categorical(name, list(spec))
    return spec


def suggest_params(trial, param_ranges: Mapping[str, Any], fixed_params: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Suggest params and merge fixed params.

    Fixed params override `param_ranges` entries by name. Additional fixed
    params are appended to the final parameter dict.
    """

    fixed = dict(fixed_params or {})
    params: dict[str, Any] = {}
    for name, spec in dict(param_ranges or {}).items():
        if name in fixed:
            params[name] = fixed[name]
        else:
            params[name] = suggest_parameter(trial, name, spec)
    for name, value in fixed.items():
        params.setdefault(name, value)
    return params


def stable_params_key(params: Mapping[str, Any]) -> str:
    """Return a deterministic key for duplicate-trial detection."""

    return json.dumps(_jsonable(params), sort_keys=True, separators=(",", ":"))


def search_space_info(param_ranges: Mapping[str, Any], fixed_params: Optional[Mapping[str, Any]] = None) -> SearchSpaceInfo:
    """Inspect a QuantBT search space for sampler compatibility."""

    fixed = set(dict(fixed_params or {}))
    has_categorical = False
    has_continuous = False
    has_dynamic_float = False
    variable_names: list[str] = []
    grid_size = 1
    finite_grid = True
    for name, spec in dict(param_ranges or {}).items():
        if name in fixed:
            continue
        kind = _spec_kind(spec)
        if kind == "constant":
            continue
        variable_names.append(name)
        if kind == "categorical":
            has_categorical = True
        if kind in {"float", "int"}:
            has_continuous = has_continuous or kind == "float"
        values = _grid_values(name, spec, allow_dynamic=True)
        if values is None:
            finite_grid = False
            has_dynamic_float = True
        else:
            grid_size *= len(values)
    return SearchSpaceInfo(
        has_categorical=has_categorical,
        has_continuous=has_continuous,
        has_dynamic_float=has_dynamic_float,
        variable_names=tuple(variable_names),
        grid_size=grid_size if finite_grid else None,
    )


def build_grid_search_space(
    param_ranges: Mapping[str, Any],
    fixed_params: Optional[Mapping[str, Any]] = None,
    *,
    max_grid_size: int = 100_000,
) -> dict[str, list[Any]]:
    """Build an Optuna GridSampler search space from finite specs."""

    fixed = set(dict(fixed_params or {}))
    grid: dict[str, list[Any]] = {}
    size = 1
    for name, spec in dict(param_ranges or {}).items():
        if name in fixed:
            continue
        values = _grid_values(name, spec, allow_dynamic=False)
        if values is None:
            raise ValueError(f"grid sampler requires finite values for {name!r}")
        if len(values) == 1 and _spec_kind(spec) == "constant":
            continue
        grid[name] = values
        size *= len(values)
        if size > int(max_grid_size):
            raise ValueError(f"grid search space has {size:,} combinations, above max_grid_size={int(max_grid_size):,}")
    if not grid:
        raise ValueError("grid sampler requires at least one non-fixed finite parameter")
    return grid


def _grid_values(name: str, spec: Any, *, allow_dynamic: bool) -> Optional[list[Any]]:
    if _is_bool_choice(spec):
        return [True, False]
    if isinstance(spec, tuple) and len(spec) in (2, 3) and all(_is_number(value) for value in spec):
        low, high = spec[0], spec[1]
        step = spec[2] if len(spec) == 3 else None
        if _looks_int(low) and _looks_int(high) and (step is None or _looks_int(step)):
            step_i = 1 if step is None else int(step)
            if step_i <= 0:
                raise ValueError(f"integer step for {name!r} must be positive")
            return list(range(int(low), int(high) + 1, step_i))
        if step is None:
            if allow_dynamic:
                return None
            raise ValueError(f"grid sampler requires a float step for {name!r}")
        return _float_grid(float(low), float(high), float(step), name)
    if isinstance(spec, range):
        values = list(spec)
        if not values:
            raise ValueError(f"param_ranges[{name!r}] is empty")
        return values
    if isinstance(spec, (list, tuple)):
        if not spec:
            raise ValueError(f"param_ranges[{name!r}] is empty")
        return list(spec)
    return [spec]


def _float_grid(low: float, high: float, step: float, name: str) -> list[float]:
    if step <= 0.0:
        raise ValueError(f"float step for {name!r} must be positive")
    if high < low:
        raise ValueError(f"high must be >= low for {name!r}")
    count = int(math.floor((high - low) / step + 1e-12)) + 1
    values = [float(low + i * step) for i in range(count)]
    if values and values[-1] < high and math.isclose(values[-1] + step, high, rel_tol=1e-9, abs_tol=1e-12):
        values.append(float(high))
    return values


def _spec_kind(spec: Any) -> str:
    if _is_bool_choice(spec):
        return "categorical"
    if isinstance(spec, range):
        return "categorical"
    if isinstance(spec, tuple) and len(spec) in (2, 3) and all(_is_number(value) for value in spec):
        if _looks_int(spec[0]) and _looks_int(spec[1]) and (len(spec) == 2 or _looks_int(spec[2])):
            return "int"
        return "float"
    if isinstance(spec, (list, tuple)):
        return "categorical"
    return "constant"


def _is_bool_choice(spec: Any) -> bool:
    return (
        isinstance(spec, (list, tuple))
        and len(spec) == 2
        and all(isinstance(value, bool) for value in spec)
        and set(spec) == {True, False}
    )


def _looks_int(value: Any) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    return value
