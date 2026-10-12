# M5-11 IDE And Cache Maintenance

## Scope

The owner approved temporarily stopping Pylance and unused notebooks to regain
research headroom. This is operational maintenance, not a scientific or package
qualification. Research execution, source07, objective, RNG and accounting were
not modified.

## Actions

- Verified the original Pylance PID/start identity and signalled only that
  process using a PID file descriptor. VS Code automatically relaunched it.
- Temporarily paused the verified replacement Pylance rather than stopping the
  extension host, which also hosts the active coding session.
- Host process census found no Jupyter kernel or notebook server. No kernel
  needed resetting; no notebook file, saved output or user data was deleted.
- Removed only inactive, reproducible `rust/target/debug/incremental` and
  `/root/.cache/ipython/numba_cache`, after source-pin and host FD/maps/cwd checks.
- Retained current tooling, virtualenvs, offline dependencies, installed
  extensions, native libraries, wheel/sdist artifacts, logs and research evidence.
- Verified protected source/artifact hashes and running research-worker and
  extension-host identities after cleanup.

## Measurements

| Measurement | Bytes | GiB/MiB |
|---|---:|---:|
| Actual immediate filesystem improvement | 151,236,608 | 144.230 MiB |
| Available RAM before reset | 2,343,555,072 | 2.183 GiB |
| Available RAM immediately after reset | 4,483,686,400 | 4.176 GiB |
| Available RAM after replacement pause | 3,726,635,008 | 3.471 GiB |
| Available disk after cleanup | 18,732,498,944 | 17.446 GiB |

Host measurements include concurrent research activity. The immediate 2-GiB
increase was partly consumed by VS Code's automatic Pylance restart; the paused
replacement retains its already-allocated memory. These numbers are not changes
to QuantBT runtime RSS. No Linux page-cache dropping or global cache prune ran.

## Receipts And Resume

Private operational receipt SHA256:
`551d7027747c1dcb49296e65e8e42f93d93f56a72022b0788b4724317692e47b`.
Pause receipt SHA256:
`c998c62c143b62d2f690a4ce8f11b264ce9bab5999316e768b3e0c641f9782c4`.

The earlier system-Python `hashlib.file_digest` compatibility failure happened
before any signal or deletion and remains recorded; the separate compatible
helper revision completed the action.

Pylance may be resumed after the heavy studies. The captured replacement PID is
`4161742`, start ticks `81093574`, with the verified Pylance server command.
Before using `kill -CONT 4161742`, verify it still identifies that same process;
do not signal a reused PID. Reloading the Python language service from VS Code
is also appropriate after research resource use has ended. This maintenance
does not permanently disable extensions or alter VS Code configuration.
