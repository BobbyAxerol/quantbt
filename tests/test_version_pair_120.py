"""Version/pair wiring only; no optimizer, financial execution or installation."""

import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import tomllib
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONSUMERS = ("qms_e03_consumer", "qms_e04_consumer", "qms_e05_consumer", "qms_g01_consumer")


def literal_assignment(path, name):
    tree = ast.parse(path.read_text())
    return next(ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))


def test_core_120_native_043_metadata_and_generated_pair_are_exact():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    locked = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    registry = json.loads((ROOT / "contracts/native_event_product_registry.json").read_text())
    generated = ROOT / "src/quantbt/core/generated_product_contracts.py"
    assert project["version"] == literal_assignment(ROOT / "src/quantbt/__init__.py", "__version__") == "1.2.0"
    assert next(p["version"] for p in locked if p["name"] == "quantbt-engine") == "1.2.0"
    assert registry["versions"]["core_package"]["version"] == "1.2.0"
    assert literal_assignment(generated, "NATIVE_EVENT_CORE_PACKAGE_VERSION") == "1.2.0"
    assert literal_assignment(generated, "NATIVE_EVENT_NATIVE_PACKAGE_VERSION") == "0.4.3"
    assert [(row["core_version"], row["native_version"]) for row in registry["compatibility"]] == [("1.2.0", "0.4.3")]
    assert registry["versions"]["native_package"]["version"] == "0.4.3"
    assert registry["versions"]["native_package"]["published"] is False
    assert next(p["version"] for p in locked if p["name"] == "quantbt-native") == "0.4.3"
    assert tomllib.loads((ROOT / "rust/native_event/pyproject.toml").read_text())["project"]["version"] == "0.4.3"
    assert tomllib.loads((ROOT / "rust/native_event/Cargo.toml").read_text())["package"]["version"] == "0.4.3"
    assert len([dep for dep in project["dependencies"] if dep.startswith("quantbt-native==0.4.3;")]) == 1
    rust = (ROOT / "rust/crates/quantbt-domain/src/generated_product_contracts.rs").read_text()
    assert 'pub const CORE_PACKAGE_VERSION: &str = "1.2.0";' in rust
    assert 'pub const NATIVE_PACKAGE_VERSION: &str = "0.4.3";' in rust
    cases = json.loads((ROOT / "tests/corpus/generated/product_contract_cases.json").read_text())["cases"]
    assert all(case["core_version"] == "1.2.0" for case in cases if "core_version" in case)


@pytest.mark.parametrize("core,native,explicit,expected", [
    ("1.1.2", "0.4.3", False, True),
    ("1.2.0", "0.4.3", False, True),
    ("1.1.1", "0.4.2", False, False),
    ("1.2.0", "0.4.2", False, False),
    ("1.2.1", "0.4.3", False, False),
    ("1.2.1", "0.4.3", True, True),
])
def test_public_cli_keeps_required_qms_for_both_approved_pairs(monkeypatch, core, native, explicit, expected):
    from tools import verify_public_native_consumer as public

    admitted = []

    def consume(spec, *, logs_directory):
        admitted.append(spec)
        assert logs_directory is None
        return {"synthetic_unit_control": True}

    monkeypatch.setattr(public, "run_consumer_proof", consume)
    args = ["--index", "pypi", "--core-version", core, "--native-version", native]
    assert public.main(args + (["--require-qms"] if explicit else [])) == 0
    assert len(admitted) == 1
    assert (admitted[0].core_version, admitted[0].native_version) == (core, native)
    assert admitted[0].require_qms is expected


@pytest.mark.parametrize("core,native,expected", [
    ("1.1.2", "0.4.3", 1),
    ("1.2.0", "0.4.3", 1),
    ("1.1.1", "0.4.2", 0),
    ("1.2.0", "0.4.2", 0),
    ("1.2.1", "0.4.3", 0),
])
def test_public_workflow_exact_pair_predicate(tmp_path, core, native, expected):
    source = (ROOT / ".github/workflows/public-native-consumer.yml").read_text()
    start = source.index("          qms_args=()\n")
    stop = source.index("          poetry --version\n", start)
    script = textwrap.dedent(source[start:stop]) + 'printf "%s\\n" "${#qms_args[@]}"\n'
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path,
        env=dict(os.environ, core_version=core, native_version=native),
        capture_output=True, text=True, check=True, timeout=5)
    assert result.stdout == str(expected) + "\n"


@pytest.fixture
def installed_modules(monkeypatch):
    quantbt = ModuleType("quantbt")
    quantbt.__path__ = []
    quantbt.__file__ = "/consumer/lib/python3.12/site-packages/quantbt/__init__.py"
    quantbt.__version__ = "1.2.0"
    core = ModuleType("quantbt.core")
    core.__path__ = []
    contract = ModuleType("quantbt.core.generated_product_contracts")
    contract.NATIVE_EVENT_CORE_PACKAGE_VERSION = "1.2.0"
    contract.NATIVE_EVENT_NATIVE_PACKAGE_VERSION = "0.4.3"
    for module in (quantbt, core, contract):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    versions = {"quantbt-engine": "1.2.0", "quantbt-native": "0.4.3"}
    native = SimpleNamespace(version=lambda: "0.4.3")
    return quantbt, native, contract, versions


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize("core", ["1.1.2", "1.2.0"])
@pytest.mark.parametrize("explicit", [False, True])
def test_installed_consumers_observe_the_expected_pair(monkeypatch, installed_modules, name, core, explicit):
    consumer = importlib.import_module("tools." + name)
    quantbt, native, contract, versions = installed_modules
    quantbt.__version__ = versions["quantbt-engine"] = contract.NATIVE_EVENT_CORE_PACKAGE_VERSION = core
    monkeypatch.setattr(consumer.metadata, "version", versions.__getitem__)
    args = dict(core_version=core, native_version="0.4.3") if explicit else {}
    assert consumer._installed_pair(quantbt, native, **args) == (core, "0.4.3")


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize("defect", ["stale_expected_core", "stale_native", "core_metadata", "native_metadata", "checkout", "stale_contract"])
def test_installed_consumers_reject_stale_or_wrong_identity(monkeypatch, installed_modules, name, defect):
    consumer = importlib.import_module("tools." + name)
    quantbt, native, contract, versions = installed_modules
    monkeypatch.setattr(consumer.metadata, "version", versions.__getitem__)
    args = {}
    if defect == "stale_expected_core":
        args = dict(core_version="1.1.2", native_version="0.4.3")
    elif defect == "stale_native":
        native.version = lambda: "0.4.2"
    elif defect == "core_metadata":
        versions["quantbt-engine"] = "1.1.2"
    elif defect == "native_metadata":
        versions["quantbt-native"] = "0.4.2"
    elif defect == "checkout":
        quantbt.__file__ = str(ROOT / "src/quantbt/__init__.py")
    elif defect == "stale_contract":
        contract.NATIVE_EVENT_CORE_PACKAGE_VERSION = "1.1.2"
    with pytest.raises(AssertionError):
        consumer._installed_pair(quantbt, native, **args)


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize("args", [dict(core_version="1.2.0"), dict(native_version="0.4.3")])
def test_installed_consumers_reject_half_specified_pair(installed_modules, name, args):
    consumer = importlib.import_module("tools." + name)
    quantbt, native, _, _ = installed_modules
    with pytest.raises(ValueError, match="required together"):
        consumer._installed_pair(quantbt, native, **args)
