"""One isolated installed-consumer command set shared by all release gates."""

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from tools.qms_release_consumers import CONSUMERS, EXAMPLES, consumer_arguments, validate_consumers


def source_hashes(root):
    names = ["tools/qms_installed_consumers.py", "tools/qms_release_consumers.py",
             *("tools/" + name for name in CONSUMERS),
             *("examples/" + name for name in EXAMPLES.values())]
    return {name: sha256((root / name).read_bytes()).hexdigest() for name in names}


def qualify(command_prefix, *, root, core, native, workspace, logs, environment=None, timeout=600):
    logs.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ if environment is None else environment,
               OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    records, retained = {}, {}
    for name in CONSUMERS:
        command = [*map(str, command_prefix), "-I", str(root / "tools" / name),
                   *consumer_arguments(name, core=core, native=native, examples=root / "examples")]
        log = logs / (name.removesuffix(".py") + ".log")
        try:
            process = subprocess.run(command, cwd=workspace, env=env, text=True,
                                     capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.write_text("$ " + " ".join(command) + "\n" + str(exc) + "\n")
            raise ValueError(f"installed QMS consumer failed to start/finish; see {log}") from exc
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"installed QMS consumer failed; see {log}")
        try:
            record = json.loads(process.stdout.splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"installed QMS consumer emitted invalid JSON; see {log}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"installed QMS consumer emitted a non-object; see {log}")
        records[name] = record
        retained[name] = dict(command=command, log_path=str(log),
                              log_sha256=sha256(log.read_bytes()).hexdigest())
    validate_consumers(records, core=core, native=native)
    return dict(consumers=records, logs=retained, consumer_source_sha256=source_hashes(root))
