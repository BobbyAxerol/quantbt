"""Outside-checkout installed artifact proof; no local-source path insertion."""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("registration", type=Path)
    parser.add_argument("example", type=Path)
    args = parser.parse_args()
    registration = json.loads(args.registration.read_text())
    import quantbt
    from quantbt import ReportingRequest, ReportingContractV1, ReportingCoverageV1, ReportingCache
    import quantbt.metrics.reporting.public as public
    root = Path(quantbt.__file__).parent
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob("*") if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")}
    assert actual == registration["core_inventory"]
    assert "site-packages" in str(root) and str(root) != str(Path(registration["checkout"]) / "src/quantbt")
    assert quantbt.__version__ == "1.1.2" and metadata.version("quantbt-native") == "0.4.3"
    native = metadata.distribution("quantbt-native")
    binaries = [Path(native.locate_file(p)) for p in native.files if str(p).endswith(".so")]
    assert len(binaries) == 1 and hashlib.sha256(binaries[0].read_bytes()).hexdigest() == registration["native_reuse"]["extension_sha256"]
    from quantbt.backends._native_event_rust import probe_native_event_rust_extension
    status = probe_native_event_rust_extension()
    assert status.available and status.compatible and status.executable, status.reason
    ns = runpy.run_path(str(args.example))
    endpoint, result, request, report = ns["example"]()
    assert endpoint.full_report(reporting=request) == report
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = endpoint.quick_plot(reporting=request)
    fig.canvas.draw()
    assert len(fig.axes) == 2
    plt.close(fig)
    json.dumps(report, allow_nan=False)
    print(json.dumps(dict(status="PASS", modules=len(actual), core="1.1.2", native="0.4.3",
        package_origin=str(root), outside_checkout=True, extension_sha256=registration["native_reuse"]["extension_sha256"],
        matplotlib_optional=True, publication=False)))


if __name__ == "__main__":
    main()
