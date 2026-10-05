"""Four recipes also preserve actual shadow/active witnesses through safe W3 IPC."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

from examples.wfo_reactive_samplers import RECIPES, configuration, execute
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from tools.qms_c03_consumer import accounts_equal


def matrix():
    import multiprocessing
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    for recipe in RECIPES:
        for mode in ("shadow", "active"):
            cfg = replace(configuration(recipe, schedule="per_fold_causal", trials=12),
                meta_selection=dict(mode=mode, native_batch_policy="require",
                                    min_matured_origins=1, label_observer=True))
            def run(worker):
                return execute(config=cfg, worker=worker,
                    meta_history=MetaHistoryContext(MetaHistory(), "C03-process", "BTC", "1D", "engineering"))
            local, process = run("inprocess"), run("process")
            accounts_equal(local, process)
            for a, b in zip(local.metadata["sampler_studies"], process.metadata["sampler_studies"], strict=True):
                assert a["rows"] == b["rows"] and a["ask_tell_digest"] == b["ask_tell_digest"]
            assert process.metadata["meta_selection"]["observer_failures"] == 0
    assert not multiprocessing.active_children()


def test_c03_t02_shadow_active_four_recipes_actual_safe_process():
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
        NUMBA_NUM_THREADS="1", PYTHONPATH=str(Path.cwd() / "src") + ":" + str(Path.cwd()))
    result = subprocess.run([sys.executable, "-c",
        "from tests.meta_selection.test_c03_meta_process import matrix; matrix()"],
        env=environment, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
