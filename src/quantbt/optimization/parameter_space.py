"""Versioned, additive parameter geometry; no strategy conditions are inferred."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Mapping

from .space import _is_bool_choice, _is_number, _looks_int, stable_params_key


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: str
    low: Any = None
    high: Any = None
    step: Any = None
    log: bool = False
    choices: tuple = ()
    active_if: tuple = ()
    fixed: bool = False
    value: Any = None

    @property
    def variable(self):
        return not self.fixed and (
            len(self.choices) > 1 if self.choices else self.low != self.high
        )

    def active(self, params):
        return all(
            parent in params and params[parent] in choices
            for parent, choices in self.active_if
        )

    def suggest(self, trial):
        if self.fixed:
            return self.value
        if self.kind in {"categorical", "boolean"}:
            return trial.suggest_categorical(self.name, list(self.choices))
        if self.kind == "integer":
            return trial.suggest_int(
                self.name, self.low, self.high, step=self.step or 1, log=self.log
            )
        return trial.suggest_float(
            self.name, self.low, self.high, step=self.step, log=self.log
        )

    def validate(self, value):
        if self.fixed:
            valid = value == self.value
        elif self.choices:
            valid = value in self.choices
        else:
            valid = (
                _is_number(value)
                and math.isfinite(float(value))
                and self.low <= value <= self.high
            )
            if self.kind == "integer":
                valid = valid and _looks_int(value)
            if valid and self.step:
                offset = (value - self.low) / self.step
                valid = math.isclose(offset, round(offset), rel_tol=0, abs_tol=1e-8)
        if not valid:
            raise ValueError(
                f"SAMPLER_SPACE_UNSUPPORTED: {self.name!r} value {value!r} violates schema"
            )

    def metadata(self):
        return dict(
            name=self.name,
            kind=self.kind,
            low=self.low,
            high=self.high,
            step=self.step,
            scale="log" if self.log else "linear",
            categories=list(self.choices),
            active_if={key: list(value) for key, value in self.active_if},
            fixed=self.fixed,
            fixed_value=self.value,
        )


def _parse(name, spec):
    if isinstance(spec, Mapping):
        extra = set(spec) - {
            "kind",
            "low",
            "high",
            "step",
            "log",
            "choices",
            "active_if",
            "value",
        }
        kind = spec.get("kind")
        if extra or kind not in {"float", "integer", "boolean", "categorical", "fixed"}:
            raise ValueError(
                f"SAMPLER_SPACE_UNSUPPORTED: {name!r} unknown fields/kind: {extra or kind}"
            )
        condition = spec.get("active_if", {})
        if not isinstance(condition, Mapping):
            raise ValueError("active_if must map prior parent names to allowed values")
        active = tuple(
            (key, tuple(values if isinstance(values, (list, tuple)) else [values]))
            for key, values in condition.items()
        )
        if kind == "fixed":
            if "value" not in spec or spec["value"] is None:
                raise ValueError(f"{name!r} fixed spec requires value")
            return ParameterSpec(
                name, kind, active_if=active, fixed=True, value=spec["value"]
            )
        if kind in {"boolean", "categorical"}:
            choices = tuple(
                spec.get("choices", [True, False] if kind == "boolean" else [])
            )
            if not choices or any(
                value is not None and not isinstance(value, (str, int, float, bool))
                for value in choices
            ):
                raise ValueError(f"{name!r} requires non-empty Optuna scalar choices")
            if any(isinstance(v, float) and not math.isfinite(v) for v in choices):
                raise ValueError(f"{name!r} choices must not contain non-finite values")
            if any(value in choices[:i] for i, value in enumerate(choices)):
                raise ValueError(f"{name!r} choices must be unique")
            if kind == "boolean" and not all(isinstance(v, bool) for v in choices):
                raise ValueError(f"{name!r} boolean choices must be bool")
            if any(key in spec for key in ("low", "high", "step", "log", "value")):
                raise ValueError(
                    f"{name!r} categorical spec does not accept numeric fields"
                )
            return ParameterSpec(name, kind, choices=choices, active_if=active)
        low, high, step = spec.get("low"), spec.get("high"), spec.get("step")
        log = spec.get("log", False)
        if not isinstance(log, bool) or "choices" in spec or "value" in spec:
            raise ValueError(f"{name!r} numeric spec has incompatible fields")
    elif _is_bool_choice(spec):
        return ParameterSpec(name, "boolean", choices=(True, False))
    elif (
        isinstance(spec, tuple)
        and len(spec) in (2, 3)
        and all(_is_number(v) for v in spec)
    ):
        low, high = spec[:2]
        step = spec[2] if len(spec) == 3 else None
        kind = (
            "integer"
            if _looks_int(low)
            and _looks_int(high)
            and (step is None or _looks_int(step))
            else "float"
        )
        log, active = False, ()
    elif isinstance(spec, (list, tuple, range)):
        if not len(spec):
            raise ValueError(f"{name!r} choices must not be empty")
        return ParameterSpec(name, "categorical", choices=tuple(spec))
    else:
        if spec is None:
            raise ValueError(f"{name!r} fixed value must not be None")
        return ParameterSpec(name, "fixed", fixed=True, value=spec)
    if (
        not all(_is_number(v) and math.isfinite(float(v)) for v in (low, high))
        or high < low
    ):
        raise ValueError(f"{name!r} requires finite ordered bounds")
    if step is not None and (
        not _is_number(step) or not math.isfinite(float(step)) or step <= 0
    ):
        raise ValueError(f"{name!r} step must be finite and positive")
    if kind == "integer" and not all(_looks_int(v) for v in (low, high, step or 1)):
        raise ValueError(f"{name!r} integer bounds/step must be integers")
    if log and (low <= 0 or (step is not None and (kind == "float" or step != 1))):
        raise ValueError(
            f"{name!r} log requires positive bounds and no float step/integer step other than 1"
        )
    cast = int if kind == "integer" else float
    return ParameterSpec(
        name,
        kind,
        cast(low),
        cast(high),
        None if step is None else cast(step),
        log,
        active_if=active,
    )


class NormalizedSearchSpace:
    schema = "quantbt-parameter-space-v1"

    def __init__(self, ranges, fixed_params=None):
        if not ranges:
            raise ValueError("param_ranges must not be empty")
        specs = []
        prior = {}
        fixed = dict(fixed_params or {})
        for name, value in {
            **dict(ranges),
            **{k: v for k, v in fixed.items() if k not in ranges},
        }.items():
            if not isinstance(name, str) or not name:
                raise ValueError("parameter names must be non-empty strings")
            spec = _parse(name, fixed[name] if name in fixed else value)
            for parent, choices in spec.active_if:
                if parent not in prior or not choices:
                    raise ValueError(
                        f"{name!r} active_if requires a prior parent and non-empty allowed values"
                    )
                for choice in choices:
                    if not prior[parent].fixed:
                        prior[parent].validate(choice)
            specs.append(spec)
            prior[name] = spec
        self.specs = tuple(specs)
        self.by_name = prior
        self.identity = hashlib.sha256(
            stable_params_key(self.metadata()).encode()
        ).hexdigest()

    def metadata(self):
        return {
            "schema": self.schema,
            "parameters": [spec.metadata() for spec in self.specs],
            "effective_builder": "omit_explicit_inactive_v1",
        }

    def suggest(self, trial):
        params = {}
        for spec in self.specs:
            if spec.active(params):
                params[spec.name] = spec.suggest(trial)
        return params

    def effective(self, requested):
        unknown = set(requested) - set(self.by_name)
        if unknown:
            raise ValueError(
                f"SAMPLER_SPACE_UNSUPPORTED: unknown params {sorted(unknown)}"
            )
        params = {}
        for spec in self.specs:
            if not spec.active(params):
                continue
            if spec.name not in requested and not spec.fixed:
                raise ValueError(
                    f"SAMPLER_SPACE_UNSUPPORTED: missing active param {spec.name!r}"
                )
            value = requested.get(spec.name, spec.value)
            spec.validate(value)
            # Identity follows the declared representation, not a warm seed's scalar type.
            if spec.fixed:
                value = spec.value
            elif spec.choices:
                value = next(choice for choice in spec.choices if choice == value)
            elif spec.kind == "integer":
                value = int(value)
            else:
                value = float(value)
            params[spec.name] = value
        return params

    def candidate_key(self, params, *, strategy_identity):
        return hashlib.sha256(
            stable_params_key(
                {
                    "strategy": strategy_identity,
                    "space": self.identity,
                    "effective": self.effective(params),
                }
            ).encode()
        ).hexdigest()
