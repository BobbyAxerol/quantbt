"""Tiny callback/pin fixtures only. Never build native code or run an account."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.mode5_research.feedback_observer import FeedbackObserver, FrozenPins, PinMismatch, file_pin


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_actual_callbacks_return_same_objects_in_original_order(tmp_path):
    path = tmp_path / "progress.jsonl"
    calls = []
    compilation, result = object(), SimpleNamespace(bars=7)

    def build(feedback):
        calls.append(("build", feedback))
        return compilation

    def execute(commands):
        calls.append(("execute", commands))
        return result

    with FeedbackObserver(path) as observer:
        assert observer.call("build", build, None) is compilation
        assert observer.call("signature_compilation", lambda c: "exact", compilation) == "exact"
        assert observer.execute("native", execute, compilation, bars=lambda r: r.bars) is result
        assert observer.call("signature_result", lambda r: "owner", result) == "owner"
        assert observer.execute("python", execute, compilation, bars=lambda r: r.bars) is result
        summary = observer.summary()
    assert calls == [("build", None), ("execute", compilation), ("execute", compilation)]
    assert summary["actual_execution_calls"] == 2 and summary["visited_bars"] == 14
    assert summary["completed_passes_by_owner"] == {"native": 1, "python": 1}
    for stage in ("build", "execute", "signature_compilation", "signature_result"):
        assert summary["stage_calls"][stage] >= 1 and summary["stage_seconds"][stage] >= 0
    completed = [r for r in records(path) if r["stage"] == "account_complete"]
    assert [(r["completed_passes"], r["completed_account_bars"], r["owner"])
            for r in completed] == [(1, 7, "native"), (2, 14, "python")]
    assert [r["sequence"] for r in records(path)] == list(range(len(records(path))))


def test_every_native_pass_is_durable_not_sampled_every_sixteen(tmp_path, monkeypatch):
    path = tmp_path / "progress.jsonl"
    monkeypatch.setenv("MODE5_JOB_PROGRESS", str(path))
    syncs = []
    original_sync = os.fsync

    def sync(fd):
        syncs.append(fd)
        original_sync(fd)

    monkeypatch.setattr(os, "fsync", sync)
    with FeedbackObserver() as observer:
        for i in range(19):
            observer.execute("native", lambda: i, bars=lambda result: 3)
            assert len([r for r in records(path) if r["stage"] == "account_complete"]) == i + 1
    assert len(syncs) == len(records(path))
    assert records(path)[-1]["completed_account_bars"] == 57


def test_failed_and_interrupted_calls_never_become_zero_work_accounts(tmp_path):
    with FeedbackObserver(tmp_path / "progress") as observer:
        observer.execute("native", lambda: object(), bars=lambda result: 4)

        def interrupted():
            raise InterruptedError("in flight")

        with pytest.raises(InterruptedError):
            observer.execute("native", interrupted, bars=lambda result: 4)
        error = InterruptedError("worker stopped")
        observer.fault_receipt(tmp_path / "fault.json", error, request={"fixture": True})
        with pytest.raises(FileExistsError):
            observer.fault_receipt(tmp_path / "fault.json", error)
    receipt = json.loads((tmp_path / "fault.json").read_text())
    assert receipt["status"] == "FAULT"
    assert receipt["work"]["actual_execution_calls"] == 1
    assert receipt["work"]["visited_bars"] == 4
    assert receipt["work"]["attempted_execution_calls"] == {"native": 2}
    assert receipt["work"]["incomplete_work"] == "UNKNOWN_NOT_ZERO"
    assert receipt["work"]["checkpoint_reuse"] is False


@pytest.mark.parametrize("count", [True, -1, 2.0, None])
def test_invalid_work_counts_are_not_invented(tmp_path, count):
    with FeedbackObserver(tmp_path / "progress") as observer:
        with pytest.raises(ValueError, match="account-bar"):
            observer.execute("fake", lambda: object(), bars=lambda result: count)
        assert observer.completed_passes == observer.completed_account_bars == 0


def test_source_changed_after_callback_keeps_actual_completed_bill_and_fault(tmp_path):
    source = tmp_path / "source"
    source.write_text("original")
    pins = FrozenPins([file_pin(source)])
    with FeedbackObserver(tmp_path / "progress", guard=pins.verify) as observer:
        def mutate():
            source.write_text("changed")
            return object()
        with pytest.raises(PinMismatch) as fault:
            observer.execute("native", mutate, bars=lambda result: 11)
        observer.fault_receipt(tmp_path / "fault.json", fault.value)
    receipt = json.loads((tmp_path / "fault.json").read_text())
    assert receipt["work"]["actual_execution_calls"] == 1
    assert receipt["work"]["visited_bars"] == 11
    assert len([r for r in records(tmp_path / "progress") if r["stage"] == "account_complete"]) == 1


def test_source_changed_before_callback_prevents_any_execution(tmp_path):
    source = tmp_path / "source"
    source.write_text("original")
    pins = FrozenPins([file_pin(source)])
    source.write_text("changed")
    with FeedbackObserver(tmp_path / "progress", guard=pins.verify) as observer:
        with pytest.raises(PinMismatch):
            observer.execute("native", lambda: pytest.fail("must not execute"), bars=lambda result: 10)
        assert not observer.attempted_calls


def test_frozen_pins_and_exclusive_journal(tmp_path):
    source = tmp_path / "source"
    source.write_text("original")
    pin = file_pin(source)
    pins = FrozenPins([pin])
    pin["sha256"] = "0"*64
    exposed = pins.records
    exposed[0]["sha256"] = "0"*64
    pins.verify()
    with pytest.raises(ValueError):
        FrozenPins([file_pin(source), file_pin(source)])
    path = tmp_path / "progress"
    with FeedbackObserver(path):
        with pytest.raises(FileExistsError):
            FeedbackObserver(path)


def test_symlink_pin_and_missing_pin_are_rejected(tmp_path):
    source = tmp_path / "source"
    source.write_text("original")
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(ValueError):
        file_pin(link)
    pins = FrozenPins([file_pin(source)])
    source.unlink()
    with pytest.raises(PinMismatch):
        pins.verify()


@pytest.fixture
def private_driver():
    # Distributed/public test runs do not need or export the ignored lane.
    path = Path(__file__).resolve().parents[1] / "upgrade/local/mode5_upgrade_v1/m5-11-1/goal-finance-runtime01/driver.py"
    if not path.is_file():
        pytest.skip("private nonfinancial driver fixtures require the ignored local lane")
    spec = importlib.util.spec_from_file_location("feedback_driver_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate_fixture(tmp_path, driver):
    artifact, source = tmp_path / "fake.so", tmp_path / "fake_source"
    artifact.write_bytes(b"not an extension, never imported")
    source.write_text("fake source")
    pin, sources = file_pin(artifact), [file_pin(source)]
    gate = dict(status="PASS", artifact=pin, source_pins=sources,
                qualification={key: "PASS" for key in driver.GATE_CHECKS})
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(gate))
    return path, pin, sources, gate


def test_exact_native_gate_and_artifact_source_pins(private_driver, tmp_path):
    path, pin, sources, gate = gate_fixture(tmp_path, private_driver)
    assert private_driver.validate_gate(file_pin(path), pin, sources) == gate
    Path(sources[0]["path"]).write_text("changed source")
    with pytest.raises(PinMismatch):
        private_driver.validate_gate(file_pin(path), pin, sources)


@pytest.mark.parametrize("change", ["status", "artifact", "source_pins", "qualification"])
def test_incomplete_or_other_artifact_gate_rejected(private_driver, tmp_path, change):
    path, pin, sources, gate = gate_fixture(tmp_path, private_driver)
    gate[change] = {"status": "FAIL", "artifact": {}, "source_pins": [], "qualification": {}}[change]
    path.write_text(json.dumps(gate))
    with pytest.raises(ValueError):
        private_driver.validate_gate(file_pin(path), pin, sources)


def test_explicit_native_import_precedes_prepared_old_path(private_driver, tmp_path, monkeypatch):
    artifact = tmp_path / "fake.so"
    artifact.write_bytes(b"fake, never loaded")
    native = SimpleNamespace(__file__=str(artifact))
    prepared = SimpleNamespace(finance=SimpleNamespace(native_binary=native))
    calls = []

    def fake_import(name):
        calls.append(name)
        assert private_driver.sys.path[0] == str(tmp_path)
        return native if name.startswith("_quantbt_native") else prepared

    monkeypatch.setattr(private_driver.importlib, "import_module", fake_import)
    monkeypatch.setattr(private_driver.sys, "path", list(private_driver.sys.path))
    assert private_driver.load_original(tmp_path, file_pin(artifact)) is prepared
    assert calls == ["_quantbt_native._quantbt_native", "prepared"]


def test_missing_main_launch_authorization_writes_fault_without_imports(private_driver, tmp_path, monkeypatch):
    path, artifact, sources, gate = gate_fixture(tmp_path, private_driver)
    request = tmp_path / "request.json"
    request.write_text('{"fixture_only":true}')
    registration = tmp_path / "registration.json"
    registration.write_text(json.dumps(dict(schema=private_driver.SCHEMA, budget=private_driver.BUDGET,
        request=json.loads(request.read_text()), native_path=str(tmp_path), native_gate=file_pin(path),
        artifact=artifact, gate_source_pins=sources, pins=[file_pin(path), artifact, *sources, file_pin(request)])))
    output = tmp_path / "output"
    monkeypatch.delenv("MODE5_JOB_PROGRESS", raising=False)
    monkeypatch.setattr(private_driver.sys, "argv", ["driver", str(output), str(request),
        "--native-path", str(tmp_path), "--registration", str(registration)])
    monkeypatch.setattr(private_driver.signal, "signal", lambda *args: None)
    monkeypatch.setattr(private_driver, "load_original", lambda *args: pytest.fail("no finance imports"))
    with pytest.raises(ValueError, match="authorization absent"):
        private_driver.main()
    assert not (output / "result.json").exists()
    fault = json.loads((output / "fault.json").read_text())
    assert fault["work"]["actual_execution_calls"] == 0 and not fault["completed_cell_qualified"]


def test_empty_book_views_are_typed_immutable_and_do_not_invent_fills(private_driver):
    import pandas as pd
    owners = [SimpleNamespace(fills=(), metadata=dict(order_events=pd.DataFrame(), command_report=pd.DataFrame()))
              for _ in range(2)]
    saved = deepcopy([o.metadata for o in owners])
    views = private_driver.empty_views(*owners, (), "A-VWAP")
    for original, view, snapshot in zip(owners, views, saved, strict=True):
        assert view is not original and not view.fills
        assert view.metadata["order_events"].bar.dtype == "int64"
        assert {"target_order_id", "parent_order_id", "related_sorted_index"} <= set(view.metadata["order_events"])
        assert view.metadata["order_events"].related_sorted_index.dtype == "int64"
        assert view.metadata["command_report"].sorted_index.dtype == "int64"
        for name in ("order_events", "command_report"):
            pd.testing.assert_frame_equal(original.metadata[name], snapshot[name])
    owners[0].fills = (object(),)
    with pytest.raises(ValueError, match="cannot contain fills"):
        private_driver.empty_views(*owners, (), "A-VWAP")


def test_empty_partial_schema_not_generically_repaired(private_driver):
    import pandas as pd
    owner = SimpleNamespace(fills=(), metadata=dict(order_events=pd.DataFrame(columns=["bar"]), command_report=pd.DataFrame()))
    with pytest.raises(ValueError, match="partial"):
        private_driver.empty_views(owner, owner, (), "A-VWAP")


def test_runtime_materialization_only_restores_frozen_inactive_input(private_driver):
    class Geometry:
        def resolve(self, params):
            effective = {k: v for k, v in params.items() if k != "time_stop_bars" or params["time_stop_on"]}
            return SimpleNamespace(identity=json.dumps(effective, sort_keys=True))
    geometry = Geometry()
    effective = dict(time_stop_on=False, fixture_parameter=2)
    identity = geometry.resolve(effective).identity
    config = {"candidates": {"A-VWAP": {"time_stop_bars": 8}}}
    assert private_driver.runtime_input("A-VWAP", effective, config, geometry, identity) == effective | {"time_stop_bars": 8}
    assert "time_stop_bars" not in effective
    active = dict(time_stop_on=True, time_stop_bars=11)
    assert private_driver.runtime_input("A-VWAP", active, config, geometry, geometry.resolve(active).identity) == active
    config["candidates"]["A-VWAP"]["time_stop_bars"] = 7
    with pytest.raises(ValueError, match="frozen"):
        private_driver.runtime_input("A-VWAP", effective, config, geometry, identity)


@pytest.mark.parametrize("mutation", [False, True])
def test_fake_original_orchestration_captures_one_python_pass_no_replay(private_driver, tmp_path, monkeypatch, mutation):
    import pandas as pd
    from tools.mode5_admission import conformance
    calls = []
    request = dict(alpha="A-HMA", params={}, candidate_id="fake-candidate")
    geometry = SimpleNamespace(identity="fake-domain", resolve=lambda p: SimpleNamespace(identity="fake-candidate", params={}))
    history = pd.DataFrame({"close": 1.}, index=pd.date_range("2020-01-01", "2024-01-01", freq="h", inclusive="left", tz="UTC"))
    context = SimpleNamespace(history=history, scored=history.loc["2021-01-01":].copy(), config={},
        design={"schema_id": "fake-domain"}, candidates=[{"requested": {}}], witness={"fixture": True},
        signature=lambda: "immutable-history", request=lambda index: deepcopy(request))
    account = SimpleNamespace(equity=[0]*26280, liquidated=False)

    class Static:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, commands):
            calls.append("python")
            return account

    class Native(Static):
        def build(self, feedback):
            calls.append("build")
            return conformance.Compilation((), ())

        def execute(self, commands):
            calls.append("native")
            if mutation:
                context.scored.iloc[0, 0] += 1.
            return account

    finance = SimpleNamespace(NativeBinding=Native, StaticBinding=Static,
        static_binding=SimpleNamespace(), numba=SimpleNamespace(get_num_threads=lambda: 1),
        parity=lambda a, b: calls.append("original_parity"), __file__=__file__)

    def original_execute(original_request, target):
        target.mkdir()
        binding = finance.NativeBinding()
        for _ in range(2):
            compilation = binding.build(None)
            compilation.signature()
            result = binding.execute(compilation.commands)
            conformance.result_signature(result)
        reference = finance.StaticBinding.execute(binding, compilation.commands)
        finance.parity(reference, result)
        (target / "actual_owner.pkl").write_bytes(b"fake owner, no financial evidence")
        row = dict(request=original_request, actual_execution_calls=3, visited_bars=3*26280)
        (target / "cell.json").write_text(json.dumps(row))
        return row

    context.execute = lambda index, target: original_execute(request, target)
    monkeypatch.setitem(private_driver.sys.modules, "private_inputs", SimpleNamespace(schema=lambda alpha: geometry))
    monkeypatch.setattr(private_driver, "load_original", lambda *args: SimpleNamespace(finance=finance, PreparedResearch=lambda alpha: context))
    monkeypatch.setattr(private_driver, "terminal_parity", lambda *args: {"status": "FAKE_FIXTURE_ONLY"})
    monkeypatch.setattr(conformance, "result_signature", lambda result: calls.append("signature") or "fake-signature")
    paths = {Path(module.__file__).resolve() for module in tuple(private_driver.sys.modules.values())
        if getattr(module, "__file__", None) and Path(module.__file__).resolve().is_relative_to(private_driver.ROOT)
        and Path(module.__file__).is_file() and ".venv" not in Path(module.__file__).parts}
    registration = dict(native_path=str(tmp_path), artifact={}, candidate_index=0, native_gate={},
        pins=[file_pin(path) for path in paths])
    output = tmp_path / "fake_output"
    output.mkdir()
    original_static, original_native, original_parity = Static.execute, finance.NativeBinding, finance.parity
    with FeedbackObserver(tmp_path / "progress", guard=lambda: None) as observer:
        if mutation:
            with pytest.raises(ValueError, match="immutable market"):
                private_driver.execute_registered(registration, request, output, observer)
            assert observer.completed_passes == 1 and observer.completed_account_bars == 26280
            assert "python" not in calls
        else:
            result = private_driver.execute_registered(registration, request, output, observer)
            assert result["actual_execution_calls"] == 3 and result["visited_bars"] == 3*26280
            assert calls == ["build", "native", "signature", "build", "native", "signature", "python", "original_parity"]
            assert result["market"]["before"] == result["market"]["after"]
            assert result["market"]["future_tape_opened"] is False
            assert observer.owner_passes == {"native": 2, "python": 1}
            assert observer.stage_calls["build"] == observer.stage_calls["signature_result"] == 2
    assert Static.execute is original_static and finance.NativeBinding is original_native
    assert finance.parity is original_parity


@pytest.mark.parametrize("changed", [False, True])
def test_main_source_fault_retains_receipt_without_native_import(private_driver, tmp_path, monkeypatch, changed):
    path, artifact, sources, gate = gate_fixture(tmp_path, private_driver)
    request_path, registration_path = tmp_path / "request.json", tmp_path / "registration.json"
    request = dict(fixture_only=True)
    request_path.write_text(json.dumps(request))
    registration = dict(schema=private_driver.SCHEMA, budget=private_driver.BUDGET, request=request,
        native_path=str(tmp_path), native_gate=file_pin(path), artifact=artifact,
        gate_source_pins=sources, pins=[file_pin(path), artifact, *sources, file_pin(request_path)])
    registration_path.write_text(json.dumps(registration))
    if changed:
        Path(sources[0]["path"]).write_text("source changed after registration")
    output = tmp_path / "output"
    monkeypatch.delenv("MODE5_JOB_PROGRESS", raising=False)
    monkeypatch.setattr(private_driver.sys, "argv", ["driver", str(output), str(request_path),
        "--native-path", str(tmp_path), "--registration", str(registration_path)])
    monkeypatch.setattr(private_driver.signal, "signal", lambda *args: None)
    monkeypatch.setattr(private_driver, "load_original", lambda *args: pytest.fail("no imports before gate"))
    with pytest.raises(PinMismatch if changed else ValueError):
        private_driver.main()
    receipt = json.loads((output / "fault.json").read_text())
    assert receipt["error_type"] == ("PinMismatch" if changed else "ValueError")
    assert receipt["work"]["actual_execution_calls"] == receipt["work"]["visited_bars"] == 0
    assert not (output / "result.json").exists()


def test_resource_preregistration_bounds_are_enforced(private_driver, tmp_path, monkeypatch):
    output, scratch = tmp_path / "output", tmp_path / "scratch"
    output.mkdir()
    scratch.mkdir()
    monkeypatch.setattr(private_driver, "BUDGET", dict(retained_bytes=10, scratch_bytes=10, reserve_bytes=1))
    private_driver.resource_check(output, scratch, output / "progress")
    (scratch / "cache").write_bytes(b"x"*11)
    with pytest.raises(ValueError, match="scratch"):
        private_driver.resource_check(output, scratch, output / "progress")
    (scratch / "cache").unlink()
    (output / "retained").write_bytes(b"x"*11)
    with pytest.raises(ValueError, match="retained"):
        private_driver.resource_check(output, scratch, output / "progress")


@pytest.mark.parametrize("mismatch", [None, "working_price", "cancel", "liquidity", "authority", "trigger", "unavailable_working"])
def test_terminal_cancel_and_liquidity_compare_actual_fake_owner_outputs(private_driver, mismatch):
    import numpy as np
    import pandas as pd
    stamp = pd.Timestamp("2021-01-01", tz="UTC")
    row = {key: None for key in private_driver.TERMINAL_COLUMNS}
    row.update(original_index=0, sorted_index=0, timestamp=stamp, action="place", symbol="FIXTURE",
        side="buy", order_type="limit", order_id="fixture-order", status=2, reject_code=0,
        fill_bar=0, fill_qty=1., fill_price=10., fill_fee=0., active=False, waiting_parent=False,
        working_qty=1., working_price=10., working_trigger_price=0., reduce_only=False)
    owners = []
    for _ in range(2):
        fill = SimpleNamespace(timestamp=stamp, order_id="fixture-order", liquidity="maker",
            metadata={"liquidity_provenance": "native_matched_order_type_v1"})
        owners.append(SimpleNamespace(fills=(fill,), diagnostics=SimpleNamespace(canceled_orders=np.zeros(2, dtype=int)),
            metadata=dict(command_report=pd.DataFrame([row]), active_orders=pd.DataFrame(),
                order_events=pd.DataFrame([dict(event_name="fill", timestamp=stamp, order_id="fixture-order")]),
                command_outcome_report_v1=pd.DataFrame([dict(order_status="FILLED")]),
                fill_policy_diagnostics=pd.DataFrame([dict(command_index=0, trigger_armed=0)]),
                native_terminal_state_v1=dict(available=True, authority="rust", reason=None, replayed=False),
                cancellation_diagnostic_unit="canceled_order_slot_transition",
                lifecycle_counters=dict(canceled_order_count=0, canceled_event_count=0))))
    native = owners[1].metadata["command_report"]
    for key in ("remaining_qty", "qty_semantics", "processed", "working_state_available", "trigger_armed",
                "terminal_event_kind", "terminal_bar", "command_bar"):
        native[key] = 0
    native["native_terminal_contract"] = "native_terminal_state_v1"
    native["working_state_available"] = True
    if mismatch == "working_price":
        native.loc[0, "working_price"] += 1.
    elif mismatch == "cancel":
        owners[1].diagnostics.canceled_orders[0] = 1
    elif mismatch == "liquidity":
        owners[1].fills[0].liquidity = "taker"
    elif mismatch == "authority":
        owners[1].metadata["native_terminal_state_v1"]["available"] = False
    elif mismatch == "trigger":
        native.loc[0, "trigger_armed"] = 1
    elif mismatch == "unavailable_working":
        native.loc[0, "working_state_available"] = False
        native.loc[0, "working_price"] = 0.
    if mismatch not in (None, "unavailable_working"):
        with pytest.raises((ValueError, AssertionError)):
            private_driver.terminal_parity(*owners, (object(),))
    else:
        qualification = private_driver.terminal_parity(*owners, (object(),))
        assert qualification["status"] == "PASS_AVAILABLE_ORACLE_FIELDS"
        assert qualification["additional_account_replays"] == 0
        assert qualification["trigger_armed_parity"] == "PASS"
        assert qualification["unavailable_working_slots"] == int(mismatch == "unavailable_working")
        assert not qualification["full_cross_owner_remaining_qty_parity"]


def test_cold_registration_only_hashes_fake_inputs_never_imports_accounts(private_driver, tmp_path, monkeypatch):
    root = tmp_path
    local = root / "upgrade/local/mode5_upgrade_v1"
    original = root / "upgrade/private/mode5_upgrade_v1/m5-11-1/attempt-01"
    finance = local / "m5-08-1/attempt-01/finance.py"
    finance.parent.mkdir(parents=True)
    finance.write_text("# fake frozen source; never imported\n")
    prepared = local / "m5-11-1/attempt-01/prepared.py"
    prepared.parent.mkdir(parents=True)
    prepared.write_text("# fake prepared source; never imported\n")
    anchor = original / "pilot-long-A-VWAP-recovery-02/registration.json"
    anchor.parent.mkdir(parents=True)
    anchor.write_text(json.dumps(dict(critical_sources=[file_pin(finance)])))
    private_registration = root / "upgrade/private/mode5_upgrade_v1/m5-02/attempt-01/registration.json"
    private_registration.parent.mkdir(parents=True)
    private_registration.write_text(json.dumps(dict(copies=str(root / "fake_copies"))))
    old_market = root / "upgrade/private/mode5_upgrade_v1/m5-08-1/attempt-01/market_identity.json"
    old_market.parent.mkdir(parents=True)
    old_market.write_text('{}')
    native = root / "native"
    native.mkdir()
    gate, artifact, sources, _ = gate_fixture(native, private_driver)
    request = root / "request.json"
    request.write_text('{"fixture_only":true}')
    market = root / "fake_market"
    market.write_text("fixture only; no tape is opened")
    registration = root / "registration.json"
    monkeypatch.setattr(private_driver, "ROOT", root)
    monkeypatch.setattr(private_driver, "LOCAL", local)
    monkeypatch.setattr(private_driver, "ORIGINAL", original)
    monkeypatch.setattr(private_driver, "native_sources", lambda: set())
    monkeypatch.setattr(private_driver, "original_inputs", lambda *args: ({}, {}, file_pin(market), {market}))
    monkeypatch.setattr(private_driver, "load_original", lambda *args: pytest.fail("cold registration must not import finance/native"))
    private_driver.register(request, registration, native, gate, 0)
    record = json.loads(registration.read_text())
    assert record["status"] == "PREREGISTERED_NO_FINANCIAL_LAUNCH"
    assert record["financial_execution_calls"] == 0 and record["future_tape_opened"] is False
    assert record["budget"] == dict(scratch_bytes=32*1024**2, retained_bytes=64*1024**2, reserve_bytes=5*1024**3)
    FrozenPins(record["pins"]).verify()
