"""Normalize only the owner-approved R03 packaging identity, never economics."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess

from tools.generate_product_contracts import _fingerprint, render_python, render_rust

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "b8f167f"
PACKAGING_FILES = frozenset({
    "pyproject.toml", "uv.lock",
    "src/quantbt/__init__.py", "src/quantbt/core/generated_product_contracts.py",
    "rust/native_event/Cargo.toml", "rust/native_event/pyproject.toml",
    "rust/Cargo.lock", "rust/crates/quantbt-domain/src/generated_product_contracts.rs",
})


def without_release_identity(source, name):
    if name not in PACKAGING_FILES:
        return source
    old = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
    expected = old
    if name.endswith("generated_product_contracts.py") or name.endswith("generated_product_contracts.rs"):
        product = json.loads(subprocess.check_output(
            ["git", "show", f"{ENTRY}:contracts/native_event_product_registry.json"], cwd=ROOT))
        product = deepcopy(product)
        product["versions"]["core_package"]["version"] = "1.1.2"
        product["versions"]["native_package"].update(version="0.4.3", published=False,
            release_policy="qms_r03_prepared_only_manylinux_x86_64_cpython_311_313")
        product["platform_wheel_matrix"][0]["status"] = "ci-certification-target"
        product["compatibility"][0].update(core_version="1.1.2", native_version="0.4.3")
        renderer = render_python if name.endswith(".py") else render_rust
        expected = renderer(product, _fingerprint(product), product["lifecycle_registry"]["fingerprint"]).encode()
    elif name == "src/quantbt/__init__.py":
        expected = old.replace(b'__version__ = "1.1.1"', b'__version__ = "1.1.2"', 1)
    elif name == "pyproject.toml":
        expected = old.replace(b'version = "1.1.1"', b'version = "1.1.2"', 1).replace(
            b"quantbt-native==0.4.2;", b"quantbt-native==0.4.3;", 1)
    elif name == "uv.lock":
        expected = old.replace(b'name = "quantbt-engine"\nversion = "1.1.1"',
                               b'name = "quantbt-engine"\nversion = "1.1.2"', 1).replace(
            b'name = "quantbt-native"\nversion = "0.4.2"',
            b'name = "quantbt-native"\nversion = "0.4.3"', 1)
    elif name == "rust/Cargo.lock":
        expected = old.replace(b'name = "quantbt-native"\nversion = "0.4.2"',
                               b'name = "quantbt-native"\nversion = "0.4.3"', 1)
    else:
        expected = old.replace(b'version = "0.4.2"', b'version = "0.4.3"', 1)
        if name.endswith("Cargo.toml"):
            expected = expected.replace(b"[features]\n",
                b'[features]\ndefault = ["qms-numeric-candidate", "qms-prepared-witness-candidate"]\n', 1)
    if source != expected:
        raise AssertionError(f"unapproved release/financial source change: {name}")
    return old
