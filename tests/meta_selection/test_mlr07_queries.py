from tools.meta_model_research import forward_queries as q
from tools.meta_model_research.protocol import GROUPS


def test_query_cap_fixed_priority_dedup_and_outcome_blindness(monkeypatch, tmp_path):
    rows = []
    for fold in range(25, 35):
        for group in GROUPS:
            for policy in ("QD", "QF"):
                rows.append(
                    dict(
                        group=group,
                        fold=fold,
                        policy=policy,
                        winner=f"{group}-{fold}",
                        query_id=f"{group}-{fold}",
                        witness_status="MISSING_EXECUTION",
                    )
                )
    controls = [
        dict(
            request=dict(
                group=g,
                fold=25,
                kind="control",
                query_id=f"control-{g}",
                policy="N",
                winner="a",
            ),
            Q=999,
        )
        for g in GROUPS
    ]
    monkeypatch.setattr(q, "verify", lambda *_: None)
    monkeypatch.setattr(q, "existing_queries", lambda: controls)
    monkeypatch.setattr(q, "read", lambda *_: dict(rows=rows))
    monkeypatch.setattr(q, "pin", lambda *_: dict(sha256="pin"))
    monkeypatch.setattr(q, "save_new", lambda _, value: value)
    first = q.register_queries(tmp_path)
    assert len(first["admitted"]) == 32 and len(first["pilot"]) == 8
    assert first["missing_distinct"] == 40
    assert [r["group"] for r in first["admitted"][:4]] == list(GROUPS)
    assert all(r["policy"] == "QF" for r in first["admitted"][4:])
    rows.reverse()
    for r in rows:
        r["Q"] = -12345
    second = q.register_queries(tmp_path)
    assert first == second


def test_prior_undefined_query_is_reused_not_reexecuted(monkeypatch, tmp_path):
    row = dict(
        group=GROUPS[0],
        fold=25,
        policy="QF",
        winner="b",
        query_id="known",
        witness_status="MISSING_EXECUTION",
    )
    old = [
        dict(
            request=dict(
                group=g,
                fold=25,
                kind="control",
                query_id=f"control-{g}",
                policy="N",
                winner="a",
            )
        )
        for g in GROUPS
    ]
    old.append(
        dict(
            request=dict(group=GROUPS[0], query_id="known"),
            observation=dict(status="NO_VARIANCE"),
        )
    )
    monkeypatch.setattr(q, "verify", lambda *_: None)
    monkeypatch.setattr(q, "existing_queries", lambda: old)
    monkeypatch.setattr(q, "read", lambda *_: dict(rows=[row]))
    monkeypatch.setattr(q, "pin", lambda *_: {})
    monkeypatch.setattr(q, "save_new", lambda _, value: value)
    result = q.register_queries(tmp_path)
    assert result["missing_distinct"] == 0 and len(result["admitted"]) == 4
