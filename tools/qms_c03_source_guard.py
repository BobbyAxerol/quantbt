"""Exact approved C03 sampler adapters; no accounting/math/RNG implementation edits."""

from hashlib import sha256
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "b2c6225"
REVIEWED = "63ab385"
ALLOW = frozenset({
    "src/quantbt/backends/reactive_wfo.py",
    "src/quantbt/backends/reactive_wfo_batch_selection.py",
    "src/quantbt/backends/reactive_wfo_sampling.py",
})


def validate_changes(names):
    forbidden = set(names) - ALLOW
    if forbidden:
        raise AssertionError(f"unapproved C03 production source change: {sorted(forbidden)}")


def without_c03_sampler(source, name):
    if name not in ALLOW:
        return source
    reviewed = subprocess.check_output(["git", "show", f"{REVIEWED}:{name}"], cwd=ROOT)
    if source != reviewed:
        raise AssertionError(f"unapproved C03 sampler adapter source: {name}")
    original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT,
                              capture_output=True, check=False)
    return original.stdout if original.returncode == 0 else source


def verify():
    from tools.qms_c04_source_guard import ALLOW as C04_ALLOW, verify as verify_c04
    from tools.qms_e01_source_guard import NAME as E01_NAME
    c04 = verify_c04()
    names = subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
                                    cwd=ROOT, text=True).splitlines()
    validate_changes(set(names) - C04_ALLOW - {E01_NAME})
    for name in set(names) - C04_ALLOW - {E01_NAME}:
        without_c03_sampler((ROOT / name).read_bytes(), name)
    if subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "pyproject.toml",
        "uv.lock", "contracts", "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"], cwd=ROOT):
        raise AssertionError("C03 changed scientific guide or release/dependency identity")
    return dict(schema="qms-c03-source-guard-v1", baseline=ENTRY, reviewed=REVIEWED,
        allowed_changes=sorted(set(names) - C04_ALLOW - {E01_NAME}), financial_rust_unchanged=True, shared_sampler_math_unchanged=True,
        exact_adapter_sha256={name: sha256((ROOT / name).read_bytes()).hexdigest() for name in names if name in ALLOW},
        later_c04_additions=c04)
