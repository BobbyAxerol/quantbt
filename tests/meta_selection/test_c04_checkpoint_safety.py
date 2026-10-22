"""C04-T03/T04: fail-closed checkpoints and local filesystem transactions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from quantbt.optimization import SamplerConfig
from quantbt.optimization.continuation import ContinuationError, ExactStudySession
from quantbt.optimization.continuation.contract import MAX_BYTES, canonical, digest
from quantbt.optimization.continuation import storage
from tests.meta_selection.test_c04_continuation import BINDING, RECIPES, advance, config


def checkpoint():
    cfg = config()
    session = ExactStudySession(cfg, binding=BINDING)
    advance(session, 12)
    text, sha = session.dumps()
    return cfg, session, text, sha


@pytest.mark.parametrize("key", list(BINDING))
def test_c04_t03_every_external_witness_binding_required(key):
    cfg, _, text, sha = checkpoint()
    with pytest.raises(ContinuationError, match="binding"):
        ExactStudySession.loads(text, config=cfg, binding={**BINDING, key: "future-or-other-input"}, expected_digest=sha)
    with pytest.raises(ContinuationError, match="binding"):
        ExactStudySession.loads(text, config=cfg, binding={k: v for k, v in BINDING.items() if k != key}, expected_digest=sha)


@pytest.mark.parametrize("update", [
    {"seed": 23}, {"budget": 63}, {"cutoff": "2025-01-01T00:00:00Z"},
    {"stage": "different-objective-stage"}, {"strategy_identity": "another-alpha"},
    {"study_name": "other-study"}, {"direction": "minimize"},
    {"sampler_config": SamplerConfig(name="sobol")},
    {"ranges": {"fixed": {"kind": "fixed", "value": 2},
                "a": {"kind": "integer", "low": 1, "high": 9},
                "z": {"kind": "float", "low": -2.0, "high": 2.0}}},
])
def test_c04_t03_identity_schema_dimension_order_gate(update):
    cfg, _, text, sha = checkpoint()
    with pytest.raises(ContinuationError, match="identity"):
        ExactStudySession.loads(text, config=replace(cfg, **update), binding=BINDING, expected_digest=sha)


@pytest.mark.parametrize("mutation", ["proposal", "objective", "event_order", "event_extra", "operation",
                                       "missing_tell", "witness", "runtime", "system_attrs", "config_type"])
def test_c04_t03_corruption_even_with_recomputed_internal_digest(mutation):
    cfg, _, text, _ = checkpoint()
    obj = json.loads(text)
    payload = obj["payload"]
    if mutation == "proposal":
        payload["events"][0]["effective"]["z"] = 0.0
    elif mutation == "objective":
        payload["events"][1]["value"] += 1.0
    elif mutation == "event_order":
        payload["events"][0], payload["events"][1] = payload["events"][1], payload["events"][0]
    elif mutation == "event_extra":
        payload["events"][0]["opaque"] = "not-permitted"
    elif mutation == "operation":
        payload["events"][0]["op"] = "unpickle"
    elif mutation == "missing_tell":
        payload["events"].pop()
    elif mutation == "witness":
        payload["witness"]["seen"] = []
    elif mutation == "runtime":
        payload["runtime"]["versions"]["optuna"] = "4.9.0"
    elif mutation == "config_type":
        payload["config"]["seed"] = float(cfg.seed)
    else:
        payload["system_attrs"] = {"cma:optimizer": "attacker-pickle-is-not-imported"}
    obj["digest"] = digest(payload)
    with pytest.raises(ContinuationError):
        ExactStudySession.loads(canonical(obj), config=cfg, binding=BINDING, expected_digest=obj["digest"])


@pytest.mark.parametrize("bad", ["", "{", "[]", '{"schema":1,"schema":2}',
                                 '{"schema":NaN}', '{"schema":Infinity}', "x" * (MAX_BYTES + 1)])
def test_c04_t03_strict_decoder(bad):
    with pytest.raises(ContinuationError):
        ExactStudySession.loads(bad, config=config(), binding=BINDING, expected_digest="x")


@pytest.mark.parametrize("update", [
    {"seed": None}, {"seed": True}, {"seed": -1}, {"budget": 0}, {"budget": True},
    {"pruner": {"name": "hyperband", "kwargs": {}}}, {"pruner": None},
    {"pruner": {"name": "median", "kwargs": {"interval_steps": 0}}},
    {"early_stopping": {"callable": "arbitrary-user-callback"}},
    {"sampler_config": SamplerConfig(kwargs={"gamma": lambda n: n})},
    {"sampler_config": SamplerConfig(kwargs={"source_trials": []})},
])
def test_c04_t03_unsupported_serializers_and_seeds_fail(update):
    with pytest.raises((ContinuationError, ValueError)):
        ExactStudySession(replace(config(), **update), binding=BINDING)


def test_c04_t03_future_warm_seed_and_mutable_config():
    cfg = config()
    warm = dict(params={"z": 1, "a": 2, "fixed": 2}, available_at=cfg.cutoff,
                space_identity=cfg.bridge().space.identity, strategy_identity=cfg.strategy_identity)
    with pytest.raises(ValueError, match="strictly before"):
        ExactStudySession(replace(cfg, warm_start=(warm,)), binding=BINDING)
    session = ExactStudySession(cfg, binding=BINDING)
    cfg.ranges["z"]["high"] = 3
    try:
        with pytest.raises(ContinuationError, match="mutated"):
            session.ask()
    finally:
        cfg.ranges["z"]["high"] = 2.0


def test_c04_t03_digest_pending_and_thread_safety():
    cfg, session, text, _ = checkpoint()
    with pytest.raises(ContinuationError, match="digest"):
        ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest="wrong")
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(ContinuationError, match="thread"):
            executor.submit(session.ask).result()
    p = session.ask()
    with pytest.raises(ContinuationError, match="RUNNING"):
        session.dumps()
    session.tell(p.number, state="FAIL", reason="WORK_EXPLICITLY_CANCELLED")
    session.dumps()


def test_c04_t04_atomic_compare_and_swap_and_replace_failure(tmp_path, monkeypatch):
    cfg, session, text, sha = checkpoint()
    path = tmp_path / "journal.json"
    assert session.save(path) == sha
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ContinuationError, match="previous_digest"):
        session.save(path)
    with pytest.raises(ContinuationError, match="digest"):
        session.save(path, previous_digest="stale")
    advance(session, 3)
    new_text, new_sha = session.dumps()
    real_replace = storage.os.replace
    monkeypatch.setattr(storage.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("injected crash")))
    with pytest.raises(OSError, match="crash"):
        session.save(path, previous_digest=sha)
    assert path.read_text() == text
    assert list(tmp_path.glob(".qms-checkpoint-*")) == []
    restored = ExactStudySession.load(path, config=cfg, binding=BINDING, expected_digest=sha)
    assert restored.dumps() == (text, sha)
    monkeypatch.setattr(storage.os, "replace", real_replace)
    assert session.save(path, previous_digest=sha) == new_sha
    assert path.read_text() == new_text
    with pytest.raises(ContinuationError, match="digest"):
        session.save(path, previous_digest=sha)


def test_c04_t04_concurrent_writer_no_lost_update(tmp_path):
    cfg, session, _, sha = checkpoint()
    path = tmp_path / "journal.json"
    session.save(path)
    advance(session, 1)
    first, first_sha = session.dumps()
    advance(session, 1)
    second, second_sha = session.dumps()
    def write(text):
        try:
            storage.write_checkpoint(path, text, previous_digest=sha)
            return "committed"
        except ContinuationError:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, (first, second)))
    assert sorted(results) == ["committed", "stale"]
    actual = path.read_text()
    assert actual in {first, second}
    expected = first_sha if actual == first else second_sha
    ExactStudySession.load(path, config=cfg, binding=BINDING, expected_digest=expected)


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t01_fresh_process_continuation_without_evaluator_during_restore(recipe, tmp_path):
    cfg = config(recipe)
    full = ExactStudySession(cfg, binding=BINDING)
    advance(full, 48)
    partial = ExactStudySession(cfg, binding=BINDING)
    advance(partial, 23)
    path = tmp_path / "journal.json"
    sha = partial.save(path)
    script = """
import json,sys
from quantbt.optimization.continuation import ExactStudySession
from tests.meta_selection.test_c04_continuation import config,BINDING,advance
session = ExactStudySession.load(sys.argv[1], config=config(sys.argv[2]), binding=BINDING, expected_digest=sys.argv[3])
# Restore has no evaluator argument; only the remaining 25 trials run here.
advance(session, 25)
print(json.dumps(session.witness(), sort_keys=True))
"""
    observed = subprocess.check_output([sys.executable, "-c", script, str(path), recipe, sha], text=True,
                                       cwd=Path(__file__).resolve().parents[2])
    assert json.loads(observed) == full.witness()
