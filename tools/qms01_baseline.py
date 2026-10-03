"""Discovery-only QMS-01 evidence. No sampler, selector or financial changes.

Run with the repository's editable environment. Spies delegate every call and
are restored on exit; timing samples run without spies. The public SMA example
is loaded without executing its example account or printing metrics.
"""

from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import re
import subprocess
import sys
from time import perf_counter, process_time
from unittest.mock import patch
import os
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
import quantbt.walkforward as wfo
from quantbt.endpoint import _WalkForwardEndpointScorer

RELEASE = "v1.1.1"
RELEASE_SHA = "2c811a7faaed3c274e93c60650e16207949f0a59"
GUIDE = "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
GUIDE_SHA = "adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d"
DIRECTORY = ROOT / "benchmarks/optimization/meta_selection"
MANIFEST = DIRECTORY / "legacy_baseline_manifest.json"
RECEIPT = DIRECTORY / "qms01_gate_receipt.json"
REQUIRED_TESTS = tuple(f"Q1-T{number:02d}" for number in range(1, 9))
REQUIRED_GATES = ("G1-SOURCE", "G1-SEAMS", "G1-BASELINE", "G1-SCOPE", "G1-OWNER")
BUDGET = {
    "bars": 547, "trials_per_study": 6, "seed": 731, "is_subperiods": 3,
    "sbb_samples": 8, "workers": 1, "timing_repeats": 3,
    "early_stopping": None, "execution_reuse": "off",
    "economic_trials_per_cutoff": 128, "economic_matured_origins": 12,
    "economic_paired_folds": 12,
    "disabled_overhead_proposed_p50_pct": 3, "disabled_overhead_proposed_p95_pct": 5,
}
ROUTES = (
    ("mode_1_decay", "global"),
    ("mode_1_decay", "per_fold_decay"),
    ("mode_1_decay", "per_fold_causal"),
    ("mode_2_sbb", "global"),
    ("mode_3_flat_minima", "global"),
    ("mode_4_is_only_robust", "global"),
    ("mode_4_is_only_robust", "per_fold_causal"),
    ("mode_5_full_robust", "global"),
)
SYMBOLS = {
    "src/quantbt/endpoint.py": (
        "EndpointConfig", "_walkforward_scoring_config",
        "QuantBTEndpoint.walk_forward", "QuantBTEndpoint.train_test_split",
        "QuantBTEndpoint.backtest", "QuantBTEndpoint._run_walk_forward",
        "_WalkForwardEndpointScorer", "_make_walkforward_endpoint_scorer",
    ),
    "src/quantbt/walkforward.py": (
        "WalkForwardConfig", "WalkForwardEngine.run",
        "WalkForwardEngine._run_per_fold_schedule", "WalkForwardEngine.optimize_params",
        "WalkForwardEngine._capture_research_records", "WalkForwardEngine._compact_trial_records",
        "WalkForwardEngine.evaluate_params_is", "WalkForwardEngine.evaluate_params",
        "WalkForwardEngine._call_strategy_for_indices", "WalkForwardEngine._score_strategy_outputs_batch",
        "select_is_only_robust_record", "_select_is_candidate_records", "_without_fold_metrics",
    ),
    "src/quantbt/backends/native_wfo_public.py": ("NativePreparedPublicWfoScorerV1",),
    "src/quantbt/backends/native_prepared_evaluation.py": ("NativePreparedEvaluationRuntimeV1",),
    "src/quantbt/strategies/wfo_prepared.py": ("PreparedWfoStrategyAdapterV1", "prepare_public_wfo_strategy"),
    "src/quantbt/core/results.py": ("BacktestScalarScoreResult",),
    "src/quantbt/optimization/space.py": ("suggest_parameter", "search_space_info"),
    "src/quantbt/backends/reactive_wfo.py": ("ReactivePreparedWfoRuntimeV1._select",),
    "src/quantbt/optimization/samplers.py": ("build_sampler",),
    "src/quantbt/optimization/optimizer.py": ("_apply_baseline_floor",),
    "src/quantbt/metrics/performance.py": ("sharpe", "_returns_for_stats", "_annualization_periods", "number_of_trades"),
    "src/quantbt/core/types.py": ("BacktestResult.daily_equity", "BacktestResult.daily_returns"),
    "examples/walk_forward_train_test.py": ("strategy",),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def safe(value):
    """Keep undefined values explicit; JSON never silently coerces them to 0."""
    if isinstance(value, pd.DataFrame):
        return safe(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return {"index": safe(value.index.tolist()), "values": safe(value.tolist())}
    if isinstance(value, np.ndarray):
        return safe(value.tolist())
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return "NaN" if np.isnan(value) else ("+Inf" if value > 0 else "-Inf")
    return value


def protected_sources() -> dict[str, str]:
    names = git("ls-files", "-z", "src", "rust", "pyproject.toml", "uv.lock", "poetry.lock", GUIDE)
    return {name: digest((ROOT / name).read_bytes()) for name in names.decode().split("\0") if name}


def symbol_map() -> list[dict]:
    entries = []
    for name, required in SYMBOLS.items():
        source = (ROOT / name).read_bytes()
        lines = source.splitlines(keepends=True)
        found = {}

        def walk(node, prefix=""):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = prefix + child.name
                    found[qualified] = child
                    walk(child, qualified + ".")

        walk(ast.parse(source))
        for qualified in required:
            node = found[qualified]
            start = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
            entries.append({
                "file": name, "symbol": qualified, "start": start, "end": node.end_lineno,
                "sha256": digest(b"".join(lines[start - 1:node.end_lineno])),
                "file_sha256": digest(source),
            })
    return entries


def source_identity() -> dict:
    # -I proves editable origins without PYTHONPATH or the current directory.
    code = """
import importlib.metadata as m, json, quantbt, _quantbt_native as n
from pathlib import Path
import hashlib
native_dir = Path(n.__file__).parent
print(json.dumps({
 'versions': {p:m.version(p) for p in ['quantbt-engine','quantbt-native','optuna','numpy','pandas','numba']},
 'core_origin': quantbt.__file__, 'native_origin': n.__file__,
 'native_binaries': {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in native_dir.glob('*.so')},
 'native_exports': sorted(x for x in dir(n) if not x.startswith('_')),
 'api': n.api_version(), 'core_abi': n.core_abi_version(),
 'product_descriptor': n.product_descriptor(),
}))
"""
    installed = json.loads(subprocess.check_output([sys.executable, "-I", "-c", code], cwd="/tmp"))
    tracked = protected_sources()
    changed = git("diff", "--name-only", RELEASE, "--", "src", "rust", "pyproject.toml", "uv.lock").decode().splitlines()
    return {
        "repository_root": str(ROOT),
        "branch": git("branch", "--show-current").decode().strip(),
        "phase_entry_sha": git("rev-parse", "HEAD").decode().strip(),
        "release_tag": RELEASE, "release_sha": git("rev-parse", RELEASE + "^{commit}").decode().strip(),
        "protected_sources": tracked, "runtime_diff_from_release": changed,
        "entry_unrelated_dirty": [],
        "capture_git_status": git("status", "--porcelain=v1", "-uall").decode().splitlines(),
        "symbols": symbol_map(), "installed": installed,
    }


def validate_identity(identity: dict) -> None:
    installed = identity["installed"]
    expected_origin = (Path(identity["repository_root"]) / "src/quantbt/__init__.py").resolve()
    if Path(installed["core_origin"]).resolve() != expected_origin:
        raise ValueError("non-canonical QuantBT import origin")
    if identity["release_sha"] != RELEASE_SHA or identity["runtime_diff_from_release"]:
        raise ValueError("released source/tag mismatch")
    if installed["versions"]["quantbt-engine"] != "1.1.1" or installed["versions"]["quantbt-native"] != "0.4.2":
        raise ValueError("distribution version mismatch")
    descriptor = installed["product_descriptor"]
    if descriptor["core_package_version"] != "1.1.1" or descriptor["native_package_version"] != "0.4.2":
        raise ValueError("native descriptor mismatch")
    if installed["api"] != "0.4" or installed["core_abi"] != "0.5" or not installed["native_binaries"]:
        raise ValueError("native ABI/binary missing")
    if identity["protected_sources"][GUIDE] != GUIDE_SHA:
        raise ValueError("detailed guide changed")
    for name, expected in identity["protected_sources"].items():
        if digest((ROOT / name).read_bytes()) != expected:
            raise ValueError("protected source changed: " + name)


def market() -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=BUDGET["bars"], freq="1D", tz="UTC")
    t = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 0.025 * t + 3.0 * np.sin(t / 13.0) + np.cos(t / 5.0)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": 1000.0 + t}, index=index)


def example_strategy():
    name = "examples/walk_forward_train_test.py"
    tree = ast.parse((ROOT / name).read_text())
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "strategy")
    namespace = {"pd": pd}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / name), "exec"), namespace)
    return namespace["strategy"]


def endpoint(mode="mode_4_is_only_robust", schedule="per_fold_causal", *, native="off", centroid=False, retention="full_trial_ledger"):
    config = {
        "scoring_backend": "proxy" if mode == "mode_2_sbb" else "endpoint",
        "top_is_fraction": 0.5, "flat_eps": 1.0, "flat_min_samples": 1,
        "flat_selector": "centroid" if centroid else "medoid",
        "is_subperiods": BUDGET["is_subperiods"], "sbb_samples": BUDGET["sbb_samples"],
        "sbb_block_length": 12, "scoring_trading_days": 365,
        "min_trades_per_year": 100, "trade_penalty_factor": 0.5,
        "native_prepared_wfo": native, "native_prepared_wfo_workers": 1,
        "wfo_execution_reuse": "off", "compact_trial_ledger": True,
        "research_retention": retention, "profile_walkforward": True,
    }
    if mode == "mode_1_decay" and schedule == "per_fold_causal":
        config.update(inner_split_frequency="monthly", inner_window_mode="rolling", inner_train_window="60D", inner_min_folds=2)
    return QuantBTEndpoint.walk_forward(
        strategy_class=example_strategy(), split_mode="2021-01-01", split_frequency="quarterly",
        window_mode="rolling", train_window="180D", target_mode="signal_notional",
        optimization_mode=mode, optimization_schedule=schedule, optimization_config=config,
        optuna_trials=BUDGET["trials_per_study"], random_seed=BUDGET["seed"],
        optuna_early_stopping=None, initial_capital=20000.0, alloc_per_trade=1000.0,
        leverage=3.0, fee_rate=0.0005, use_funding=False, target_runtime="rust" if native != "off" else "numba",
    )


def record_payload(record) -> dict:
    return safe(asdict(record))


def trace_run(data=None, *, mode="mode_4_is_only_robust", schedule="per_fold_causal", native="off", centroid=False, retention="full_trial_ledger"):
    data = market() if data is None else data
    engine = wfo.WalkForwardEngine
    original_select = wfo._select_is_candidate_records
    original_optimize = engine.optimize_params
    original_batch = engine._score_strategy_outputs_batch
    original_is = engine.evaluate_params_is
    events, pools, studies, batches = [], [], [], []
    owners, completed_runs = [], []
    original_run = engine.run
    original_endpoint_batch = _WalkForwardEndpointScorer.score_batch
    scorer_windows = []

    def run(self, *args, **kwargs):
        result = original_run(self, *args, **kwargs)
        completed_runs.append(result)
        return result

    def select(records, param_ranges, config):
        candidates = original_select(records, param_ranges, config)
        completed = [item for item in records if not item.pruned and np.isfinite(item.objective)]
        pools.append({"all_trials": [record_payload(item) for item in records],
                      "eligible_ids": [item.trial_id for item in completed],
                      "raw_best_trial_id": max(completed, key=lambda item: np.mean([row.get("is_sharpe_raw", item.mean_is_sharpe) for row in item.fold_metrics])).trial_id,
                      "objective_best_trial_id": max(completed, key=lambda item: item.objective).trial_id,
                      "native_anchor": record_payload(candidates[0]),
                      "filtered_candidate_ids": [item.trial_id for item in candidates]})
        events.append({"event": "native_selection", "pool_number": len(pools) - 1})
        return candidates

    def optimize(self, *args, **kwargs):
        wall_started = datetime.now(timezone.utc).isoformat()
        result = original_optimize(self, *args, **kwargs)
        owners.append(self)
        fold = kwargs["folds"][0]
        exact_anchor = None
        if centroid and result[0].selection_metadata.get("requires_evaluation"):
            # Discovery-only auxiliary evaluation in the still-live lifetime.
            # It does not replace the native result or tell anything to Optuna.
            exact_anchor = original_is(self, data=kwargs["data"], folds=kwargs["folds"],
                                       params=dict(result[0].params), trial_id=-1)
        studies.append({"study_id": kwargs.get("study_id", 0), "cutoff": safe(fold.train_end),
                        "wall_search_started_at": wall_started,
                        "wall_search_completed_at": datetime.now(timezone.utc).isoformat(),
                        "fold_execution_cutoff": safe(fold.cutoff_timestamp),
                        "selected": record_payload(result[0]),
                        "diagnostic_anchor_replay": None if exact_anchor is None else record_payload(exact_anchor),
                        "compact_trials": [record_payload(item) for item in result[1]],
                        "compact_candidates": [record_payload(item) for item in result[2]]})
        events.append({"event": "optimize_return_before_params_by_fold", "study_id": kwargs.get("study_id", 0)})
        return result

    def endpoint_batch(self, tasks):
        for task in tasks:
            scorer_windows.append({"context": task["context"], "fold_id": task["fold"].fold_id,
                                   "visible_data_end": safe(task["data"].index[-1]),
                                   "requested_end": safe(task["index"][-1])})
        return original_endpoint_batch(self, tasks)

    def batch(self, data, tasks):
        metrics = original_batch(self, data, tasks)
        for task, metric in zip(tasks, metrics, strict=True):
            _output, index, fold, params, context = task
            batches.append({"context": context, "fold_id": fold.fold_id, "params": dict(params),
                            "start": safe(index[0]), "end": safe(index[-1]), "bars": len(index), "metrics": safe(metric)})
            events.append({"event": "score", "context": context, "fold_id": fold.fold_id})
        return metrics

    def score_is(self, *args, **kwargs):
        result = original_is(self, *args, **kwargs)
        events.append({"event": "is_record", "trial_id": result.trial_id})
        return result

    with ExitStack() as stack:
        for obj, name, replacement in (
            (wfo, "_select_is_candidate_records", select), (engine, "optimize_params", optimize),
            (engine, "_score_strategy_outputs_batch", batch), (engine, "evaluate_params_is", score_is),
            (engine, "run", run),
            (_WalkForwardEndpointScorer, "score_batch", endpoint_batch),
        ):
            stack.enter_context(patch.object(obj, name, replacement))
        bt = endpoint(mode, schedule, native=native, centroid=centroid, retention=retention)
        result = bt.backtest(data=data, symbols=["BTC"], param_ranges={"window": (3, 31, 2)})

    wf = result.metadata["walk_forward"]
    summary = safe({key: wf.get(key) for key in (
        "params", "params_by_fold", "best_trial", "fold_table", "fold_selection_table",
        "trial_table", "candidate_table", "n_folds", "n_studies", "n_optuna_trial_rows",
        "validation_claim", "causality_claim", "oos_used_for_selection", "fold_account_policy",
        "account_execution", "native_prepared_wfo", "prepared_scoring_cache", "performance_profile",
    )})
    payload = {"mode": mode, "schedule": schedule, "summary": summary, "pools": pools,
               "studies": studies, "score_tasks": batches, "events": events,
               "scorer_windows": scorer_windows,
               "equity": safe(result.equity), "positions": safe(result.positions.to_dict(orient="list")),
               "stitched_signal": safe(completed_runs[-1].oos_output),
               "report": safe(result.full_report(scope="full", trading_days=365)),
               "account_contract": safe(asdict(bt.config.account)),
               "canonical_one_way_fee_rate": bt.config.v2_fee_rate,
               "retention": retention}
    return payload, result, owners[-1] if owners else None


def anchor_fixture(selector="medoid"):
    # A spike at x=9 loses to the dense 2/3/4 IS plateau. No mock selector.
    records = [wfo.WalkForwardTrialRecord(
        trial_id=i, params={"x": x}, objective=score, mean_is_sharpe=score,
        mean_oos_sharpe=0.0, mean_decay=0.0, std_decay=0.0,
        fold_metrics=[{"is_sharpe_raw": score, "oos_evaluated": False}],
        selection_metadata={"temporal_score": score, "temporal_q25": score},
    ) for i, (x, score) in enumerate(((9, 10.0), (2, 8.0), (3, 8.1), (4, 8.2)))]
    config = wfo.WalkForwardConfig(
        optimization_mode="mode_4_is_only_robust", top_is_fraction=1.0,
        flat_eps=0.25, flat_min_samples=2, flat_selector=selector,
    )
    selected = wfo.select_is_only_robust_record(records, {"x": (0, 10, 1)}, config)
    return records, selected, config


def resource_snapshot() -> dict:
    rss = {"peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0}
    for filename, key, prefix in (("/proc/self/status", "rss_mib", "VmRSS:"),
                                  ("/proc/self/smaps_rollup", "pss_mib", "Pss:")):
        path = Path(filename)
        if path.exists():
            line = next(line for line in path.read_text().splitlines() if line.startswith(prefix))
            rss[key] = float(line.split()[1]) / 1024.0
    return rss


def build_manifest() -> dict:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    identity = source_identity()
    validate_identity(identity)
    data = market()
    lanes = []
    for mode, schedule in ROUTES:
        payload, result, _engine = trace_run(data, mode=mode, schedule=schedule)
        lanes.append(payload)
    native_payload, _result, _engine = trace_run(data, native="require")
    measurements = []
    for repeat in range(BUDGET["timing_repeats"] + 1):
        bt = endpoint(retention="none")
        before = resource_snapshot()
        wall, cpu = perf_counter(), process_time()
        measured = bt.backtest(data=data, symbols=["BTC"], param_ranges={"window": (3, 31, 2)})
        measurements.append({"repeat": repeat, "warmup": repeat == 0,
                             "wall_seconds": perf_counter() - wall, "cpu_seconds": process_time() - cpu,
                             "before": before, "after": resource_snapshot(),
                             "equity_sha256": digest(measured.equity.to_numpy(dtype="<f8").tobytes()),
                             "prepared_scoring_cache": safe(measured.metadata["walk_forward"].get("prepared_scoring_cache"))})
    eligible = len(lanes[6]["studies"])
    validate_identity(identity)
    records, anchor, _config = anchor_fixture()
    return {
        "schema": "quantbt.qms01.legacy-baseline.v1", "phase": "QMS-01",
        "wall_generated_at": datetime.now(timezone.utc).isoformat(), "source": identity,
        "budget": BUDGET, "strategy": {"source": "examples/walk_forward_train_test.py::strategy",
        "tape": "deterministic_synthetic_daily_v1", "real_market": False,
        "data_sha256": digest(pd.util.hash_pandas_object(data, index=True).values.tobytes())},
        "lanes": lanes, "native_lane": native_payload, "timing": measurements,
        "measurement": {"method": "same-process warm repetitions; timings exclude discovery spies",
                        "peak_rss_scope": "whole baseline process including preceding lanes/imports/JIT",
                        "thread_env": {key: os.environ.get(key) for key in (
                            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS")},
                        "cpu_count": os.cpu_count(), "spies_delegated_without_mutation": True},
        "anchor_fixture": {"records": [record_payload(item) for item in records], "selected": record_payload(anchor)},
        "maturity": {"declared_fixture_origins": eligible, "matured_sealed_meta_origins": 0,
                     "available_meta_archive": False, "economic_status": "NOT_RUN_BUDGET",
                     "reason": "No sealed historical meta tasks exist; two smoke folds are not 12 mature origins."},
        "status": {"technical": "AWAITING_TEST_RECEIPT", "empirical": "NOT_ASSESSED",
                   "performance": "MEASURED_BASELINE_ONLY", "owner_review": "PENDING",
                   "can_start_next_phase": False},
    }


def verify_manifest(manifest: dict) -> None:
    validate_identity(manifest["source"])
    if manifest["budget"] != BUDGET:
        raise ValueError("registered budget changed")
    if [(item["mode"], item["schedule"]) for item in manifest["lanes"]] != list(ROUTES):
        raise ValueError("required baseline route missing")
    for lane in manifest["lanes"]:
        if not lane["equity"]["values"] or not lane["score_tasks"] or not lane["pools"]:
            raise ValueError("baseline payload missing")
        if not all(isinstance(value, (int, float)) and np.isfinite(value) for value in lane["equity"]["values"]):
            raise ValueError("non-finite equity")
        for pool in lane["pools"]:
            actual = [item["trial_id"] for item in pool["all_trials"] if not item["pruned"] and isinstance(item["objective"], (int, float)) and np.isfinite(item["objective"])]
            if actual != pool["eligible_ids"]:
                raise ValueError("eligible pool IDs tampered")
    if not any(not row["warmup"] and row["wall_seconds"] > 0 and row["after"]["peak_rss_mib"] > 0 for row in manifest["timing"]):
        raise ValueError("resource evidence missing")


def junit_checks(path: Path) -> dict:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases or any(item.find(name) is not None for item in cases for name in ("failure", "error", "skipped")):
        raise ValueError("test receipt requires actual successful unskipped testcases")
    groups = {identifier: [] for identifier in REQUIRED_TESTS}
    for item in cases:
        match = re.match(r"test_q1_t(\d\d)_", item.attrib["name"])
        if match:
            groups[f"Q1-T{match[1]}"].append(item.attrib["name"])
    if any(not names for names in groups.values()):
        raise ValueError("required QMS test group missing from execution log")
    return {"total_passed": len(cases), "required_tests": groups,
            "qms_passed": sum(map(len, groups.values())), "skipped": 0, "failed": 0}


def write_receipt(junit: Path, manifest_path: Path) -> None:
    junit = junit.resolve()
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text())
    verify_manifest(manifest)
    tests = junit_checks(junit)
    required = (manifest_path, junit, ROOT / "tools/qms01_baseline.py",
                ROOT / "tests/meta_selection/test_qms01_baseline.py",
                ROOT / "docs/meta_selection/SOURCE_AND_SEAM_MAP.md",
                ROOT / "docs/meta_selection.md", ROOT / "handoff/WFO_META_CURRENT.md")
    receipt = {
        "schema": "quantbt.meta_selection.gate.v1", "phase": "QMS-01", "guide_version": "QMS-V1.1",
        "baseline_commit_expected": RELEASE_SHA, "baseline_release": "1.1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "implementation_status": "COMPLETE", "technical_gate": "PASS",
        "empirical_status": "NOT_ASSESSED", "performance": "MEASURED_BASELINE_ONLY",
        "required_gate_registry": list(REQUIRED_GATES),
        "gates": {name: "PENDING" if name == "G1-OWNER" else "PASS" for name in REQUIRED_GATES},
        "tests": tests, "evidence_refs": {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in required},
        "owner_review": {"status": "PENDING", "decision_ref": None}, "can_start_next_phase": False,
        "open_financial_repairs": [],
        "blocked_until_owning_phase": {
            "centroid_meta_labels": "QMS-03/05 exact same-IS evaluation inside live fold lifetime",
            "scalar_metric_validity": "QMS-03/06 authoritative support/variance/activity; no placeholder inference",
            "reactive_meta": "QMS-06 separate qualification of reset-flat route",
            "economic_study": "QMS-08 needs authorized primary real-alpha data and 12 mature origins",
        },
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n")
    verify_receipt(RECEIPT, manifest_path)


def verify_receipt(path: Path, manifest_path: Path) -> None:
    manifest_path = manifest_path.resolve()
    receipt = json.loads(path.read_text())
    verify_manifest(json.loads(manifest_path.read_text()))
    if receipt["required_gate_registry"] != list(REQUIRED_GATES):
        raise ValueError("required gates changed")
    if receipt["owner_review"] != {"status": "PENDING", "decision_ref": None} or receipt["can_start_next_phase"] is not False:
        raise ValueError("QMS-01 discovery tool cannot approve the owner gate")
    if receipt["gates"] != {name: "PENDING" if name == "G1-OWNER" else "PASS" for name in REQUIRED_GATES}:
        raise ValueError("gate disposition changed")
    required_refs = {str(manifest_path.relative_to(ROOT)), "tools/qms01_baseline.py",
                     "tests/meta_selection/test_qms01_baseline.py", "docs/meta_selection/SOURCE_AND_SEAM_MAP.md",
                     "docs/meta_selection.md", "handoff/WFO_META_CURRENT.md",
                     "benchmarks/optimization/meta_selection/qms01_tests.xml"}
    if set(receipt["evidence_refs"]) != required_refs:
        raise ValueError("required evidence reference missing")
    for name, expected in receipt["evidence_refs"].items():
        if digest((ROOT / name).read_bytes()) != expected:
            raise ValueError("evidence digest mismatch: " + name)
    actual = junit_checks(ROOT / "benchmarks/optimization/meta_selection/qms01_tests.xml")
    if receipt["tests"] != actual:
        raise ValueError("test counts do not match executed JUnit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=MANIFEST)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--receipt", type=Path, help="Seal evidence from the actual JUnit execution log")
    args = parser.parse_args()
    if args.verify:
        verify_manifest(json.loads(args.output.read_text()))
        if args.receipt is not None:
            verify_receipt(RECEIPT, args.output)
        print("QMS-01 source, budget, route and payload verification passed")
    elif args.receipt is not None:
        write_receipt(args.receipt, args.output)
        print("QMS-01 technical receipt verified; owner acceptance remains pending")
    else:
        if args.output == MANIFEST and RECEIPT.exists():
            parser.error("baseline evidence is sealed; replay to a new --output instead of overwriting it")
        manifest = build_manifest()
        verify_manifest(manifest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Compact machine evidence retains every registered value, not raw tape.
        args.output.write_text(json.dumps(safe(manifest), separators=(",", ":"), allow_nan=False) + "\n")
        print(f"QMS-01 baseline written: {args.output}")


if __name__ == "__main__":
    main()
