"""Performance amendments cannot weaken historical source seals."""

import subprocess

import pytest

from tools import qms_pre05_source_guard as guard


def test_scope_is_portable_dispatch_only():
    assert guard.verify()["changed_runtime"] == sorted(guard.ALLOW)
    assert guard.verify()["native_rebuild_required"] is False


def test_mutating_one_reviewed_byte_is_rejected():
    name = next(iter(guard.ALLOW))
    source = (guard.ROOT / name).read_bytes()
    assert guard.without_pre05(source, name) == guard.baseline(name)
    with pytest.raises(AssertionError, match="unreviewed PRE05"):
        guard.without_pre05(source + b"\n# invalid scientific mutation\n", name)


def test_old_receipts_are_not_resealed():
    for phase in ("02", "03", "04"):
        for tail in ("reviewed_source", "closure"):
            if phase == "02" and tail == "reviewed_source":
                continue
            name = f"benchmarks/optimization/meta_selection/qms_pre_e06_{phase}_{tail}.json"
            old = subprocess.check_output(
                ["git", "show", f"{guard.ENTRY}:{name}"], cwd=guard.ROOT
            )
            assert (guard.ROOT / name).read_bytes() == old


def test_historical_normalizer_is_not_a_whole_file_exemption():
    from tools.qms_pre04_source_guard import verify

    assert len(verify()["changed_runtime"]) == 13
    name = next(iter(guard.ALLOW))
    assert guard.prior_names({name}, "ba61e63") == set()
    assert guard.without_pre05(b"unknown", "src/quantbt/walkforward.py") == b"unknown"
