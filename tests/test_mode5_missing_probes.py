"""Fake original owners only: no alpha, data tape, native build or account work."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tools.mode5_research import missing_probes as probes
from tools.mode5_research.jobs import Candidate


def domain(alpha):
    specs = [dict(name="period", kind="integer", low=1, high=200, fixed=False,
                  fixed_value=None, categories=[], active_if={})]
    if alpha == "A-SC":
        specs += [dict(name="src_col", kind="fixed", low=None, high=None, fixed=True,
                       fixed_value="close", categories=[], active_if={})]
    return dict(parameters=specs, constraints=[], inactive={})


@pytest.fixture
def frozen():
    bundle, parents, geometries = {}, {}, {}
    for key, alpha, symbol, index in (("rsi", "A-RSI", "ETHUSDT", 10), ("sc", "A-SC", "BTCUSDT", 33)):
        geometry = domain(alpha)
        geometries[alpha] = geometry
        def params(n):
            return dict(period=n, **({"src_col": "close"} if alpha == "A-SC" else {}))
        rows = [dict(admitted=True, effective=params(n+1), candidate_id=probes.effective_id(geometry, params(n+1)))
                for n in range(128)]
        parent = dict(schema_id=probes.canonical_digest(geometry), design_id=f"original-{key}", rows=rows)
        parents[alpha] = parent
        request = dict(probes.BASE, alpha=alpha, symbol=symbol, params=params(180),
            candidate_id=probes.effective_id(geometry, params(180)), design_id=f"neighbor-{key}", proposal_row=7,
            parent_candidate_id=rows[index]["candidate_id"], parent_design_id=parent["design_id"],
            parent_panel_index=index, neighborhood_center=0, probe_direction="axis:period:1",
            probe_radius=.1, probe_seed=732, role="selection_probe")
        row = dict(row_id=7, status="READY", effective=request["params"], candidate_id=request["candidate_id"],
                   direction=request["probe_direction"], execution_index=0)
        neighborhood = dict(neighborhood_id=request["design_id"], original_index=index,
            parent_candidate_id=request["parent_candidate_id"], role=request["role"], radius=.1, seed=732,
            center=0, rows=[row])
        entry = dict(index=0, request=request, request_sha256=probes.canonical_digest(request),
            status="MISSING_ACCOUNT_EVALUATION", launch_authorized=False, compatible_coordinate_role_matches=[],
            role=request["role"], center=0, neighborhood_id=request["design_id"], row_id=7,
            candidate_id=request["candidate_id"])
        cov = dict(original_index=index, candidate_id=rows[index]["candidate_id"], geometry_id=parent["schema_id"],
            candidate_roster=[r["candidate_id"] for r in rows], financial_launch_authorized=False,
            status="FIT_AND_EXACT_DIRECTIONS_NOT_REGISTERED", recipe=deepcopy(probes.RECIPE))
        bundle[key] = dict(bounded_neighborhood_manifest=dict(parent_geometry_id=parent["schema_id"],
            recipe=deepcopy(probes.RECIPE), launches_authorized=False, request_count=1,
            neighborhoods=[neighborhood], executions=[entry], covariance_requests=[cov]),
            candidate_requests=[{"must_not_execute": True}], annual_view_requests=[{"not_an_account": True}])
    return bundle, parents, geometries


def test_cold_collect_preserves_exact_requests_and_pending_covariance(frozen):
    bundle, parents, geometries = frozen
    before = deepcopy(bundle)
    entries, covariance = probes.collect_missing(*frozen)
    assert bundle == before and len(entries) == len(covariance) == 2
    for entry, key in zip(entries, ("rsi", "sc"), strict=True):
        assert entry["request"] == bundle[key]["bounded_neighborhood_manifest"]["executions"][0]["request"]
        assert entry["analysis_id"] == probes.canonical_digest(entry["analysis"])
        assert "not_whole_128" in entry["analysis"]["scope"]
    assert all(c["account_specs"] == [] and c["financial_executions"] == 0 for c in covariance)
    assert all("PRIOR_DIRECTION_SEAL" in c["status"] for c in covariance)


@pytest.mark.parametrize("change", ["params", "candidate", "parent", "role", "seed", "radius",
                                  "symbol", "start", "budget", "economics", "match", "duplicate", "covariance"])
def test_rejects_changed_scope_or_reuse_without_qualification(frozen, change):
    bundle, parents, geometries = frozen
    manifest = bundle["rsi"]["bounded_neighborhood_manifest"]
    entry = manifest["executions"][0]
    request = entry["request"]
    if change == "params":
        request["params"]["period"] = 180.5
    elif change == "candidate":
        request["candidate_id"] = "changed"
    elif change == "parent":
        request["parent_panel_index"] = 49
    elif change == "role":
        request["role"] = "local_validation"
    elif change in {"seed", "radius"}:
        request["probe_" + change] = 0
    elif change == "symbol":
        request["symbol"] = "BTCUSDT"
    elif change == "start":
        request["start"] = "2022-01-01"
    elif change == "budget":
        request["max_feedback_runs"] = 128
    elif change == "economics":
        request["fee_multiplier"] = .1
    elif change == "match":
        entry["compatible_coordinate_role_matches"] = [{"existing": "unqualified"}]
    elif change == "duplicate":
        manifest["executions"].append(deepcopy(entry))
        manifest["request_count"] = 2
    else:
        manifest["covariance_requests"][0]["recipe"]["rho"] = .9
    entry["request_sha256"] = probes.canonical_digest(request)
    with pytest.raises(ValueError):
        probes.collect_missing(bundle, parents, geometries)


def test_fixed_domain_and_boolean_casts_are_not_repaired():
    geometry = domain("A-SC")
    for params in ({"period": True, "src_col": "close"}, {"period": 180, "src_col": "open"},
                   {"period": float("nan"), "src_col": "close"}, {"period": 201, "src_col": "close"}):
        with pytest.raises(ValueError):
            probes.effective_id(geometry, params)


@pytest.fixture
def runtime(tmp_path, frozen):
    entries, _ = probes.collect_missing(*frozen)
    source = tmp_path / "owner.py"
    source.write_text("immutable fake owner\n")
    state = dict(contexts=[], calls=[], mode="success")

    class FakeEndpoint:
        def __init__(self, owner):
            self.owner = owner

        def backtest(self, **kwargs):
            state["calls"].append((self.owner, kwargs))
            if state["mode"] == "account_failure":
                raise RuntimeError("in-flight work unknown")
            if state["mode"] == "interrupt":
                signal.raise_signal(signal.SIGTERM)
            if state["mode"] == "source_mutation":
                source.write_text("changed fake owner\n")
            if state["mode"] == "data_mutation":
                state["contexts"][-1].signature_value = "changed"
            if state["mode"] == "economics_mutation":
                config["original_economics"] = "changed"
            return SimpleNamespace(equity=range(26280))

    class Factory:
        @staticmethod
        def pct_equity(**kwargs):
            state["calls"].append(("pct_equity", kwargs))
            return FakeEndpoint("endpoint")

        @staticmethod
        def event_driven(**kwargs):
            state["calls"].append(("event_driven", kwargs))
            return FakeEndpoint("callback")

    def engine(**kwargs):
        state["calls"].append(("direct", kwargs))
        if state["mode"] == "second_failure":
            raise RuntimeError("second owner failed")
        return SimpleNamespace(result=SimpleNamespace(equity=range(26280)))

    config = {"original_economics": "unchanged"}
    finance = SimpleNamespace(QuantBTEndpoint=Factory, BacktestEngine=engine, CONFIG=config,
                             static_binding=SimpleNamespace(CONFIG=config), __file__=str(source))

    def execute(request, actual):
        actual.mkdir()
        (actual / "request.json").write_text(json.dumps(request))
        if request["alpha"] == "A-RSI":
            finance.QuantBTEndpoint.pct_equity(fee_rate=.001).backtest(signal="original-real-signal")
            finance.BacktestEngine(hedge_type="%_equity")
            passes = 2
        else:
            finance.QuantBTEndpoint.event_driven(backend="python", profile="audit").backtest(
                strategy="original-BarCloseBinding-instance")
            passes = 1
        row = dict(status="PASS", request=request, actual_execution_calls=passes, visited_bars=passes*26280,
                   scored_bars=26280, scored_days=1095, clean_oos=False, route=probes.ROUTES[request["alpha"]])
        (actual / "cell.json").write_text(json.dumps(row))
        (actual / "paths.npz").write_text("fake artifact, not an account path\n")
        return row

    finance.execute = execute

    def context_factory(alpha):
        entry = next(e for e in entries if e["request"]["alpha"] == alpha)
        request = entry["request"]
        context = SimpleNamespace(finance=finance, config=config, witness=probes.file_pin(source),
                                  signature_value="unchanged")
        context.signature = lambda: context.signature_value
        original = dict(request, params={"period": 11}, candidate_id=request["parent_candidate_id"],
                        design_id=request["parent_design_id"])
        def original_request(index):
            assert index == request["parent_panel_index"]  # Never the neighbor execution index.
            return original
        context.request = original_request
        state["contexts"].append(context)
        return context

    def qualification(context, request, actual):
        if state["mode"] == "qualification_failure":
            raise ValueError("retained path fails qualification")
        return dict(status="PASS", fake_only=True, validation_account_reexecutions=0)

    def run(alpha="A-RSI", name="run"):
        entry = next(e for e in entries if e["request"]["alpha"] == alpha)
        return probes.execute_one(entry, output=tmp_path / name, progress=tmp_path / (name + ".jsonl"),
            pins=[probes.file_pin(source)], context_factory=context_factory, qualify=qualification,
            validate_context=lambda c, r: None)

    return SimpleNamespace(run=run, state=state, source=source, finance=finance, factory=Factory,
                           engine=engine, entries=entries, tmp=tmp_path, context_factory=context_factory)


@pytest.mark.parametrize("alpha,passes", [("A-RSI", 2), ("A-SC", 1)])
def test_actual_owner_delegation_receipt_and_lowerbound_journal(runtime, alpha, passes):
    result = runtime.run(alpha)
    assert result["actual_execution_calls"] == passes and result["visited_bars"] == passes * 26280
    assert result["elapsed_seconds"] > 0 and result["accounting_qualification"]["fake_only"]
    assert result["request"] == next(e["request"] for e in runtime.entries if e["request"]["alpha"] == alpha)
    probes.verify_artifacts(result)
    rows = [json.loads(line) for line in (runtime.tmp / "run.jsonl").read_text().splitlines()]
    assert len([r for r in rows if r["stage"] == "account_complete"]) == passes
    assert rows[-1]["stage"] == "worker_complete" and rows[-1]["completed_passes"] == passes
    assert all(r["elapsed_seconds"] >= 0 for r in rows)
    assert runtime.finance.QuantBTEndpoint is runtime.factory and runtime.finance.BacktestEngine is runtime.engine
    if alpha == "A-SC":
        assert runtime.state["calls"][-1][1]["strategy"] == "original-BarCloseBinding-instance"
    else:
        assert runtime.state["calls"][-1][1]["hedge_type"] == "%_equity"


@pytest.mark.parametrize("mode,passes,status", [("account_failure", 0, "FAULT"), ("second_failure", 1, "FAULT"),
    ("source_mutation", 1, "FAULT"), ("data_mutation", 1, "FAULT"), ("economics_mutation", 1, "FAULT"),
    ("qualification_failure", 2, "FAULT"),
    ("interrupt", 0, "INTERRUPTED")])
def test_fault_receipt_preserves_completed_work_and_unknown_inflight(runtime, mode, passes, status):
    runtime.state["mode"] = mode
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(BaseException):
        runtime.run()
    result = probes.read_json(runtime.tmp / "run/result.json")
    assert result["status"] == status and result["actual_execution_calls"] == passes
    assert result["visited_bars"] == passes * 26280 and result["elapsed_seconds"] > 0
    assert result["accounting_qualification"] == "NOT_QUALIFIED"
    assert "unknown" in result["counts_are"] and result["work"]["incomplete_work"] == "UNKNOWN_NOT_ZERO"
    assert runtime.finance.QuantBTEndpoint is runtime.factory and runtime.finance.BacktestEngine is runtime.engine
    assert signal.getsignal(signal.SIGTERM) == previous


def test_source_failure_before_load_still_has_completion_receipt(runtime):
    entry = runtime.entries[0]
    pin = probes.file_pin(runtime.source)
    runtime.source.write_text("changed before runtime\n")
    with pytest.raises(RuntimeError):
        probes.execute_one(entry, output=runtime.tmp / "pre", progress=runtime.tmp / "pre.jsonl", pins=[pin],
            context_factory=runtime.context_factory, qualify=lambda *a: None, validate_context=lambda *a: None)
    result = probes.read_json(runtime.tmp / "pre/result.json")
    assert result["actual_execution_calls"] == result["visited_bars"] == 0
    assert not runtime.state["contexts"] and result["error_type"] == "PinMismatch"


def test_output_collision_never_overwrites_and_fresh_context_each_candidate(runtime):
    runtime.run(name="first")
    before = probes.file_pin(runtime.tmp / "first/result.json")
    with pytest.raises(FileExistsError):
        runtime.run(name="first")
    assert probes.file_pin(runtime.tmp / "first/result.json") == before
    runtime.run(name="second")
    assert len(runtime.state["contexts"]) == 2 and runtime.state["contexts"][0] is not runtime.state["contexts"][1]


def test_artifact_mutation_prevents_cold_qualification(runtime):
    result = runtime.run()
    (runtime.tmp / "run/actual/paths.npz").write_text("tampered\n")
    with pytest.raises(ValueError):
        probes.verify_artifacts(result)


def test_specs_use_pinned_argv_not_shell_and_domain_result(tmp_path, frozen):
    entries, _ = probes.collect_missing(*frozen)
    driver, registration = tmp_path / "driver.py", tmp_path / "registration.json"
    driver.write_text("fake driver\n")
    registration.write_text("{}\n")
    executable = Path(sys.executable).resolve()
    pins = [probes.file_pin(p) for p in (driver, executable)]
    groups = probes.job_specs(entries, driver=driver, registration=registration,
                             executable=executable, cwd=tmp_path, pins=pins)
    assert len(groups) == 2
    for values in groups.values():
        candidate = Candidate.from_dict(values[0])
        assert candidate.result_file == "result.json" and "accounting_qualification.json" in candidate.required_outputs
        assert candidate.argv[0] == str(executable) and candidate.argv[3] == "worker"
        assert dict(candidate.env) == {"M5_ATTEMPT": "attempt-01"}
        assert str(registration) in {p["path"] for p in candidate.pins}


def test_private_driver_import_is_cold_and_does_not_prepare_or_launch():
    path = Path(__file__).resolve().parents[1] / "upgrade/local/mode5_upgrade_v1/m5-11-1/goal-selector-finance01/driver.py"
    if not path.exists():
        pytest.skip("private driver intentionally not shipped")
    before = set(sys.modules)
    spec = importlib.util.spec_from_file_location("cold_missing_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not ({"prepared", "finance", "sc_panel", "private_inputs", "_quantbt_native"} & (set(sys.modules) - before))


def test_private_wrapper_preserves_controlled_prefix_without_finance():
    root = Path(__file__).resolve().parents[1]
    wrapper = root / "upgrade/local/mode5_upgrade_v1/m5-11-1/goal-selector-finance01/controlled-python.sh"
    controlled = root / ".maturin/qms08/release-regression-v1"
    if not wrapper.exists() or not controlled.exists():
        pytest.skip("private controlled runtime intentionally not shipped")
    result = subprocess.run([str(wrapper), "-B", "-c",
        "import json,sys;print(json.dumps([sys.prefix, 'finance' in sys.modules]))"],
        capture_output=True, text=True, check=True, timeout=5)
    assert json.loads(result.stdout) == [str(controlled), False]
