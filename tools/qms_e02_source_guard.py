"""Exact reviewed E02 adapters; older source seals are not file exemptions."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "82c1421"
MANIFEST = ROOT / "benchmarks/optimization/meta_selection/qms_e02_reviewed_source.json"
ALLOW = frozenset([
    "src/quantbt/walkforward.py", "src/quantbt/backends/reactive_wfo.py",
    *["src/quantbt/optimization/meta_selection/" + name for name in
      ("runtime.py", "reactive.py", "observer.py")],
    *["src/quantbt/optimization/meta_selection/domains/" + name for name in
      ("__init__.py", "contracts.py", "registry.py", "base.py", "scalar.py", "reactive.py")],
])


def checked_source(source, name):
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get("baseline") != ENTRY or set(manifest.get("source_sha256", {})) != ALLOW:
        raise AssertionError("E02 reviewed manifest scope mismatch")
    if name not in ALLOW or sha256(source).hexdigest() != manifest["source_sha256"][name]:
        raise AssertionError(f"unreviewed E02 adapter bytes: {name}")


def without_e02_adapter(source, name):
    if name not in ALLOW:
        return source
    original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT,
                              capture_output=True, check=False)
    if original.returncode == 0 and source == original.stdout:
        return source
    checked_source(source, name)
    return original.stdout if original.returncode == 0 else source


def verify():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY,
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard",
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    if names != ALLOW:
        raise AssertionError(f"E02 changed unexpected/missing source: {sorted(names ^ ALLOW)}")
    for name in names:
        checked_source((ROOT / name).read_bytes(), name)
    protected = ("rust", "pyproject.toml", "uv.lock", "contracts",
        "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md")
    if subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", *protected], cwd=ROOT):
        raise AssertionError("E02 changed math/native/release/scientific identity")
    return dict(schema="qms-e02-exact-source-guard-v1", baseline=ENTRY,
        source_sha256=json.loads(MANIFEST.read_text())["source_sha256"],
        financial_numeric_source_unchanged=True, route_activation_unchanged=True)
