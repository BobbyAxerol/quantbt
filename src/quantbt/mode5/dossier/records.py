"""Content-addressed immutable metadata, including copy/pickle round trips."""
from dataclasses import dataclass
import json

from quantbt.mode5.diagnostics.identity import canonical, digest


@dataclass(frozen=True)
class Record:
    payload: str

    def __post_init__(self):
        data = json.loads(self.payload)
        if not isinstance(data, dict) or canonical(data) != self.payload:
            raise ValueError("canonical JSON object required")

    @classmethod
    def of(cls, data):
        return cls(canonical(data))

    @property
    def data(self):
        return json.loads(self.payload)

    @property
    def identity(self):
        return digest(self.data)


def require_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("explicit nonempty identity/reason required")


def pointer(data, path):
    """RFC 6901 pointer into one hash-verified JSON source."""
    if path == "":
        return data
    if not path.startswith("/"):
        raise ValueError("absolute JSON pointer required")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data
