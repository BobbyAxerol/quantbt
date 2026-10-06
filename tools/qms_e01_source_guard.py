"""Permit only the approved E01 reporting expression, never WFO arithmetic."""

from hashlib import sha256
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "5fecad2"
NAME = "src/quantbt/walkforward.py"
OLD = b'''            oos_used_for_selection = self.config.optimization_mode not in {
                "mode_2_sbb",
                "mode_4_is_only_robust",
                "mode_5_full_robust",
            } and self.config.candidate_selection_metric not in {
                "is_plateau_robust",
                "is_only_robust",
                "full_robust",
                "full_plateau_robust",
                "full_temporal_robust",
                "full_best",
            }
'''
NEW = b'''            oos_used_for_selection = bool(
                optimization_requested
                and selected_record.selection_metadata.get("stage") == "oos_candidate_selection"
                and selected_record.selection_metadata.get("selected_by")
                in {"robust_decay", "mean_oos_sharpe"}
            )
'''


def without_e01_provenance(source, name):
    from tools.qms_e02_source_guard import without_e02_adapter
    try:
        source = without_e02_adapter(source, name)
    except AssertionError as exc:
        raise AssertionError("unapproved E01 source outside reviewed later adapter") from exc
    if name != NAME:
        return source
    original = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
    assert original.count(OLD) == 1
    if source not in (original, original.replace(OLD, NEW)):
        raise AssertionError("unapproved E01 WFO change outside reporting expression")
    return original


def verify():
    from tools.qms_e02_source_guard import ALLOW as E02_ALLOW, verify as verify_e02
    verify_e02()
    from tools.qms_e02_source_guard import reviewed_scope
    E02_ALLOW = reviewed_scope()
    names = subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
                                    cwd=ROOT, text=True).splitlines()
    if set(names) - E02_ALLOW:
        raise AssertionError("E01 must change only the WFO reporting expression")
    from tools.qms_e02_source_guard import without_e02_adapter
    source = (ROOT / NAME).read_bytes()
    current = without_e02_adapter(source, NAME)
    original = without_e01_provenance(source, NAME)
    return dict(schema="qms-e01-source-guard-v1", baseline=ENTRY,
                before_sha256=sha256(original).hexdigest(), after_sha256=sha256(current).hexdigest(),
                search_account_rng_source_exact=True, report_only=True)
