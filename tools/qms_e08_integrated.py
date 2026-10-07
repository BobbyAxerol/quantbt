"""Local integrated sampler, continuation and domain consumers, never publishing."""

import json
import os
from pathlib import Path
import subprocess

from tools.qms_e08_package import LANE
from tools.qms_installed_execution import ROOT, artifact_manifest, digest
from tools.qms_installed_consumers import source_hashes
from tools.qms_release_consumers import CONSUMERS, consumer_arguments, validate_consumers

EXTRA = {
    "qms_e03_consumer.py": "wfo_meta_scalar.py",
    "qms_e04_consumer.py": "wfo_meta_portfolio.py",
    "qms_e05_consumer.py": "wfo_meta_package.py",
    "qms_g01_consumer.py": None,
}


def qualify():
    proof = json.loads((LANE/"proof.json").read_text())
    directory = LANE/"integrated-proof"
    if directory.exists() or (LANE/"integrated-proof.json").exists():
        raise ValueError("refuse sealed integrated proof overwrite")
    directory.mkdir()
    manifest = artifact_manifest(proof)
    manifest["allowed_consumers"] = [*CONSUMERS, *EXTRA]
    names = ["tools/qms_e08_integrated.py", "tools/qms_e08_related_consumer.py",
        "tools/qms_e08_consumer.py", "tools/qms_release_consumers.py",
        *("tools/"+n for n in (*CONSUMERS, *EXTRA)),
        *("examples/"+n for n in EXTRA.values() if n)]
    manifest["fixture_sha256"].update(source_hashes(ROOT))
    manifest["fixture_sha256"].update({n: digest(ROOT/n) for n in names})
    request = directory/"manifest.json"
    request.write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n")
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    all_rows = {}
    for kind in ("pair", "sdist"):
        rows = {}
        for name in (*CONSUMERS, *EXTRA):
            arguments = (consumer_arguments(name, core=proof["core"], native=proof["native"],
                examples=ROOT/"examples") if name in CONSUMERS else
                ["--example", str(ROOT/"examples"/EXTRA[name])] if EXTRA[name] else [])
            command = [str(LANE/kind/"bin/python"), "-I", str(ROOT/"tools/qms_e08_related_consumer.py"),
                "--root", str(ROOT), "--manifest", str(request), "--consumer", name, "--", *arguments]
            log = directory/(kind+"-"+name.removesuffix(".py")+".log")
            try:
                process = subprocess.run(command, cwd=directory, env=environment,
                    text=True, capture_output=True, timeout=900, check=False)
            except subprocess.TimeoutExpired as error:
                def text(value):
                    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                log.write_text(text(error.stdout)+text(error.stderr)+"\nTIMEOUT\n")
                raise ValueError(f"consumer timed out; preserved {log}") from error
            log.write_text("$ "+" ".join(command)+"\n"+process.stdout+process.stderr)
            if process.returncode:
                raise ValueError(f"integrated consumer failed; preserved {log}")
            row = json.loads(process.stdout.splitlines()[-1])
            if row["manifest_sha256"] != digest(request) or row["publication"] is not False:
                raise ValueError("wrong integrated manifest/publication identity")
            rows[name] = row
            print(f"{kind}/{name}: PASS", flush=True)
        validate_consumers({n: rows[n]["result"] for n in CONSUMERS}, core=proof["core"], native=proof["native"])
        from tools.qms_e04_installed import validate_consumer as portfolio
        from tools.qms_e05_installed import validate_consumer as package
        from tools.qms_g01_installed import validate_consumer as metric
        pair = (proof["core"], proof["native"])
        scalar = rows["qms_e03_consumer.py"]["result"]
        expected = {(r, b) for b in ("native_vectorized", "native_event") for r in ("signal_notional", "notional", "unit")}
        expected.update({("pct_equity", "legacy"), ("dca_ladder", "legacy")})
        cells = scalar.get("cells", [])
        if ((scalar.get("core"), scalar.get("native")) != pair or len(cells) != 8
                or {(c["target"], c["backend"]) for c in cells} != expected
                or not all(c.get("off_shadow_account_exact") and c.get("active_original_witness") for c in cells)):
            raise ValueError("incomplete original scalar consumer proof")
        portfolio(rows["qms_e04_consumer.py"]["result"], pair)
        package(rows["qms_e05_consumer.py"]["result"], pair)
        metric(rows["qms_g01_consumer.py"]["result"], proof)
        all_rows[kind] = rows
    for name, expected in manifest["fixture_sha256"].items():
        if digest(ROOT/name) != expected:
            raise ValueError("source drift during integrated proof")
    if artifact_manifest(proof)["core_inventory"] != manifest["core_inventory"]:
        raise ValueError("canonical source drift during integrated proof")
    receipt = dict(schema="qms-e08-integrated-installed-v1", rows=all_rows,
        artifact_refs=proof["artifact_refs"], manifest_sha256=digest(request),
        retained_sha256={p.name: digest(p) for p in directory.iterdir() if p.is_file()},
        remote=False, publication=False, empirical_promotion=False)
    with (LANE/"integrated-proof.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    result = qualify()
    print(json.dumps(dict(schema=result["schema"], consumers=sum(len(r) for r in result["rows"].values()), publication=False)))
