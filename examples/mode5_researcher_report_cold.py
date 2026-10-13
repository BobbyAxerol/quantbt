"""Render a retained diagnostic snapshot without finance or optimization.

Public export is the default. Private output needs an explicit flag and must
remain outside source control/package artifacts. Reading a snapshot validates
its internal contracts; fresh evidence/access verification requires the original
EvidenceCatalog and ResearcherReport.verify(catalog).
"""

import argparse
from pathlib import Path

from quantbt.mode5.dossier.researcher_report import ResearcherReport


def render_snapshot(payload, *, private=False, output_format="markdown"):
    if type(private) is not bool or output_format not in {"markdown", "json"}:
        raise ValueError("explicit privacy policy and markdown/json format required")
    report = ResearcherReport.from_json(payload)
    renderer = report.to_markdown if output_format == "markdown" else report.to_json
    return renderer(public=not private)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True,
                        help="retained ResearcherReport JSON; never an alpha module")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--private", action="store_true",
                        help="include private values; do not publish this output")
    args = parser.parse_args(argv)
    print(render_snapshot(args.report.read_text(encoding="utf-8"),
                          private=args.private, output_format=args.format))


if __name__ == "__main__":
    main()
