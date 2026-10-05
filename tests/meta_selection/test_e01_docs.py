"""E01-T03: scoped anchor/summary validation, not a retrospective receipt rewrite."""

from pathlib import Path

import pytest

from tools.check_docs_links import markdown_anchors, validate_links

ROOT = Path(__file__).resolve().parents[2]
CURRENT = [ROOT / "handoff/WFO_META_CURRENT.md", *[ROOT / "docs/meta_selection" / name for name in (
    "QUALIFICATION.md", "RELEASE_HANDOFF.md", "RELEASE_GAP_REPORT.md", "QMSE01_REPORT.md")]]


def test_e01_t03_current_links_and_fragments_exist():
    assert validate_links(ROOT, check_anchors=True, files=CURRENT) == []


@pytest.mark.parametrize("link", ["#missing", "target.md#missing", "target.md#fresh-heading-9"])
def test_e01_t03_negative_anchor_fixtures_are_rejected(tmp_path, link):
    (tmp_path / "target.md").write_text("# Fresh Heading\n<a id='legacy-anchor'></a>\n")
    source = tmp_path / "source.md"
    source.write_text(f"# Source\n[broken]({link})\n")
    assert len(validate_links(tmp_path, check_anchors=True, files=[source])) == 1
    assert validate_links(tmp_path, files=[source]) == []


def test_e01_t03_explicit_legacy_and_unicode_duplicate_headers_are_valid(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("# New Heading\n<a id='old-heading'></a>\n# Kiểm tra `RNG`\n# New Heading\n")
    source = tmp_path / "source.md"
    source.write_text("[legacy](target.md#old-heading) [repeat](target.md#new-heading-1)\n"
                      "[unicode](target.md#ki%E1%BB%83m-tra-rng)\n")
    assert validate_links(tmp_path, check_anchors=True, files=[source]) == []
    assert "qms-capability-gap-roadmap---planning_only" in markdown_anchors((ROOT / "upgrade/implement.md").read_text())


def test_e01_t03_code_and_comments_are_not_live_anchors_or_links(tmp_path):
    path = tmp_path / "example.md"
    path.write_text("# Real\n```markdown\n# Fake\n[missing](absent.md#none)\n```\n"
                    "<!-- <a id='hidden'></a> [missing](absent.md) -->\n[real](#real)\n")
    assert validate_links(tmp_path, check_anchors=True) == []
    assert markdown_anchors(path.read_text()) == {"real"}


def test_e01_t03_current_handoff_does_not_claim_c02_c05_are_planning_only():
    current = (ROOT / "handoff/WFO_META_CURRENT.md").read_text().split("## Historical Local Debt Closure")[0]
    assert "C02-C05\nremain planning-only" not in current
    assert all(label in current for label in ("C02 transport", "C03 samplers", "C04 continuation", "C05 geometry"))
    assert "NOT_ACTIVATED" in current and "new source/artifact qualification" in current
