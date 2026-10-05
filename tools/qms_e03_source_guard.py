"""Exact E03 route amendment; retain all earlier seals, financial math unchanged."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "b00ad56"
MANIFEST = ROOT / "benchmarks/optimization/meta_selection/qms_e03_reviewed_source.json"
ALLOW = frozenset({"src/quantbt/endpoint.py",
    *["src/quantbt/optimization/meta_selection/" + n for n in ("config.py", "runtime.py")],
    *["src/quantbt/optimization/meta_selection/domains/" + n for n in
      ("registry.py", "scalar.py", "scalar_contract.py", "reactive.py")]})


def without_e03_scalar(source, name):
    if name not in ALLOW:
        return source
    original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT, capture_output=True)
    before = original.stdout if original.returncode == 0 else b""
    if source == before:
        return source
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get("baseline") != ENTRY or set(manifest.get("source_sha256", {})) != ALLOW:
        raise AssertionError("E03 reviewed manifest scope mismatch")
    if sha256(source).hexdigest() != manifest["source_sha256"][name]:
        raise AssertionError(f"unreviewed E03 scalar bytes: {name}")
    return before


def verify():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY,
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard",
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    if names != ALLOW:
        raise AssertionError(f"E03 unreviewed/missing production changes: {sorted(names ^ ALLOW)}")
    for name in names:
        without_e03_scalar((ROOT / name).read_bytes(), name)
    protected = ("rust", "src/quantbt/core", "src/quantbt/sizing", "src/quantbt/backtester.py",
        "src/quantbt/engines.py", "pyproject.toml", "uv.lock", "contracts",
        "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md")
    if subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", *protected], cwd=ROOT):
        raise AssertionError("E03 financial/math/native/release identity changed")
    return dict(schema="qms-e03-exact-source-v1", baseline=ENTRY,
        source_sha256=json.loads(MANIFEST.read_text())["source_sha256"],
        financial_numeric_source_unchanged=True, publication=False)
