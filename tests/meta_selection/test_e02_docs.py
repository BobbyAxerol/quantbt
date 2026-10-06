"""Current E02 completion/admission docs, separate from immutable earlier reports."""

from hashlib import sha256
from pathlib import Path

from tools.check_docs_links import validate_links
from tools.qms01_baseline import GUIDE, GUIDE_SHA

ROOT = Path(__file__).resolve().parents[2]


def test_e02_final_docs_links_and_explicit_phase_anchors():
    names = ("upgrade/implement.md", "handoff/WFO_META_CURRENT.md", *[
        "docs/meta_selection/"+n+".md" for n in ("QMSE02_REPORT", "DOMAIN_ADAPTER_CONTRACT",
        "DOMAIN_EMPIRICAL_REGISTRATION", "INTEGRATION", "USAGE", "QUALIFICATION", "RELEASE_HANDOFF")])
    assert validate_links(ROOT, check_anchors=True, files=[ROOT/n for n in names]) == []


def test_e02_final_current_summary_is_complete_without_authorizing_next_phase():
    plan = (ROOT/"upgrade/implement.md").read_text()
    e02 = plan.split('#### QMS-E02 -', 1)[1].split('<a id="qms-e03">', 1)[0]
    assert "COMPLETE_LOCAL_APPROVED_SCOPE" in e02
    assert "AUTHORIZED_IN_PROGRESS" not in e02
    current = (ROOT/"handoff/WFO_META_CURRENT.md").read_text().split("## Historical Local Debt Closure")[0]
    assert "no E02-E08 execution is authorized" not in current
    assert "E06-E08 are unapproved" in current
    assert "E05 bounded software and installed proofs are complete" in current
    assert "E03 is now authorized" in current


def test_e02_final_docs_preserve_original_guide_and_separate_empirical_promotion():
    assert sha256((ROOT/GUIDE).read_bytes()).hexdigest() == GUIDE_SHA
    contract = (ROOT/"docs/meta_selection/DOMAIN_ADAPTER_CONTRACT.md").read_text()
    assert "No new real-alpha study" in contract
    template = (ROOT/"docs/meta_selection/DOMAIN_EMPIRICAL_REGISTRATION.md").read_text()
    assert "Q" in template and "owner" in template.lower()
    assert "C01/C05" in contract


def test_e02_final_docs_disclose_resource_overhead_and_correct_current_mode2_flag():
    report = (ROOT/"docs/meta_selection/QMSE02_REPORT.md").read_text()
    assert all(value in report for value in ("+5.23%", "+2.25%", "+1.22%", "not speed improvement"))
    integration = (ROOT/"docs/meta_selection/INTEGRATION.md").read_text()
    assert "E01 corrected its legacy false" in integration
    assert "despite its legacy top-level\nfalse flag" not in integration
