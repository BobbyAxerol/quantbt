"""Private retained-evidence views using the shared handoff renderer.

This is a reader of the bounded source-specific snapshot, never a replacement
for the original Dossier/catalog or authority to compile its historical recipe.
"""
from quantbt.diagnostics.calibration.render import grid, table
from quantbt.mode5.dossier.records import Record

from .handoff_readback import SCHEMA


def _values(value):
    if isinstance(value, dict):
        if {"value", "unit", "status", "ref"} <= set(value):
            return dict(value=value["value"], unit=value["unit"], status=value["status"])
        return {key: _values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_values(item) for item in value]
    return value


def _number(value):
    return value["value"]


def render(record: Record, *, private=False):
    if type(private) is not bool:
        raise ValueError("private disclosure requires an explicit boolean")
    d = record.data
    if d.get("schema") != SCHEMA or d.get("status") != "COLD_RETAINED_METADATA_READBACK":
        raise ValueError("original bounded metadata readback required")
    if not private:
        return "# Retained Evidence Review\n\nPrivate source-bound research data redacted; no execution authority.\n"
    lines = ["# Retained Evidence To Researcher Choice", "",
        "Cold retained-value review, not a new economic experiment, archive admission or executable historical plan."]
    lines += table("Decision Summary", dict(readback_id=record.identity,
        alpha_contexts=len(d["alphas"]), source_files=len(d["sources"]),
        archive_authority=d["archive_authority"],
        retained_cross_mode_disposition=_values(d["disposition"]["methods"]),
        next_action="Keep frozen comparator. Explicitly supply the matching current Dossier/catalog, binding and researcher preferences before compiling a new recipe.").items())
    lines += grid("Alpha Behavior", ("Alpha", "Market / account scope", "Diagnostics", "Archive", "Regime drill-down", "Limitations"),
        ((alpha, _values(a["scope"]), _values(a["diagnostics"]),
          dict(status=a["archive"]["status"], quantities=_values(a["archive"]["quantities"])),
          a["regime_ref"], a["limits"])
         for alpha, a in d["alphas"].items()))
    lines += ["", "Archive origins and repeated coordinates are not independent replications."
        " Regime pointers are retained drill-down references, not newly computed regime measurements."]
    annual = []
    for alpha, a in d["alphas"].items():
        for arm, winner in a["winners"].items():
            for values in winner["center"]["annual"]:
                annual.append((alpha, arm, _number(values["environment_id"]),
                    _number(values["net_return"]), _number(values["raw_sharpe"]),
                    _number(values["max_drawdown"]), _number(values["utility"]),
                    _number(values["daily_count"]),
                    {k: _number(values[k]) for k in ("support_pass", "risk_pass", "quality_pass")},
                    values["account_identity"]["ref"]))
    lines += grid("Static Candidate Annual Views", ("Alpha", "Arm", "Calendar", "Net return (decimal)",
        "Retained Sharpe", "Max DD (fraction)", "Utility (decimal)", "Daily observations", "Gates", "Account source"), annual)
    lines += grid("Fragility And Cost", ("Alpha", "Arm", "Held evidence", "Geometric coverage", "Basin status", "Double-fee summary", "Source"),
        ((alpha, arm, _values(w["held"]), _values(w["geometric_coverage"]), _values(w["basin_certified"]),
          {k: _values(w["double_fee"][k]) for k in ("whole", "summary", "activity")}, w["evidence_ref"])
         for alpha, a in d["alphas"].items() for arm, w in a["winners"].items()))
    lines += table("Recipe Comparison", dict(formal_attempts=_values(d["formal"]["counts"]),
        counterexamples=d["formal"]["counterexamples"],
        interpretation="A saved Raw winner can outperform the registered recipe winner under the same formula; this does not retrospectively change either selected dict.").items())
    lines += grid("Actual Search Response", ("Alpha", "Arm", "Sampler / objective / attempts / states"),
        ((alpha, arm, _values(s)) for alpha, a in d["alphas"].items() for arm, s in a["studies"].items()))
    lines += grid("Matched Assistance", ("Alpha", "Direction", "Fold", "Original paired values and validity masks"),
        ((p["alpha"], p["direction"], p["fold"], _values(p)) for p in d["assistance"]["pairs"]))
    lines += ["", "Static objective deltas are not forward decay. For valid forward pairs only, R = Q - delta_IS; undefined stays null."]
    lines += table("Run Configuration", dict(status="REQUIRES_ORIGINAL_TYPED_INPUTS_AND_EXPLICIT_NEW_CHOICE",
        use="CalibrationRecipe.continuous -> CalibrationWorksheet.choose -> Mode5RunPack.compile -> prepare -> endpoint.backtest -> reconcile",
        source_evidence="References and units above remain available in retained-readback.json. They do not substitute for the original catalog or current execution contract.",
        options="Supported continuous annual selectors stay available. Archive-seeding and temporal-regret policies remain research-only; not automatically promoted by this view.",
        missing_inputs="Exact current Dossier/catalog, effective domain, original producer/account/clock, allowed data, references, preferences and separate source-bound access.").items())
    lines += table("Post-Run Qualification", dict(new_handoff_execution="NOT_RUN_ON_PRIVATE_ALPHAS",
        original_research_disposition=_values(d["disposition"]), original_assistance_work=_values(d["assistance"]["work"]),
        current_readback_work=d["work"], limits=d["limits"]).items())
    return "\n".join(lines) + "\n"
