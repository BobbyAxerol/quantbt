#!/usr/bin/env python3
"""Shared, versioned measurement rules for native benchmark evidence.

The helpers in this module deliberately know nothing about a trading engine.
They make the *work denominator* and candidate identity explicit so benchmark
claims cannot accidentally use full input tape volume when an engine actually
simulates only a subset of causal test windows.
"""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tomllib
from types import ModuleType
from typing import Any, Mapping, Sequence


MEASUREMENT_CONTRACT_SCHEMA = "quantbt-native-measurement-contract-v1"
WORK_COUNTER_SCHEMA = "quantbt-native-work-counters-v1"
CURRENT_CANDIDATE_EVIDENCE_SCHEMA = "quantbt-current-candidate-evidence-v1"
HISTORICAL_SCOPE_ONLY = "historical_scope_only"
CURRENT_CANDIDATE_VERIFIED = "current_candidate_verified"

IDENTITY_REQUIRED_FIELDS = frozenset(
    {
        "git_commit",
        "git_dirty",
        "git_status_sha256",
        "canonical_source_sha256",
        "product_registry_sha256",
        "lifecycle_registry_sha256",
        "core_distribution",
        "native_distribution",
        "native_extension",
        "python",
        "platform",
        "cpu_count",
        "thread_environment",
        "data_sha256",
        "intent_sha256",
        "measurement_contract_sha256",
        "warmup_procedure",
    }
)

WORK_COUNTER_REQUIRED_FIELDS = frozenset(
    {
        "schema",
        "supplied_market_bars",
        "symbol_count",
        "candidate_count",
        "scenario_count",
        "fold_count",
        "folds",
        "planned_candidate_fold_scenario_tasks",
        "executed_candidate_fold_scenario_tasks",
        "skipped_candidate_fold_scenario_tasks",
        "early_terminated_candidate_fold_scenario_tasks",
        "warmup_bar_visits",
        "planned_simulation_bar_visits",
        "actual_simulation_bar_visits",
        "actual_simulation_symbol_bar_visits",
        "logical_full_tape_candidate_fold_bar_visits",
        "logical_full_tape_candidate_fold_symbol_bar_visits",
        "actual_visit_basis",
    }
)


def file_sha256(path: Path) -> str:
    """Return the raw file checksum used for immutable historical evidence."""

    return sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    """Return a JSON-content hash independent of presentation whitespace."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def typed_array_sha256(*arrays: Any) -> str:
    """Hash typed numeric inputs without reducing them to a lossy value digest.

    Shape, dtype and C-order payload all affect native execution.  The helper
    is intentionally small so benchmark scripts can bind data and intent
    identity without building pandas objects or a second serialization format.
    """

    digest = sha256()
    for ordinal, value in enumerate(arrays):
        if value is None:
            digest.update(f"{ordinal}:none".encode("utf-8"))
            continue
        shape = tuple(getattr(value, "shape", ()))
        dtype = getattr(value, "dtype", None)
        tobytes = getattr(value, "tobytes", None)
        if not callable(tobytes):
            raise TypeError("typed_array_sha256 expects values with tobytes()")
        digest.update(f"{ordinal}:{shape}:{dtype}".encode("utf-8"))
        digest.update(b"\0")
        digest.update(tobytes(order="C"))
        digest.update(b"\0")
    return digest.hexdigest()


def _integer(value: Any, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if integer != value or integer < minimum:
        comparison = f">= {minimum}" if minimum else ">= 0"
        raise ValueError(f"{label} must be {comparison}")
    return integer


def _fold_value(fold: object, name: str) -> Any:
    if isinstance(fold, Mapping):
        if name not in fold:
            raise ValueError(f"fold is missing {name!r}")
        return fold[name]
    try:
        return getattr(fold, name)
    except AttributeError as exc:
        raise ValueError(f"fold is missing {name!r}") from exc


def build_work_counters(
    *,
    supplied_market_bars: int,
    candidate_count: int,
    scenario_count: int,
    symbol_count: int,
    folds: Sequence[object],
    warmup_bar_visits: int = 0,
    skipped_candidate_fold_scenario_tasks: int = 0,
    early_terminated_candidate_fold_scenario_tasks: int = 0,
    actual_simulation_bar_visits: int | None = None,
) -> dict[str, Any]:
    """Build exact execution-work counters for a causal candidate/fold run.

    ``test_start`` and ``test_end`` are half-open offsets into the supplied
    tape.  They represent bars the executor actually visits.  Training data
    remains input provenance; it is never counted as simulated work merely
    because it was available to feature generation.

    If a run terminates early, the caller must supply observed aggregate visits
    rather than letting this helper fabricate a full-window denominator.
    """

    supplied = _integer(supplied_market_bars, label="supplied_market_bars", minimum=1)
    candidates = _integer(candidate_count, label="candidate_count")
    scenarios = _integer(scenario_count, label="scenario_count")
    symbols = _integer(symbol_count, label="symbol_count", minimum=1)
    warmup = _integer(warmup_bar_visits, label="warmup_bar_visits")
    skipped = _integer(
        skipped_candidate_fold_scenario_tasks,
        label="skipped_candidate_fold_scenario_tasks",
    )
    early = _integer(
        early_terminated_candidate_fold_scenario_tasks,
        label="early_terminated_candidate_fold_scenario_tasks",
    )
    if not folds:
        raise ValueError("folds cannot be empty")

    normalized_folds: list[dict[str, int]] = []
    seen_fold_ids: set[int] = set()
    for ordinal, fold in enumerate(folds):
        fold_id = _integer(_fold_value(fold, "fold_id"), label=f"fold[{ordinal}].fold_id")
        if fold_id in seen_fold_ids:
            raise ValueError(f"duplicate fold_id {fold_id}")
        seen_fold_ids.add(fold_id)
        test_start = _integer(_fold_value(fold, "test_start"), label=f"fold[{ordinal}].test_start")
        test_end = _integer(_fold_value(fold, "test_end"), label=f"fold[{ordinal}].test_end")
        if test_start >= test_end or test_end > supplied:
            raise ValueError(f"fold[{ordinal}] test window must be within supplied market bars")
        normalized_folds.append(
            {
                "fold_id": fold_id,
                "test_start": test_start,
                "test_end": test_end,
                "planned_test_bar_visits": test_end - test_start,
            }
        )

    planned_tasks = candidates * scenarios * len(normalized_folds)
    if skipped + early > planned_tasks:
        raise ValueError("skipped plus early-terminated tasks exceeds planned tasks")
    executed_tasks = planned_tasks - skipped
    planned_visits = candidates * scenarios * sum(
        item["planned_test_bar_visits"] for item in normalized_folds
    )
    if actual_simulation_bar_visits is None:
        if early or skipped:
            raise ValueError(
                "actual_simulation_bar_visits is required when tasks are skipped or terminate early"
            )
        actual_visits = planned_visits
        actual_basis = "derived_exhaustive_test_windows"
    else:
        actual_visits = _integer(
            actual_simulation_bar_visits,
            label="actual_simulation_bar_visits",
        )
        if actual_visits > planned_visits:
            raise ValueError("actual_simulation_bar_visits cannot exceed planned visits")
        actual_basis = "observed_executor_counter"

    counters = {
        "schema": WORK_COUNTER_SCHEMA,
        "supplied_market_bars": supplied,
        "symbol_count": symbols,
        "candidate_count": candidates,
        "scenario_count": scenarios,
        "fold_count": len(normalized_folds),
        "folds": normalized_folds,
        "planned_candidate_fold_scenario_tasks": planned_tasks,
        "executed_candidate_fold_scenario_tasks": executed_tasks,
        "skipped_candidate_fold_scenario_tasks": skipped,
        "early_terminated_candidate_fold_scenario_tasks": early,
        "warmup_bar_visits": warmup,
        "planned_simulation_bar_visits": planned_visits,
        "actual_simulation_bar_visits": actual_visits,
        "actual_simulation_symbol_bar_visits": actual_visits * symbols,
        "logical_full_tape_candidate_fold_bar_visits": supplied * planned_tasks,
        "logical_full_tape_candidate_fold_symbol_bar_visits": supplied * planned_tasks * symbols,
        "actual_visit_basis": actual_basis,
    }
    validate_work_counters(counters)
    return counters


def validate_work_counters(counters: Mapping[str, Any]) -> None:
    """Raise when a reported benchmark denominator is internally inconsistent."""

    missing = sorted(WORK_COUNTER_REQUIRED_FIELDS - set(counters))
    if missing:
        raise ValueError(f"work counters missing required fields: {', '.join(missing)}")
    if counters["schema"] != WORK_COUNTER_SCHEMA:
        raise ValueError("unsupported work counter schema")
    supplied = _integer(counters["supplied_market_bars"], label="supplied_market_bars", minimum=1)
    symbols = _integer(counters["symbol_count"], label="symbol_count", minimum=1)
    candidates = _integer(counters["candidate_count"], label="candidate_count")
    scenarios = _integer(counters["scenario_count"], label="scenario_count")
    fold_count = _integer(counters["fold_count"], label="fold_count", minimum=1)
    folds = counters["folds"]
    if not isinstance(folds, list) or len(folds) != fold_count:
        raise ValueError("work counters fold_count does not match folds")
    planned_tasks = candidates * scenarios * fold_count
    if _integer(
        counters["planned_candidate_fold_scenario_tasks"],
        label="planned_candidate_fold_scenario_tasks",
    ) != planned_tasks:
        raise ValueError("planned candidate/fold/scenario task count is inconsistent")
    skipped = _integer(
        counters["skipped_candidate_fold_scenario_tasks"],
        label="skipped_candidate_fold_scenario_tasks",
    )
    early = _integer(
        counters["early_terminated_candidate_fold_scenario_tasks"],
        label="early_terminated_candidate_fold_scenario_tasks",
    )
    executed = _integer(
        counters["executed_candidate_fold_scenario_tasks"],
        label="executed_candidate_fold_scenario_tasks",
    )
    if skipped + early > planned_tasks or executed != planned_tasks - skipped:
        raise ValueError("candidate/fold/scenario task counters are inconsistent")
    expected_window_visits = 0
    seen_ids: set[int] = set()
    for ordinal, fold in enumerate(folds):
        fold_id = _integer(fold.get("fold_id"), label=f"fold[{ordinal}].fold_id")
        if fold_id in seen_ids:
            raise ValueError("work counter fold ids must be unique")
        seen_ids.add(fold_id)
        start = _integer(fold.get("test_start"), label=f"fold[{ordinal}].test_start")
        end = _integer(fold.get("test_end"), label=f"fold[{ordinal}].test_end")
        visits = _integer(
            fold.get("planned_test_bar_visits"),
            label=f"fold[{ordinal}].planned_test_bar_visits",
        )
        if start >= end or end > supplied or visits != end - start:
            raise ValueError("work counter fold window is invalid")
        expected_window_visits += visits
    planned_visits = candidates * scenarios * expected_window_visits
    if _integer(counters["planned_simulation_bar_visits"], label="planned_simulation_bar_visits") != planned_visits:
        raise ValueError("planned simulation bar visits are inconsistent")
    actual = _integer(counters["actual_simulation_bar_visits"], label="actual_simulation_bar_visits")
    if actual > planned_visits:
        raise ValueError("actual simulation bar visits exceed planned visits")
    if _integer(
        counters["actual_simulation_symbol_bar_visits"],
        label="actual_simulation_symbol_bar_visits",
    ) != actual * symbols:
        raise ValueError("actual simulation symbol-bar visits are inconsistent")
    expected_logical = supplied * planned_tasks
    if _integer(
        counters["logical_full_tape_candidate_fold_bar_visits"],
        label="logical_full_tape_candidate_fold_bar_visits",
    ) != expected_logical:
        raise ValueError("logical full-tape candidate/fold bar visits are inconsistent")
    if _integer(
        counters["logical_full_tape_candidate_fold_symbol_bar_visits"],
        label="logical_full_tape_candidate_fold_symbol_bar_visits",
    ) != expected_logical * symbols:
        raise ValueError("logical full-tape candidate/fold symbol-bar visits are inconsistent")
    if counters["actual_visit_basis"] not in {
        "derived_exhaustive_test_windows",
        "observed_executor_counter",
    }:
        raise ValueError("unknown actual visit basis")
    if early and counters["actual_visit_basis"] != "observed_executor_counter":
        raise ValueError("early-terminated tasks require observed executor counters")


def throughput_per_second(visits: int, seconds: float) -> float:
    """Return a denominator-safe visit rate with a stable zero-time guard."""

    visits_int = _integer(visits, label="visits")
    elapsed = float(seconds)
    if elapsed < 0.0:
        raise ValueError("seconds must be >= 0")
    return float(visits_int / elapsed) if elapsed else 0.0


def _git_value(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _source_files(root: Path) -> list[Path]:
    roots = (
        root / "src" / "quantbt",
        root / "rust" / "crates",
        root / "rust" / "native_event",
    )
    files: list[Path] = []
    for directory in roots:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or any(part in {"target", "__pycache__"} for part in path.parts):
                continue
            files.append(path)
    for relative in (
        "pyproject.toml",
        "rust/Cargo.toml",
        "rust/Cargo.lock",
        "contracts/native_event_product_registry.json",
        "contracts/native_event_contract_registry.json",
    ):
        path = root / relative
        if path.is_file():
            files.append(path)
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def _source_tree_sha256(root: Path) -> str:
    digest = sha256()
    for path in _source_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _project_distribution(path: Path, fallback: str) -> dict[str, str | None]:
    if not path.is_file():
        return {"distribution": fallback, "version": None}
    try:
        project = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {"distribution": fallback, "version": None}
    return {
        "distribution": str(project.get("name", fallback)),
        "version": None if project.get("version") is None else str(project["version"]),
    }


def _extension_identity(native_module: ModuleType | None = None) -> dict[str, Any]:
    module = native_module
    if module is None:
        spec = importlib.util.find_spec("_quantbt_native")
        if spec is None:
            return {
                "available": False,
                "module_path": None,
                "module_sha256": None,
                "wrapper_path": None,
                "wrapper_sha256": None,
                "version": None,
                "api_version": None,
                "capability_sha256": None,
            }
        try:
            module = __import__("_quantbt_native")
        except Exception:  # pragma: no cover - optional wheel import is host-specific
            module = None
    if module is None:
        return {
            "available": False,
            "module_path": None,
            "module_sha256": None,
            "wrapper_path": None,
            "wrapper_sha256": None,
            "version": None,
            "api_version": None,
            "capability_sha256": None,
        }
    wrapper_raw = getattr(module, "__file__", None)
    wrapper_path = Path(str(wrapper_raw)) if wrapper_raw else None
    # Maturin installs a Python package wrapper that imports the compiled
    # extension as ``_quantbt_native._quantbt_native``. Hash the executable
    # module for wheel identity while retaining the wrapper hash as provenance.
    compiled_module = getattr(module, "_quantbt_native", None)
    compiled_raw = getattr(compiled_module, "__file__", None)
    compiled_path = Path(str(compiled_raw)) if compiled_raw else None
    module_path = compiled_path if compiled_path is not None and compiled_path.is_file() else wrapper_path
    capabilities: Any = ()
    for name in ("version", "api_version", "capabilities"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            try:
                value = candidate()
            except Exception:  # pragma: no cover - extension-specific failure guard
                value = None
        else:
            value = candidate
        if name == "capabilities":
            capabilities = value or ()
        elif name == "version":
            version = value
        else:
            api_version = value
    return {
        "available": True,
        "module_path": str(module_path) if module_path is not None else None,
        "module_sha256": file_sha256(module_path) if module_path is not None and module_path.is_file() else None,
        "wrapper_path": str(wrapper_path) if wrapper_path is not None else None,
        "wrapper_sha256": file_sha256(wrapper_path) if wrapper_path is not None and wrapper_path.is_file() else None,
        "version": None if version is None else str(version),
        "api_version": None if api_version is None else str(api_version),
        "capability_sha256": canonical_json_sha256(capabilities),
    }


def capture_measurement_identity(
    *,
    root: Path,
    warmup_procedure: str,
    native_module: ModuleType | None = None,
    data_sha256: str | None = None,
    intent_sha256: str | None = None,
    measurement_contract_path: Path | None = None,
) -> dict[str, Any]:
    """Capture reproducibility identity without requiring a native wheel.

    ``data_sha256`` and ``intent_sha256`` deliberately belong to the caller:
    this generic helper cannot know which arrays define a workload's market
    tape or typed intent.  A current-candidate promotion record must provide
    both.  Historical evidence may retain ``None`` because Phase 72 freezes it
    as scope-only rather than silently upgrading its provenance.
    """

    root = root.resolve()
    status = _git_value(root, "status", "--porcelain=v1")
    commit = _git_value(root, "rev-parse", "HEAD") or "unavailable"
    product = root / "contracts" / "native_event_product_registry.json"
    lifecycle = root / "contracts" / "native_event_contract_registry.json"
    contract = (
        root / "benchmarks" / "native_event" / "manifests" / "phase72_measurement_contract_v1.json"
        if measurement_contract_path is None
        else measurement_contract_path.resolve()
    )
    thread_keys = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS")
    return {
        "git_commit": commit,
        "git_dirty": bool(status),
        "git_status_sha256": sha256(status.encode("utf-8")).hexdigest(),
        "canonical_source_sha256": _source_tree_sha256(root),
        "product_registry_sha256": file_sha256(product) if product.is_file() else None,
        "lifecycle_registry_sha256": file_sha256(lifecycle) if lifecycle.is_file() else None,
        "core_distribution": _project_distribution(root / "pyproject.toml", "quantbt-engine"),
        "native_distribution": _project_distribution(
            root / "rust" / "native_event" / "pyproject.toml", "quantbt-native"
        ),
        "native_extension": _extension_identity(native_module),
        "python": sys.version,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "thread_environment": {key: os.environ.get(key) for key in thread_keys},
        "data_sha256": None if data_sha256 is None else str(data_sha256),
        "intent_sha256": None if intent_sha256 is None else str(intent_sha256),
        "measurement_contract_sha256": file_sha256(contract) if contract.is_file() else None,
        "warmup_procedure": str(warmup_procedure),
    }


def load_measurement_contract(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    """Read and validate the static Phase 72 measurement contract."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("measurement contract must be a JSON object")
    contract_root = path.resolve().parents[3] if root is None else root.resolve()
    validate_measurement_contract(payload, root=contract_root)
    return payload


def validate_measurement_contract(payload: Mapping[str, Any], *, root: Path) -> None:
    """Validate route ownership, profile pairing, and frozen history references."""

    required = {
        "schema",
        "measurement_contract_id",
        "identity_required_fields",
        "counter_schema",
        "current_candidate_evidence",
        "profile_pairs",
        "required_matrix",
        "routes",
        "historical_manifests",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"measurement contract missing required fields: {', '.join(missing)}")
    if payload["schema"] != MEASUREMENT_CONTRACT_SCHEMA:
        raise ValueError("unsupported measurement contract schema")
    if payload["counter_schema"] != WORK_COUNTER_SCHEMA:
        raise ValueError("measurement contract has unsupported counter schema")
    if set(payload["identity_required_fields"]) != IDENTITY_REQUIRED_FIELDS:
        raise ValueError("measurement contract identity fields drift")
    candidate_evidence = payload["current_candidate_evidence"]
    if not isinstance(candidate_evidence, Mapping):
        raise ValueError("measurement contract current_candidate_evidence must be an object")
    required_candidate_keys = {
        "schema",
        "require_clean_tree",
        "identity_required_fields",
        "native_extension_required_fields",
        "comparator_required_fields",
        "measurement_required_fields",
    }
    candidate_missing = sorted(required_candidate_keys - set(candidate_evidence))
    if candidate_missing:
        raise ValueError(
            "measurement contract current_candidate_evidence missing "
            + ", ".join(candidate_missing)
        )
    if candidate_evidence["schema"] != CURRENT_CANDIDATE_EVIDENCE_SCHEMA:
        raise ValueError("measurement contract has unsupported current candidate evidence schema")
    if candidate_evidence["require_clean_tree"] is not True:
        raise ValueError("current candidate evidence must require a clean tree")
    if set(candidate_evidence["identity_required_fields"]) != IDENTITY_REQUIRED_FIELDS:
        raise ValueError("current candidate evidence identity fields drift")
    for key in (
        "native_extension_required_fields",
        "comparator_required_fields",
        "measurement_required_fields",
    ):
        values = candidate_evidence[key]
        if not isinstance(values, list) or not values or not all(isinstance(item, str) and item for item in values):
            raise ValueError(f"current candidate evidence {key} must be a non-empty string list")
    matrix = payload["required_matrix"]
    if not isinstance(matrix, Mapping):
        raise ValueError("measurement contract required_matrix must be an object")
    for key in ("bars", "symbols", "candidates", "folds", "intent_types", "churn", "profiles"):
        if not isinstance(matrix.get(key), list) or not matrix[key]:
            raise ValueError(f"measurement contract matrix missing {key}")
    pair_ids: set[str] = set()
    for pair in payload["profile_pairs"]:
        for key in ("id", "python_profile", "native_profile", "result_contract", "timing_scope"):
            if not str(pair.get(key, "")).strip():
                raise ValueError(f"measurement profile pair missing {key}")
        pair_id = str(pair["id"])
        if pair_id in pair_ids:
            raise ValueError("measurement profile pair ids must be unique")
        pair_ids.add(pair_id)
        if pair["python_profile"] != pair["native_profile"]:
            raise ValueError("measurement profiles must compare like-for-like retention")
    route_ids: set[str] = set()
    for route in payload["routes"]:
        for key in (
            "id", "public_surface", "planner", "native_entry", "result_adapter",
            "authority", "current_status", "owner_phase", "fixture", "anchor_paths",
        ):
            if route.get(key) in (None, "", []):
                raise ValueError(f"measurement route missing {key}")
        route_id = str(route["id"])
        if route_id in route_ids:
            raise ValueError("measurement route ids must be unique")
        route_ids.add(route_id)
        if _integer(route["owner_phase"], label=f"route {route_id} owner_phase", minimum=72) < 72:
            raise ValueError("measurement route owner phase must be >= 72")
        if not isinstance(route["anchor_paths"], list):
            raise ValueError("measurement route anchor_paths must be a list")
        for relative in route["anchor_paths"]:
            if not (root / str(relative)).is_file():
                raise ValueError(f"measurement route anchor does not exist: {relative}")
    for historical in payload["historical_manifests"]:
        for key in ("path", "manifest_id", "sha256", "product_registry_fingerprint"):
            if not str(historical.get(key, "")).strip():
                raise ValueError(f"historical manifest missing {key}")
        path = root / str(historical["path"])
        if not path.is_file() or file_sha256(path) != historical["sha256"]:
            raise ValueError(f"historical manifest checksum drift: {historical['path']}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("manifest_id") != historical["manifest_id"]:
            raise ValueError(f"historical manifest id drift: {historical['path']}")
        if manifest.get("product_registry_fingerprint") != historical["product_registry_fingerprint"]:
            raise ValueError(f"historical registry fingerprint drift: {historical['path']}")


def current_candidate_evidence_violations(
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[str]:
    """Return fail-closed violations for promotion-eligible benchmark evidence.

    The registry only stores a candidate summary.  This validator makes its
    otherwise easy-to-forge fields meaningful: both comparator sides must carry
    the same timing/accounting/metric contract, identity must bind a compiled
    native wheel and typed inputs, and summary limits must point at an immutable
    artifact.  Historical evidence intentionally bypasses this helper because
    it is never promotion eligible.
    """

    specification = contract.get("current_candidate_evidence")
    if not isinstance(specification, Mapping):
        return ["measurement contract has no current candidate evidence specification"]
    violations: list[str] = []

    def require_mapping(value: Any, label: str) -> Mapping[str, Any] | None:
        if not isinstance(value, Mapping):
            violations.append(f"{label} must be an object")
            return None
        return value

    def require_text(value: Any, label: str) -> bool:
        if not isinstance(value, str) or not value.strip():
            violations.append(f"{label} must be non-empty text")
            return False
        return True

    def require_hash(value: Any, label: str) -> bool:
        if not require_text(value, label):
            return False
        if len(str(value)) != 64 or any(char not in "0123456789abcdef" for char in str(value).lower()):
            violations.append(f"{label} must be a SHA-256 hex digest")
            return False
        return True

    identity = require_mapping(evidence.get("candidate_identity"), "candidate_identity")
    if identity is not None:
        for field in specification["identity_required_fields"]:
            if identity.get(field) is None:
                violations.append(f"candidate_identity missing {field}")
        if specification["require_clean_tree"] and identity.get("git_dirty") is not False:
            violations.append("candidate_identity git_dirty must be false")
        for field in (
            "git_status_sha256",
            "canonical_source_sha256",
            "product_registry_sha256",
            "lifecycle_registry_sha256",
            "data_sha256",
            "intent_sha256",
            "measurement_contract_sha256",
        ):
            require_hash(identity.get(field), f"candidate_identity.{field}")
        for field in ("git_commit", "python", "platform", "warmup_procedure"):
            require_text(identity.get(field), f"candidate_identity.{field}")
        for field in ("core_distribution", "native_distribution"):
            distribution = require_mapping(identity.get(field), f"candidate_identity.{field}")
            if distribution is not None:
                require_text(distribution.get("distribution"), f"candidate_identity.{field}.distribution")
                require_text(distribution.get("version"), f"candidate_identity.{field}.version")
        extension = require_mapping(identity.get("native_extension"), "candidate_identity.native_extension")
        if extension is not None:
            if extension.get("available") is not True:
                violations.append("candidate_identity.native_extension.available must be true")
            for field in specification["native_extension_required_fields"]:
                if extension.get(field) is None:
                    violations.append(f"candidate_identity.native_extension missing {field}")
            require_hash(extension.get("module_sha256"), "candidate_identity.native_extension.module_sha256")
            require_hash(extension.get("capability_sha256"), "candidate_identity.native_extension.capability_sha256")
            for field in ("version", "api_version"):
                require_text(extension.get(field), f"candidate_identity.native_extension.{field}")

    pair_id = evidence.get("profile_pair")
    pairs = {
        str(item.get("id")): item
        for item in contract.get("profile_pairs", ())
        if isinstance(item, Mapping)
    }
    pair = pairs.get(str(pair_id))
    if pair is None:
        violations.append("current candidate evidence has an unknown profile pair")
    comparator = require_mapping(evidence.get("comparator_contract"), "comparator_contract")
    if comparator is not None:
        python_contract = require_mapping(comparator.get("python"), "comparator_contract.python")
        native_contract = require_mapping(comparator.get("native"), "comparator_contract.native")
        if python_contract is not None and native_contract is not None:
            for field in specification["comparator_required_fields"]:
                python_value = python_contract.get(field)
                native_value = native_contract.get(field)
                if python_value is None or native_value is None:
                    violations.append(f"comparator_contract missing {field}")
                    continue
                if python_value != native_value:
                    violations.append(f"comparator_contract {field} differs between Python and Rust")
            annualization = python_contract.get("annualization_days")
            if isinstance(annualization, bool) or not isinstance(annualization, (int, float)) or annualization <= 0:
                violations.append("comparator_contract annualization_days must be > 0")
            if pair is not None:
                if python_contract.get("timing_scope") != pair.get("timing_scope"):
                    violations.append("comparator_contract timing_scope differs from the declared profile pair")
                if python_contract.get("result_contract") != pair.get("result_contract"):
                    violations.append("comparator_contract result_contract differs from the declared profile pair")

    measurements = require_mapping(evidence.get("measurement"), "measurement")
    if measurements is not None:
        for field in specification["measurement_required_fields"]:
            if measurements.get(field) is None:
                violations.append(f"measurement missing {field}")
        sample_count = measurements.get("sample_count")
        if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count <= 0:
            violations.append("measurement sample_count must be a positive integer")
        median = measurements.get("median_seconds")
        p95 = measurements.get("p95_seconds")
        for value, label in ((median, "median_seconds"), (p95, "p95_seconds"), (measurements.get("cold_rss_mb"), "cold_rss_mb"), (measurements.get("warm_rss_mb"), "warm_rss_mb")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                violations.append(f"measurement {label} must be >= 0")
        if isinstance(median, (int, float)) and not isinstance(median, bool) and isinstance(p95, (int, float)) and not isinstance(p95, bool) and p95 < median:
            violations.append("measurement p95_seconds cannot be less than median_seconds")
        parity = require_mapping(measurements.get("parity"), "measurement.parity")
        if parity is not None and parity.get("passed") is not True:
            violations.append("measurement parity.passed must be true")
        require_hash(measurements.get("artifact_sha256"), "measurement.artifact_sha256")
    return violations


def historical_manifest_record(
    contract: Mapping[str, Any], *, relative_path: str
) -> Mapping[str, Any] | None:
    """Return an immutable historical record for a benchmark manifest, if any."""

    for record in contract.get("historical_manifests", []):
        if str(record.get("path")) == relative_path:
            return record
    return None


__all__ = [
    "CURRENT_CANDIDATE_VERIFIED",
    "CURRENT_CANDIDATE_EVIDENCE_SCHEMA",
    "HISTORICAL_SCOPE_ONLY",
    "IDENTITY_REQUIRED_FIELDS",
    "MEASUREMENT_CONTRACT_SCHEMA",
    "WORK_COUNTER_SCHEMA",
    "WORK_COUNTER_REQUIRED_FIELDS",
    "build_work_counters",
    "canonical_json_sha256",
    "capture_measurement_identity",
    "current_candidate_evidence_violations",
    "file_sha256",
    "historical_manifest_record",
    "load_measurement_contract",
    "throughput_per_second",
    "typed_array_sha256",
    "validate_measurement_contract",
    "validate_work_counters",
]
