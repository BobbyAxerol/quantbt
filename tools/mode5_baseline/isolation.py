"""Bounded, manifest-first copies of untrusted research inputs."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


MAX_BYTES = 64 * 1024 * 1024


def file_identity(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected regular input: {path}")
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def canonical_digest(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def private_output(path: Path, allowed_roots, protected_roots=()) -> Path:
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink output is forbidden")
    resolved = path.resolve()
    protected = [Path(root).resolve() for root in protected_roots]
    if any(resolved == root or resolved.is_relative_to(root) for root in protected):
        raise ValueError("protected output is forbidden")
    roots = [Path(root).resolve() for root in allowed_roots]
    if not any(resolved.is_relative_to(root) and resolved != root for root in roots):
        raise ValueError("output must be a new private revision")
    if path.exists():
        raise ValueError("append-only revision already exists")
    return resolved


def write_json(path: Path, value) -> None:
    # Exclusive creation prevents silently rewriting historical receipts.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def zip_manifest(path: Path, *, max_bytes=MAX_BYTES) -> dict:
    source = file_identity(path)
    members, seen, total = [], set(), 0
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or ":" in name
                    or ".." in parts or "\x00" in name):
                raise ValueError("unsafe archive path")
            normalized = "/".join(parts)
            if parts[0] == "input-manifest.json":
                raise ValueError("reserved manifest member")
            if normalized in seen:
                raise ValueError("duplicate archive member")
            seen.add(normalized)
            mode = item.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("archive links/special files are forbidden")
            if item.flag_bits & 1:
                raise ValueError("encrypted archive is unsupported")
            total += item.file_size
            if total > max_bytes or len(seen) > 4096:
                raise ValueError("archive exceeds registered budget")
            excluded = "__pycache__" in parts or Path(name).suffix in {".pyc", ".pyo"}
            payload = archive.read(item) if not item.is_dir() else b""
            members.append({"name": normalized, "bytes": len(payload),
                            "sha256": sha256(payload).hexdigest(),
                            "directory": item.is_dir(), "excluded_bytecode": excluded})
    files = {row["name"] for row in members if not row["directory"]}
    if any(any(parent.as_posix() in files for parent in PurePosixPath(name).parents)
           for name in seen):
        raise ValueError("archive file/directory collision")
    return {"source": source, "members": members, "expanded_bytes": total}


def extract_reviewed_zip(path: Path, output: Path, *, allowed_roots, protected_roots=()) -> dict:
    output = private_output(output, allowed_roots, protected_roots)
    manifest = zip_manifest(path)
    output.mkdir(parents=True)
    write_json(output / "input-manifest.json", manifest)
    with zipfile.ZipFile(path) as archive:
        for info, row in zip(archive.infolist(), manifest["members"], strict=True):
            if row["excluded_bytecode"] or row["directory"]:
                continue
            target = output / row["name"]
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = archive.read(info)
            if sha256(payload).hexdigest() != row["sha256"]:
                raise ValueError("archive changed after manifest")
            with target.open("xb") as stream:
                stream.write(payload)
    if file_identity(path) != manifest["source"]:
        raise ValueError("archive changed after inspection")
    return manifest


def copy_reviewed_files(paths, output: Path, *, allowed_roots, protected_roots=()) -> dict:
    output = private_output(output, allowed_roots, protected_roots)
    identities = [file_identity(Path(path)) for path in paths]
    names = [Path(row["path"]).name for row in identities]
    if len(set(names)) != len(names) or sum(row["bytes"] for row in identities) > MAX_BYTES:
        raise ValueError("copy collision or budget exceeded")
    output.mkdir(parents=True)
    write_json(output / "input-manifest.json", {"files": identities})
    for row in identities:
        source = Path(row["path"])
        target = output / source.name
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
        if file_identity(source) != row or file_identity(target)["sha256"] != row["sha256"]:
            raise ValueError("copy identity changed")
        if source.stat().st_ino == target.stat().st_ino:
            raise ValueError("editable copy shares the protected inode")
    return {"files": identities, "hardlinks": False}


def copy_python_tree(source: Path, output: Path, *, allowed_roots, protected_roots=()) -> dict:
    output = private_output(output, allowed_roots, protected_roots)
    paths = sorted(source.rglob("*.py"))
    identities = [file_identity(path) | {"relative": path.relative_to(source).as_posix()}
                  for path in paths]
    if sum(row["bytes"] for row in identities) > MAX_BYTES:
        raise ValueError("copy budget exceeded")
    output.mkdir(parents=True)
    write_json(output / "input-manifest.json", {"files": identities})
    for row in identities:
        path = Path(row["path"])
        target = output / row["relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(path.read_bytes())
        if file_identity(target)["sha256"] != row["sha256"] or path.stat().st_ino == target.stat().st_ino:
            raise ValueError("invalid editable copy")
    return {"files": identities, "hardlinks": False, "bytecode_copied": False}
