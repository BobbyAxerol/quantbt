"""Reconcile summaries without inventing paths, metrics or cache permission."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from .isolation import canonical_digest


def load_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=invalid)


def interval_record(window: dict, *, reviewed=False) -> dict:
    start, scored, end = (datetime.fromisoformat(window[key])
                          for key in ("start", "sim_start", "end"))
    if not start <= scored < end:
        raise ValueError("invalid scored/warmup interval")
    return {"start": start.isoformat(), "scored_start": scored.isoformat(),
            "end": end.isoformat(), "elapsed_scored_days": (end - scored).total_seconds() / 86400,
            "warmup_days": (scored - start).total_seconds() / 86400,
            "right_boundary": "HISTORICAL_END_INCLUSIVITY_UNVERIFIED",
            "role": "EXPLORATORY_REVIEWED_2024" if reviewed else "DEVELOPMENT_REVIEWED",
            "raw_label": window.get("name"), "bars": None}


def duplicate_decisions(rows: list[dict]) -> dict:
    groups = {}
    decisions = []
    for number, row in enumerate(rows):
        key = canonical_digest({"alpha": row["alpha_id"], "params": row["best_params"]})
        groups.setdefault(key, []).append(number)
        decisions.append({"decision_row": number, "alpha_id": row["alpha_id"],
                          "selector": row["formulation_name"], "parameter_id": key})
    by_alpha = {}
    for row in decisions:
        by_alpha.setdefault(row["alpha_id"], set()).add(row["parameter_id"])
    return {"decision_records": decisions, "groups": groups,
            "unique_by_alpha": {k: len(v) for k, v in by_alpha.items()},
            "unique_parameter_vectors": len(groups),
            "execution_reuse_authorized": False,
            "reason": "matching params alone do not witness data/clock/economics/source identity"}


def metric_availability(summary: dict, requested: str) -> dict:
    requirements = {"psr": ("returns", "frequency", "metric_contract"),
                    "tail": ("returns", "metric_contract"),
                    "campaign_tail": ("closed_campaigns", "metric_contract")}
    if requested not in requirements:
        raise ValueError("unknown requested metric")
    missing = [key for key in requirements[requested] if key not in summary]
    return {"status": "MISSING_REQUIRED_INPUT" if missing else "INPUTS_PRESENT_UNVERIFIED",
            "missing": missing, "value": None,
            "action": "locate retained paths; otherwise register targeted replay"}


def sampler_observation(requested, actual, independent=None, *, verified=False) -> dict:
    independent = dict(independent or {})
    aliases = {"tpe": "TPESampler", "tpe_legacy": "TPESampler",
               "tpe_multivariate_group": "TPESampler", "sobol": "QMCSampler",
               "cmaes": "CmaEsSampler"}
    mixed = aliases.get(requested, requested) != actual or any(independent.values())
    return {"requested": requested, "resolved": actual,
            "independent_counts": independent, "mixed": mixed if verified else None,
            "purity": "MIXED_OBSERVED" if verified and mixed else
                      "RESOLUTION_ONLY" if verified else "HISTORICAL_LABEL_ONLY",
            "reason": "independent sampling or different resolved family" if mixed else
                      "no draw-level witness; do not certify sampler purity"}


def spec_table_errata(spec: str, rows: list[dict], *, source_ref: str) -> list[dict]:
    result, alpha = [], None
    by_key = {(r["alpha_id"], r["formulation_name"]): (i, r)
              for i, r in enumerate(rows)}
    for line_no, line in enumerate(spec.splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        if cells[0] in {r["alpha_id"] for r in rows}:
            alpha = cells[0]
        pair = by_key.get((alpha, cells[1]))
        if pair is None:
            continue
        index, row = pair
        match = re.search(r"(\d+)\s+fills", cells[5])
        comparisons = [("oos_2024_fills", int(match.group(1))) ] if match else []
        try:
            comparisons.append(("oos_2024_max_dd_pct", float(cells[4].replace("%", ""))))
        except ValueError:
            pass
        for field, old in comparisons:
            new = row[field]
            agrees = old == new if field.endswith("fills") else abs(old - new) <= 0.0051
            if not agrees:
                result.append({"kind": "ARTIFACT_DISCREPANCY", "field": field,
                               "old_value": old, "new_value": new,
                               "prose_pointer": f"{source_ref}:L{line_no}",
                               "json_pointer": f"D3#/{index}/{field}",
                               "status": "RECOMPUTED_FROM_ARTIFACT"})
    return result


def reconcile(baseline, t1, t2, spec: str) -> dict:
    count = sum(len(environment) for rows in baseline["score_table"].values()
                for environment in rows.values())
    t1_table, t2_table = [], []
    for i, row in enumerate(t1["matrix_summary"]):
        key = f'{row["alpha_id"]}_{row["sampler_name"]}'
        winner = t1["winners"][key]
        if row["params"] != winner["best_params"]:
            raise ValueError("T1 winner/summary parameter mismatch")
        for name, stress_name in (("oos_sharpe_2024", "sharpe"),
                                  ("oos_return_pct", "return_pct"),
                                  ("oos_max_dd_pct", "max_dd_pct"), ("oos_fills", "fills")):
            if row[name] != t1["stress_table"][key]["R_HOLDOUT"][stress_name]:
                raise ValueError("T1 summary/stress mismatch")
        t1_table.append({k: v for k, v in row.items() if k != "params"} |
                        {"source_pointer": f"D2#/matrix_summary/{i}",
                         "evidence_status": "HISTORICAL_REPORTED"})
    for i, row in enumerate(t2):
        t2_table.append({k: v for k, v in row.items()
                        if k not in {"best_params", "in_sample_details"}} |
                       {"source_pointer": f"D3#/{i}", "evidence_status": "HISTORICAL_REPORTED"})
    windows = {"baseline_holdout": interval_record(baseline["metadata"]["holdout"]["R_HOLDOUT"], reviewed=True),
               "t1_holdout": interval_record(t1["metadata"]["stress_regimes"]["R_HOLDOUT"], reviewed=True),
               "t1_tune": interval_record(t1["metadata"]["tune_window"])}
    return {"schema": "quantbt.mode5_baseline.reconciliation.v1", "baseline_records": count,
            "t1_winners": len(t1["winners"]),
            "t1_stress_records": sum(map(len, t1["stress_table"].values())),
            "t1_table": t1_table, "t2_table": t2_table,
            "duplicates": duplicate_decisions(t2), "windows": windows,
            "actual_sampler_labels": t1["metadata"]["samplers"],
            "metric_recovery": {k: metric_availability({}, k) for k in ("psr", "tail", "campaign_tail")},
            "numeric_errata": spec_table_errata(spec, t2, source_ref="D0"),
            "financial_replay": "NOT_RUN", "full_trial_panel": "NOT_IN_MASTER_EXPORT"}
