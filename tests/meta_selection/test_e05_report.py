"""Receipt renderer exposes open gates, never economic claims from tests."""

from tools.qms_e05_report import render


def test_e05_t06_report_keeps_scientific_empirical_and_public_gates_open():
    text = render({"tests": {"distinct_tests": 50}})
    assert "50 distinct checks PASS" in text
    for word in ("Not empirical promotion", "E03-G01", "separate approval",
                 "insufficient history", "not fabricated bars", "unchanged"):
        assert word in text
