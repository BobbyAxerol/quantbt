"""Opt-in continuous-account binding over the existing sealed Mode5 contracts."""

from dataclasses import asdict

from ..optimization.parameter_space import NormalizedSearchSpace, ParameterSpec
from .continuous import ContinuousAccountContract, CONTINUOUS_POLICY
from .continuous_scope import ContinuousAccountScope
from .continuous_eligibility import WholeAccountEligibility
from .diagnostics.access import AccessWitness
from .dossier.records import Record
from .geometry.schema import EffectiveGeometry, OrderedConstraint
from .integration_contracts import Mode5Calibration, calibration_binding

SCHEMA = "quantbt.mode5.public_binding.continuous.v1"


def restore_geometry(value):
    specs = tuple(ParameterSpec(s["name"], s["kind"], low=s["low"], high=s["high"],
        step=s["step"], log=s["scale"] == "log", choices=tuple(s["categories"]),
        active_if=tuple((k, tuple(v)) for k, v in s["active_if"].items()),
        fixed=s["fixed"], value=s["fixed_value"]) for s in value["parameters"])
    geometry = EffectiveGeometry(specs, weights=tuple(value["weights"].items()),
        inactive=tuple(value["inactive"].items()), casts=tuple(value["casts"].items()),
        constraints=tuple(OrderedConstraint(tuple(c["names"]), c["strict"]) for c in value["constraints"]),
        version=value["version"])
    if Record.of(geometry.metadata()).data != Record.of(value).data:
        raise ValueError("unknown or altered effective geometry policies")
    return geometry


def continuous_calibration_binding(*, geometry, source, execution, witness,
                                   quality_floor_comparison="greater_or_equal_v1", eligibility_policy=None, **kwargs):
    """Freeze the original scorer authority; this is not execution qualification."""
    if (not isinstance(geometry, EffectiveGeometry) or not isinstance(source, Record)
            or not isinstance(execution, Record) or not isinstance(witness, AccessWitness)):
        raise TypeError("typed effective geometry, source/execution and data rights required")
    legacy = calibration_binding(**kwargs).data
    windows = kwargs["windows"]
    if not windows:
        raise ValueError("continuous calibration needs explicit attribution windows")
    if quality_floor_comparison not in {"greater_or_equal_v1", "strict_greater_v1"}:
        raise ValueError("explicit versioned quality-floor comparison required")
    step = kwargs["metrics"]["bar_interval_ns"]
    continuous = dict(
        account_policy=CONTINUOUS_POLICY, geometry=geometry.metadata(), source=source.data,
        execution=execution.data, witness=asdict(witness),
        start_ns=min(w.start_ns for w in windows), stop_ns=max(w.end_ns for w in windows)+step,
        quality_floor_comparison=quality_floor_comparison)
    if eligibility_policy is not None:
        if not isinstance(eligibility_policy, WholeAccountEligibility) or quality_floor_comparison != "greater_or_equal_v1":
            raise ValueError("typed prospective whole-account eligibility requires its declared comparison")
        continuous["eligibility_policy"] = eligibility_policy.metadata()
    return Record.of({**legacy, "schema": SCHEMA, "continuous": continuous})


class ContinuousMode5Calibration(Mode5Calibration):
    """A versioned provider contract, not a reset-flat binding with a new label."""

    @property
    def continuous_contract(self):
        b = self.binding.data
        c = b["continuous"]
        return ContinuousAccountContract(c["start_ns"], c["stop_ns"], restore_geometry(c["geometry"]),
            Record.of(b["metrics"]), self.binding.identity, Record.of(c["source"]), Record.of(c["execution"]),
            self.access, AccessWitness(**c["witness"]))

    def validate_binding(self):
        b = self.binding.data
        if b.get("schema") != SCHEMA or "continuous" not in b:
            raise ValueError("explicit continuous binding schema required")
        # Reuse common scientific/sampler validation without executing V1. The
        # projection is never sealed, dispatched or reported as the real binding.
        projection = {k: v for k, v in b.items() if k != "continuous"}
        projection["schema"] = "quantbt.mode5.public_binding.v1"
        common = object.__new__(Mode5Calibration)
        for name in ("dossier", "plan", "catalog", "journal"):
            object.__setattr__(common, name, getattr(self, name))
        object.__setattr__(common, "binding", Record.of(projection))
        Mode5Calibration.validate_binding(common)
        c = b["continuous"]
        fields = {"account_policy", "geometry", "source", "execution", "witness", "start_ns", "stop_ns", "quality_floor_comparison"}
        if "eligibility_policy" in c:
            WholeAccountEligibility.read(c["eligibility_policy"])
            if c["quality_floor_comparison"] != "greater_or_equal_v1":
                raise ValueError("whole-account eligibility comparison differs from its policy")
            fields.add("eligibility_policy")
        if set(c) != fields:
            raise ValueError("complete continuous policy fields required")
        if c["quality_floor_comparison"] not in {"greater_or_equal_v1", "strict_greater_v1"}:
            raise ValueError("unbound quality-floor comparison")
        contract = self.continuous_contract
        step = b["metrics"]["bar_interval_ns"]
        windows = self.windows
        if (windows[0].start_ns != contract.start_ns or windows[-1].end_ns+step != contract.stop_ns
                or any(a.end_ns+step != z.start_ns for a, z in zip(windows, windows[1:]))):
            raise ValueError("attribution windows must partition one complete continuous account")
        import pandas as pd
        for w in windows:
            year = pd.Timestamp(w.start_ns, tz="UTC").year
            start = max(contract.start_ns, int(pd.Timestamp(f"{year}-01-01", tz="UTC").value))
            stop = min(contract.stop_ns, int(pd.Timestamp(f"{year+1}-01-01", tz="UTC").value))
            if w.environment_id != str(year) or (w.start_ns, w.end_ns+step) != (start, stop):
                raise ValueError("continuous selector windows must use explicit calendar-year IDs")
        recipe = self.plan.record.data["recipe"]
        if recipe["domain"].get("effective_geometry_identity") != contract.geometry.identity:
            raise ValueError("original effective geometry must be sealed in the recipe")
        if recipe["retention"].get("contract_id") != "continuous_account_observation_v1":
            raise ValueError("explicit continuous observation retention contract required")

    def preflight(self, engine, data, index, param_ranges):
        super().preflight(engine, data, index, param_ranges)
        c = self.continuous_contract
        space = NormalizedSearchSpace(param_ranges)
        if space.specs != c.geometry.specs:
            raise ValueError("sampler dimensions/order differ from original effective geometry")
        ContinuousAccountScope.from_contract(c, index)
        if engine.config.fold_account_policy != "carry_position":
            raise NotImplementedError("continuous calibration requires carry_position inside a fresh account")

