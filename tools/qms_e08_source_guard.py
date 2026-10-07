"""Byte-exact output/metadata amendments; historical receipts stay historical."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "0da632e"
E07_ENTRY = "1a0f892"
RUNTIME = "src/quantbt/optimization/meta_selection/runtime.py"
MANIFEST = ROOT / "benchmarks/optimization/meta_selection/qms_e08_reviewed_source.json"
GUIDE = "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
GUIDE_SHA = "adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d"
ALLOW = frozenset({"src/quantbt/wfo_execution.py",
                   "src/quantbt/optimization/meta_selection/telemetry.py"})


def baseline(name, entry=ENTRY):
    return subprocess.check_output(["git", "show", f"{entry}:{name}"], cwd=ROOT)


def without_e08(source, name):
    if name not in ALLOW:
        return source
    before = baseline(name)
    if source == before:
        return before
    manifest = json.loads(MANIFEST.read_text())
    if (manifest.get("baseline") != ENTRY
            or set(manifest.get("source_sha256", {})) != ALLOW
            or manifest["source_sha256"][name] != sha256(source).hexdigest()):
        raise AssertionError(f"unreviewed E08 metadata amendment: {name}")
    return before


def without_e07_e08(source, name):
    source = without_e08(source, name)
    if name != RUNTIME:
        return source
    before = baseline(name, E07_ENTRY)
    after = baseline(name)
    if source not in (before, after):
        raise AssertionError("unreviewed E07 output amendment")
    return before


def verify():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--",
        "src", "rust", "pyproject.toml", "MANIFEST.in", "uv.lock", "contracts"],
        cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard",
        "--", "src", "rust", "contracts"], cwd=ROOT, text=True).splitlines())
    if names != ALLOW:
        raise AssertionError(f"unreviewed E08 runtime scope: {sorted(names ^ ALLOW)}")
    for name in ALLOW:
        assert without_e08((ROOT / name).read_bytes(), name) == baseline(name)
    if sha256((ROOT / GUIDE).read_bytes()).hexdigest() != GUIDE_SHA:
        raise AssertionError("scientific guide changed")
    return dict(schema="qms-e08-exact-source-guard-v1", baseline=ENTRY,
        source_sha256={n: sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(ALLOW)},
        scientific_or_accounting_changed=False, native_rebuild_required=False, publication=False)


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
