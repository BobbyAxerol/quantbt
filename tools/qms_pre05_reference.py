"""Benchmark-only exact entry blocks; never a production backend/fallback."""

from contextlib import contextmanager
from hashlib import sha256
from functools import lru_cache
import inspect
import subprocess
import sys

from tools.qms_pre05_workloads import ENTRY, ROOT

BLOCKS = (
    "src/quantbt/optimization/meta_selection/common.py",
    "src/quantbt/optimization/meta_selection/witness.py",
)


@lru_cache(maxsize=1)
def sources():
    return {
        name: (
            subprocess.check_output(["git", "show", ENTRY + ":" + name], cwd=ROOT),
            (ROOT / name).read_bytes(),
        )
        for name in BLOCKS
    }


def entry_module(module, name, *, optimized=False):
    source = sources()[name][bool(optimized)]
    namespace = dict(module.__dict__)
    exec(compile(source, name + "@" + ENTRY, "exec"), namespace)
    # Exceptions retain the current type; only identical portable block bodies vary.
    namespace["MetaRecordError"] = module.MetaRecordError
    return namespace, sha256(source).hexdigest()


@contextmanager
def baseline_blocks(*, optimized=False):
    from quantbt.optimization.meta_selection import common, witness

    old, common_sha = entry_module(common, BLOCKS[0], optimized=optimized)
    functions = {
        id(getattr(common, n)): old[n]
        for n in ("wire", "canonical", "digest", "freeze")
    }
    originals = {
        id(old[n]): getattr(common, n)
        for n in ("wire", "canonical", "digest", "freeze")
    }
    saved = []
    for name, module in tuple(sys.modules.items()):
        if name.startswith("quantbt.") and module is not None:
            for attr, value in tuple(vars(module).items()):
                if id(value) in functions:
                    saved.append((module, attr, value))
                    setattr(module, attr, functions[id(value)])
    previous, witness_sha = entry_module(witness, BLOCKS[1], optimized=optimized)
    previous["digest"] = old["digest"]
    owner = witness.PreparedMetricWitness
    names = (
        "__init__",
        "_get",
        "calendar_key",
        "_owned_prefix",
        "market_signature",
        "header",
        "validate_source",
        "metadata",
        "close",
    )
    descriptors = {n: inspect.getattr_static(owner, n) for n in names}
    for n in names:
        setattr(owner, n, inspect.getattr_static(previous["PreparedMetricWitness"], n))
    try:
        yield dict(zip(BLOCKS, (common_sha, witness_sha), strict=True))
    finally:
        for n, v in descriptors.items():
            setattr(owner, n, v)
        for module, attr, value in saved:
            setattr(module, attr, value)
        # Restore aliases imported lazily during the reference call too.
        for name, module in tuple(sys.modules.items()):
            if name.startswith("quantbt.") and module is not None:
                for attr, value in tuple(vars(module).items()):
                    if id(value) in originals:
                        setattr(module, attr, originals[id(value)])
