"""Optional schema assistance; no data access, ordinal encoding or auto-sampler."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .config import SamplerConfig
from .parameter_space import NormalizedSearchSpace
from .samplers import WFO_RECIPES, resolved_sampler_kwargs, validate_sampler_geometry
from .space import _is_number, _looks_int, stable_params_key


@dataclass(frozen=True, slots=True)
class SamplerSpaceAssessment:
    """Compatibility facts, not a prediction of optimization or trading quality."""

    requested_sampler: str
    resolved_sampler: str
    resolution: str
    caller_sampler_override: bool
    static_numeric: tuple[str, ...]
    conditional_numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    fixed: tuple[str, ...]
    numeric_declarations: tuple[str, ...]
    schema_overrides: tuple[str, ...]
    condition_overrides: tuple[str, ...]
    requested_issue: str | None
    notes: tuple[str, ...]
    input_space_identity: str
    effective_space_identity: str
    schema: str = "quantbt-sampler-space-helper-v1"

    def metadata(self) -> dict[str, Any]:
        return asdict(self)


class SamplerSpacePlan:
    """Reusable configuration with defensive copies and original-typed params."""

    def __init__(self, ranges, sampler, assessment):
        self._ranges = deepcopy(ranges)
        self._sampler = deepcopy(sampler)
        self._space = NormalizedSearchSpace(self._ranges)
        self.assessment = assessment

    @property
    def param_ranges(self) -> dict[str, Any]:
        return deepcopy(self._ranges)

    @property
    def sampler_config(self) -> SamplerConfig:
        return deepcopy(self._sampler)

    def optimization_config(self, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Explicitly apply this sampler; leave meta/account/objective policies alone."""
        return {**deepcopy(dict(base or {})), "sampler_config": self.sampler_config}

    def decode(self, requested: Mapping[str, Any]) -> dict[str, Any]:
        """Validate/canonicalize params, omit inactive fields; no encoded label IDs."""
        return self._space.effective(requested)


def _spec_mapping(spec):
    if spec.fixed:
        value = {"kind": "fixed", "value": spec.value}
    elif spec.choices:
        value = {"kind": spec.kind, "choices": list(spec.choices)}
    else:
        value = {"kind": spec.kind, "low": spec.low, "high": spec.high,
                 "step": spec.step, "log": spec.log}
    if spec.active_if:
        value["active_if"] = dict(spec.active_if)
    return value


def _declared_numeric(spec):
    if spec.fixed:
        if not _is_number(spec.value):
            raise ValueError(f"{spec.name!r}: a fixed label/boolean is not numeric")
        return _spec_mapping(spec)
    if spec.kind in {"float", "integer"}:
        return _spec_mapping(spec)
    # Categories are never ordinal-coded. Only an explicitly declared, exact
    # integer lattice can become a numeric distribution without adding values.
    if not spec.choices or not all(_looks_int(v) for v in spec.choices):
        raise ValueError(f"{spec.name!r}: numeric declaration requires integer choices; "
                         "use an explicit numeric schema override for float bounds")
    values = sorted(int(v) for v in spec.choices)
    if len(set(values)) != len(values):
        raise ValueError(f"{spec.name!r}: numeric choices must be unique")
    if len(values) == 1:
        result = {"kind": "fixed", "value": values[0]}
    else:
        step = values[1] - values[0]
        if any(b - a != step for a, b in zip(values, values[1:])):
            raise ValueError(f"{spec.name!r}: irregular numeric support; conversion would add values")
        result = {"kind": "integer", "low": values[0], "high": values[-1], "step": step}
    if spec.active_if:
        result["active_if"] = dict(spec.active_if)
    return result


def _config(value):
    cfg = deepcopy(value) if isinstance(value, SamplerConfig) else SamplerConfig(**dict(value))
    if cfg.name not in WFO_RECIPES:
        raise ValueError(f"sampler-space helper supports existing WFO recipes: {sorted(WFO_RECIPES)}")
    resolved_sampler_kwargs(cfg, seed=None)
    stable_params_key(cfg.metadata())
    return cfg


def prepare_sampler_space(
    param_ranges: Mapping[str, Any],
    *,
    preferred_sampler: str = "cmaes",
    numeric_parameters: Sequence[str] = (),
    parameter_overrides: Mapping[str, Any] | None = None,
    fixed_params: Mapping[str, Any] | None = None,
    active_if: Mapping[str, Mapping[str, Any]] | None = None,
    sampler_config: SamplerConfig | Mapping[str, Any] | None = None,
    on_incompatible: str = "raise",
    objective_count: int = 1,
) -> SamplerSpacePlan:
    """Prepare an optional sampler plan from caller-declared parameter semantics.

    Numeric tuples/schemas retain their meaning. Lists/ranges stay categorical
    unless a caller declares a regular integer lattice numeric. Never infer
    conditions from parameter names, encode strings/bools as numbers or execute
    a strategy. Overrides may deliberately change support and are recorded.
    ``recommend`` explicitly permits a compatible legacy-TPE alternative;
    an incompatible caller ``sampler_config`` is never silently replaced.
    Constructor kwargs/dependencies/seed/constraints retain factory preflight.
    """
    if on_incompatible not in {"raise", "recommend"}:
        raise ValueError("on_incompatible must be raise or recommend")
    if type(objective_count) is not int or objective_count < 1:
        raise ValueError("objective_count must be a positive integer")
    if isinstance(numeric_parameters, (str, bytes)):
        raise ValueError("numeric_parameters must be a sequence of parameter names")
    declared = tuple(numeric_parameters)
    if any(not isinstance(n, str) for n in declared) or len(set(declared)) != len(declared):
        raise ValueError("numeric_parameters must contain unique string names")
    original = NormalizedSearchSpace(param_ranges)
    ranges = deepcopy(dict(param_ranges))
    overrides = deepcopy(dict(parameter_overrides or {}))
    conditions = deepcopy(dict(active_if or {}))
    unknown = (set(declared) | set(overrides) | set(conditions)) - set(ranges)
    if unknown:
        raise ValueError(f"unknown parameter declarations: {sorted(unknown)}")
    ranges.update(overrides)
    # Reuse the existing fixed-parameter precedence, including added constants.
    space = NormalizedSearchSpace(ranges, fixed_params)
    if fixed_params:
        ranges = {s.name: _spec_mapping(s) for s in space.specs}
    for name in declared:
        ranges[name] = _declared_numeric(space.by_name[name])
    for name, condition in conditions.items():
        if not isinstance(condition, Mapping):
            raise ValueError("active_if overrides must map parent names to allowed values")
        spec = NormalizedSearchSpace(ranges).by_name[name]
        ranges[name] = {**_spec_mapping(spec), "active_if": dict(condition)}
    space = NormalizedSearchSpace(ranges)
    requested = _config({"name": preferred_sampler})
    cfg = requested if sampler_config is None else _config(sampler_config)
    issue = None
    try:
        validate_sampler_geometry(cfg, ranges, objective_count=objective_count)
    except ValueError as exc:
        issue = str(exc)
        if on_incompatible != "recommend" or sampler_config is not None:
            raise ValueError(f"SAMPLER_HELPER_INCOMPATIBLE: {issue}") from exc
        cfg = _config({"name": "tpe_legacy"})
    variable = [s for s in space.specs if s.variable]
    notes = ["Schema compatibility only; strategy smoothness and economic performance are unknown.",
             "No market/strategy access, meta activation, RNG draw or sampler construction."]
    if cfg.name == "cmaes" and cfg.mixed_space_policy == "explicit_independent":
        notes.append("Categories/conditional dimensions may be sampled independently, not joint CMA geometry.")
    if cfg.name == "cmaes" and len([s for s in variable if not s.choices and not s.active_if]) == 1:
        notes.append("One static numeric dimension; inspect actual factory relative/independent proposal telemetry.")
    assessment = SamplerSpaceAssessment(
        requested_sampler=cfg.name if sampler_config is not None else requested.name,
        resolved_sampler=cfg.name,
        resolution="RECOMMENDED_ALTERNATIVE" if issue else "COMPATIBLE",
        caller_sampler_override=sampler_config is not None,
        static_numeric=tuple(s.name for s in variable if not s.choices and not s.active_if),
        conditional_numeric=tuple(s.name for s in variable if not s.choices and s.active_if),
        categorical=tuple(s.name for s in variable if s.choices),
        fixed=tuple(s.name for s in space.specs if not s.variable),
        numeric_declarations=declared,
        schema_overrides=tuple(overrides), condition_overrides=tuple(conditions),
        requested_issue=issue, notes=tuple(notes), input_space_identity=original.identity,
        effective_space_identity=space.identity,
    )
    return SamplerSpacePlan(ranges, cfg, assessment)
