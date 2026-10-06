"""Exact owner-approved metric compatibility amendment, not a file exemption."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "51894c2"
MANIFEST = ROOT / "benchmarks/optimization/meta_selection/qms_g01_reviewed_source.json"
ALLOW = frozenset({
    "rust/crates/quantbt-engine/src/metrics_v2.rs",
    "rust/crates/quantbt-engine/src/lib.rs",
    "rust/crates/quantbt-execution/src/target.rs",
    "rust/native_event/src/lib.rs",
    "src/quantbt/backends/native_prepared_evaluation.py",
    "src/quantbt/backends/native_wfo_public.py",
    "src/quantbt/preparation/native_execution.py",
    "src/quantbt/preparation/native_target_requests.py",
})


def without_g01(source, name):
    if name not in ALLOW:
        return source
    original = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
    if source == original:
        return source
    manifest = json.loads(MANIFEST.read_text())
    if manifest["baseline"] != ENTRY or set(manifest["source_sha256"]) != ALLOW:
        raise AssertionError("G01 reviewed compatibility scope mismatch")
    if sha256(source).hexdigest() != manifest["source_sha256"][name]:
        raise AssertionError(f"unreviewed G01 compatibility bytes: {name}")
    return original


def protected_changes(entry, protected):
    names = subprocess.check_output(["git", "diff", "--name-only", entry,
        "--", *protected], cwd=ROOT, text=True).splitlines()
    remaining = []
    for name in names:
        current = without_g01((ROOT / name).read_bytes(), name)
        original = subprocess.run(["git", "show", f"{entry}:{name}"], cwd=ROOT, capture_output=True)
        if current != original.stdout:
            remaining.append(name)
    return remaining


def verify():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY,
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard",
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    if names != ALLOW:
        raise AssertionError(f"unreviewed/missing G01 production changes: {sorted(names ^ ALLOW)}")
    for name in names:
        without_g01((ROOT/name).read_bytes(), name)
    return dict(schema="qms-g01-exact-amendment-v1", baseline=ENTRY,
        source_sha256=json.loads(MANIFEST.read_text())["source_sha256"],
        compatibility_policy="legacy_zero_base_v1", native_default_unchanged=True,
        scientific_estimator_changed=False, financial_execution_changed=False,
        native_rebuild_required=True, publication=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    if parser.parse_args().seal_reviewed:
        MANIFEST.write_text(json.dumps(dict(baseline=ENTRY, source_sha256={
            name: sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(ALLOW)}),
            indent=2, sort_keys=True)+"\n")
    print(json.dumps(verify(), sort_keys=True))
