from __future__ import annotations

import subprocess
import sys
from unittest.mock import Mock

import pytest

from tools import run_test_shards


@pytest.fixture
def shards(monkeypatch):
    paths = [run_test_shards.TEST_ROOT / f"test_sample_{number}.py" for number in range(3)]
    collect = Mock(return_value=[paths[:2], paths[2:]])
    monkeypatch.setattr(run_test_shards, "_collect", collect)
    return paths, collect


def mock_runs(monkeypatch, codes):
    run = Mock(side_effect=[subprocess.CompletedProcess([], code) for code in codes])
    monkeypatch.setattr(run_test_shards.subprocess, "run", run)
    return run


@pytest.mark.parametrize("code", [1, 2, -9])
def test_default_stops_at_first_failure(monkeypatch, shards, capsys, code):
    run = mock_runs(monkeypatch, [0, code, 0])
    assert run_test_shards.main(["--max-files-per-shard", "1"]) == code
    assert run.call_count == 2
    assert "[3]" not in capsys.readouterr().out


@pytest.mark.parametrize("codes, expected", [([1, 0, 2], 1), ([-9, 0, 1], 137), ([0, 0, 5], 5)])
def test_keep_going_runs_every_shard_and_reports_failures(monkeypatch, shards, capsys, codes, expected):
    paths, collect = shards
    run = mock_runs(monkeypatch, codes)
    assert run_test_shards.main(["--profile", "ci-core", "--max-files-per-shard", "1", "--keep-going"]) == expected
    collect.assert_called_once_with("ci-core")
    assert run.call_count == len(paths)
    output = capsys.readouterr().out
    assert "completed 3 isolated pytest shard(s)" in output
    assert f"failed {sum(code != 0 for code in codes)} of 3 isolated pytest shard(s):" in output
    for number, (path, code, call) in enumerate(zip(paths, codes, run.call_args_list), start=1):
        relative = str(path.relative_to(run_test_shards.PROJECT_ROOT))
        assert call.args[0] == [sys.executable, "-m", "pytest", "-q", relative]
        assert call.kwargs["cwd"] == run_test_shards.PROJECT_ROOT
        assert call.kwargs["check"] is False
        assert "MPLCONFIGDIR" in call.kwargs["env"]
        summary = f"[{number}] exit code {code}: {relative}"
        assert (summary in output) == bool(code)


@pytest.mark.parametrize("flags", [[], ["--keep-going"]])
def test_all_pass(monkeypatch, shards, capsys, flags):
    run = mock_runs(monkeypatch, [0, 0, 0])
    assert run_test_shards.main(["--max-files-per-shard", "1", *flags]) == 0
    assert run.call_count == 3
    output = capsys.readouterr().out
    assert output.endswith("completed 3 isolated pytest shard(s)\n")
    assert "failed" not in output


def test_list_unchanged_with_keep_going(monkeypatch, shards, capsys):
    run = mock_runs(monkeypatch, [])
    args = ["--max-files-per-shard", "1", "--list"]
    assert run_test_shards.main(args) == 0
    expected = capsys.readouterr().out
    assert run_test_shards.main([*args, "--keep-going"]) == 0
    assert capsys.readouterr().out == expected
    assert "[3]" in expected
    assert expected.endswith("completed 3 isolated pytest shard(s)\n")
    run.assert_not_called()


def test_fork_parent_file_is_a_singleton_without_reordering_or_omitting_tests(tmp_path, monkeypatch):
    paths = ["test_a.py", "meta_selection/test_pre04_public.py", "meta_selection/test_z.py",
             "options/test_option.py", "native_event/test_native.py", "test_real.py"]
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(run_test_shards, "TEST_ROOT", tmp_path)
    groups = run_test_shards._collect("ci-core")
    flat = [path.relative_to(tmp_path).as_posix() for group in groups for path in group]
    assert flat == ["meta_selection/test_pre04_public.py", "meta_selection/test_z.py", "test_a.py", "options/test_option.py"]
    assert len(flat) == len(set(flat))
    assert next(group for group in groups if any(p.name == "test_pre04_public.py" for p in group)) == [tmp_path / paths[1]]


def test_fork_thread_limit_is_child_local_not_global(monkeypatch):
    special = run_test_shards.TEST_ROOT / "meta_selection/test_pre04_public.py"
    regular = run_test_shards.TEST_ROOT / "test_regular.py"
    monkeypatch.setattr(run_test_shards, "_collect", lambda profile: [[special], [regular]])
    names = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS")
    for name in names:
        monkeypatch.setenv(name, "4")
    run = mock_runs(monkeypatch, [0, 0])
    assert run_test_shards.main(["--profile", "ci-core"]) == 0
    assert all(run.call_args_list[0].kwargs["env"][name] == "1" for name in names)
    assert all(run.call_args_list[1].kwargs["env"][name] == "4" for name in names)


def test_host_suite_is_singleton_without_omitting_other_files(tmp_path, monkeypatch):
    names = ["test_before.py", "test_mode5_research_jobs.py", "test_z.py"]
    for name in names:
        (tmp_path / name).touch()
    monkeypatch.setattr(run_test_shards, "TEST_ROOT", tmp_path)
    groups = run_test_shards._collect("ci-core")
    assert [[p.name for p in group] for group in groups] == [[name] for name in names]


@pytest.mark.parametrize("sudo,uid,expected_prefix", [(False, 1000, []), (True, 0, []),
                                                    (True, 1000, ["sudo", "-n", "--"])])
def test_privilege_is_explicit_and_only_for_fake_worker_host_suite(monkeypatch, sudo, uid, expected_prefix):
    host = run_test_shards.TEST_ROOT / "test_mode5_research_jobs.py"
    regular = run_test_shards.TEST_ROOT / "test_regular.py"
    monkeypatch.setattr(run_test_shards, "_collect", lambda profile: [[host], [regular]])
    monkeypatch.setattr(run_test_shards.os, "geteuid", lambda: uid)
    run = mock_runs(monkeypatch, [0, 0])
    assert run_test_shards.main(["--profile", "ci-core", *(["--sudo-host-tests"] if sudo else [])]) == 0
    host_command, regular_command = [call.args[0] for call in run.call_args_list]
    assert host_command == expected_prefix + [sys.executable, "-m", "pytest", "-q", str(host.relative_to(run_test_shards.PROJECT_ROOT))]
    assert regular_command == [sys.executable, "-m", "pytest", "-q", str(regular.relative_to(run_test_shards.PROJECT_ROOT))]


def test_host_privilege_cannot_expand_to_an_unrelated_file(monkeypatch):
    host = run_test_shards.TEST_ROOT / "test_mode5_research_jobs.py"
    other = run_test_shards.TEST_ROOT / "test_regular.py"
    monkeypatch.setattr(run_test_shards, "_collect", lambda profile: [[host, other]])
    run = mock_runs(monkeypatch, [])
    with pytest.raises(ValueError, match="dedicated singleton"):
        run_test_shards.main(["--sudo-host-tests"])
    run.assert_not_called()
