"""Inventory historical panels without manufacturing richer observations."""

from tools.mode5_baseline.evidence import load_json
from tools.mode5_baseline.isolation import file_identity


def recover_master_panels(baseline_path, t1_path, t2_path):
    baseline, t1, t2 = map(load_json, (baseline_path, t1_path, t2_path))
    rows = []
    for candidate, environments in baseline["score_table"].items():
        for environment, metrics in environments.items():
            for ordinal, metric in enumerate(metrics):
                rows.append(dict(source="baseline", pointer=f"/score_table/{candidate}/{environment}/{ordinal}",
                    candidate=candidate, environment=environment, metric=metric,
                    status="HISTORICAL_REPORTED", execution_reuse_authorized=False))
    for candidate, environments in t1["stress_table"].items():
        for environment, metric in environments.items():
            rows.append(dict(source="T1", pointer=f"/stress_table/{candidate}/{environment}",
                candidate=candidate, environment=environment, metric=metric,
                status="HISTORICAL_REPORTED", execution_reuse_authorized=False))
    for ordinal, record in enumerate(t2):
        rows.append(dict(source="T2", pointer=f"/{ordinal}", candidate=record["alpha_id"],
            environment="reported_comparison", metric=record,
            status="HISTORICAL_REPORTED", execution_reuse_authorized=False))
    return dict(schema="quantbt.mode5.panel_recovery.v1", rows=rows,
        counts={name: sum(row["source"] == name for row in rows) for name in ("baseline", "T1", "T2")},
        artifacts=[file_identity(p) for p in (baseline_path, t1_path, t2_path)],
        full_adaptive_trial_panel="MISSING_FROM_MASTER_EXPORTS",
        richer_paths="REPLAY_REQUIRED_UNLESS_SEPARATELY_MANIFEST_BOUND",
        rewritten_optimizer_history=False, replayed_executions=0)
