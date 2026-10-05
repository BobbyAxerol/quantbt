"""Only exact reviewed additive continuation modules may cross older gates."""

from hashlib import sha256
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "1a1f10d"
REVIEWED = "f3ab6cf"
ALLOW = frozenset("src/quantbt/optimization/continuation/" + name
                  for name in ("__init__.py", "contract.py", "session.py", "storage.py"))


def validate_changes(names):
    if set(names) - ALLOW:
        raise AssertionError(f"unapproved C04 production change: {sorted(set(names) - ALLOW)}")


def verify():
    from tools.qms_e01_source_guard import NAME as E01_NAME, verify as verify_e01
    verify_e01()
    names = subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
                                    cwd=ROOT, text=True).splitlines()
    names = [name for name in names if name != E01_NAME]
    validate_changes(names)
    hashes = {}
    for name in names:
        reviewed = subprocess.check_output(["git", "show", f"{REVIEWED}:{name}"], cwd=ROOT)
        if (ROOT / name).read_bytes() != reviewed:
            raise AssertionError(f"C04 unreviewed continuation bytes: {name}")
        hashes[name] = sha256(reviewed).hexdigest()
    if set(names) != ALLOW:
        raise AssertionError("C04 reviewed modules missing")
    protected = ("pyproject.toml", "uv.lock", "contracts",
                 "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md")
    if subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", *protected], cwd=ROOT):
        raise AssertionError("C04 changed release/dependency/scientific contract")
    return dict(schema="qms-c04-source-guard-v1", baseline=ENTRY, reviewed=REVIEWED,
                additive_module_sha256=hashes, financial_samplers_math_unchanged=True,
                public_endpoints_unchanged=True, release_identity_unchanged=True)
