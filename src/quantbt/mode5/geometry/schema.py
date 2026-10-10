"""Schema-frozen units, effective casts and explicitly constrained manifolds."""

from dataclasses import asdict, dataclass
import json
import math

from quantbt.optimization.parameter_space import NormalizedSearchSpace, ParameterSpec
from quantbt.mode5.diagnostics.identity import canonical, digest


@dataclass(frozen=True)
class OrderedConstraint:
    names: tuple[str, ...]
    strict: bool = True

    def __post_init__(self):
        if type(self.names) is not tuple or len(self.names) < 2 or len(set(self.names)) != len(self.names):
            raise ValueError("ordered constraint requires distinct named axes")

    def require(self, params):
        if not all(name in params for name in self.names):
            raise ValueError("coupled constraint has an inactive/missing axis")
        values = [params[name] for name in self.names]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in values):
            raise ValueError("ordered constraint requires finite numeric values")
        if any(a >= b if self.strict else a > b for a, b in zip(values, values[1:])):
            raise ValueError("INFEASIBLE_ORDERED_MANIFOLD")


@dataclass(frozen=True)
class ResolvedPoint:
    schema_id: str
    requested_json: str
    effective_json: str
    active_names: tuple[str, ...]
    changes: tuple[tuple[str, str], ...]

    @property
    def params(self):
        return json.loads(self.effective_json)

    @property
    def identity(self):
        return digest(dict(schema=self.schema_id, effective=self.params))


@dataclass(frozen=True)
class EffectiveGeometry:
    specs: tuple[ParameterSpec, ...]
    weights: tuple[tuple[str, float], ...] = ()
    inactive: tuple[tuple[str, str], ...] = ()
    casts: tuple[tuple[str, str], ...] = ()
    constraints: tuple[OrderedConstraint, ...] = ()
    version: str = "schema_gower_effective_v1"

    @classmethod
    def from_ranges(cls, ranges, **kwargs):
        return cls(NormalizedSearchSpace(ranges).specs, **kwargs)

    def __post_init__(self):
        if (type(self.specs) is not tuple or not self.specs or
                any(not isinstance(s, ParameterSpec) for s in self.specs)):
            raise ValueError("immutable shared parameter schema required")
        names = {s.name for s in self.specs}
        if len(names) != len(self.specs):
            raise ValueError("duplicate parameter")
        for entries in (self.weights, self.inactive, self.casts):
            if type(entries) is not tuple or len(dict(entries)) != len(entries) or any(k not in names for k, _ in entries):
                raise ValueError("explicit unique axis policies required")
        if any(not math.isfinite(w) or w <= 0 for _, w in self.weights):
            raise ValueError("frozen positive schema weights required")
        if any(not reason for _, reason in self.inactive) or any(c != "truncate_integer_v1" for _, c in self.casts):
            raise ValueError("inactive evidence/cast version missing")
        if any(dict(self.casts).get(s.name) and s.kind != "integer" for s in self.specs):
            raise ValueError("integer cast requires integer effective domain")
        if type(self.constraints) is not tuple or any(set(c.names) - names for c in self.constraints):
            raise ValueError("unknown coupled axes")
        canonical(self.metadata())

    def metadata(self):
        return dict(version=self.version, parameters=[s.metadata() for s in self.specs],
            weights=dict(self.weights), inactive=dict(self.inactive), casts=dict(self.casts),
            constraints=[asdict(c) for c in self.constraints], branch_mismatch="union_axis_penalty_one_v1",
            repair="reject_no_silent_sort", quantization="source_cast_then_shared_schema_validation")

    @property
    def identity(self):
        return digest(self.metadata())

    def resolve(self, requested):
        raw = dict(requested)
        if set(raw) - {s.name for s in self.specs}:
            raise ValueError("unknown axis")
        inactive, casts = dict(self.inactive), dict(self.casts)
        effective, active, changes = {}, [], []
        for s in self.specs:
            if s.name in inactive or not s.active(effective):
                if s.name in raw:
                    changes.append((s.name, "source_inactive" if s.name in inactive else "conditional_inactive"))
                continue
            if s.name not in raw and not s.fixed:
                raise ValueError(f"missing active axis {s.name}")
            value = raw.get(s.name, s.value)
            if s.name in casts:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("nonfinite integer cast")
                cast = int(value)
                if value != cast:
                    changes.append((s.name, casts[s.name]))
                value = cast
            s.validate(value)
            if s.fixed:
                value = s.value
            elif s.choices:
                value = next(choice for choice in s.choices if choice == value)
            else:
                value = int(value) if s.kind == "integer" else float(value)
            effective[s.name] = value
            if s.variable:
                active.append(s.name)
        for constraint in self.constraints:
            constraint.require(effective)
        return ResolvedPoint(self.identity, canonical(raw), canonical(effective), tuple(active), tuple(changes))

    def numeric_names(self, point):
        return tuple(s.name for s in self.specs if s.name in point.active_names and not s.choices)

    def coordinate(self, name, value):
        s = next(s for s in self.specs if s.name == name)
        if s.choices or not s.variable:
            raise ValueError("only active numeric axes have Euclidean coordinates")
        transform = math.log if s.log else float
        return (transform(value) - transform(s.low)) / (transform(s.high) - transform(s.low))

    def decode(self, name, z):
        s = next(s for s in self.specs if s.name == name)
        if not math.isfinite(z) or not 0 <= z <= 1 or s.choices or not s.variable:
            raise ValueError("numeric coordinate outside frozen schema")
        raw = math.exp(math.log(s.low) + z * math.log(s.high/s.low)) if s.log else s.low + z*(s.high-s.low)
        step = s.step or (1 if s.kind == "integer" else None)
        if step:
            count = math.floor((s.high-s.low)/step + 1e-10)
            offset = min(count, max(0, math.floor((raw-s.low)/step + .5)))
            raw = s.low + offset*step
        return int(raw) if s.kind == "integer" else float(raw)

    def distance(self, left, right):
        if left.schema_id != self.identity or right.schema_id != self.identity:
            raise ValueError("incompatible geometry")
        a, b = left.params, right.params
        axes = set(left.active_names) | set(right.active_names)
        weights = dict(self.weights)
        total, denominator = 0., 0.
        for s in self.specs:
            if s.name not in axes:
                continue
            w = weights.get(s.name, 1.)
            if s.name not in a or s.name not in b:
                delta = 1.
            elif s.choices:
                delta = float(a[s.name] != b[s.name])
            else:
                delta = abs(self.coordinate(s.name, a[s.name]) - self.coordinate(s.name, b[s.name]))
            total += w*delta
            denominator += w
        return total/denominator if denominator else 0.
