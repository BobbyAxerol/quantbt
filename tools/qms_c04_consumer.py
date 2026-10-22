"""Fresh installed four-recipe exact checkpoint continuation, never publishes."""

from hashlib import sha256
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys
import tempfile


def example_module(path):
    spec = importlib.util.spec_from_file_location("c04_installed_example", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def qualify(*, example, core_version, native_version):
    import quantbt
    import optuna
    import _quantbt_native as native
    from quantbt.optimization.continuation import ExactStudySession

    origin = Path(quantbt.__file__).resolve()
    assert "site-packages" in origin.parts
    assert metadata.version("quantbt-engine") == quantbt.__version__ == core_version
    assert metadata.version("quantbt-native") == native.version() == native_version
    module = example_module(example)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    with tempfile.TemporaryDirectory(prefix="c04-installed-") as workspace:
        rows = [module.prove(recipe, Path(workspace)) for recipe in module.RECIPES]
    assert all(row["fresh_process_exact"] for row in rows)
    assert all(row["states"] == ["COMPLETE", "FAIL", "PRUNED"] for row in rows)
    return dict(schema="qms-c04-installed-consumer-v1", core=core_version, native=native_version,
                core_origin=str(origin), python=sys.version, matrix=rows,
                example_sha256=sha256(Path(example).read_bytes()).hexdigest(),
                continuation_module=ExactStudySession.__module__,
                no_source_imports=True, no_financial_replay=True,
                scientific_or_economic_claim=False, publication=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    parser.add_argument("--core-version", required=True)
    parser.add_argument("--native-version", required=True)
    print(json.dumps(qualify(**vars(parser.parse_args())), sort_keys=True))
