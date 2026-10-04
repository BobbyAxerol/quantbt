"""Q8 software expectations; real-alpha/remote/owner acceptance stays explicit."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.model import RidgeLearner
from quantbt.optimization.meta_selection.selection import MetaSelector
from tools.qms01_baseline import endpoint, market, example_strategy, ROUTES
from tools.qms08_gate import (
    ROOT,
    GATES,
    TEST_IDS,
    test_coverage as coverage,
    verify_pair,
)
from tools.qms08_research import empirical_disposition, paired_decomposition


@pytest.mark.parametrize("mode,schedule", ROUTES)
def test_q8_t01_fixed_params_and_explicit_off_legacy_parity(mode, schedule):
    base = endpoint(mode, schedule, retention="none")
    old = base.config.walkforward_config
    new = QuantBTEndpoint(
        replace(
            base.config, walkforward_config=replace(old, meta_selection={"mode": "off"})
        )
    )
    arguments = {"params": {"window": 11}}
    if schedule != "global":
        # Existing per-fold schedules deliberately reject one fixed dictionary.
        for bt in (base, new):
            with pytest.raises(ValueError, match="require param_ranges"):
                bt.backtest(data=market(), **arguments)
        arguments = {"param_ranges": {"window": (3, 31, 2)}}
    a = base.backtest(data=market(), **arguments)
    b = new.backtest(data=market(), **arguments)
    pd.testing.assert_series_equal(a.equity, b.equity, check_exact=True)
    pd.testing.assert_frame_equal(a.positions, b.positions, check_exact=True)
    assert (
        a.metadata["walk_forward"]["params_by_fold"]
        == b.metadata["walk_forward"]["params_by_fold"]
    )
    assert "meta_selection" not in b.metadata["walk_forward"]
    json.dumps(b.full_report(trading_days=365), default=str)


def test_q8_t01_train_test_holdout_off_and_fixed_account_controls():
    config = dict(
        strategy_class=example_strategy(),
        test_start="2021-01-01",
        optimization_mode="mode_4_is_only_robust",
        optuna_trials=4,
        random_seed=731,
        target_mode="signal_notional",
        target_runtime="numba",
        initial_capital=20000,
        alloc_per_trade=1000,
        leverage=3,
        fee_rate=0.0005,
        use_funding=False,
    )
    a = QuantBTEndpoint.train_test_split(**config)
    b = QuantBTEndpoint.train_test_split(
        **config, optimization_config={"meta_selection": {"mode": "off"}}
    )
    ar = a.backtest(data=market(), param_ranges={"window": (3, 31, 2)})
    br = b.backtest(data=market(), param_ranges={"window": (3, 31, 2)})
    pd.testing.assert_series_equal(ar.equity, br.equity, check_exact=True)
    assert (
        ar.metadata["walk_forward"]["params"] == br.metadata["walk_forward"]["params"]
    )
    bt = QuantBTEndpoint(a.engine.scorer.score_config)
    expected = bt.backtest(
        data=market(), signal=ar.metadata["walk_forward_result"].oos_output
    )
    pd.testing.assert_series_equal(expected.equity, ar.equity)


@pytest.mark.parametrize("case", ["off", "sampler", "history", "unsupported"])
def test_q8_t02_runnable_complete_contract_examples(case):
    from examples.wfo_meta_contract import run_case

    result = run_case(case)
    assert result["case"] == case
    if case == "history":
        assert result["reviewed_origins"] > 0 and result["current_oos_used"] is False
        assert result["live_trading_authorized"] is False


def test_q8_t03_real_alpha_not_claimed_from_engineering_lineage():
    disposition = empirical_disposition()
    assert disposition["status"] == "EMPIRICAL_VALIDATION_NOT_RUN"
    assert disposition["market_gain"] is None
    assert (
        disposition["attempted_trials"] == disposition["paired_valid_locked_folds"] == 0
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempted_trials_per_cutoff", 127),
        ("matured_origins", 11),
        ("locked_folds", 11),
        ("samplers", ["a", "b", "c"]),
        ("owner_decision_ref", ""),
        ("development_folds", -1),
        ("development_folds", 11),
        ("matured_origins", True),
        ("locked_folds", 12.0),
        ("samplers", ["sobol", "sobol"]),
        ("alpha_identity", " "),
    ],
)
def test_q8_t04_empirical_budget_support_not_fabricated(field, value):
    registration = dict(
        data_digest="declared-not-executed",
        alpha_identity="BTC-cell",
        samplers=["tpe_legacy"],
        attempted_trials_per_cutoff=128,
        matured_origins=12,
        development_folds=0,
        locked_folds=12,
        owner_decision_ref="unit-fixture-only",
    )
    assert empirical_disposition(registration)["status"] == "REGISTERED_NOT_EXECUTED"
    registration[field] = value
    with pytest.raises(ValueError):
        empirical_disposition(registration)


@pytest.mark.parametrize(
    "field,value", [("start", "not-a-date"), ("end", "2019-12-31"), ("fold_id", True)]
)
def test_q8_t05_invalid_calendar_and_identity_fail_closed(field, value):
    raw = pair()
    raw[field] = value
    with pytest.raises(ValueError):
        paired_decomposition([raw])


def pair(fold=1, native=(3, 1), meta=(2, 1)):
    return dict(
        fold_id=fold,
        start="2020-01-01",
        end="2020-03-31",
        native=dict(status="VALID", is_sharpe=native[0], forward_sharpe=native[1]),
        meta=dict(status="VALID", is_sharpe=meta[0], forward_sharpe=meta[1]),
    )


def test_q8_t05_lower_is_does_not_imply_forward_improvement():
    r = paired_decomposition([pair()])
    assert r["rows"][0]["r"] == 1 and r["rows"][0]["q"] == 0
    assert r["rows"][0]["is_difference"] == 1
    negative = paired_decomposition([pair(native=(3, 1), meta=(2, -1))])
    assert negative["mean_fold_r"] == -1 and negative["mean_fold_q"] == -2
    assert negative["edge_certified"] is False
    zero = paired_decomposition([pair(native=(0, 0), meta=(0, 0))])
    assert zero["paired_valid_folds"] == 1 and zero["mean_fold_r"] == 0


@pytest.mark.parametrize(
    "status", ["NO_TRADES", "ZERO_VARIANCE", "UNDEFINED", "FAILED"]
)
def test_q8_t05_undefined_calendar_and_negative_outcomes_preserved(status):
    invalid = pair(fold=2)
    invalid["meta"] = dict(status=status, is_sharpe=None, forward_sharpe=None)
    r = paired_decomposition([pair(), invalid])
    assert r["calendar_folds"] == 2 and r["paired_valid_folds"] == 1
    assert r["rows"][1]["fold_id"] == 2 and r["rows"][1]["r"] is None
    assert r["continuous_account_sharpe"] is None
    invalid["meta"]["forward_sharpe"] = 0
    with pytest.raises(ValueError):
        paired_decomposition([invalid])


@pytest.mark.parametrize("mutation", ["missing", "failure", "error", "skip", "count"])
def test_q8_t06_required_64_ids_and_logs_fail_closed(tmp_path, mutation):
    import xml.etree.ElementTree as ET

    root = ET.Element("testsuite", tests="64", failures="0", errors="0", skipped="0")
    for test in TEST_IDS:
        ET.SubElement(
            root, "testcase", name="test_" + test.lower().replace("-", "_") + "_example"
        )
    path = tmp_path / "receipt.xml"
    ET.ElementTree(root).write(path)
    assert len(coverage(path)["members"]) == 64
    if mutation == "missing":
        root.remove(root[-1])
        root.set("tests", "63")
    elif mutation == "count":
        root.set("tests", "65")
    else:
        ET.SubElement(root[0], {"skip": "skipped"}.get(mutation, mutation))
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError):
        coverage(path)
    assert len(GATES) == 6


def test_q8_t07_actual_candidate_wheel_sdist_consumers():
    # CI has one actual installed lane per matrix job. Local qualification
    # requires all three; a provided reference is verified, never a skip/mock.
    supplied = os.environ.get("QMS08_PACKAGE_PROOF")
    proofs = (
        [Path(supplied)]
        if supplied
        else sorted((ROOT / ".maturin/qms08/qualified").glob("cp*/proof.json"))
    )
    assert len(proofs) == (1 if supplied else 3), (
        "Build the QMS08 isolated installed interpreter lanes first"
    )
    for path in proofs:
        proof = json.loads(path.read_text())
        assert verify_pair(proof)
        guard = subprocess.run(
            [
                str(path.parent / "core_off/bin/python"),
                "-I",
                "-c",
                """
import importlib.util
from quantbt.optimization.config import SamplerConfig
from quantbt.optimization.samplers import build_sampler
assert importlib.util.find_spec('optuna') is None
try:
    build_sampler(SamplerConfig(name='tpe_legacy'), seed=731,
                  search_space={'window': (3, 31, 2)}, objective_count=1)
except ImportError as error:
    assert str(error) == 'QuantBT optimization requires optuna'
    print(str(error))
else:
    raise AssertionError('missing Optuna did not fail clearly')
""",
            ],
            cwd=path.parent,
            capture_output=True,
            text=True,
        )
        assert guard.returncode == 0, guard.stderr
        assert guard.stdout.strip() == "QuantBT optimization requires optuna"
        damaged = deepcopy(proof)
        damaged["consumers"]["pair"]["actual_meta_folds"] = 0
        with pytest.raises(ValueError):
            verify_pair(damaged)
        damaged = deepcopy(proof)
        damaged["release_authorized"] = "false"
        with pytest.raises(ValueError):
            verify_pair(damaged)
        damaged = deepcopy(proof)
        damaged["consumers"]["pair"]["fixed_account_rows"] += 1
        with pytest.raises(ValueError, match="scalar/metadata"):
            verify_pair(damaged)


@pytest.fixture(scope="module")
def verifier_fixture(tmp_path_factory):
    import xml.etree.ElementTree as ET
    from tools.qms08_gate import collect_evidence, gather_checks

    gather_checks()
    root = ET.Element("testsuite", tests="64", failures="0", errors="0", skipped="0")
    # Synthetic XML only exercises verifier rejection; it is never a gate receipt.
    for test in TEST_IDS:
        ET.SubElement(
            root, "testcase", name="test_" + test.lower().replace("-", "_") + "_fixture"
        )
    path = tmp_path_factory.mktemp("qms08-verifier") / "fixture.xml"
    ET.ElementTree(root).write(path)
    return collect_evidence(), path


@pytest.mark.parametrize(
    "mutation",
    [
        "gates",
        "ids",
        "source",
        "empirical",
        "scalar",
        "complete",
        "owner",
        "release",
        "checks",
        "check_log",
        "entry",
        "history",
    ],
)
def test_q8_t06_envelope_claim_and_execution_log_tamper_rejected(
    verifier_fixture, mutation
):
    from tools.qms08_gate import validate

    original, path = verifier_fixture
    damaged = deepcopy(original)
    if mutation == "gates":
        damaged["required_gates"] = []
    elif mutation == "ids":
        damaged["required_test_ids"] = []
    elif mutation == "source":
        damaged["source_hashes"].clear()
    elif mutation == "empirical":
        damaged["empirical"]["attempted_trials"] = 128
    elif mutation == "scalar":
        damaged["paired_report"]["mean_fold_r"] = 1
    elif mutation == "complete":
        damaged["complete_scientific_study"] = True
    elif mutation == "owner":
        damaged["owner_review"] = "APPROVED"
    elif mutation == "release":
        damaged["release_authorized"] = "false"
    elif mutation == "checks":
        damaged["source_checks"].clear()
    elif mutation == "entry":
        damaged["entry"] = "not-the-approved-entry"
    elif mutation == "history":
        damaged["historical_artifacts"].clear()
    else:
        next(iter(damaged["source_checks"].values()))["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate(damaged, path)


@pytest.mark.parametrize("workflow", ["ci.yml", "publish.yml", "native-release.yml"])
def test_q8_t07_existing_test_jobs_prepare_isolated_qms_fixtures(workflow):
    import yaml

    path = ROOT / ".github/workflows" / workflow
    jobs = yaml.safe_load(path.read_text())["jobs"]
    steps = next(
        job["steps"]
        for job in jobs.values()
        if any(
            "run_test_shards.py" in step.get("run", "") for step in job.get("steps", [])
        )
    )
    fixture = next(
        i
        for i, step in enumerate(steps)
        if step.get("uses") == "./.github/actions/qms-fixtures"
    )
    regression = next(
        i for i, step in enumerate(steps) if "run_test_shards.py" in step.get("run", "")
    )
    assert fixture < regression
    action = yaml.safe_load(
        (ROOT / ".github/actions/qms-fixtures/action.yml").read_text()
    )
    commands = action["runs"]["steps"][0]["run"]
    assert "build_qms04_candidate" in commands and "build_qms06_candidate" in commands
    assert "build_qms07_candidate" in commands and "tools.qms08_package" in commands
    assert "GITHUB_ENV" in commands and "publish" not in commands


def test_q8_t07_remote_candidate_matrix_is_non_publishing():
    import yaml

    path = ROOT / ".github/workflows/qms-candidate.yml"
    workflow = yaml.safe_load(path.read_text())
    assert workflow["permissions"] == {"contents": "read"}
    matrix = workflow["jobs"]["installed-candidate"]["strategy"]["matrix"]
    assert matrix == {
        "runner": ["ubuntu-22.04", "ubuntu-24.04"],
        "python": ["3.11", "3.12", "3.13"],
    }
    assert "pypi-publish" not in path.read_text() and "id-token" not in path.read_text()


def test_q8_t08_report_regeneration_never_executes_or_infers(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("report regeneration executed/inferred")

    monkeypatch.setattr(QuantBTEndpoint, "backtest", forbidden)
    monkeypatch.setattr(RidgeLearner, "fit", forbidden)
    monkeypatch.setattr(MetaSelector, "propose", forbidden)
    raw = [pair(), pair(fold=2, native=(3, 1), meta=(2, -1))]
    saved = json.dumps(paired_decomposition(raw), allow_nan=False)
    assert json.loads(saved) == paired_decomposition(raw)
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            "559b4d1",
            "--name-only",
            "--",
            "src",
            "rust",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=ROOT,
        text=True,
    )
    assert not changed.strip()
    assert empirical_disposition()["live_certified"] is False
