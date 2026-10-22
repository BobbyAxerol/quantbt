"""Read exact historical test inputs without checking out or rebuilding a tree."""

from __future__ import annotations

from functools import cache
from hashlib import sha256
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]


class GitSnapshot:
    def __init__(self, commit: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("historical tests require a full immutable Git commit")
        self.commit = commit
        self._git("merge-base", "--is-ancestor", commit, "HEAD")

    def _git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout

    @cache
    def read_bytes(self, relative: str) -> bytes:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"not a repository-relative historical path: {relative}")
        return self._git("show", f"{self.commit}:{relative}")

    def read_json(self, relative: str) -> dict:
        return json.loads(self.read_bytes(relative))

    def assert_retained(self, relative: str) -> None:
        assert (ROOT / relative).read_bytes() == self.read_bytes(relative), relative

    def assert_record(self, record: dict) -> None:
        content = self.read_bytes(record["path"])
        assert sha256(content).hexdigest() == record["sha256"], record["path"]
        if "bytes" in record:
            assert len(content) == record["bytes"], record["path"]

    def source_identity(self) -> dict[str, str]:
        roots = ("src/quantbt", "rust/crates", "rust/native_event")
        extras = (
            "pyproject.toml", "rust/Cargo.toml", "rust/Cargo.lock",
            "contracts/native_event_product_registry.json",
            "contracts/native_event_contract_registry.json",
        )
        paths = self._git(
            "ls-tree", "-r", "--name-only", "-z", self.commit, "--", *roots, *extras
        ).decode("utf-8").split("\0")
        # Match measurement_contract._source_files, including every file type
        # and its relative-path/NUL framing, not just Python or registry files.
        digest = sha256()
        for relative in sorted(set(paths) - {""}):
            if {"target", "__pycache__"}.intersection(PurePosixPath(relative).parts):
                continue
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(self.read_bytes(relative))
            digest.update(b"\0")
        return {
            "canonical_source_sha256": digest.hexdigest(),
            "product_registry_sha256": sha256(self.read_bytes(extras[-2])).hexdigest(),
            "lifecycle_registry_sha256": sha256(self.read_bytes(extras[-1])).hexdigest(),
        }

    def materialize(self, destination: Path, paths: set[str]) -> None:
        contents = {relative: self.read_bytes(relative) for relative in paths}
        assert sum(map(len, contents.values())) <= 8 * 1024 * 1024
        for relative, content in contents.items():
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def load_module(self, destination: Path, relative: str):
        path = destination / relative
        specification = importlib.util.spec_from_file_location(
            f"historical_{self.commit}_{path.stem}", path
        )
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module
