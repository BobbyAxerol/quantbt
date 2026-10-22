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
