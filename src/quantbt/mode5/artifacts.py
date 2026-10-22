"""Cold-path evidence identities and exclusive immutable receipt writes."""
from hashlib import sha256
import json
from pathlib import Path


def file_identity(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected regular input: {path}")
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=digest.hexdigest())


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
