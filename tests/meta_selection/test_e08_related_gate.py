"""Local integrated consumers cannot execute an unregistered checkout program."""

import json
from types import SimpleNamespace

import pytest

from tools.qms_e08_related_consumer import consume


@pytest.mark.parametrize("consumer", ("../private.py", "/tmp/private.py", "qms_unknown.py"))
def test_unregistered_consumer_rejected_before_runtime_import(tmp_path, consumer):
    manifest = tmp_path/"manifest.json"
    manifest.write_text(json.dumps(dict(allowed_consumers=["qms08_consumer.py"])))
    with pytest.raises(ValueError, match="unregistered"):
        consume(SimpleNamespace(manifest=manifest, consumer=consumer))
