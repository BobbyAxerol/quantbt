"""Full available cells, not a winning row pretending to be an adaptive panel."""

import json

from tools.mode5_diagnostics.recovery import recover_master_panels


def test_historical_inventory_keeps_every_available_environment_and_negative_cell(tmp_path):
    payloads = [
        {"score_table": {"alpha": {"development": [{"score": 2}, {"score": -3}],
                                    "reviewed": [{"score": 1}, {"score": -4}]}}},
        {"stress_table": {"candidate1": {"env1": {"score": 2}, "env2": {"score": -8}},
                           "candidate2": {"env1": {"score": 1}, "env2": {"score": -1}}}},
        [{"alpha_id": "alpha", "score": -6}, {"alpha_id": "alpha", "score": 5}],
    ]
    paths = [tmp_path / f"source{i}.json" for i in range(3)]
    for path, payload in zip(paths, payloads):
        path.write_text(json.dumps(payload))
    result = recover_master_panels(*paths)
    assert result["counts"] == {"baseline": 4, "T1": 4, "T2": 2}
    assert len(result["rows"]) == 10 and sum(row["metric"]["score"] < 0 for row in result["rows"]) == 5
    assert all(not row["execution_reuse_authorized"] for row in result["rows"])
    assert result["full_adaptive_trial_panel"] == "MISSING_FROM_MASTER_EXPORTS"
    assert result["replayed_executions"] == 0 and not result["rewritten_optimizer_history"]
