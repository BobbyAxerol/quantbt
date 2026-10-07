"""Exact window-binding repair; no old scientific/source receipt is rewritten."""

import subprocess
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "feb61e1"
NAME = "src/quantbt/wfo_execution.py"
BASE = "src/quantbt/optimization/meta_selection/domains/base.py"
PATCH = b'''        # This endpoint requires exact-window rates; retain its strict guard.
        if isinstance(config.funding_rate, pd.Series):
            if not config.funding_rate.index.is_unique:
                raise ValueError("funding series index must be unique")
            endpoint = QuantBTEndpoint(replace(config, funding_rate=config.funding_rate.loc[output.index]))
'''
BASE_PATCH = b'''        from collections.abc import Mapping
        funding_source = execution.funding_rate
        if isinstance(funding_source, Mapping):
            funding_source = {s: "aligned_series" if hasattr(v, "index") else v
                              for s, v in funding_source.items()}
'''


def without_intrabar_window_funding(source):
    before = subprocess.check_output(["git", "show", f"{ENTRY}:{NAME}"], cwd=ROOT)
    if source == before:
        return source
    if source.count(PATCH) != 1 or source.replace(PATCH, b"", 1) != before:
        raise AssertionError("unreviewed PRE02 execution-window bytes")
    return before


def verify():
    from tools.qms_pre03_source_guard import ALLOW as later_allow, verify as later_verify
    from tools.qms_pre04_source_guard import ALLOW as pre04_allow
    later_allow = later_allow | pre04_allow
    names = subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
                                    cwd=ROOT, text=True).splitlines()
    names += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", "src", "rust"],
                                    cwd=ROOT, text=True).splitlines()
    later = set(names) & later_allow
    if later:
        later_verify()
    if set(names) != {NAME, BASE} | later:
        raise AssertionError("PRE02 runtime repair must be limited to exact funding bindings")
    for name in names:
        without_pre02_repairs((ROOT/name).read_bytes(), name)
    return dict(baseline=ENTRY, scope="exact intrabar-window and funding-source bindings only",
                scientific_estimator_changed=False, native_kernel_changed=False,
                later_source_amendment="PRE03_APPROVED_NESTED_SCALAR" if later else None)


def without_pre02_repairs(source, name):
    from tools.qms_pre03_source_guard import without_pre03
    source = without_pre03(source, name)
    if name == NAME:
        return without_intrabar_window_funding(source)
    if name != BASE:
        return source
    before = subprocess.check_output(["git", "show", f"{ENTRY}:{BASE}"], cwd=ROOT)
    if source == before:
        return source
    if source.count(BASE_PATCH) != 1:
        raise AssertionError("unreviewed PRE02 funding-source bytes")
    normalized = source.replace(BASE_PATCH, b"", 1).replace(
        b'else funding_source}),', b'else execution.funding_rate}),', 1)
    if normalized != before:
        raise AssertionError("unreviewed PRE02 funding-source bytes")
    return before


def verify_pre01_archive(payload):
    """Certify the frozen PRE01 commit, not today's amended financial source."""
    name = "benchmarks/optimization/meta_selection/qms_pre_e06_01_inventory.json"
    archived = json.loads(subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT))
    if payload != archived:
        raise ValueError("PRE-E06 inventory is incomplete, tampered or stale")
    for path, expected in {**archived["source_and_test_sha256"], **archived["documentation_sha256"]}.items():
        content = subprocess.check_output(["git", "show", f"{ENTRY}:{path}"], cwd=ROOT)
        if sha256(content).hexdigest() != expected:
            raise ValueError("PRE01 archive hash mismatch")
    return payload


def verify_pre01_patch():
    from tools.qms_pre_e06_inventory import ENTRY as PRE01_ENTRY, PATCH_ALLOW, check_public_text
    names = subprocess.check_output(["git", "diff", "--name-only", PRE01_ENTRY, ENTRY], cwd=ROOT,
                                    text=True).splitlines()
    if set(names)-PATCH_ALLOW:
        raise ValueError("non-phase file in historical PRE01 patch")
    for name in names:
        diff = subprocess.check_output(["git", "diff", "--unified=0", PRE01_ENTRY, ENTRY, "--", name],
                                       cwd=ROOT, text=True)
        check_public_text("\n".join(line[1:] for line in diff.splitlines()
                                   if line.startswith("+") and not line.startswith("+++")))
    return True
