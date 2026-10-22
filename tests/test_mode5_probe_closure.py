"""Fake custody and synthetic continuous-path fixtures; never account execution."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from tools.mode5_research import jobs, probe_closure as c
from tools.mode5_research import panels as p


def completed_cell(*args):
    # Numeric fixtures use the real public owner; the cold loader is checked
    # separately in a fresh process, not bypassed in the research driver.
    with patch.object(c.views, "numeric_owner", return_value=p):
        return c.completed_cell(*args)


def scope():
    base, union = dict(entries=[]), dict(status="PASS", fit_requests_closed=4, fits=[], executions=[], neighborhoods=[])
    index = 0
    for key, indices in c.TARGETS.items():
        for center, original_index in enumerate(indices):
            union["fits"].append(dict(alpha=key, original_index=original_index, supported=True))
            for role_no, role in enumerate(c.ROLES):
                nid, parent = f"union-{key}-{original_index}-{role}", f"parent-{original_index}"
                n = dict(alpha=key, center=center, original_index=original_index, parent_candidate_id=parent,
                    role=role, seed=732+role_no, neighborhood_id=nid, rows=[],
                    covariance_status="REGULARIZED_PROPOSALS_NOT_HESSIAN",
                    coverage=dict(status="OBSERVED_REQUIRED_RADII", uncovered_axes=[], uncovered_groups=[]))
                size = 37 if key == "sc" and role_no == 1 else 38
                for row_id in range(size):
                    old = index < 195
                    request = dict(alpha="A-"+key.upper(), role=role, candidate_id=f"p-{index}", params=dict(x=index),
                        design_id=f"schema-{index}" if old else nid, parent_panel_index=original_index,
                        parent_candidate_id=parent, proposal_row=row_id, probe_direction="axis:x:1" if old else "covariance:0:1",
                        neighborhood_center=center, start="2021-01-01", stop="2024-01-01", symbol="SYNTHETIC")
                    execution = dict(index=index, alpha=key, role=role, candidate_id=request["candidate_id"], request=request,
                        request_sha256=c.prior.digest(request), request_design_id=request["design_id"], union_design_id=nid,
                        source="PRESERVED_SEALED_SCHEMA_REQUEST" if old else "NEW_COVARIANCE_ROLE_REQUEST_NO_ACCOUNT_EVIDENCE",
                        original_schema_execution=dict(request=deepcopy(request)) if old else None)
                    union["executions"].append(execution)
                    n["rows"].append(dict(status="READY", execution_index=index, row_id=row_id, effective=request["params"],
                        candidate_id=request["candidate_id"], direction=request["probe_direction"]))
                    if old:
                        base["entries"].append(dict(cell_id=f"old-{index}", request=deepcopy(request)))
                    index += 1
                n["rows"].append(dict(status="DUPLICATE", execution_index=None, row_id=size))
                union["neighborhoods"].append(n)
    return base, union


def local_fixture():
    base, union = scope()
    entries, neighborhoods = c.union_scope(base, union)
    reg = dict(neighborhoods=neighborhoods, objectives={k: dict(metric="economic_utility", quality_floor=0,
        reference_scale=1, reference_id="original", unit="decimal_return") for k in c.TARGETS})
    centers, evaluations = [], {}
    for center, i in enumerate(c.TARGETS["rsi"]):
        centers.append(dict(panel_index=i, center=center, candidate_id=f"parent-{i}", cell=dict(path="center"),
            metrics=metrics(.6), covariance="supported original owner", params=dict(x=i)))
    for e in entries:
        r = e["request"]
        if e["alpha"] == "rsi":
            evaluations[e["execution_index"]] = dict(center=r["neighborhood_center"], role=r["role"],
                candidate_id=r["candidate_id"], direction=r["probe_direction"], status="COMPLETE", metrics=metrics(.4),
                utility=.4, cell=dict(path="cell"), paths=dict(path="paths"))
    return reg, centers, evaluations


def metrics(utility):
    return dict(economic_utility=utility, return_status="VALID", account_mode="continuous_development_2021_2023",
        daily_count=1095, max_drawdown=.2)


def seal(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs._seal(path, value)
    return c.prior.pin(path)


def fake_checkpoint(root, request, cell_id, extra=None):
    attempt = root / "cells" / cell_id / "attempt-0001"
    output = attempt / "output"
    output.mkdir(parents=True)
    launcher = root / "launcher"
    if not launcher.exists():
        seal(launcher, dict(fake_only=True))
    source = root / "source"
    if not source.exists():
        seal(source, dict(immutable=True))
    candidate = jobs.Candidate.create(cell_id, request, [str(launcher)], root,
        [c.prior.pin(launcher), c.prior.pin(source)], result_file="result.json", required_outputs=("result.json",))
    passes = 2 if request["alpha"] == "A-RSI" else 1
    counts = dict(account_passes=passes, account_bars=passes*26280)
    result = dict(status="PASS", request=request, actual_execution_calls=passes, visited_bars=passes*26280)
    if extra:
        result.update(extra(output, counts))
    seal(output / "result.json", result)
    receipt = dict(cell_id=cell_id, status="COMPLETE", log=c.prior.pin(source), exact_counts=counts)
    # The normal COMPLETE record resolves its checkpoint relative to this log.
    log = seal(attempt / "child.log", dict(fake_child_no_execution=True))
    receipt["log"] = log
    seal(attempt / "receipt.json", receipt)
    jobs._checkpoint(candidate, attempt, output, counts)
    return candidate, receipt, c.prior.pin(attempt / "checkpoint.json")


def reconciliation_fixture(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    entries, lanes = [], []
    sources = ("PRESERVED_SEALED_SCHEMA_REQUEST", "NEW_COVARIANCE_ROLE_REQUEST_NO_ACCOUNT_EVIDENCE")
    for i, source in enumerate(sources):
        request = dict(alpha="A-RSI" if i == 0 else "A-SC", candidate_id=f"c{i}")
        candidate, receipt, checkpoint = fake_checkpoint(store, request, f"cell-{i}")
        lane = store / "runs" / f"lane-{i}"
        reg_pin = seal(lane / "registration.json", dict(store=str(store), candidates=[candidate.to_dict()]))
        done_pin = seal(lane / "completion.json", dict(status="COMPLETE", all_owned_children_reaped=True,
            errors=[], records=[receipt]))
        lanes.append(dict(lane=str(lane), registration=reg_pin, completion=done_pin, candidates=1))
        entries.append(dict(cell_id=candidate.cell_id if i == 0 else None, request=request,
            request_sha256=c.prior.digest(request), source=source))
    planned = seal(tmp_path / "controller-registration.json", dict(lanes=lanes[:1]))
    completion = seal(tmp_path / "controller-completion.json", dict(status="COMPLETE_ACCOUNT_WORK_NOT_SCIENCE_GATE",
        error=None, interrupted_signals=[], registered_lanes=1, completed_lanes=[lanes[0]["completion"]]))
    overlay = seal(tmp_path / "overlay.json", dict(schema="mode5.probe_overlay_completion.v1", store=str(store), lanes=lanes[1:]))
    reg = dict(controller_registration=planned, entries=entries, store=str(store), recipe_id="recipe",
               request_roster_sha256=c.prior.digest([e["request"] for e in entries]))
    return reg, completion, overlay, lanes


def test_exact_union_scope_preserves_request_designs_and_aliases():
    base, union = scope()
    entries, neighborhoods = c.union_scope(base, union)
    assert len(entries) == 303 and 3*len(entries) == 909
    assert [e["request"] for e in entries[:195]] == [e["request"] for e in base["entries"]]
    assert entries[0]["request"]["design_id"] != entries[0]["union_design_id"]
    assert sum(r["status"] == "DUPLICATE" for ns in neighborhoods.values() for n in ns for r in n["rows"]) == 8


@pytest.mark.parametrize("fault", ["missing", "duplicate", "design", "role", "candidate", "ledger", "fit", "order", "alias"])
def test_union_scope_rejects_changed_contract(fault):
    base, union = scope()
    if fault == "missing":
        union["executions"].pop()
    elif fault == "duplicate":
        union["executions"][1] = deepcopy(union["executions"][0])
    elif fault in {"design", "role", "candidate"}:
        union["executions"][0]["request"][{"design": "design_id", "role": "role", "candidate": "candidate_id"}[fault]] = "changed"
    elif fault == "ledger":
        union["neighborhoods"][0]["rows"][0]["effective"] = dict(x=-1)
    elif fault == "fit":
        union["fits"][0]["supported"] = False
    elif fault == "order":
        union["executions"].reverse()
    elif fault == "alias":
        union["neighborhoods"][0]["rows"][-1]["execution_index"] = 0
    with pytest.raises((ValueError, KeyError)):
        c.union_scope(base, union)


@pytest.mark.parametrize("key,value", [("gamma", 2), ("reference_scale", 2), ("quality_floor", -.1),
    ("minimum_daily_count", 365), ("risk_drawdown_max", .6), ("aggregate", "annual"), ("annual_local", "enabled")])
def test_recipe_rejects_unapproved_math(key, value):
    with pytest.raises(ValueError):
        c.recipe_identity(dict(c.LOCAL, **{key: value}), c.views.UTILITY)


def test_original_local_math_lexicographic_tie_and_all_probes():
    reg, centers, evaluations = local_fixture()
    result = c.compare_local(reg, "rsi", centers, evaluations)
    assert result["chosen_candidate"] == "parent-10"
    assert all(r["score"] == .4 and r["components"]["gamma"] == 1 and r["components"]["reference_scale"] == 1
               and r["components"]["actual_days"] == 1095 for r in result["component_rows"])
    assert result["full_panel_local_status"] == "NOT_EVALUABLE"
    assert result["annual_local_status"] == "NOT_AUTHORIZED"


def test_validation_is_post_decision_only_and_overlap_dependent():
    reg, centers, evaluations = local_fixture()
    before = c.compare_local(reg, "rsi", centers, evaluations)
    for e in evaluations.values():
        if e["role"] == "local_validation":
            e["utility"] = e["metrics"]["economic_utility"] = -100.
    after = c.compare_local(reg, "rsi", centers, evaluations)
    assert before["chosen_candidate"] == after["chosen_candidate"]
    assert before["selection_input_sha256"] == after["selection_input_sha256"]
    assert not any(r["eligible"] for r in after["validation_post_decision"])
    assert all(not r["temporal_oos"] and not r["independent_overlaps"] for r in after["overlap"])


@pytest.mark.parametrize("fault", ["missing", "failed", "undefined", "coverage", "days", "role", "negative", "risk"])
def test_probe_failures_never_disappear(fault):
    reg, centers, evaluations = local_fixture()
    selection = [i for i, e in evaluations.items() if e["role"] == "selection_probe"]
    for i in selection:
        e = evaluations[i]
        if fault == "missing":
            del evaluations[i]
        elif fault == "failed":
            e["status"] = "FAULT"
        elif fault == "undefined":
            e["metrics"]["return_status"], e["utility"] = "UNDEFINED", None
        elif fault == "days":
            e["metrics"]["daily_count"] = 365
        elif fault == "role":
            e["role"] = "local_validation"
        elif fault == "negative":
            e["utility"] = e["metrics"]["economic_utility"] = -.2
        elif fault == "risk":
            e["metrics"]["max_drawdown"] = .51
    if fault == "coverage":
        reg["neighborhoods"]["rsi"][0]["coverage"]["uncovered_axes"] = ["x"]
    if fault in {"days", "role"}:
        with pytest.raises(ValueError):
            c.compare_local(reg, "rsi", centers, evaluations)
    else:
        result = c.compare_local(reg, "rsi", centers, evaluations)
        assert result["chosen_candidate"] is None
        assert len(result["component_rows"]) == 3
        assert result["status"] == ("NO_SELECTION" if fault in {"negative", "risk"} else "NOT_EVALUABLE")


def test_undefined_center_retained_and_no_roster_expansion():
    reg, centers, evaluations = local_fixture()
    centers[0]["metrics"]["economic_utility"] = None
    result = c.compare_local(reg, "rsi", centers, evaluations)
    assert result["status"] == "NOT_EVALUABLE"
    assert result["component_rows"][0]["status"] == "UNDEFINED_CENTER_RETAINED"
    with pytest.raises(ValueError):
        c.compare_local(reg, "rsi", centers[:2], evaluations)


def test_reconcile_verifies_real_checkpoint_manifest_not_a_survivor_subset(tmp_path):
    reg, completion, overlay, _ = reconciliation_fixture(tmp_path)
    with patch.object(c, "validate_registration"), patch.object(jobs, "_reuse", wraps=jobs._reuse) as reuse:
        result = c.reconcile(reg, completion, overlay)
    assert reuse.call_count == 2 and result["financial_executions"] == 0
    assert result["inherited_account_passes"] == 3 and result["inherited_account_bars"] == 78840
    assert [r["request_sha256"] for r in result["inputs"]] == [e["request_sha256"] for e in reg["entries"]]


@pytest.mark.parametrize("fault", ["absent", "duplicate", "incomplete", "mutation", "source", "store", "request", "receipt"])
def test_reconcile_blocks_unqualified_union(tmp_path, fault):
    reg, completion, overlay, lanes = reconciliation_fixture(tmp_path)
    overlay_value = c.views.sealed_json(overlay)
    if fault == "absent":
        overlay_value["lanes"] = []
    elif fault == "duplicate":
        overlay_value["lanes"] *= 2
    elif fault == "store":
        overlay_value["store"] += "-other"
    elif fault == "incomplete":
        value = c.views.sealed_json(completion)
        value["status"] = "INCOMPLETE"
        completion = seal(tmp_path / "incomplete-controller.json", value)
    elif fault in {"mutation", "source", "receipt"}:
        path = Path(reg["store"]) / ("source" if fault == "source" else "cells/cell-1/attempt-0001/" +
            ("output/result.json" if fault == "mutation" else "receipt.json"))
        path.write_bytes(b"mutated fake evidence")
    elif fault == "request":
        reg["entries"][1]["request"] = dict(alpha="A-SC", candidate_id="other")
    overlay = seal(tmp_path / "changed-overlay.json", overlay_value)
    with patch.object(c, "validate_registration"), pytest.raises(ValueError):
        c.reconcile(reg, completion, overlay)


def synthetic_checkpoint(tmp_path, kind="positive", suffix=None, mutate=None):
    import numpy as np
    start, stop = p._ns("2021-01-01"), p._ns("2024-01-01")
    times = np.arange(start, stop, p.HOUR_NS, dtype=np.int64)
    marks = np.r_[np.linspace(20200., 40000., 365), np.linspace(40200., 60000., 365),
                  np.linspace(60200., 80000., 365)]
    if kind == "flat":
        marks[:] = 20000.
    if kind == "negative":
        marks = np.linspace(19900., 10000., 1095)
    if suffix is not None:
        marks[730:] = suffix
    contract = p.ReportingContractV1(scope="full", unit="account_period", currency="USDT", baseline_equity=20000.,
        baseline_time_ns=start-p.HOUR_NS, scope_end_ns=stop-p.HOUR_NS, sampling="observed_daily_utc",
        annual_periods=365., equity_clock="bar_close")
    covered = p.ReportingCoverageV1(result_identity="fake", producer="test", profile="compact", ledger="omitted",
        retained_rows=0, dropped_rows=0, reason="no account fixture")
    obs = p.AccountObservations(times_ns=times, equity=np.repeat(marks, 24), coverage=covered).with_derived_returns(
        contract, partial_mask=np.zeros(1095, dtype=bool), witness="synthetic")
    source = dict(times_ns=times.copy(), equity=obs.equity.copy(), daily_returns=obs.returns.values.copy(),
        positions=np.zeros(26280), fees=np.ones(26280)*.001, funding=np.ones(26280)*.0001, turnover=np.ones(26280))
    request = dict(alpha="A-RSI", candidate_id="synthetic", params=dict(x=1), role="selection_probe",
        start="2021-01-01", stop="2024-01-01", probe_direction="axis:x:1", proposal_row=0,
        design_id="original-design", symbol="SYNTHETIC", parent_panel_index=10)
    provenance = p.CandidateProvenance("test", "test", "A-RSI", "synthetic", "raw", "effective", "axis:x:1", (0,),
        "execution", "design", "SYNTHETIC", "REVIEWED_EXPLORATORY_DEVELOPMENT", "synthetic only", p._ns("2020-01-01"),
        stop, p._ns("2026-10-10"), p._ns("2026-10-10"), "no execution", (("paths", "synthetic"),))
    verified = p.VerifiedCell(provenance, start, stop, contract, obs,
        tuple(p.FrozenBuffer.from_array(k, source[k]) for k in ("positions", "fees", "funding", "turnover")),
        None, None, "{}", "PASS", None)
    rows = p.continuous_annual_rows(verified, utility_policy=p.UtilityPolicy(**c.views.UTILITY), backend="python")
    m = dict(total_return=rows[0].metric("net_return").value, max_drawdown=rows[0].metric("drawdown").value,
        sharpe=rows[0].metric("sharpe").value, daily_loss_es=rows[0].metric("daily_loss_es").value,
        economic_utility=rows[0].metric("economic_utility").value)

    def artifacts(output, counts):
        actual = output / "actual"
        actual.mkdir()
        if mutate:
            mutate(source)
        np.savez_compressed(actual / "paths.npz", **source)
        cell = dict(request=request, metrics=m, path=c.prior.pin(actual / "paths.npz"), scored_bars=26280,
            scored_days=1095, clean_oos=False, actual_execution_calls=2, visited_bars=52560,
            route="fake original owner", execution_key="fake")
        seal(actual / "cell.json", cell)
        seal(actual / "request.json", request)
        seal(actual / "development_access.json", dict(future_tape_opened=False, original_contract_preserved=True,
            mutable_strategy_or_account_reused=False, allowed_stop="2024-01-01"))
        qualification = dict(status="PASS", fixture_only=True)
        seal(output / "accounting_qualification.json", qualification)
        return dict(accounting_qualification=qualification)

    tmp_path.mkdir(exist_ok=True)
    candidate, _, checkpoint = fake_checkpoint(tmp_path, request, "synthetic", artifacts)
    value = c.views.sealed_json(checkpoint)
    entry = dict(request=request, cell_id=candidate.cell_id, union_design_id="union-overlay",
                 request_sha256=c.prior.digest(request))
    item = dict(cell_id=candidate.cell_id, checkpoint=checkpoint, output=value["output"], exact_counts=value["exact_counts"])
    registration = dict(original_reporting_contract=asdict(contract), annual_utility=c.views.UTILITY,
                        outcome_timing="CURRENT_READ_DEVELOPMENT; synthetic only")
    return registration, entry, item


def test_cold_rows_are_carried_attribution_and_reconcile_costs(tmp_path):
    reg, entry, item = synthetic_checkpoint(tmp_path)
    _, rows = completed_cell(reg, entry, item)
    assert [r["environment_id"] for r in rows] == ["whole_path", "2021", "2022", "2023"]
    assert [r["environment_baseline"]["equity"] for r in rows[1:]] == [20000., 40000., 60000.]
    assert all(not r["annual_local_authorized"] and r["union_design_id"] == "union-overlay" for r in rows)
    assert sum(r["money_pnl"] for r in rows[1:]) == rows[0]["money_pnl"]
    assert all(r["calendar_days"] == 365 for r in rows[1:])


def test_cold_future_suffix_does_not_change_earlier_attribution(tmp_path):
    import numpy as np
    a = synthetic_checkpoint(tmp_path / "a")
    b = synthetic_checkpoint(tmp_path / "b", suffix=np.linspace(1000., 900000., 365))
    _, before = completed_cell(*a)
    _, after = completed_cell(*b)
    for x, y in zip(before[1:3], after[1:3], strict=True):
        assert [{k: val for k, val in m.items() if k != "components"} for m in x["metrics"]] == [
            {k: val for k, val in m.items() if k != "components"} for m in y["metrics"]]
        for name in ("equity", "as_of_ns"):
            assert x["environment_baseline"][name] == y["environment_baseline"][name]
        assert x["money_pnl"] == y["money_pnl"]


@pytest.mark.parametrize("kind", ["flat", "negative"])
def test_negative_and_no_trade_outputs_retained(tmp_path, kind):
    reg, entry, item = synthetic_checkpoint(tmp_path, kind=kind)
    _, rows = completed_cell(reg, entry, item)
    utility = c.prior.metric(rows[0], "economic_utility")
    assert utility == 0 if kind == "flat" else utility < 0
    if kind == "flat":
        assert c.prior.metric(rows[0], "sharpe") is None


@pytest.mark.parametrize("fault", ["calendar", "daily", "nonfinite", "count", "output", "request"])
def test_cold_source_and_calendar_failures(tmp_path, fault):
    import numpy as np

    def mutation(arrays):
        if fault == "calendar":
            arrays["times_ns"][0] += 1
        elif fault == "daily":
            arrays["daily_returns"][0] += .5
        elif fault == "nonfinite":
            arrays["equity"][0] = np.nan

    reg, entry, item = synthetic_checkpoint(tmp_path, mutate=mutation)
    if fault == "count":
        item["exact_counts"]["account_bars"] += 1
    elif fault == "output":
        item["output"] += "-changed"
    elif fault == "request":
        entry["request"]["params"] = dict(x=2)
    with pytest.raises((ValueError, AssertionError)):
        completed_cell(reg, entry, item)


def test_analyze_rejects_195_only_and_misordered_inputs():
    base, union = scope()
    entries, _ = c.union_scope(base, union)
    reg = dict(entries=entries, recipe_id="same", request_roster_sha256="same")
    for roster in (entries[:195], list(reversed(entries))):
        inputs = dict(status="PASS", recipe_id="same", request_roster_sha256="same",
                      inputs=[dict(request_sha256=e["request_sha256"]) for e in roster])
        with patch.object(c, "validate_registration"), pytest.raises(ValueError):
            c.analyze(reg, inputs)


def test_source_validation_failure_has_fault_and_cleanup_receipt(tmp_path):
    registration = seal(tmp_path / "registration.json", dict(budget=dict(scratch_bytes=32*jobs.MIB,
        retained_bytes=64*jobs.MIB, reserve_bytes=5*jobs.GIB)))
    input_pin = seal(tmp_path / "input.json", dict(status="PASS"))
    with patch.object(c, "validate_registration", side_effect=ValueError("source-pin failure")), pytest.raises(ValueError):
        c.run_phase(registration["path"], input_pin["path"], "fault-01", "analyze")
    fault = c.views.sealed_json(c.prior.pin(tmp_path / "fault-01/fault.json"))
    assert fault["error"] == "source-pin failure" and fault["elapsed_seconds"] >= 0
    assert fault["financial_executions"] == 0
    assert (tmp_path / "fault-01/cleanup.json").is_file()
    assert [r["event"] for r in jobs.read_journal(tmp_path / "fault-01/journal")] == ["cold_start", "cold_fault"]
    with pytest.raises(FileExistsError):
        c.run_phase(registration["path"], input_pin["path"], "fault-01", "analyze")


def test_cold_registration_imports_no_finance_or_numeric_runtime():
    completed = subprocess.run([str(Path(sys.executable).resolve()), "-B", "-c",
        "from tools.mode5_research import probe_closure; import sys; "
        "assert 'numpy' not in sys.modules; assert 'numba' not in sys.modules; "
        "assert not any(probe_closure.views.forbidden(n) for n in sys.modules)"],
        cwd=c.ROOT, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
