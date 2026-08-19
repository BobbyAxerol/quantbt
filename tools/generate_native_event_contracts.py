"""Generate Python and Rust contract constants from the canonical JSON registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"
PYTHON_OUTPUT = ROOT / "src" / "quantbt" / "core" / "generated_native_event_contracts.py"
# The pure domain crate is the single Rust source of contract constants. The
# PyO3 crate consumes it as a dependency and must not keep a second generated
# copy that could drift from the engine.
RUST_OUTPUT = ROOT / "rust" / "crates" / "quantbt-domain" / "src" / "generated_contracts.rs"


def canonical_payload() -> tuple[dict, str]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return payload, hashlib.sha256(canonical).hexdigest()


def render_python(payload: dict, fingerprint: str) -> str:
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    return (
        '"""Generated from contracts/native_event_contract_registry.json; do not edit."""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n\n"
        f'NATIVE_EVENT_CONTRACT_FINGERPRINT = "{fingerprint}"\n'
        f"NATIVE_EVENT_CONTRACT_REGISTRY = json.loads({serialized!r})\n"
        "CONTRACT_CODES = {item[\"contract_id\"]: int(item[\"contract_code\"]) "
        "for item in NATIVE_EVENT_CONTRACT_REGISTRY[\"contracts\"]}\n"
        "CONTRACT_IDS_BY_CODE = {value: key for key, value in CONTRACT_CODES.items()}\n"
        "COMMAND_OUTCOME_CODES = dict(NATIVE_EVENT_CONTRACT_REGISTRY[\"command_outcomes\"])\n"
        "ORDER_STATUS_CODES = dict(NATIVE_EVENT_CONTRACT_REGISTRY[\"order_statuses\"])\n"
        "LIFECYCLE_EVENT_KIND_CODES = dict(NATIVE_EVENT_CONTRACT_REGISTRY[\"lifecycle_event_kinds\"])\n"
    )


def rust_name(value: str) -> str:
    return value.replace("-", "_").upper()


def rust_string_constant(name: str, value: str) -> list[str]:
    """Render the small subset of rustfmt wrapping used by this artifact.

    ``--check`` is intentionally runnable from the Python-only CI job.  The
    generated source must therefore already be rustfmt-stable instead of
    relying on a locally installed Rust toolchain to normalize it after write.
    """

    inline = f'pub const {name}: &str = "{value}";'
    if len(inline) <= 100:
        return [inline]
    return [f"pub const {name}: &str =", f'    "{value}";']


def render_rust(payload: dict, fingerprint: str) -> str:
    lines = [
        "//! Generated from contracts/native_event_contract_registry.json; do not edit.",
        "#![allow(dead_code)]",
        "",
        *rust_string_constant("CONTRACT_REGISTRY_FINGERPRINT", fingerprint),
    ]
    for contract in payload["contracts"]:
        name = rust_name(contract["contract_id"])
        lines.append(f'pub const CONTRACT_{name}: i64 = {int(contract["contract_code"])};')
        lines.append(f'pub const CONTRACT_ID_{name}: &str = "{contract["contract_id"]}";')
    for group_name, prefix in (
        ("command_outcomes", "COMMAND_OUTCOME"),
        ("order_statuses", "ORDER_STATUS"),
        ("lifecycle_event_kinds", "LIFECYCLE_EVENT_KIND"),
    ):
        for key, value in payload[group_name].items():
            lines.append(f"pub const {prefix}_{key}: i64 = {int(value)};")
    lines.extend(
        [
            "",
            "#[derive(Clone, Copy, Debug, Eq, PartialEq)]",
            "pub struct LifecycleTransition {",
            "    pub action: &'static str,",
            "    pub from_status: &'static str,",
            "    pub to_status: &'static str,",
            "    pub outcome: i64,",
            "    pub reason: &'static str,",
            "}",
            "",
            "pub const LIFECYCLE_TRANSITIONS: &[LifecycleTransition] = &[",
        ]
    )
    for item in payload["transitions"]:
        outcome = f'COMMAND_OUTCOME_{item["outcome"]}'
        lines.extend(
            (
                "    LifecycleTransition {",
                f'        action: "{item["action"]}",',
                f'        from_status: "{item["from"]}",',
                f'        to_status: "{item["to"]}",',
                f"        outcome: {outcome},",
                f'        reason: "{item["reason"]}",',
                "    },",
            )
        )
    lines.extend(
        [
            "];",
            "",
            "#[cfg(test)]",
            "mod tests {",
            "    use super::*;",
            "    use std::collections::HashSet;",
            "",
            "    #[test]",
            "    fn generated_contract_ids_are_stable() {",
            "        assert_eq!(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, 2);",
            "        assert_eq!(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN, 3);",
            "        assert_eq!(CONTRACT_REGISTRY_FINGERPRINT.len(), 64);",
            "    }",
            "",
            "    #[test]",
            "    fn lifecycle_transition_keys_are_unique() {",
            "        let mut keys = HashSet::new();",
            "        for item in LIFECYCLE_TRANSITIONS {",
            "            assert!(keys.insert((item.action, item.from_status, item.to_status)));",
            "        }",
            "        assert!(LIFECYCLE_TRANSITIONS.len() >= 25);",
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def generated_outputs() -> dict[Path, str]:
    payload, fingerprint = canonical_payload()
    return {
        PYTHON_OUTPUT: render_python(payload, fingerprint),
        RUST_OUTPUT: render_rust(payload, fingerprint),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when generated contract constants are stale")
    args = parser.parse_args(argv)
    outputs = generated_outputs()
    if args.check:
        stale = [path for path, content in outputs.items() if not path.is_file() or path.read_text(encoding="utf-8") != content]
        if stale:
            print("stale native-event generated artifacts:", file=sys.stderr)
            print("\n".join(str(path.relative_to(ROOT)) for path in stale), file=sys.stderr)
            return 1
        print("native-event contract generation check: PASS")
        return 0

    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
    rustfmt = shutil.which("rustfmt")
    if rustfmt is not None:
        subprocess.run([rustfmt, str(RUST_OUTPUT)], check=True)
    print("native-event contracts generated: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
