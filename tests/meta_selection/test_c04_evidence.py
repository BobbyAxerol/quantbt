"""C04-T06 independently verifies actual retained artifact/cost evidence."""

import json

import pytest

from tools.qms_c04_gate import ROOT, qualify, verify_cost, verify_package
from tools.qms_c04_source_guard import verify

COST = ROOT / "benchmarks/optimization/meta_selection/qms_c04_continuation_evidence.json"


def test_c04_t06_installed_proof_cannot_certify_a_publication(tmp_path):
    # The actual installed proof runs in the separate artifact gate; source
    # tests must never depend on ignored VPS-specific build directories.
    actual = {"source_guard": verify(), "publication": True, "native_rebuilt": False}
    path = tmp_path / "not-a-proof.json"
    path.write_text(json.dumps(actual))
    with pytest.raises(ValueError, match="source/scope"):
        verify_package(path)


def test_c04_t06_retained_cost_exact_future_sequence():
    actual = verify_cost(COST)
    assert len(actual["cells"]) == 8


def test_c04_t06_cost_claim_or_missing_sampler_evidence_fails(tmp_path):
    actual = json.loads(COST.read_text())
    actual["economic_claim"] = True
    path = tmp_path / "bad-cost.json"
    path.write_text(json.dumps(actual))
    with pytest.raises(ValueError, match="unsupported"):
        verify_cost(path)


def test_c04_t06_package_source_mismatch_fails(tmp_path):
    actual = {"source_guard": {"reviewed": "unreviewed-source"}}
    path = tmp_path / "bad-package.json"
    path.write_text(json.dumps(actual))
    with pytest.raises(ValueError, match="source/scope"):
        verify_package(path)


@pytest.mark.parametrize("body", ["", '<testcase name="x"><failure/></testcase>',
                                 '<testcase name="x"><skipped/></testcase>', '<testcase name="x"/>'])
def test_c04_t06_nonpassing_or_missing_required_tests_is_not_certification(tmp_path, body):
    path = tmp_path / "tests.xml"
    path.write_text(f"<testsuite>{body}</testsuite>")
    with pytest.raises(ValueError, match="passing regression|required test IDs"):
        qualify(junit=[path], package=None, cost=None, check_proof=None)
