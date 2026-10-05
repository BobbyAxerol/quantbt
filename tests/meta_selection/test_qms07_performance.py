"""Q7: lossless DSA, exact identity/lifetime and chronological decisions."""

from dataclasses import fields, replace

import numpy as np
import pytest

from quantbt.optimization.meta_selection.common import canonical, digest
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from tests.meta_selection.test_qms03_history import (
    make_task,
    revision_for,
    snapshot,
    stamp,
)


def test_q7_t03_derived_values_do_not_change_portable_bytes_or_replacements():
    task, schema = make_task(n=6)
    revision = revision_for(task, schema)
    history = MetaHistory()
    history.append(revision)
    view = snapshot(history, task, stamp("2022-12-31"))
    fitted = RidgeLearner(
        settings=RidgeSettings(min_matured_origins=1),
        runtime=NumericRuntime(native_policy="reference"),
    ).fit(schema, view, fit_completed_at=stamp("2023-01-01"))
    for record, properties in (
        (task.family, ("family_id",)),
        (task, ("task_id",)),
        (revision.panel, ("panel_id",)),
        (revision, ("content_digest", "training_rows")),
        (view, ("snapshot_id", "origin_count", "training_rows")),
        (fitted.model, ("model_id",)),
    ):
        before = canonical(record)
        for name in properties:
            assert getattr(record, name) is getattr(record, name)
        assert canonical(record) == before
        assert "_derived" not in {f.name for f in fields(record)}
        clone = replace(record)
        assert not hasattr(clone, "_derived")
        assert canonical(clone) == before
        for name in properties:
            assert getattr(clone, name) == getattr(record, name)
    assert revision.content_digest == digest(
        {"schema": "qms-revision-v1", "record": revision}
    )
    changed = replace(view, information_as_of=stamp("2023-12-31"))
    assert changed.snapshot_id != view.snapshot_id


def test_q7_t04_object_owned_memo_has_no_global_retention():
    task, schema = make_task()
    revision = revision_for(task, schema)
    for _ in range(30):
        assert len(revision.training_rows) == 3
        assert revision.revision_id
    assert set(revision._derived) == {"content_digest", "training_rows"}
    with pytest.raises(TypeError):
        revision._derived["training_rows"] = ()
    assert all(np.isfinite(row.origin_weight) for row in revision.training_rows)
    with pytest.raises((AttributeError, TypeError)):
        revision.outcomes = ()


@pytest.fixture(scope="module")
def native():
    from tools.build_qms07_candidate import OUTPUT, load

    paths = list(OUTPUT.glob("_quantbt_native*.so"))
    assert len(paths) == 1, (
        "run tools.build_qms07_candidate before native certification"
    )
    return load(paths[0])


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("tie_boundary", [False, True])
def test_q7_t01_full_chronological_membership_and_actual_decisions(
    native, resume, tie_boundary
):
    from tools.qms07_corpus import replay, compare_sequences

    expected = replay(
        NumericRuntime(native_policy="reference", work_cache=False),
        tie_boundary=tie_boundary,
    )
    actual = replay(
        NumericRuntime(native_policy="require", native_module=native),
        resume=resume,
        tie_boundary=tie_boundary,
    )
    compare_sequences(expected, actual)
    assert len(actual["decisions"]) == 6
    assert actual["retained_history"] == 8
    assert actual["decisions"][0]["reference_boundary_fallback"]
    assert actual["decisions"][0]["params"] != {"recipe": "anchor"}
    if tie_boundary:
        assert len(actual["decisions"][0]["ties"]) == 2


def test_q7_t03_late_revision_reweights_entire_origin(native):
    from tools.qms07_corpus import replay

    actual = replay(
        NumericRuntime(native_policy="require", native_module=native), resume=True
    )
    early, late = actual["decisions"][0], actual["decisions"][3]
    origin = early["fit_rows"][0][0]
    first = [row for row in early["fit_rows"] if row[0] == origin]
    revised = [row for row in late["fit_rows"] if row[0] == origin]
    assert len(first) == 3 and len(revised) == 2
    assert sum(row[3] for row in first) == sum(row[3] for row in revised) == 1
    assert first[0][1] != revised[0][1]


def test_q7_t02_perturbed_floor_recomputes_whole_pool(native, monkeypatch):
    from tests.meta_selection.test_qms04_ridge import policy_fixture
    from quantbt.optimization.meta_selection.selection import MetaSelector

    schema, view, reference_fit, task = policy_fixture()
    runtime = NumericRuntime(native_policy="require", native_module=native)
    fitted = RidgeLearner(
        settings=replace(reference_fit.model.settings, epsilon=0.3),
        runtime=runtime,
    ).fit(schema, view, fit_completed_at=reference_fit.model.fit_completed_at)
    original = runtime.rank

    def disturbed(*args, **kwargs):
        y, q = original(*args, **kwargs)
        y[1] += 1e-12
        q[1] -= 1e-12
        return y, q

    monkeypatch.setattr(runtime, "rank", disturbed)
    decision = MetaSelector(runtime=runtime).propose(task, fitted, full_ranking=True)
    expected = MetaSelector(runtime=NumericRuntime(native_policy="reference")).propose(
        task,
        fitted,
        full_ranking=True,
    )
    assert (
        decision.numeric["fallback_reason"] == "WHOLE_REFERENCE_FIT_AND_RANK_BOUNDARY"
    )
    assert decision.tie_set == expected.tie_set
    assert decision.ranked_ids == expected.ranked_ids
    assert decision.proposed_params == expected.proposed_params
    assert decision.predictions == expected.predictions


@pytest.mark.parametrize("changed", ["context", "v", "y", "weights", "lambda"])
def test_q7_t03_exact_fit_cache_identity_and_independent_outputs(native, changed):
    runtime = NumericRuntime(native_policy="require", native_module=native)
    v, y, w = np.arange(18.0).reshape(6, 3) / 10, np.arange(6.0), np.full(6, 1 / 6)
    first = runtime.fit(v, y, w, 10.0, cache_identity=("snapshot", "basis", "policy"))
    cached = runtime.fit(v, y, w, 10.0, cache_identity=("snapshot", "basis", "policy"))
    assert runtime.work_cache.hits == 1
    for x, z in zip(first, cached, strict=True):
        np.testing.assert_array_equal(x, z)
    cached[2][:] = 900
    untouched = runtime.fit(
        v, y, w, 10.0, cache_identity=("snapshot", "basis", "policy")
    )
    np.testing.assert_array_equal(untouched[2], first[2])
    if changed == "v":
        v[0, 0] += 0.01
    if changed == "y":
        y[0] += 0.01
    if changed == "weights":
        w[0] += 0.01
    identity = (
        ("other-snapshot", "basis", "policy")
        if changed == "context"
        else ("snapshot", "basis", "policy")
    )
    before = runtime.calls
    runtime.fit(v, y, w, 11.0 if changed == "lambda" else 10.0, cache_identity=identity)
    assert runtime.calls == before + 1
    runtime.work_cache.clear()
    assert runtime.work_cache.retained_bytes == 0


@pytest.mark.parametrize(
    "changed", ["model", "task", "pool_order", "v", "beta", "delta"]
)
def test_q7_t03_prediction_cache_covers_full_pool_and_model(native, changed):
    runtime = NumericRuntime(native_policy="require", native_module=native)
    v, beta, delta = np.ones((7, 3)), np.arange(3.0), np.arange(7.0)
    context = ("model", "task", tuple(range(7)))
    runtime.rank(v, beta, delta, cache_identity=context)
    runtime.rank(v, beta, delta, cache_identity=context)
    assert runtime.work_cache.hits == 1
    if changed == "v":
        v[0, 0] += 0.01
    if changed == "beta":
        beta[0] += 0.01
    if changed == "delta":
        delta[0] += 0.01
    if changed == "model":
        context = ("new-model", "task", tuple(range(7)))
    if changed == "task":
        context = ("model", "new-task", tuple(range(7)))
    if changed == "pool_order":
        context = ("model", "task", tuple(reversed(range(7))))
    before = runtime.calls
    runtime.rank(v, beta, delta, cache_identity=context)
    assert runtime.calls == before + 1


def test_q7_t04_workspace_bypass_not_information_truncation(monkeypatch):
    from quantbt.optimization.meta_selection.numerics import NumericLimits
    from quantbt.optimization.meta_selection.common import MetaRecordError

    runtime = NumericRuntime(
        native_policy="reference", limits=NumericLimits(max_workspace_bytes=8000)
    )
    monkeypatch.setattr(np, "diag", lambda *a: pytest.fail("NxN weights forbidden"))
    monkeypatch.setattr(np.linalg, "inv", lambda *a: pytest.fail("inverse forbidden"))
    runtime.fit(np.ones((20, 3)), np.ones(20), np.ones(20), 10, cache_identity="full")
    assert runtime.work_cache.retained_bytes <= 1000
    with pytest.raises(MetaRecordError, match="RESOURCE_LIMIT"):
        runtime.fit(np.ones((1000, 30)), np.ones(1000), np.ones(1000), 10)


def test_q7_t05_actual_native_resolution_and_required_capability(native):
    from quantbt.optimization.meta_selection.common import MetaRecordError

    runtime = NumericRuntime(native_policy="require", native_module=native)
    assert runtime.metadata["selected_backend_by_block"]["gram_solve"] == "rust"
    assert runtime.native_identity["descriptor"]["owned_inputs"]
    assert runtime.metadata["qualification_calls"] == 3
    assert runtime.metadata["fast_math"] is False
    fallback = NumericRuntime(native_module=object())
    assert fallback.metadata["selected_backend_by_block"]["rank"] == "numpy"
    assert "UNAVAILABLE_OR_UNQUALIFIED" in fallback.reason
    with pytest.raises(MetaRecordError):
        NumericRuntime(native_policy="require", native_module=object())


def test_q7_t05_native_batch_releases_gil_and_detaches_outputs(native):
    import threading
    from time import perf_counter, sleep

    v = np.ones((131072, 24), dtype=np.float64)
    y = np.ones(len(v), dtype=np.float64)
    w = np.full(len(v), 1 / len(v), dtype=np.float64)
    go, stop, ready = threading.Event(), threading.Event(), threading.Event()
    ticks = []

    def witness():
        ready.set()
        go.wait()
        while not stop.is_set():
            if len(ticks) < 2000:
                ticks.append(perf_counter())
            sleep(0.0005)

    thread = threading.Thread(target=witness)
    thread.start()
    ready.wait()
    go.set()
    started = perf_counter()
    try:
        gram, b, beta = native.qms_fit_v1(v, y, w, 10.0)
        completed = perf_counter()
    finally:
        stop.set()
        thread.join()
    assert any(started + 0.001 < t < completed - 0.001 for t in ticks)
    before = gram.copy()
    v[0, 0] = 900
    np.testing.assert_array_equal(gram, before)
    assert not np.shares_memory(gram, v)
    assert np.isfinite(b).all() and np.isfinite(beta).all()


@pytest.mark.parametrize("n,d", [(180, 8), (4096, 8), (4096, 24), (512, 64)])
def test_q7_t07_identical_numeric_information_and_precision(native, n, d):
    rng = np.random.default_rng(731)
    v, y, w = rng.normal(size=(n, d)), rng.normal(size=n), rng.uniform(0.1, 1, size=n)
    runtime = NumericRuntime(native_policy="require", native_module=native)
    expected = NumericRuntime(native_policy="reference").fit(v, y, w, 10)
    actual = runtime.fit(v, y, w, 10)
    for x, z in zip(actual, expected, strict=True):
        assert x.dtype == np.dtype("float64")
        np.testing.assert_allclose(x, z, rtol=1e-9, atol=1e-10)
    assert runtime.copied_bytes == v.nbytes + y.nbytes + w.nbytes


def test_q7_t06_observer_rng_does_not_change_sequential_main_lane():
    import random
    from quantbt.optimization.meta_selection.runtime import isolated_observer_rng

    rng = np.random.get_state()
    python_rng = random.getstate()
    with isolated_observer_rng(731):
        np.random.normal(size=100)
        random.random()
    restored = np.random.get_state()
    assert rng[0] == restored[0]
    np.testing.assert_array_equal(rng[1], restored[1])
    assert rng[2:] == restored[2:]
    assert python_rng == random.getstate()


def measured_evidence():
    import json
    from tools.qms07_performance import DIRECTORY

    return json.loads((DIRECTORY / "qms07_performance_evidence.json").read_text())


def test_q7_t06_actual_public_sequential_trace_is_entry_exact():
    from tools.qms07_performance import compare_public

    evidence = measured_evidence()
    for arm in evidence["arms"].values():
        for a, b in zip(
            arm["samples"]["entry"], arm["samples"]["current"], strict=True
        ):
            compare_public(a, b)
            assert a["trial_rows"] == b["trial_rows"] == 36


def test_q7_t04_actual_rss_pss_plateau_and_bounded_retention():
    evidence = measured_evidence()
    plateau = evidence["memory_plateau"]["plateau"]
    assert len(plateau) == 20
    assert all(r["retained_cache_bytes"] <= 8_000_000 for r in plateau)
    # Registered fixed N=4096,d=24,P=600 workspace lane, after first allocation.
    for field in ("rss_mib", "pss_mib"):
        assert (
            max(r[field] for r in plateau[5:]) - min(r[field] for r in plateau[5:]) <= 8
        )


def test_q7_t08_disabled_gate_is_measured_not_owner_approval():
    evidence = measured_evidence()
    gate = evidence["disabled_gate"]
    assert gate["owner_accepted"] is False
    assert gate["status"] == "MEASURED_OWNER_BUDGET_PENDING"
    arm = evidence["arms"]["disabled"]
    assert len(arm["samples"]["entry"]) == len(arm["samples"]["current"]) == 8
    expected = (
        arm["relative_change"]["p50_seconds"] <= 0.03
        and arm["relative_change"]["p95_seconds"] <= 0.05
    )
    assert gate["working_targets_pass"] is expected
    assert all(
        row["evidence"]["observer_attempts"] == 0
        for rows in arm["samples"].values()
        for row in rows
    )


def test_q7_t07_protected_financial_source_and_published_pair_unchanged():
    import subprocess
    import json
    import sys
    from tools.qms07_performance import ROOT, ENTRY

    changed = subprocess.check_output(
        ["git", "diff", ENTRY, "559b4d1", "--name-only", "--", "src/quantbt", "rust"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    assert all(
        p.startswith("src/quantbt/optimization/meta_selection/")
        or p == "rust/native_event/src/qms_numeric.rs"
        for p in changed
    )
    # Later owner-approved adapter changes do not rewrite the sealed QMS-07
    # receipt. R03 authorizes packaging only, independently byte-validated.
    current = subprocess.check_output(
        ["git", "diff", "6c0f877", "--name-only", "--", "src/quantbt", "rust"],
        cwd=ROOT, text=True,
    ).splitlines()
    from tools.qms_release_source_guard import PACKAGING_FILES, without_release_identity
    from tools.qms_c02_source_guard import ALLOW, verify
    verify()
    for name in set(current) & PACKAGING_FILES:
        without_release_identity((ROOT / name).read_bytes(), name)
    assert all(p.startswith("src/quantbt/optimization/meta_selection/") or p in PACKAGING_FILES or p in ALLOW or p in {
        "src/quantbt/endpoint.py", "src/quantbt/walkforward.py",
        "src/quantbt/backends/reactive_wfo.py", "src/quantbt/backends/reactive_wfo_support.py",
        "src/quantbt/backends/native_event.py", "src/quantbt/backends/_native_event_rust.py",
    } for p in current)
    from tools.qms08_package import declared_pair
    versions = json.loads(subprocess.check_output(
        [sys.executable, "-I", "-c", "import importlib.metadata as m,json;print(json.dumps([m.version('quantbt-engine'),m.version('quantbt-native')]))"],
        cwd="/tmp", text=True))
    assert tuple(versions) == declared_pair()
