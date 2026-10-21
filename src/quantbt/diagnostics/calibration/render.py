"""Five ordered researcher views over the same bounded immutable records."""
from html import escape
import json


def cell(value):
    value = escape(json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False), quote=True)
    return value.replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def table(title, rows):
    lines = ["", "## " + title, "", "| Field | Retained value |", "|---|---|"]
    lines.extend("| " + cell(key) + " | " + cell(value) + " |" for key, value in rows)
    return lines


def grid(title, columns, rows):
    lines = ["", "## " + title, "", "| " + " | ".join(columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)
    return lines


def render_worksheet(worksheet, *, private=False):
    d = worksheet.to_dict(private=private)
    lines = ["# Diagnostics To Mode 5", "", "Researcher decision support; no automatic execution or deployment."]
    lines += table("Decision Summary", d.items() if not private else dict(
        worksheet_id=worksheet.identity, selection=d["selection"],
        archive_status="SUPPLIED" if d["archive"] else "NO_ARCHIVE",
        options=[dict(option_id=c["recipe"]["option_id"], readiness=c["readiness"],
            missing_contracts=c["missing_contracts"], economic_superiority="NOT_QUALIFIED") for c in d["cards"]]).items())
    if not private:
        return "\n".join(lines) + "\n"
    lines += table("Alpha Behavior", dict(context=d["context"], diagnostic=d["diagnostic"]).items())
    lines += grid("Measured Findings", ("Finding", "Basis / status", "Value", "Unit", "Support", "Uncertainty / masks", "Interpretation", "Competing explanation", "Next action"),
        ((f["label"], f["basis"] + " / " + f["status"], f["value"], f["unit"], f["support"],
          dict(uncertainty=f["uncertainty"], masks=f["masks"]),
          f["interpretation"], f["rival_explanation"], f["decision_implication"] + " " + f["next_test"])
         for f in d["findings"]))
    if not d["findings"]:
        lines += ["", "No source-bound finding supplied; no metric or regime conclusion is inferred from the recipe."]
    if d["archive"]:
        lines += grid("Archive Admission", ("Evidence", "Disposition", "Reasons", "Missing inputs"),
            ((r["evidence_id"], r["disposition"], r["reasons"], r["missing_inputs"])
             for r in d["archive"]["rows"]))
    lines += ["", "Absent findings remain unmeasured; archive recurrence is not independent evidence or basin volume."]
    lines += grid("Recipe Comparison", ("Option", "Readiness", "Objective", "Sampler", "Selector", "Attempts", "Rationale", "Missing proof"),
        ((c["recipe"]["option_id"], c["readiness"], (c["recipe"]["spec"] or {}).get("objective"),
          (c["recipe"]["spec"] or {}).get("sampler"), (c["recipe"]["spec"] or {}).get("selector"),
          (c["recipe"]["spec"] or {}).get("search_budget"), c["recipe"]["reason"], c["missing_contracts"])
         for c in d["cards"]))
    for index, card in enumerate(d["cards"], 1):
        recipe = card["recipe"]
        lines += table("Recipe Comparison " + str(index), dict(option_id=recipe["option_id"],
            reason=recipe["reason"], readiness=card["readiness"],
            missing_contracts=card["missing_contracts"], field_origins=recipe["field_origins"],
            economic_superiority=recipe["economic_superiority"]).items())
    selected = d["selection"]
    chosen = next((c["recipe"] for c in d["cards"] if selected
                   and c["recipe"]["option_id"] == selected["option_id"]), None)
    if chosen and chosen["spec"] is not None:
        lines += table("Run Configuration", chosen["spec"].items())
        b = chosen["binding"]
        lines += table("Metric And Eligibility Preferences", b["metrics"].items())
        lines += table("Resolved Selection And Initialization", dict(selection=b["selection"],
            sampler=b["sampler"], warm_start=b["warm_start"], batch_size=b["batch_size"],
            local_offsets=b["local_offsets"],
            annual_account_resets=0, account_policy=b["continuous"]["account_policy"]).items())
        lines += grid("Annual Attribution Windows", ("Environment", "First scored mark (ns)", "Last scored mark (ns)", "Manifest", "Role"),
            ((w["environment_id"], w["start_ns"], w["end_ns"], w["witness"]["manifest_id"], w["witness"]["role"])
             for w in b["windows"]))
    else:
        lines += table("Run Configuration", [("status", "NO_EXECUTABLE_CHOICE")])
    lines += table("Post-Run Qualification", [("status", "NOT_RUN"),
        ("next_action", "Compile the explicit choice, export privately, preflight original inputs, then call backtest explicitly."),
        ("limits", "Regret is not decay; calendar views are not independent OOS; no automatic recipe or seed policy is enabled.")])
    return "\n".join(lines) + "\n"


def render_run(report, *, private=False):
    d = report.to_dict(private=private)
    lines = ["# Mode 5 Run Reconciliation"]
    lines += table("Post-Run Qualification", ((k, v) for k, v in d.items() if k != "actual_decision"))
    if d.get("actual_decision"):
        from quantbt.mode5.decision_report import DecisionReport
        if private:
            lines += ["", DecisionReport.from_json(json.dumps(d["actual_decision"])).to_markdown(private=True)]
        else:
            lines += table("Actual Decision", d["actual_decision"]["summary"].items())
    return "\n".join(lines) + "\n"
