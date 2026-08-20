#!/usr/bin/env python3
"""Generate product compatibility artifacts from the native-event product registry.

The lifecycle registry remains the canonical source for bar-level semantics.
This registry owns the separate product surface: package pairing, protocol/ABI
versions, certified workload descriptors, deprecations, and generated public
compatibility documentation.  The command validates both registries and
metadata before writing anything, so a release cannot silently drift across
Python, Rust, or wheel metadata.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"
PYTHON_OUTPUT = ROOT / "src" / "quantbt" / "core" / "generated_product_contracts.py"
RUST_OUTPUT = ROOT / "rust" / "crates" / "quantbt-domain" / "src" / "generated_product_contracts.rs"
DOC_OUTPUT = ROOT / "docs" / "contracts" / "generated_product_compatibility.md"
CORPUS_OUTPUT = ROOT / "tests" / "corpus" / "generated" / "product_contract_cases.json"
MANIFEST_OUTPUT = ROOT / "contracts" / "generated_product_manifest.json"


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _fingerprint(payload: Any) -> str:
    return sha256(_canonical_json(payload)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"registry must be a JSON object: {path}")
    return payload


def _read_project_versions() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    core = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    native = tomllib.loads((ROOT / "rust" / "native_event" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    cargo = tomllib.loads((ROOT / "rust" / "native_event" / "Cargo.toml").read_text(encoding="utf-8"))["package"]
    return core, native, cargo


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], *, label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"{label} missing required keys: {', '.join(missing)}")


def load_and_validate() -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Return product/lifecycle registries and stable fingerprints after validation."""

    product = _read_json(PRODUCT_REGISTRY)
    lifecycle = _read_json(LIFECYCLE_REGISTRY)
    _require_keys(
        product,
        (
            "schema_version", "registry_id", "lifecycle_registry", "versions",
            "runtime_descriptor", "stable_capability_matrix", "extension_capabilities",
            "capability_normalization", "promotion_policy", "workloads", "compatibility", "deprecations",
        ),
        label="product registry",
    )
    if int(product["schema_version"]) != 1:
        raise ValueError("unsupported product registry schema_version")
    lifecycle_declared = product["lifecycle_registry"]
    lifecycle_fingerprint = _fingerprint(lifecycle)
    if lifecycle_declared.get("fingerprint") != lifecycle_fingerprint:
        raise ValueError("product registry lifecycle fingerprint does not match lifecycle registry")
    if int(lifecycle_declared.get("schema_version", -1)) != int(lifecycle.get("schema_version", -2)):
        raise ValueError("product registry lifecycle schema version does not match lifecycle registry")

    versions = product["versions"]
    _require_keys(
        versions,
        (
            "core_package", "native_package", "native_protocol", "command_abi",
            "result_abi", "trace_schema", "strategy_ir", "capability_descriptor",
        ),
        label="product version registry",
    )
    core, native, cargo = _read_project_versions()
    expected_core = versions["core_package"]
    expected_native = versions["native_package"]
    if (core["name"], str(core["version"]), str(core["requires-python"])) != (
        expected_core["distribution"], expected_core["version"], expected_core["python_requires"],
    ):
        raise ValueError("pyproject.toml core package metadata differs from product registry")
    if (native["name"], str(native["version"]), str(cargo["version"])) != (
        expected_native["distribution"], expected_native["version"], expected_native["version"],
    ):
        raise ValueError("native pyproject/Cargo package metadata differs from product registry")

    runtime = product["runtime_descriptor"]
    _require_keys(runtime, ("descriptor_version", "native_api", "contracts", "orders", "account", "portfolio"), label="runtime descriptor")
    contract_ids = {str(item["contract_id"]) for item in lifecycle["contracts"]}
    unknown_contracts = sorted(set(runtime["contracts"]) - contract_ids)
    if unknown_contracts:
        raise ValueError(f"runtime descriptor references unknown lifecycle contracts: {unknown_contracts}")
    capability = product["stable_capability_matrix"]
    _require_keys(capability, ("version", "capabilities"), label="stable capability matrix")
    if not capability["capabilities"] or not all(isinstance(value, bool) for value in capability["capabilities"].values()):
        raise ValueError("stable capabilities must be a non-empty boolean mapping")
    if len(set(product["extension_capabilities"])) != len(product["extension_capabilities"]):
        raise ValueError("extension capabilities must be unique")
    normalization = product["capability_normalization"]
    if set(normalization) != set(capability["capabilities"]):
        raise ValueError("capability normalization must cover exactly the stable capability names")
    raw_capabilities = set(product["extension_capabilities"])
    for stable_name, raw_names in normalization.items():
        if not isinstance(raw_names, list) or not raw_names or not all(isinstance(item, str) for item in raw_names):
            raise ValueError(f"capability normalization for {stable_name!r} must be a non-empty string list")
        unknown = sorted(set(raw_names) - raw_capabilities)
        if unknown:
            raise ValueError(
                f"capability normalization for {stable_name!r} references unknown raw capabilities: {unknown}"
            )
    workload_ids = [str(item.get("id", "")) for item in product["workloads"]]
    if not workload_ids or "" in workload_ids or len(set(workload_ids)) != len(workload_ids):
        raise ValueError("workload descriptors require unique non-empty ids")
    for workload in product["workloads"]:
        _require_keys(
            workload,
            (
                "id", "contracts", "strategy_modes", "profiles", "max_symbols",
                "account_models", "portfolio_modes", "package_policies", "trace_schemas",
                "maturity", "platforms", "auto_promotion",
            ),
            label=f"workload {workload.get('id', '<missing>')}",
        )
        if sorted(set(workload["contracts"]) - contract_ids):
            raise ValueError(f"workload {workload['id']} references an unknown lifecycle contract")
        if workload["maturity"] not in {"experimental", "certified", "promoted"}:
            raise ValueError(f"workload {workload['id']} has invalid maturity")
    promotion = product["promotion_policy"]
    _require_keys(
        promotion,
        (
            "schema_version", "table_version", "default_backend_policy", "default_stage",
            "stages", "rules",
        ),
        label="native promotion policy",
    )
    if int(promotion["schema_version"]) != 1:
        raise ValueError("unsupported native promotion policy schema_version")
    if not isinstance(promotion["table_version"], str) or not promotion["table_version"].strip():
        raise ValueError("native promotion policy table_version must be a non-empty string")
    if promotion["default_backend_policy"] not in {
        "certified_only", "prefer_native", "prefer_compatibility",
    }:
        raise ValueError("native promotion policy has an invalid default_backend_policy")
    stages = tuple(str(stage) for stage in promotion["stages"])
    if stages != ("explicit_only", "static_ir", "portfolio", "package"):
        raise ValueError("native promotion policy stages must be explicit_only, static_ir, portfolio, package")
    if promotion["default_stage"] not in stages:
        raise ValueError("native promotion policy default_stage is not declared")
    rule_ids: set[str] = set()
    enabled_workloads: set[str] = set()
    for rule in promotion["rules"]:
        _require_keys(
            rule,
            ("id", "workload_id", "stage", "enabled", "min_bars", "required_capabilities"),
            label="native promotion rule",
        )
        rule_id = str(rule["id"])
        if not rule_id or rule_id in rule_ids:
            raise ValueError("native promotion rules require unique non-empty ids")
        rule_ids.add(rule_id)
        if str(rule["workload_id"]) not in workload_ids:
            raise ValueError(f"native promotion rule {rule_id} references an unknown workload")
        if str(rule["stage"]) not in stages or str(rule["stage"]) == "explicit_only":
            raise ValueError(f"native promotion rule {rule_id} has an invalid promotion stage")
        if not isinstance(rule["enabled"], bool):
            raise ValueError(f"native promotion rule {rule_id} enabled must be boolean")
        if (
            not isinstance(rule["min_bars"], int)
            or isinstance(rule["min_bars"], bool)
            or rule["min_bars"] < 0
        ):
            raise ValueError(
                f"native promotion rule {rule_id} min_bars must be a non-negative integer"
            )
        capabilities_required = tuple(str(item) for item in rule["required_capabilities"])
        if not capabilities_required or len(set(capabilities_required)) != len(capabilities_required):
            raise ValueError(f"native promotion rule {rule_id} requires unique native capabilities")
        unknown_capabilities = sorted(set(capabilities_required) - raw_capabilities)
        if unknown_capabilities:
            raise ValueError(
                f"native promotion rule {rule_id} references unknown capabilities: {unknown_capabilities}"
            )
        if bool(rule["enabled"]):
            enabled_workloads.add(str(rule["workload_id"]))
    for workload in product["workloads"]:
        auto_promoted = bool(workload["auto_promotion"])
        if auto_promoted != (str(workload["id"]) in enabled_workloads):
            raise ValueError(
                f"workload {workload['id']} auto_promotion must exactly match an enabled promotion rule"
            )
        if auto_promoted and workload["maturity"] != "promoted":
            raise ValueError(f"auto-promoted workload {workload['id']} must have maturity='promoted'")
    if not product["compatibility"]:
        raise ValueError("product compatibility matrix cannot be empty")
    for pair in product["compatibility"]:
        _require_keys(
            pair,
            (
                "core_version", "native_version", "native_protocol_min", "native_protocol_max",
                "command_abis", "result_abis", "status", "fallback",
            ),
            label="compatibility pair",
        )
    product_fingerprint = _fingerprint(product)
    return product, lifecycle, product_fingerprint, lifecycle_fingerprint


def _python_literal(payload: Any) -> str:
    return repr(json.dumps(payload, indent=2, sort_keys=True))


def render_python(product: dict[str, Any], product_fingerprint: str, lifecycle_fingerprint: str) -> str:
    runtime = deepcopy(product["runtime_descriptor"])
    versions = product["versions"]
    promotion = product["promotion_policy"]
    return "\n".join(
        (
            '"""Generated from contracts/native_event_product_registry.json; do not edit."""',
            "",
            "from __future__ import annotations",
            "",
            "import json",
            "",
            f'PRODUCT_CONTRACT_REGISTRY_FINGERPRINT = "{product_fingerprint}"',
            f'PRODUCT_CONTRACT_REGISTRY_ID = "{product["registry_id"]}"',
            f'PRODUCT_CONTRACT_REGISTRY_SCHEMA_VERSION = {int(product["schema_version"])}',
            f'NATIVE_EVENT_LIFECYCLE_REGISTRY_FINGERPRINT = "{lifecycle_fingerprint}"',
            f"NATIVE_EVENT_PRODUCT_REGISTRY = json.loads({_python_literal(product)})",
            f"NATIVE_EVENT_RUNTIME_DESCRIPTOR = json.loads({_python_literal(runtime)})",
            f'NATIVE_EVENT_CAPABILITY_MATRIX_VERSION = "{product["stable_capability_matrix"]["version"]}"',
            "NATIVE_EVENT_STABLE_CAPABILITIES = dict(NATIVE_EVENT_PRODUCT_REGISTRY[\"stable_capability_matrix\"][\"capabilities\"])",
            "NATIVE_EVENT_EXTENSION_CAPABILITIES = tuple(NATIVE_EVENT_PRODUCT_REGISTRY[\"extension_capabilities\"])",
            "NATIVE_EVENT_CAPABILITY_NORMALIZATION = dict(NATIVE_EVENT_PRODUCT_REGISTRY[\"capability_normalization\"])",
            "NATIVE_EVENT_PROMOTION_POLICY = dict(NATIVE_EVENT_PRODUCT_REGISTRY[\"promotion_policy\"])",
            f'NATIVE_EVENT_PROMOTION_TABLE_VERSION = "{promotion["table_version"]}"',
            "WORKLOAD_CAPABILITY_DESCRIPTORS = tuple(NATIVE_EVENT_PRODUCT_REGISTRY[\"workloads\"])",
            "NATIVE_EVENT_COMPATIBILITY_MATRIX = tuple(NATIVE_EVENT_PRODUCT_REGISTRY[\"compatibility\"])",
            "NATIVE_EVENT_DEPRECATION_MATRIX = tuple(NATIVE_EVENT_PRODUCT_REGISTRY[\"deprecations\"])",
            f'NATIVE_EVENT_CORE_PACKAGE_VERSION = "{versions["core_package"]["version"]}"',
            f'NATIVE_EVENT_NATIVE_PACKAGE_VERSION = "{versions["native_package"]["version"]}"',
            f'NATIVE_EVENT_CORE_PROTOCOL_MIN = {int(versions["native_protocol"]["minimum"])}',
            f'NATIVE_EVENT_CORE_PROTOCOL_MAX = {int(versions["native_protocol"]["maximum"])}',
            f'NATIVE_EVENT_COMMAND_ABI_VERSION = "{versions["command_abi"]["current"]}"',
            f'NATIVE_EVENT_RESULT_ABI_VERSION = "{versions["result_abi"]["current"]}"',
            f'NATIVE_EVENT_TRACE_SCHEMA_VERSION = "{versions["trace_schema"]["current"]}"',
            f'NATIVE_EVENT_STRATEGY_IR_VERSION = "{versions["strategy_ir"]["current"]}"',
            "",
        )
    )


def _rust_string_list(name: str, values: list[str]) -> list[str]:
    inline = f"pub const {name}: &[&str] = &[" + ", ".join(f'\"{value}\"' for value in values) + "];"
    if len(inline) <= 100:
        return [inline, ""]
    lines = [f"pub const {name}: &[&str] = &["]
    lines.extend(f'    "{value}",' for value in values)
    lines.append("];\n")
    return lines


def _rust_string_constant(name: str, value: str) -> list[str]:
    inline = f'pub const {name}: &str = "{value}";'
    if len(inline) <= 100:
        return [inline]
    return [f"pub const {name}: &str =", f'    "{value}";']


def render_rust(product: dict[str, Any], product_fingerprint: str, lifecycle_fingerprint: str) -> str:
    versions = product["versions"]
    runtime = product["runtime_descriptor"]
    promotion = product["promotion_policy"]
    lines = [
        "//! Generated from contracts/native_event_product_registry.json; do not edit.",
        "#![allow(dead_code)]",
        "",
        *_rust_string_constant("PRODUCT_CONTRACT_REGISTRY_FINGERPRINT", product_fingerprint),
        *_rust_string_constant("LIFECYCLE_REGISTRY_FINGERPRINT", lifecycle_fingerprint),
        *_rust_string_constant("CORE_PACKAGE_VERSION", versions["core_package"]["version"]),
        *_rust_string_constant("NATIVE_PACKAGE_VERSION", versions["native_package"]["version"]),
        *_rust_string_constant("NATIVE_API_VERSION", runtime["native_api"]),
        *_rust_string_constant("SEMANTIC_DESCRIPTOR_VERSION", runtime["descriptor_version"]),
        f'pub const CORE_PROTOCOL_MIN: i64 = {int(versions["native_protocol"]["minimum"])};',
        f'pub const CORE_PROTOCOL_MAX: i64 = {int(versions["native_protocol"]["maximum"])};',
        f'pub const COMMAND_ABI_VERSION: &str = "{versions["command_abi"]["current"]}";',
        f'pub const RESULT_ABI_VERSION: &str = "{versions["result_abi"]["current"]}";',
        f'pub const TRACE_SCHEMA_VERSION: &str = "{versions["trace_schema"]["current"]}";',
        f'pub const STRATEGY_IR_VERSION: &str = "{versions["strategy_ir"]["current"]}";',
        f'pub const PROMOTION_POLICY_TABLE_VERSION: &str = "{promotion["table_version"]}";',
        f'pub const PROMOTION_POLICY_DEFAULT_STAGE: &str = "{promotion["default_stage"]}";',
        f'pub const PROMOTION_POLICY_DEFAULT_BACKEND_POLICY: &str = "{promotion["default_backend_policy"]}";',
        "",
    ]
    lines.extend(_rust_string_list("NATIVE_EXTENSION_CAPABILITIES", list(product["extension_capabilities"])))
    lines.extend(_rust_string_list("RUNTIME_CONTRACT_IDS", list(runtime["contracts"])))
    lines.extend(_rust_string_list("RUNTIME_ORDER_TYPES", list(runtime["orders"]["types"])))
    lines.extend(_rust_string_list("RUNTIME_GAP_POLICIES", list(runtime["orders"]["gap_policy"])))
    lines.extend(_rust_string_list("RUNTIME_PNL_MODELS", list(runtime["account"]["pnl_models"])))
    lines.extend(_rust_string_list("RUNTIME_MARGIN_MODELS", list(runtime["account"]["margin_models"])))
    lines.extend(_rust_string_list("RUNTIME_LIQUIDATION_MODELS", list(runtime["account"]["liquidation_models"])))
    lines.extend(
        (
            f'pub const RUNTIME_PARTIAL_FILL: bool = {str(bool(runtime["orders"]["partial_fill"])).lower()};',
            f'pub const RUNTIME_VOLUME_MODEL: &str = "{runtime["orders"]["volume_model"]}";',
            f'pub const RUNTIME_PORTFOLIO_TARGET_EXECUTION: bool = {str(bool(runtime["portfolio"]["target_execution"])).lower()};',
            f'pub const RUNTIME_PACKAGE_ATOMICITY: &str = "{runtime["portfolio"]["package_atomicity"]}";',
            "",
        )
    )
    return "\n".join(lines)


def render_docs(product: dict[str, Any], product_fingerprint: str, lifecycle_fingerprint: str) -> str:
    versions = product["versions"]
    promotion = product["promotion_policy"]
    lines = [
        "# Generated Native Product Compatibility",
        "",
        "> Generated by `tools/generate_product_contracts.py`; do not edit by hand.",
        "",
        "This table is the release-facing contract for the optional Rust companion. "
        "Automatic routing is controlled by the versioned promotion policy below, not merely by extension import success.",
        "",
        "## Registry",
        "",
        f"- Product registry: `{product['registry_id']}` schema `{product['schema_version']}`",
        f"- Product fingerprint: `{product_fingerprint}`",
        f"- Lifecycle registry fingerprint: `{lifecycle_fingerprint}`",
        f"- Core distribution: `{versions['core_package']['distribution']}=={versions['core_package']['version']}`",
        f"- Native distribution: `{versions['native_package']['distribution']}=={versions['native_package']['version']}` (published: `{str(bool(versions['native_package']['published'])).lower()}`)",
        "",
        "## Promotion Policy",
        "",
        f"- Table version: `{promotion['table_version']}` (schema `{promotion['schema_version']}`)",
        f"- Default user policy: `{promotion['default_backend_policy']}`",
        f"- Configured automatic stage: `{promotion['default_stage']}`",
        "- Emergency controls: `QUANTBT_DISABLE_NATIVE=1` and `QUANTBT_NATIVE_PROMOTION_MAX=<stage>`.",
        "",
        "| Rule | Workload | Stage | Enabled | Required capabilities |",
        "|---|---|---|---|---|",
    ]
    for rule in promotion["rules"]:
        lines.append(
            "| `{id}` | `{workload}` | `{stage}` | `{enabled}` | `{capabilities}` |".format(
                id=rule["id"],
                workload=rule["workload_id"],
                stage=rule["stage"],
                enabled=str(bool(rule["enabled"])).lower(),
                capabilities=", ".join(rule["required_capabilities"]),
            )
        )
    lines.extend(
        (
            "",
        "## Version Matrix",
        "",
        "| Contract | Current | Compatibility policy |",
        "|---|---|---|",
        f"| Native protocol | `{versions['native_protocol']['minimum']}..{versions['native_protocol']['maximum']}` | exact staged pair only |",
        f"| Command ABI | `{versions['command_abi']['current']}` | listed ABI only |",
        f"| Result ABI | `{versions['result_abi']['current']}` | listed ABI only |",
        f"| Trace schema | `{versions['trace_schema']['current']}` | retained for {versions['trace_schema']['readable_release_lines']} release lines |",
        f"| Strategy IR | `{versions['strategy_ir']['current']}` | bounded IR v1 templates only |",
        "",
        "## Workload Capabilities",
        "",
        "| Workload | Contracts | Strategy mode | Profiles | Maturity | Auto |",
        "|---|---|---|---|---|---|",
        )
    )
    for workload in product["workloads"]:
        lines.append(
            "| `{id}` | `{contracts}` | `{strategy}` | `{profiles}` | `{maturity}` | `{auto}` |".format(
                id=workload["id"],
                contracts=", ".join(workload["contracts"]),
                strategy=", ".join(workload["strategy_modes"]),
                profiles=", ".join(workload["profiles"]),
                maturity=workload["maturity"],
                auto=str(bool(workload["auto_promotion"])).lower(),
            )
        )
    lines.extend(("", "## Exact Package Pairs", "", "| Core | Native | Protocol | Status | Fallback |", "|---|---|---|---|---|"))
    for pair in product["compatibility"]:
        lines.append(
            f"| `{pair['core_version']}` | `{pair['native_version']}` | `{pair['native_protocol_min']}..{pair['native_protocol_max']}` | `{pair['status']}` | {pair['fallback']} |"
        )
    lines.extend(("", "## Deprecations", "", "| Feature | Replacement | Warning | Error | Target | Owner |", "|---|---|---|---|---|---|"))
    for item in product["deprecations"]:
        lines.append(
            f"| {item['feature']} | {item['replacement']} | {item['warning_from'] or '-'} | {item['error_from'] or '-'} | {item['removal_target'] or '-'} | {item['owner']} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_corpus(product: dict[str, Any], product_fingerprint: str) -> str:
    first_pair = product["compatibility"][0]
    promotion = product["promotion_policy"]
    payload = {
        "schema": "quantbt-product-contract-corpus-v1",
        "registry_fingerprint": product_fingerprint,
        "cases": [
            {
                "id": "exact_staged_core_native_pair",
                "core_version": first_pair["core_version"],
                "native_version": first_pair["native_version"],
                "expected": "compatible",
            },
            {
                "id": "native_version_mismatch",
                "core_version": first_pair["core_version"],
                "native_version": "0.0.0",
                "expected": "incompatible",
            },
            {
                "id": "auto_routing_remains_python",
                "workloads": [item["id"] for item in product["workloads"]],
                "promotion_table_version": promotion["table_version"],
                "default_stage": promotion["default_stage"],
                "expected": "not_promoted",
            },
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def render_manifest(product_fingerprint: str, lifecycle_fingerprint: str, rendered: dict[Path, str]) -> str:
    payload = {
        "schema": "quantbt-generated-product-manifest-v1",
        "product_registry": str(PRODUCT_REGISTRY.relative_to(ROOT)),
        "product_registry_fingerprint": product_fingerprint,
        "lifecycle_registry": str(LIFECYCLE_REGISTRY.relative_to(ROOT)),
        "lifecycle_registry_fingerprint": lifecycle_fingerprint,
        "generated": {
            str(path.relative_to(ROOT)): _sha256_text(text)
            for path, text in sorted(rendered.items(), key=lambda item: str(item[0]))
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def generated_outputs() -> dict[Path, str]:
    product, _lifecycle, product_fingerprint, lifecycle_fingerprint = load_and_validate()
    rendered = {
        PYTHON_OUTPUT: render_python(product, product_fingerprint, lifecycle_fingerprint),
        RUST_OUTPUT: render_rust(product, product_fingerprint, lifecycle_fingerprint),
        DOC_OUTPUT: render_docs(product, product_fingerprint, lifecycle_fingerprint),
        CORPUS_OUTPUT: render_corpus(product, product_fingerprint),
    }
    rendered[MANIFEST_OUTPUT] = render_manifest(product_fingerprint, lifecycle_fingerprint, rendered)
    return rendered


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _check(outputs: dict[Path, str]) -> list[Path]:
    return [path for path, expected in outputs.items() if not path.is_file() or path.read_text(encoding="utf-8") != expected]


def _rustfmt(path: Path) -> None:
    rustfmt = shutil_which("rustfmt")
    if rustfmt is not None:
        subprocess.run([rustfmt, str(path)], check=True)


def shutil_which(command: str) -> str | None:
    """Avoid importing a large helper at generator import time."""

    from shutil import which

    return which(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when any generated artifact is stale")
    args = parser.parse_args(argv)
    try:
        outputs = generated_outputs()
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"product contract generation failed: {exc}", file=sys.stderr)
        return 1

    if args.check:
        stale = _check(outputs)
        if stale:
            print("stale generated product artifacts:", file=sys.stderr)
            print("\n".join(str(path.relative_to(ROOT)) for path in stale), file=sys.stderr)
            return 1
        print("product contract generation check: PASS")
        return 0

    for path, content in outputs.items():
        _write(path, content)
    _rustfmt(RUST_OUTPUT)
    # rustfmt can change only whitespace; refresh the manifest against the final file.
    rendered = {path: path.read_text(encoding="utf-8") for path in outputs if path != MANIFEST_OUTPUT}
    product, _lifecycle, product_fingerprint, lifecycle_fingerprint = load_and_validate()
    _write(MANIFEST_OUTPUT, render_manifest(product_fingerprint, lifecycle_fingerprint, rendered))
    print("generated product contracts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
