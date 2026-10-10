from dataclasses import asdict

from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source, Matrix, KINDS
from quantbt.mode5.dossier.dossier import AXES, DEPENDENCIES, Dossier, radar_point
from quantbt.mode5.dossier.plans import CalibrationPlan, FIELDS


def fixture(tmp_path):
    definitions = {a: dict(metric="utility", unit="decimal_return", direction=1,
        reference_id="frozen-1", lower=0., upper=1.) for a in AXES}
    raw = {"cells": [{"utility": .2}, {"utility": -.3}], "definitions": definitions,
           "inventory": {k: [k+"/0", k+"/1"] for k in KINDS}}
    path = tmp_path / "source.json"
    write_json(path, raw)
    identity = file_identity(path)
    witness = AccessWitness("development-1", "synthetic", 0, 8, 9)
    policy = AccessPolicy("diagnostic-1", ("synthetic",), ("development-1",), 10, "diagnostic")
    catalog = EvidenceCatalog([Source("registered", str(path), identity["sha256"], identity["bytes"], witness)], policy)
    rosters = tuple(Record.of({"kind": k, "entries": [dict(row_id=f"{k}/{i}",
        ref=catalog.ref("registered", f"/cells/{i}")) for i in range(2)]}) for k in KINDS)
    matrices = tuple(Matrix.assemble(k, r, catalog) for k, r in zip(KINDS, rosters))
    axes = {a: {"refs": [catalog.ref("registered", "/cells")], "status": "DESCRIPTIVE_ONLY"} for a in AXES}
    radar = {a: [radar_point(**definitions[a], value=.2, support={"days": 91}, uncertainty=None,
        reason=None, ref=catalog.ref("registered", "/cells/0/utility"),
        definition_ref=catalog.ref("registered", f"/definitions/{a}"))] for a in AXES}
    assessments = [dict(recipe_id=f"{selector}:{version}", status="CONSIDER_FINITE_PANEL",
        selected_decisions=1, reasons=["adequate registered finite panel"],
        refs=[catalog.ref("registered", "/cells")]) for selector, version in (
            ("full_dro_cvar", "environment_floor_mean_v1"),
            ("full_pareto_chebyshev", "pareto_chebyshev_v1"))]
    kwargs = dict(context=Record.of({k: "frozen-1" for k in DEPENDENCIES}), matrices=matrices,
        rosters=rosters, inventory=Record.of(raw["inventory"]), inventory_ref=catalog.ref("registered", "/inventory"),
        catalog=catalog, axes=axes, radar=radar, batteries={"technical": "valid synthetic"},
        assessments=assessments, limitations=["not independent economic confirmation"], compute_bill={"simulations": 0})
    return Dossier.create(**kwargs), catalog, kwargs


def spec(dossier, selector="full_dro_cvar"):
    out = {k: {"contract_id": "synthetic-"+k} for k in FIELDS}
    version = "environment_floor_mean_v1" if selector == "full_dro_cvar" else "pareto_chebyshev_v1"
    coefficients = {"mean": .5} if selector == "full_dro_cvar" else {"rho": .01}
    out.update(search_budget=8,
        sampler=dict(name="tpe_legacy", seeds=[731], schedule="sequential_exact", fallback="raise"),
        objective=dict(version=version, coefficients=coefficients, reference_id="frozen-1",
            channel=dict(name="ECONOMIC_UTILITY_V1", metric_contract="economic.v1", unit="decimal_return")),
        selector=dict(id=selector, tie_break="candidate_id_lexicographic_v1"),
        domain=dict(schema_id=dossier.record.data["context"]["schema"], ranges={"x": [1, 2]}))
    out["probes"].update(design="none_for_environment_formula", budget=0)
    out["validation"].update(no_auto_deploy=True, roles=["independent_validation"],
                              contamination_status="future separate registration required")
    out["reuse"]["selection_policy"] = asdict(AccessPolicy(
        "selection-1", ("synthetic",), ("development-1",), 10, "selection"))
    return out
