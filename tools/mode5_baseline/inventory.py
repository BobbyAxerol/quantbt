"""Map actual shared source and loaded dependencies, not proposed APIs."""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import importlib.util
from pathlib import Path
import subprocess
import sys

from .isolation import canonical_digest, file_identity


BINDINGS = (
    ("public_route", "endpoint.py", "QuantBTEndpoint.walk_forward", "tests/test_phase49a_walkforward_schedules.py"),
    ("configuration", "walkforward.py", "WalkForwardConfig", "tests/test_walkforward_phase1.py"),
    ("legacy_selection", "walkforward.py", "select_full_sample_robust_record", "tests/test_walkforward_phase1.py"),
    ("legacy_plateau", "walkforward.py", "select_is_plateau_robust_record", "tests/test_walkforward_phase1.py"),
    ("shared_schema", "optimization/parameter_space.py", "NormalizedSearchSpace", "tests/meta_selection/test_qms02_samplers.py"),
    ("sampler_factory", "optimization/samplers.py", "build_sampler", "tests/test_optimization_samplers.py"),
    ("sampler_observer", "optimization/wfo_study.py", "ObservedSampler", "tests/meta_selection/test_qms02_samplers.py"),
    ("prepared_context", "walkforward.py", "PreparedWalkForwardContext", "tests/test_phase49b_wfo_performance.py"),
    ("domain_evaluator", "optimization/meta_selection/domains/base.py", "DomainAdapter", "tests/meta_selection/test_e02_adapters.py"),
    ("metric_contract", "optimization/meta_selection/records.py", "MetricContract", "tests/meta_selection/test_qms03_history.py"),
    ("report_contract", "metrics/report_contracts.py", "ReportingContractV1", "tests/metrics/test_reporting_conformance.py"),
    ("output_retention", "planning/output.py", "compile_output_requirements", "tests/native_event/contract/test_phase52a_planning.py"),
    ("trial_records", "optimization/result.py", "OptimizationTrialRecord", "tests/test_optimization_core.py"),
    ("causal_history", "optimization/meta_selection/history.py", "MetaHistory", "tests/meta_selection/test_qms03_history.py"),
    ("native_evaluation", "backends/native_prepared_evaluation.py", "NativePreparedEvaluationRuntimeV1", "tests/test_phase73_prepared_evaluation.py"),
)

NEW_SELECTORS = ("full_dro_cvar", "full_sam_basin", "full_pareto_chebyshev",
                 "full_alpha_adaptive_invariant")


def source_symbols(path: Path) -> dict:
    tree = ast.parse(path.read_text(), filename=str(path))
    symbols = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols[node.name] = node.lineno
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols[f"{node.name}.{child.name}"] = child.lineno
    return symbols


def binding_map(repo: Path) -> dict:
    rows = []
    for responsibility, relative, symbol, test in BINDINGS:
        path = repo / "src/quantbt" / relative
        line = source_symbols(path).get(symbol)
        if line is None:
            raise ValueError(f"unresolved source symbol: {relative}:{symbol}")
        rows.append({"responsibility": responsibility, "source": f"src/quantbt/{relative}",
                     "symbol": symbol, "line": line, "sha256": file_identity(path)["sha256"],
                     "test": test, "test_present": (repo / test).is_file(),
                     "consumer": "Mode5 research layer via existing shared contract",
                     "disposition": "REUSE_EXISTING_NO_DUPLICATE",
                     "runtime_qualification": "NOT_RUN_IN_M5_01"})
    if not all(row["test_present"] for row in rows):
        missing = [row["test"] for row in rows if not row["test_present"]]
        raise ValueError(f"source-binding test references missing: {missing}")
    return {"schema": "quantbt.mode5_baseline.binding_map.v1", "bindings": rows,
            "proposed_selectors": {name: "NOT_IMPLEMENTED_FUTURE_M5_07_10" for name in NEW_SELECTORS},
            "legacy_selectors": ["full_robust", "full_plateau_robust", "full_temporal_robust", "full_best"],
            "new_financial_engine": False, "meta_implicitly_activated": False}


def provenance() -> dict:
    versions, imports = {}, {}
    for name in ("quantbt-engine", "quantbt-native", "numpy", "pandas", "numba", "optuna", "cmaes", "pytest"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    for name in ("quantbt", "optuna", "_quantbt_native"):
        spec = importlib.util.find_spec(name)
        imports[name] = file_identity(Path(spec.origin)) if spec and spec.origin else None
    core = importlib.import_module("quantbt")
    native = importlib.import_module("_quantbt_native")
    extension_paths = [Path(module.__file__) for name, module in tuple(sys.modules.items())
                       if name.startswith("_quantbt_native") and getattr(module, "__file__", "").endswith(".so")]
    from quantbt.backends._native_event_rust import probe_native_event_rust_extension
    status = probe_native_event_rust_extension()
    commands = {}
    for executable in ("rustc", "cargo"):
        try:
            commands[executable] = subprocess.check_output([executable, "--version"], text=True).strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            commands[executable] = {"status": "UNAVAILABLE", "reason": type(exc).__name__}
    return {"python": sys.version, "executable": sys.executable, "packages": versions,
            "imports": imports, "loaded_core_version": core.__version__,
            "native_module_version": getattr(native, "__version__", None),
            "extensions": [file_identity(path) for path in sorted(set(extension_paths))],
            "native_api": status.api_version, "native_compatible": status.compatible,
            "native_capabilities": dict(status.capabilities), "toolchain": commands,
            "qualification": "IMPORT_PROVENANCE_ONLY_NOT_NEW_WHEEL_CERTIFICATION"}


def compatibility_key(identity: dict) -> str:
    required = ("core_sha256", "native_sha256", "module_origin", "data_id", "clock_id",
                "economics_id", "alpha_sha256", "parameter_id", "terminal_id", "warmup_id")
    if any(not identity.get(key) for key in required):
        raise ValueError("incomplete execution compatibility witness")
    return canonical_digest({key: identity[key] for key in required})


def sampler_factory_manifest() -> list[dict]:
    from quantbt.optimization.config import SamplerConfig
    from quantbt.optimization.samplers import build_sampler, resolved_sampler_kwargs
    from .evidence import sampler_observation

    rows = []
    for name in ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"):
        config = SamplerConfig(name=name)
        sampler = build_sampler(config, seed=731, search_space={"synthetic_x": (0.1, 1.0)}, objective_count=1)
        _, kwargs = resolved_sampler_kwargs(config, 731)
        rows.append(sampler_observation(name, type(sampler).__name__, verified=True) |
                    {"resolved_kwargs": kwargs, "scope": "synthetic factory-only preflight; no RNG draws/study",
                     "independent_draw_witness": "tests.xml: test_m5t_004_actual_observer_detects_independent_draws"})
    return rows


def alpha_inventory(path: Path) -> dict:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports = sorted({node.module for node in ast.walk(tree)
                      if isinstance(node, ast.ImportFrom) and node.module})
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str) and "params" in ast.unparse(node.value):
                keys.add(node.slice.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if "params" in ast.unparse(node.func.value) and node.args and isinstance(node.args[0], ast.Constant):
                keys.add(node.args[0].value)
    return file_identity(path) | {"observed_parameter_keys": sorted(keys),
                                  "imports": imports, "symbols": source_symbols(path),
                                  "import_executed": False, "effective_schema": "PENDING_M5_02_ADMISSION"}
