"""C02 permits witness/control adaptation, not economic or scientific changes."""

from hashlib import sha256
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "0bb77b5"
REVIEWED = "2b9f05a"
GUIDE = "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
GUIDE_SHA = "adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d"
ALLOW = frozenset({
    "src/quantbt/backends/_native_event_rust.py", "src/quantbt/backends/native_event.py",
    "src/quantbt/backends/reactive_wfo.py", "src/quantbt/backends/reactive_wfo_workers.py",
    "src/quantbt/backends/reactive_wfo_batch.py", "src/quantbt/endpoint.py",
    "src/quantbt/optimization/meta_selection/observer.py", "src/quantbt/optimization/meta_selection/reactive.py",
    "src/quantbt/optimization/meta_selection/reactive_transport.py",
    "src/quantbt/optimization/meta_selection/reactive_execution.py",
    "src/quantbt/optimization/meta_selection/reactive_batch_witness.py",
    "rust/native_event/src/reactive_numeric.rs",
})
TOKEN_GETTER = b'''    fn cancellation_tokens(&self, py: Python<'_>) -> PyResult<Vec<Py<ReactiveCancellationTokenCore>>> {
        self.candidates
            .iter()
            .map(|candidate| candidate.core.cancellation_token(py))
            .collect()
    }

'''


def validate_rust_control(source, original):
    if source.count(TOKEN_GETTER) != 1 or source.replace(TOKEN_GETTER, b"") != original:
        raise AssertionError("unapproved native financial/control source change")


def validate_changes(names):
    forbidden = set(names) - ALLOW
    if forbidden:
        raise AssertionError(f"unapproved C02 production source change: {sorted(forbidden)}")


def without_c02_witness(source, name):
    """Restore only exact, reviewed adapters before older economic byte gates.

    This never skips a protected module. An extra arithmetic/comment change
    fails rather than being hidden by the C02 file-name allowlist.
    """
    from tools.qms_c03_source_guard import without_c03_sampler
    source = without_c03_sampler(source, name)
    if name not in ALLOW:
        return source
    if name == "rust/native_event/src/reactive_numeric.rs":
        original = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
        validate_rust_control(source, original)
        return original
    original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT,
                              capture_output=True, check=False)
    reviewed = subprocess.check_output(["git", "show", f"{REVIEWED}:{name}"], cwd=ROOT)
    if source != reviewed:
        raise AssertionError(f"unapproved C02 witness adapter source: {name}")
    return original.stdout if original.returncode == 0 else source


def verify():
    from tools.qms_c03_source_guard import ALLOW as C03_ALLOW, verify as verify_c03
    c03 = verify_c03()
    names = subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
                                    cwd=ROOT, text=True).splitlines()
    validate_changes(set(names) - C03_ALLOW)
    for name in set(names) & ALLOW:
        without_c02_witness((ROOT / name).read_bytes(), name)
    name = "rust/native_event/src/reactive_numeric.rs"
    original = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
    validate_rust_control((ROOT / name).read_bytes(), original)
    if sha256((ROOT / GUIDE).read_bytes()).hexdigest() != GUIDE_SHA:
        raise AssertionError("detailed scientific guide changed")
    if subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--",
                                "pyproject.toml", "uv.lock", "contracts"], cwd=ROOT):
        raise AssertionError("C02 changed release/product identity")
    return dict(schema="qms-c02-source-guard-v1", baseline=ENTRY, allowed_changes=names,
                financial_rust_unchanged=True, additive_atomic_token_getter=True,
                guide_sha256=GUIDE_SHA, release_identity_unchanged=True, later_c03_adapters=c03)
