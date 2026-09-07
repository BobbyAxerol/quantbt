from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.check_release_artifacts import inspect_artifact  # noqa: E402
from tools.scan_public_secrets import content_matches  # noqa: E402
from tools.check_canonical_source_layout import root_mirror_regrowth  # noqa: E402


def test_phase48b_retired_mirror_cannot_regrow_and_excludes_root_benchmarks() -> None:
    assert root_mirror_regrowth(PROJECT_ROOT) == []
    assert (PROJECT_ROOT / "benchmarks").is_dir()


def test_phase48b_canonical_layout_check_mode_and_agent_plan_visibility() -> None:
    tool = PROJECT_ROOT / "tools" / "check_canonical_source_layout.py"
    completed = subprocess.run(
        [sys.executable, str(tool), "--check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "canonical source layout/no-regrowth gate: PASS" in completed.stdout

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "upgrade/implement.md"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0

    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", "upgrade/implement.md"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.returncode != 0, ignored.stdout


def test_phase48b_gitignore_keeps_public_engineering_files_visible() -> None:
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "upgrade/\n" not in text
    assert "benchmarks/\n" not in text
    assert "upgrade/private/" in text
    assert "benchmarks/**/profiles/" in text
    assert ".pypirc" in text


def test_phase48b_release_workflows_run_visibility_and_artifact_gates() -> None:
    workflow_root = PROJECT_ROOT / ".github" / "workflows"
    for name in ("ci.yml", "publish-testpypi.yml", "publish.yml"):
        text = (workflow_root / name).read_text(encoding="utf-8")
        assert "git ls-files --error-unmatch upgrade/implement.md" in text
        assert 'tools/scan_public_secrets.py" --root "$GITHUB_WORKSPACE' in text
        assert 'tools/check_release_artifacts.py" --dist "$GITHUB_WORKSPACE/dist' in text


def test_phase48b_manifest_has_sdist_private_path_prunes() -> None:
    text = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for private_path in ("upgrade/private", "upgrade/local", "upgrade/drafts", "data/private"):
        assert f"prune {private_path}" in text
    assert "global-exclude .pypirc" in text


def test_phase48b_secret_scan_uses_high_confidence_patterns() -> None:
    assert content_matches("docs/example.md", b"token and password are documented") == []
    findings = content_matches("notes.txt", b"pypi-" + b"A" * 40)
    assert len(findings) == 1
    assert "credential-like content" in findings[0]
    assert content_matches("credentials/prod.json", b"{}")


def test_phase48b_artifact_gate_rejects_secret_path_and_non_core_member(tmp_path: Path) -> None:
    artifact = tmp_path / "quantbt_engine-1.0.7-py3-none-any.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("quantbt/__init__.py", "")
        archive.writestr("quantbt_engine-1.0.7.dist-info/METADATA", "")
        archive.writestr("quantbt/.env", "TOKEN=secret")
        archive.writestr("private/readme.txt", "not package source")

    findings = inspect_artifact(artifact)

    assert any("secret-like archive path" in finding for finding in findings)
    assert any("non-core wheel member" in finding for finding in findings)
