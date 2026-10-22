# M5-12 Closeout

Canonical input SHA256: `852ad3d20a384cb5bd589257361cc22b8b1474e39dfc63f521d98ff61eee43fd`

Recorded values and dispositions are reproduced without recomputation. Rendering does not certify artifacts, scientific success or release authority.

## Recorded Summary

| Field | Recorded Value |
| --- | --- |
| Phase Status | PARTIAL\_TECHNICAL\_CLOSURE |
| Scientific Status | DESCRIPTIVE\_ONLY |
| Next Phase Ready | false |
| source\_identity.source\_commit | bf3f919550a82ac97d6c4c81073a52880d5e3331 |
| source\_identity.branch | feat/mode5-diagnostics-first |

## Installed Consumers

| Kind | Feature Cases | Execution Cases | Pct-Equity Cases | Integrated Families | Private Alpha Controls | Representative Reports | Recorded Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| pair | 44 | 149 | 19 | 8 | 5 | 4 | PASS\_LOCAL\_EXACT\_ARTIFACT |
| sdist | 44 | 149 | 19 | 8 | 5 | 4 | PASS\_LOCAL\_EXACT\_ARTIFACT |

## Status

```json
{
  "next_phase_ready": false,
  "phase_id": "M5-12",
  "schema": "quantbt.mode5_upgrade.phase_report.v1",
  "scientific_status": "DESCRIPTIVE_ONLY",
  "status": "PARTIAL_TECHNICAL_CLOSURE"
}
```

## Source And Artifacts

```json
{
  "input_artifacts": [
    {
      "bytes": 1352811,
      "path": ".maturin/qms08/m5-12-local-v6/cp312/dist/quantbt_engine-1.1.2-py3-none-any.whl",
      "sha256": "016c166438481cfec3bd1d6c5d646870b3152f387328af9fc0b16649ce0f0450"
    },
    {
      "bytes": 1183679,
      "path": ".maturin/qms08/m5-12-local-v6/cp312/dist/quantbt_engine-1.1.2.tar.gz",
      "sha256": "039b654190ecc7760aebe33ee3320165bb2fdcda13ae7d30003fb91199683d31"
    },
    {
      "bytes": 1222936,
      "path": ".maturin/qms08/m5-12-local-v6/cp312/dist/quantbt_native-0.4.3-cp312-cp312-manylinux_2_34_x86_64.whl",
      "sha256": "36661d59decd7a3d45e9a08aa0a96d2f6d422083869c49332b8b0d5300db11a9"
    },
    {
      "bytes": 28556,
      "path": ".maturin/qms08/m5-12-local-v6/cp312/proof.json",
      "sha256": "6298bc4e9ad9f47351d7f3e8639d83a993e0848fa5132f83c3cd867c39d86eba"
    },
    {
      "bytes": 209477,
      "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/historical-traceability.json",
      "sha256": "6200fd20bcabfbab2a2e175c03b6466bdb3c611c3186c16188faf8fc945538f0"
    }
  ],
  "protected_sources_unchanged": {
    "approved_runtime_amendments": [
      "b4c4f93",
      "45fd6ec",
      "bf3f919"
    ],
    "cleanup": {
      "bytes": 492,
      "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/cleanup-v6-terminal.json",
      "sha256": "cd565c57f21bc5d9d57e50a9e06239af925f356a70b9ddf45015caa72c9a6151"
    },
    "guide": true,
    "historical_receipts": true,
    "original_inputs": true,
    "owner_uncommitted_plan_hunk": "PRESERVED_UNSTAGED"
  },
  "source_identity": {
    "branch": "feat/mode5-diagnostics-first",
    "provenance": {
      "acc01_amendment_sha256": "95af947a570cc5c10bc6655c922b7dd8497f02e6da422aa3479af0163a94e0f1",
      "acc01_changed_sources": [
        "rust/crates/quantbt-execution/src/target.rs",
        "rust/native_event/src/lib.rs",
        "src/quantbt/backends/native_event.py",
        "src/quantbt/backends/native_option.py",
        "src/quantbt/backends/native_vectorized.py",
        "src/quantbt/core/account_metadata.py",
        "src/quantbt/core/event.py",
        "src/quantbt/core/market_tape.py",
        "src/quantbt/core/results.py",
        "src/quantbt/core/vectorized.py",
        "src/quantbt/endpoint.py",
        "src/quantbt/metrics/reporting/account.py",
        "src/quantbt/metrics/reporting/adapters.py",
        "src/quantbt/metrics/reporting/cache.py",
        "src/quantbt/metrics/reporting/drawdown.py",
        "src/quantbt/metrics/reporting/execution.py",
        "src/quantbt/metrics/reporting/inputs.py",
        "src/quantbt/metrics/reporting/ledger.py",
        "src/quantbt/metrics/reporting/results.py",
        "src/quantbt/metrics/reporting/snapshots.py",
        "src/quantbt/options/authority.py",
        "src/quantbt/options/endpoint_validation.py",
        "src/quantbt/options/execution.py",
        "src/quantbt/options/fees.py",
        "src/quantbt/options/hedging.py",
        "src/quantbt/options/ledger.py",
        "src/quantbt/options/lifecycle.py",
        "src/quantbt/options/margin.py",
        "src/quantbt/options/packages.py",
        "src/quantbt/options/reporting.py",
        "src/quantbt/options/schema.py",
        "src/quantbt/options/strategy.py",
        "src/quantbt/options/validation.py",
        "src/quantbt/reporting/executed_attribution.py"
      ],
      "acc01_source_commit": "70fe9f7c9b14469e6ea935e75f180f26ca1c175e",
      "baseline_commit": "59275659778e1e3306b35a3c92c7623a7e17c0c3",
      "cold_extraction_semantics_unchanged": true,
      "current_source_qualified": true,
      "financial_numeric_source_unchanged": false,
      "financial_rust_unchanged": false,
      "financial_source_changed": true,
      "historical_guards_reexecuted": false,
      "historical_receipts": {
        "c02": {
          "claim_scope": "historical_only",
          "path": "benchmarks/optimization/meta_selection/qms_c02_transport.json",
          "sha256": "e2b6a11e5b47602a8758895424d6ec8df13454cee12811818268b766765d250d",
          "source": {
            "additive_atomic_token_getter": true,
            "allowed_changes": [
              "rust/native_event/src/reactive_numeric.rs",
              "src/quantbt/backends/_native_event_rust.py",
              "src/quantbt/backends/native_event.py",
              "src/quantbt/backends/reactive_wfo.py",
              "src/quantbt/backends/reactive_wfo_batch.py",
              "src/quantbt/backends/reactive_wfo_workers.py",
              "src/quantbt/endpoint.py",
              "src/quantbt/optimization/meta_selection/observer.py",
              "src/quantbt/optimization/meta_selection/reactive.py",
              "src/quantbt/optimization/meta_selection/reactive_batch_witness.py",
              "src/quantbt/optimization/meta_selection/reactive_execution.py",
              "src/quantbt/optimization/meta_selection/reactive_transport.py"
            ],
            "baseline": "0bb77b5",
            "financial_rust_unchanged": true,
            "guide_sha256": "adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d",
            "release_identity_unchanged": true,
            "schema": "qms-c02-source-guard-v1"
          }
        },
        "e04": {
          "claim_scope": "historical_only",
          "path": "benchmarks/optimization/meta_selection/qms_e04_software_closure.json",
          "sha256": "92220636ad363547e52a57af95bcbbe52259fd1f11bccb98c29973e5c3ea387a",
          "source": {
            "baseline": "7b83ba4",
            "financial_numeric_source_unchanged": true,
            "publication": false,
            "schema": "qms-e04-exact-source-v1",
            "source_sha256": {
              "src/quantbt/endpoint.py": "a9688c49416167955a01054f4f596c571b793d62c5b19fb34bd4d125e5d5de8c",
              "src/quantbt/optimization/meta_selection/config.py": "7045e938ed951b233e3cb4fc7e3f374fb42c0fcc1f326921f78f13b151e5f4ec",
              "src/quantbt/optimization/meta_selection/domains/portfolio.py": "d01b9525c9cedba7e05eca13ef2e2f221966fd853dc001761c46ac36f6915980",
              "src/quantbt/optimization/meta_selection/domains/portfolio_contract.py": "a81f4805ec052fbf81f895971082c6fa3c56d52344b1f56d8d21fc93004b7a39",
              "src/quantbt/optimization/meta_selection/domains/portfolio_witness.py": "637735a33edbdeea1e1a5288bec55f3375668c89124d1df5a79a25db0ac66748",
              "src/quantbt/optimization/meta_selection/domains/registry.py": "d818c4d83143b6cf655d52be5e5c71cdaa349876e84a4bca18c0e458051d3199",
              "src/quantbt/optimization/meta_selection/observer.py": "0476769a47d791f4badcae3180a506ce52148120b0165e8278476f03e2ccbabd",
              "src/quantbt/optimization/meta_selection/runtime.py": "476fa8d40b6c20f733ee9234ef04548cf3c0279d338479f8843ac30446d50b96",
              "src/quantbt/walkforward.py": "f39b48cea35de46aaaa1d4a3914ca52f694785f6397111ef62247a4fc735896f"
            }
          }
        }
      },
      "historical_receipts_unchanged": true,
      "m5_12_pct_alias_amendment_sha256": "98cb60821074a8d3e4f320c0235c23f9bf5e0fa8c9ba0fef8d2bee878a023e36",
      "m5_12_pct_alias_changed_sources": [
        "src/quantbt/backends/native_wfo_public.py",
        "src/quantbt/endpoint.py"
      ],
      "m5_12_pct_alias_source_commit": "45fd6ec5bc0f2556ff024ffd1314469e06c0b07a",
      "m5_12_pct_amendment_sha256": "cef8e2dfa6995197367ec896123a21747a6baf34dba48fcfa19de93c85d4d784",
      "m5_12_pct_changed_sources": [
        "rust/crates/quantbt-execution/src/target.rs",
        "rust/native_event/src/lib.rs",
        "src/quantbt/backends/native_prepared_evaluation.py",
        "src/quantbt/backends/native_wfo_public.py",
        "src/quantbt/endpoint.py",
        "src/quantbt/optimization/meta_selection/observer.py"
      ],
      "m5_12_pct_source_commit": "b4c4f934a33465b379657bbe1b73745280db84fe",
      "m5_12_snapshot_amendment_sha256": "0efc267ed8f2f000669916badc99b365b10d2eb8a03ce4acc96256c1a92fe8ab",
      "m5_12_snapshot_changed_sources": [
        "src/quantbt/mode5/continuous.py",
        "src/quantbt/mode5/continuous_retention.py"
      ],
      "native_artifacts_qualified": false,
      "pre_m512_amendment_sha256": "f1d4115f7000b4c7d266157a13cb80f9cc4c26e5fca5ad474267888990ce1b24",
      "pre_m512_extracted_sources": [
        "src/quantbt/backends/native_option.py",
        "src/quantbt/backends/native_portfolio.py",
        "src/quantbt/backends/option_validation.py",
        "src/quantbt/backends/portfolio_reports.py"
      ],
      "pre_m512_source_commit": "77af917f4184e4061a908c68557420223434e2db",
      "previous_source_commit": "9c2bfd95c65f71618f52c736dfff341953066961",
      "publication": false,
      "qualification_sha256": "e3e557086c940971f8cd3573fcf812fce24fe862564367d417abac9887050e6c",
      "qualified_source_count": 466,
      "repair_amendment_sha256": "490806eab1e5118675dab4b5013df19ea0b3a3bde633632d9e0d3c4a99253edb",
      "repair_changed_sources": [
        "contracts/generated_public_api_inventory.json",
        "rust/crates/quantbt-execution/src/target.rs",
        "rust/crates/quantbt-portfolio/src/lib.rs",
        "rust/native_event/src/lib.rs",
        "src/quantbt/backends/native_event.py",
        "src/quantbt/backends/native_intrabar_rust.py",
        "src/quantbt/backends/native_option.py",
        "src/quantbt/backends/native_portfolio.py",
        "src/quantbt/backends/native_prepared_evaluation.py",
        "src/quantbt/backends/native_vectorized.py",
        "src/quantbt/backends/native_wfo_public.py",
        "src/quantbt/backends/option_validation.py",
        "src/quantbt/backends/portfolio_reports.py",
        "src/quantbt/backtester.py",
        "src/quantbt/core/account_metadata.py",
        "src/quantbt/core/constraints.py",
        "src/quantbt/core/engine.py",
        "src/quantbt/core/event.py",
        "src/quantbt/core/intrabar_kernel.py",
        "src/quantbt/core/intrabar_reference.py",
        "src/quantbt/core/market_tape.py",
        "src/quantbt/core/portfolio_validation.py",
        "src/quantbt/core/preprocessor.py",
        "src/quantbt/core/results.py",
        "src/quantbt/core/schema.py",
        "src/quantbt/core/vectorized.py",
        "src/quantbt/endpoint.py",
        "src/quantbt/engines.py",
        "src/quantbt/metrics/performance.py",
        "src/quantbt/metrics/reporting/account.py",
        "src/quantbt/metrics/reporting/adapters.py",
        "src/quantbt/metrics/reporting/cache.py",
        "src/quantbt/metrics/reporting/drawdown.py",
        "src/quantbt/metrics/reporting/execution.py",
        "src/quantbt/metrics/reporting/inputs.py",
        "src/quantbt/metrics/reporting/ledger.py",
        "src/quantbt/metrics/reporting/results.py",
        "src/quantbt/metrics/reporting/snapshots.py",
        "src/quantbt/mode5/continuous.py",
        "src/quantbt/mode5/continuous_retention.py",
        "src/quantbt/optimization/meta_selection/observer.py",
        "src/quantbt/options/authority.py",
        "src/quantbt/options/endpoint_validation.py",
        "src/quantbt/options/execution.py",
        "src/quantbt/options/fees.py",
        "src/quantbt/options/hedging.py",
        "src/quantbt/options/ledger.py",
        "src/quantbt/options/lifecycle.py",
        "src/quantbt/options/margin.py",
        "src/quantbt/options/packages.py",
        "src/quantbt/options/reporting.py",
        "src/quantbt/options/schema.py",
        "src/quantbt/options/strategy.py",
        "src/quantbt/options/validation.py",
        "src/quantbt/portfolio.py",
        "src/quantbt/reporting/executed_attribution.py",
        "src/quantbt/reporting/portfolio_audit.py",
        "src/quantbt/sizing/fast.py",
        "src/quantbt/sizing/modes.py"
      ],
      "schema": "quantbt.portfolio.current_source_qualification.v1",
      "scopes": [
        "src",
        "rust",
        "pyproject.toml",
        "uv.lock",
        "contracts",
        "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
      ],
      "source_commit": "bf3f919550a82ac97d6c4c81073a52880d5e3331",
      "source_metadata_amendments": [
        {
          "after_sha256": "dc348140142390a81f078d4dcf9562ad032d4a60f99e106e7d63b041f15c439f",
          "before_sha256": "522e7ff87b95e5dba73369f4a0b7395e094d271443c72a31e05be3377a709103",
          "financial_source_changed": false,
          "path": "contracts/generated_public_api_inventory.json"
        }
      ]
    },
    "qualification_tooling_commit": "4b3c80da46acce3d8272e65dd5ea9b0ac2cab0b5",
    "qualified_source_count": 466,
    "source_commit": "bf3f919550a82ac97d6c4c81073a52880d5e3331"
  }
}
```

## Research Scope

```json
{
  "alpha_scope": [
    "A-RSI",
    "A-SC",
    "A-HMA",
    "A-HASH",
    "A-VWAP",
    "N1",
    "N2"
  ],
  "data_roles": [
    "Public synthetic software controls",
    "Actual private adapters on bounded synthetic tapes",
    "Retained reviewed/exploratory economic evidence; not new OOS"
  ],
  "hypotheses_tested": [
    "Exact installed artifacts retain current domain, metric and causal contracts.",
    "Accepted pct quantities/activity agree with the reference contract; stale capabilities/history fail closed.",
    "Continuous snapshot copy/pickle preserves values, units and independent immutable headers.",
    "Reports reproduce without execution; absent private history cannot invent assertions."
  ]
}
```

## Requirements And Traceability

```json
{
  "requirements": [
    {
      "evidence": [
        {
          "bytes": 20610,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/m5t111-v6-phase77-2-smoke.json",
          "sha256": "07bb7a96920b0a14a553902c1a03001fd8eec5cdaad736667948384af7bc92bc"
        },
        {
          "bytes": 65648,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-cost-origin-proof.json",
          "sha256": "3523c633181bcc0458c270a679487727a285933a5cf88a11c3d44b5e1e17295c"
        }
      ],
      "id": "M5T-111",
      "limit": "One warmed pair; p50/p95 and universal speedup unavailable. Initial pair is not cold OS/cache.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 187257,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/regression-reconciliation.json",
          "sha256": "27b70430d383720aa4c85044d29a3fba698991671dbe8b95068faaf7e33f1866"
        },
        {
          "bytes": 209477,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/historical-traceability.json",
          "sha256": "6200fd20bcabfbab2a2e175c03b6466bdb3c611c3186c16188faf8fc945538f0"
        }
      ],
      "id": "M5T-112",
      "limit": "Work units and dependent observations are separate; global regression financial calls were not instrumented.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 4327,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-pair-03/pair-verified.json",
          "sha256": "7a31c9a62d3d3053e4e12ef9327be69f7ab27689927fd1490a7896a437550378"
        },
        {
          "bytes": 4341,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-sdist-03/sdist-verified.json",
          "sha256": "b93154d3ec6e1ca1bfd81e21b1ac6cf9bf10e1018a3aeb18e3494a6f40869066"
        }
      ],
      "id": "M5T-113",
      "limit": "Four representative report views per kind; twelve historical report seals are retained, not all rerendered.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 98252,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-pair-proof.json",
          "sha256": "1eebe38514770b5c51025651810a603e8841559afe9f97d5b84401114264cd90"
        },
        {
          "bytes": 98573,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-sdist-proof.json",
          "sha256": "1f4f123df913169d62101940c0255890bdc85198914d278afba7c185ef25be18"
        }
      ],
      "id": "M5T-114",
      "limit": "Actual bounded calibration/winner/donor reconciliation plus exact snapshot roundtrips; no broad economics inferred.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 28556,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/proof.json",
          "sha256": "6298bc4e9ad9f47351d7f3e8639d83a993e0848fa5132f83c3cd867c39d86eba"
        },
        {
          "bytes": 98252,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-pair-proof.json",
          "sha256": "1eebe38514770b5c51025651810a603e8841559afe9f97d5b84401114264cd90"
        },
        {
          "bytes": 7700,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-execution-pair-proof.json",
          "sha256": "96bc8d3daeaa7552296e2c45dfaeb251c737a8f0732b8d28675c5e3cc44c100f"
        },
        {
          "bytes": 35790,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-pct-pair-proof.json",
          "sha256": "d22858d978b2a168c1d4f665a7325024565042a9b81d4f1475b817c1d80b48cc"
        },
        {
          "bytes": 57050,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/integrated-pair-proof.json",
          "sha256": "2e2310dac870173d536af88ea4f413848d1a1578f0d4c6a80fbde1b115f52562"
        },
        {
          "bytes": 4445,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-adapter-v6-pair/complete.json",
          "sha256": "094d3836fe957b391766d6236c200fc9c1e5225a732a60c55b598c0f6bad18fe"
        },
        {
          "bytes": 3003,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-rsi-pair-03/complete.json",
          "sha256": "ec03031e77987ddda9f160deca66538db31d96d83d6fd903db2a7ed01bde11fe"
        },
        {
          "bytes": 4327,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-pair-03/pair-verified.json",
          "sha256": "7a31c9a62d3d3053e4e12ef9327be69f7ab27689927fd1490a7896a437550378"
        },
        {
          "bytes": 98573,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-sdist-proof.json",
          "sha256": "1f4f123df913169d62101940c0255890bdc85198914d278afba7c185ef25be18"
        },
        {
          "bytes": 7720,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-execution-sdist-proof.json",
          "sha256": "16370575ece809c1404ea1a0e620fcf63c7cb61a0c046b69b65335bc079dee2b"
        },
        {
          "bytes": 35798,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-pct-sdist-proof.json",
          "sha256": "12e6265a59a96a5f5ac5ece2be8146f30c0f2cd24d36056459f9c0b5a79020b0"
        },
        {
          "bytes": 57111,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/integrated-sdist-proof.json",
          "sha256": "fef505de361f39334ac1a755f3a322df784b6564d79d52bb56d076960300e9ef"
        },
        {
          "bytes": 4450,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-adapter-v6-sdist/complete.json",
          "sha256": "ade1619f46a51d8d8d3559e2bcd550e515ae96685f441cb0cfd14b6ee7e5f7e4"
        },
        {
          "bytes": 3008,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-rsi-sdist-03/complete.json",
          "sha256": "a8ea9e51f6684c2b0a974a9aed2ebfb11f7fd2c9c52372ab5cd2e9efb6935b56"
        },
        {
          "bytes": 4341,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-sdist-03/sdist-verified.json",
          "sha256": "b93154d3ec6e1ca1bfd81e21b1ac6cf9bf10e1018a3aeb18e3494a6f40869066"
        }
      ],
      "id": "M5T-115",
      "limit": "Only local CPython3.12 Linux x86_64; not manylinux/six-row/public-index qualification.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 98252,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-pair-proof.json",
          "sha256": "1eebe38514770b5c51025651810a603e8841559afe9f97d5b84401114264cd90"
        },
        {
          "bytes": 98573,
          "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-sdist-proof.json",
          "sha256": "1f4f123df913169d62101940c0255890bdc85198914d278afba7c185ef25be18"
        }
      ],
      "id": "M5T-116",
      "limit": "Narrowed current access is revalidated; no backdated full-history diagnostic authority.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 920,
          "log": {
            "bytes": 98,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/final-operations.log",
            "sha256": "449f48faab28952069f2e297454c2a3b0f42069bcbc27c7b2b56439fc80297ed"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/final-operations.json",
          "rss": {
            "bytes": 1228,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/final-operations-rss.log",
            "sha256": "e1590601926f3f2c4a4c83d8a8fa11485c0e3a80617510bd718ccf4b99916fc7"
          },
          "seconds": 2.2207370288670063,
          "sha256": "ec1ce927bc34d8c6888a3ea75e7bc28f154f81f1f4164d9c08f8da0f717c6c4a",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 187257,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/regression-reconciliation.json",
          "sha256": "27b70430d383720aa4c85044d29a3fba698991671dbe8b95068faaf7e33f1866"
        }
      ],
      "id": "M5T-117",
      "limit": "V5 operational controls retain unchanged session/cache contract bytes and exact native; current installed rights/lifecycle run separately. No automatic full-WFO/account recovery.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 492,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/cleanup-v6-terminal.json",
          "sha256": "cd565c57f21bc5d9d57e50a9e06239af925f356a70b9ddf45015caa72c9a6151"
        },
        {
          "bytes": 3850,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/final-static.json",
          "sha256": "696289c8ac82c61f6ae672635b17be7ec1dfa6af80316b0189b67b6efd847e36"
        },
        {
          "bytes": 1272,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/cleanup-final40-reconciliation.json",
          "sha256": "c9676e01e89660098c559300b809cc74e2e9099165795ea0151264c60ee11d5d"
        }
      ],
      "id": "M5T-118",
      "limit": "Approved changes and original failures retained; no publication or historical unchanged-finance claim.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 927,
          "log": {
            "bytes": 421,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/snapshot-source-guard.log",
            "sha256": "52cd6ee4b87d65d1ad3d7bc1ce9959de40aede7f3bebef55c0f976c69c2ff8c8"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/snapshot-source-guard.json",
          "rss": {
            "bytes": 1217,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/snapshot-source-guard-rss.log",
            "sha256": "472869a6f115fc2d556fb7df9924911f487d496ca36ade648216b7f90aabfb06"
          },
          "seconds": 14.462779860943556,
          "sha256": "6a8b11cc65145b167ef2fe066209c236a065e5123c04d4b3a2aef90126a33d75",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 727,
          "log": {
            "bytes": 99,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/traceability-public-checkout.log",
            "sha256": "48b8c70868190faf0db987106acb37728d88cc8d60589178841b51ff8d8498bc"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/traceability-public-checkout.json",
          "rss": {
            "bytes": 1042,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/traceability-public-checkout-rss.log",
            "sha256": "8244c2834f85b012d3ba338b09b31b2d0a45fdf61856322b1f6fdc202b9a05a2"
          },
          "seconds": 1.1685355158988386,
          "sha256": "3324e7c6742838a914539d4fd381c75551dbe66aa238dbf8e6315ec716ee78ac",
          "status": "EXECUTED_EXIT_ZERO"
        }
      ],
      "id": "M5T-119",
      "limit": "Schema/renderer/missing-custody negatives are not standalone scientific certification.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    },
    {
      "evidence": [
        {
          "bytes": 209477,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/historical-traceability.json",
          "sha256": "6200fd20bcabfbab2a2e175c03b6466bdb3c611c3186c16188faf8fc945538f0"
        },
        {
          "bytes": 187257,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/regression-reconciliation.json",
          "sha256": "27b70430d383720aa4c85044d29a3fba698991671dbe8b95068faaf7e33f1866"
        }
      ],
      "id": "M5T-120",
      "limit": "All120 IDs and twelve phases reconciled by scope; no blanket120-PASS inference.",
      "status": "LOCAL_RECORDED_WITH_EXPLICIT_SCOPE"
    }
  ],
  "reuse_dispositions": [
    {
      "evidence": {
        "bytes": 209477,
        "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/historical-traceability.json",
        "sha256": "6200fd20bcabfbab2a2e175c03b6466bdb3c611c3186c16188faf8fc945538f0"
      },
      "scope": "M5-01..11",
      "status": "RETAINED_SOURCE_BOUND_OWNER_ACCEPTED_SCOPE"
    },
    {
      "evidence": {
        "bytes": 187257,
        "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/regression-reconciliation.json",
        "sha256": "27b70430d383720aa4c85044d29a3fba698991671dbe8b95068faaf7e33f1866"
      },
      "scope": "Initial failed attempts",
      "status": "FAIL_RETAINED_NOT_RELABELED"
    },
    {
      "evidence": {
        "path": ".maturin/qms08/m5-12-local-v4/cp312/native-build.json",
        "sha256": "16c7b69416b7d80b94f517a931c8a89941e7411d4f3c1b0969ed6e0ba98b44b2"
      },
      "scope": "Native build",
      "status": "EXACT_FRESH_BUILD_REUSED_AFTER_FULL_RUST_IDENTITY_CHECK"
    }
  ]
}
```

## Test Runs

```json
{
  "test_runs": [
    {
      "evidence": {
        "bytes": 187257,
        "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/regression-reconciliation.json",
        "sha256": "27b70430d383720aa4c85044d29a3fba698991671dbe8b95068faaf7e33f1866"
      },
      "scope": "Frozen43source shards and focused recovery"
    },
    {
      "executions": [
        {
          "bytes": 559,
          "log": {
            "bytes": 279,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-preflight.log",
            "sha256": "51966373da804ec806072066ecbb0cb257d3a43c83a43d4422c1052e5cbd3128"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-preflight.json",
          "rss": {
            "bytes": 889,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-preflight-rss.log",
            "sha256": "c946306e3f1e3b319e61ca72ac9fd3c6b80310bf208b2f173d72b19f8842e0c9"
          },
          "seconds": 58.79379047686234,
          "sha256": "50d334a5b64bd7f3b2fddb0e540d57e1fc7dbeecfc816580beadd1d51f39bd6e",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 579,
          "log": {
            "bytes": 5997,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-execution.log",
            "sha256": "b1e410ebd5943a2d474c06598ee1da3c1abf63862e0685552c8a1de797cb3930"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-execution.json",
          "rss": {
            "bytes": 916,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-execution-rss.log",
            "sha256": "6557dc1427f42163f300370a8b05d0a89508799099e5ef249315d70d0d337645"
          },
          "seconds": 397.4253320740536,
          "sha256": "4b8a123cdf1c48425e3e9234c0c6540d940e81416f4772f42f7d212c276d1c56",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 558,
          "log": {
            "bytes": 107,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-pct.log",
            "sha256": "f048c0543ff85c257dddfadaafdcb07c3d1469c8f1326afea5c17d3af7dd18f8"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-pct.json",
          "rss": {
            "bytes": 900,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-pct-rss.log",
            "sha256": "15f320bd6e5b01795ef049f33c3cc887b469786455ecf6a6efc5024d8d60e8a1"
          },
          "seconds": 24.43717524386011,
          "sha256": "71082fd0713cca34dd74dcba02a28647aa587696b66fbed97783c7007ec76a4d",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 557,
          "log": {
            "bytes": 332,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-integrated.log",
            "sha256": "f0db063365a4feb2ee324c0094920f5d862a4302619329d335239d9de5b1da80"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-integrated.json",
          "rss": {
            "bytes": 902,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-integrated-rss.log",
            "sha256": "3de424034dd7149dd3d68adcfa69a14eba30a60bf7becfdc9c80e041aa3e14da"
          },
          "seconds": 282.7143052208703,
          "sha256": "a2059e032804e2f1ae78deee2b5944ee93d547873d5ed8042569583fcd63f345",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 822,
          "log": {
            "bytes": 0,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-four.log",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-four.json",
          "rss": {
            "bytes": 1139,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-four-rss.log",
            "sha256": "5a4e1e4d77ccfaacdaeae81a57ea9e2515f69c5c6d6b28abba18a816f11249b3"
          },
          "seconds": 16.973635267000645,
          "sha256": "7f5fa1bf2e545a3d8873e142d0b36080edc847e2633c71e1d5e6a9b83248f3c2",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 715,
          "log": {
            "bytes": 0,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-rsi.log",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-rsi.json",
          "rss": {
            "bytes": 1033,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-rsi-rss.log",
            "sha256": "d1ef8b8e9b6341572ddb6b9c025574b63f734001b58181dceee1ef0ff0b2398d"
          },
          "seconds": 6.782603554893285,
          "sha256": "1465080b70fbcd6ce45f046e3ebe6ce0c7f68035737b7b259f21b185ff89b4a1",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 602,
          "log": {
            "bytes": 202,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-reproduce.log",
            "sha256": "12b2407480967a394843406c89efce8bd5ea1aed865991194ccbe48e711ccf37"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-reproduce.json",
          "rss": {
            "bytes": 949,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-reproduce-rss.log",
            "sha256": "e56f4d5cdd495f9f9d5e52576296c47ebea149929c8b94c6e2f9f166f1c9a384"
          },
          "seconds": 15.106431554071605,
          "sha256": "16f3f0270492555d83a827f946d358b64b9b914a971baf1633c08fad733263fc",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 539,
          "log": {
            "bytes": 598,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-missing-optuna.log",
            "sha256": "0da4537cbf80d65a11d84ac465091e8aa742ca30256d8408cfc7e92dc0e7733a"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-missing-optuna.json",
          "rss": {
            "bytes": 888,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-missing-optuna-rss.log",
            "sha256": "f7384016062e73aae410e099be118a59df541d6d7f4120d5ee844edd1019dfb6"
          },
          "seconds": 7.741138528101146,
          "sha256": "e67a970e4bd023320a21fdba1cf34c2773c8dff89688b9f64f64acc497f9c76b",
          "status": "EXECUTED_EXIT_ZERO"
        }
      ],
      "scope": "pair"
    },
    {
      "executions": [
        {
          "bytes": 560,
          "log": {
            "bytes": 282,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-preflight.log",
            "sha256": "8d7cd23bed40ac2c42b59f5758cd2a3e66e7dd853cf40c057b0aa89ea0e42339"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-preflight.json",
          "rss": {
            "bytes": 883,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-preflight-rss.log",
            "sha256": "dd15183137cdc440ce83912be6c756e1b002b7a0d4f271fde59114f8462ebdbe"
          },
          "seconds": 57.34417317411862,
          "sha256": "af9b9848238c396010c3c9569bfed3e5b7f2308bf4fa2dfbaa4578a672106e47",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 581,
          "log": {
            "bytes": 6019,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-execution.log",
            "sha256": "86838ad43dcb6da52150c1e95b0b966eb1ce5b1ebe037f86ae8a8b37e66bc98c"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-execution.json",
          "rss": {
            "bytes": 918,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-execution-rss.log",
            "sha256": "116f1deb3b5a502e994899fee60a21ec3a88e5d762f420a77e654ac69cd1902e"
          },
          "seconds": 408.03356380108744,
          "sha256": "f21c8594321c59f3705678b0188ef56122872208d18f8efa728cd1a7ab665bcb",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 560,
          "log": {
            "bytes": 108,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-pct.log",
            "sha256": "0318971198a9c6004243d8139345853087e44c2efd2ffd4401894ee388962a8f"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-pct.json",
          "rss": {
            "bytes": 899,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-pct-rss.log",
            "sha256": "87c4e2a4941cdacef6aa6a3c1c8ae06a2c8644f99c1fe3dec38a2c9d6a929511"
          },
          "seconds": 24.631971734808758,
          "sha256": "987fc9f8e758ca7ca5c272c941529969c108d5e337252ff32343a27375015040",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 558,
          "log": {
            "bytes": 340,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-integrated.log",
            "sha256": "2deaa381bc886ad71456bf924feeb1eb3ffb7b9b9235afdafd859ab933e62294"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-integrated.json",
          "rss": {
            "bytes": 903,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-integrated-rss.log",
            "sha256": "ab96f7bb067e757a7c1cc8e39a805007d2ec69a88d651f984e9f2b1437d91d4b"
          },
          "seconds": 288.0993845879566,
          "sha256": "849ccedd876321568227878bf8df141fbe0af972ebb609acb6bc17a00668185c",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 825,
          "log": {
            "bytes": 0,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-four.log",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-four.json",
          "rss": {
            "bytes": 1140,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-four-rss.log",
            "sha256": "ca22418ee06bbd3b573facf28dbac1e03800feae87c9faef1be8cf15069ff762"
          },
          "seconds": 17.015693590976298,
          "sha256": "28ec7395907d9abf5df667d0b0ff01f4b74d9b3b94dbe952f9a6f332ddfa25e1",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 717,
          "log": {
            "bytes": 0,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-rsi.log",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-rsi.json",
          "rss": {
            "bytes": 1033,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-rsi-rss.log",
            "sha256": "73f83baaa452dc178fc715a4b92f761eb51ae0bb5e3c14dd25532e15b491d1f5"
          },
          "seconds": 6.981475384905934,
          "sha256": "fd0723a8cf9672167dce40093bdd551eeaa998d925d1076e509668fc58b6d7ba",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 603,
          "log": {
            "bytes": 204,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-reproduce.log",
            "sha256": "8b29bc1f21e24c8bfc9772a0fce1192a8371fbbc3032108a197554c1d1e91078"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-reproduce.json",
          "rss": {
            "bytes": 949,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-reproduce-rss.log",
            "sha256": "adab1738c01ec1163a1c4835d7b120d7301f69bd350af2897cf4873d5519437c"
          },
          "seconds": 15.20894001214765,
          "sha256": "4ead2997678f8037a9a38e32e50eb9023c4bf912f30bdc7d681b959e1b3f8ebc",
          "status": "EXECUTED_EXIT_ZERO"
        },
        {
          "bytes": 541,
          "log": {
            "bytes": 601,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-missing-optuna.log",
            "sha256": "a2b3779da85b5ebf8e34036f8620c6292d8f8fd28b19fd61f589318070f6a621"
          },
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-missing-optuna.json",
          "rss": {
            "bytes": 890,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-missing-optuna-rss.log",
            "sha256": "cfde6884bd06efffaa2b72521a3ae3443f762bf818f54fbd33c1eea9dd1fa09c"
          },
          "seconds": 7.838133814046159,
          "sha256": "9ad6d9f611dee790dda55f7839684cec24fa5fef57ae17c712fb574d3e41ae94",
          "status": "EXECUTED_EXIT_ZERO"
        }
      ],
      "scope": "sdist"
    }
  ]
}
```

## Numeric Results And Matrices

```json
{
  "matrices": {
    "architecture_api_inventory_native_contract_source_privacy_static": {
      "bytes": 3850,
      "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/final-static.json",
      "sha256": "696289c8ac82c61f6ae672635b17be7ec1dfa6af80316b0189b67b6efd847e36"
    },
    "formula_registry": {
      "formulas": {
        "environment_floor_mean_v1": {
          "definition": "min(v) + mean_coefficient * weighted_mean(v) - activity_penalty",
          "family": "environment",
          "required_coefficients": [
            "mean"
          ]
        },
        "environment_lower_tail_v2": {
          "definition": "floor_coefficient * min(v) + tail_coefficient * lower_probability_mass_mean(v,alpha) - dispersion_coefficient * weighted_lower_tie_MAD(v) - activity_penalty",
          "family": "environment",
          "required_coefficients": [
            "floor",
            "tail",
            "dispersion",
            "alpha"
          ]
        },
        "finite_panel_minimax_regret_v1": {
          "definition": "-max(benchmark-economic_utility) - activity_penalty",
          "family": "environment",
          "required_coefficients": []
        },
        "legacy_floor_mean_regret_v1": {
          "definition": "min(v) - mean_coefficient * weighted_mean(benchmark-v) - activity_penalty",
          "family": "environment",
          "required_coefficients": [
            "mean"
          ]
        },
        "legacy_spec_1_1_quantile": {
          "definition": "floor_coefficient * min(v) + tail_coefficient * linear_quantile(v,alpha) - dispersion_coefficient * unweighted_midpoint_MAD(v) - activity_penalty",
          "family": "environment",
          "required_coefficients": [
            "floor",
            "tail",
            "dispersion",
            "alpha"
          ]
        },
        "local_downside_v1": {
          "definition": "weighted_mean(center) - gamma * max(0,weighted_mean(center)-min(probe_aggregates)) - activity_penalty",
          "family": "local",
          "required_coefficients": [
            "gamma"
          ]
        },
        "pareto_chebyshev_v1": {
          "definition": "-max(weight * frozen_normalized_gap) - rho * sum(weight * frozen_normalized_gap) - activity_penalty",
          "family": "pareto",
          "required_coefficients": [
            "rho"
          ]
        },
        "unified_same_channel_v1": {
          "definition": "floor_coefficient * min(v) + mean_coefficient * weighted_mean(v) - dispersion_coefficient * population_weighted_SD(v) - fragility_coefficient * local_downside - activity_penalty",
          "family": "unified",
          "required_coefficients": [
            "floor",
            "mean",
            "dispersion",
            "fragility"
          ]
        }
      },
      "identity": "894d389b962c895d5513e8196858de94fef977ceda3fbd3d769b97636689e09b",
      "local_scope": "schema union optional covariance; finite observed probes, not a global robust ball",
      "null_policy": "retain incomplete/failed rows; no favorable default or silent environment drop",
      "pareto_scope": "post-selection on actual generation; no NSGA-II generation or hypervolume claim",
      "public_activation": false,
      "references": "frozen per stage; full-panel revision for changes",
      "schema": "mode5.formulas.v1",
      "tie_policy": "candidate_id_lexicographic_v1",
      "units": "all scalar components and penalties have the explicitly selected channel unit"
    },
    "historical_phases": [
      {
        "current_disposition": {
          "evidence": {
            "bytes": 1889,
            "path": "docs/mode5/evidence/m5-01-exit-review.json",
            "sha256": "d1ce6713f580350f34b93796b331ac592609d2f89f5abf444cf9b78511264eb8"
          },
          "owner_exit": "EXTRACTED_MEMBERS_ACCEPTED",
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-01",
        "json": {
          "bytes": 1619,
          "path": "docs/mode5/evidence/m5-01.json",
          "sha256": "1e9a5f9b3d05eb498f2fe125ebc64297a2e7e55c069a16f90afb9b53ec4a4148",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 12866,
          "path": "docs/mode5/M5_01_BASELINE_REPORT.md",
          "sha256": "1a95297cb5253bb9281027ef749677bdef36e32ff144bb332bdf3113bb1cb71f",
          "status": "RETAINED"
        },
        "recorded_source": {
          "committed_tested_phase_source": "14dd9b825087352176e3120ce790e0edef63c275"
        },
        "recorded_status": "INPUT_EXIT_PENDING",
        "scope": "source/helper/artifact controls; extracted-member exit approved separately"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-02",
        "json": {
          "bytes": 8384,
          "path": "docs/mode5/evidence/m5-02.json",
          "sha256": "92ed2a0dd505f274ea70053cd959782f4275aa05f4d50cbb1cbac3dc8bd8be76",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 9545,
          "path": "docs/mode5/M5_02_ADMISSION_REPORT.md",
          "sha256": "b70cf343c66d8a545b2cf7da65117b9ab8555d0cf7f7ba58e2933c60deeac9e6",
          "status": "RETAINED"
        },
        "recorded_source": {
          "qualified_phase_commits": [
            "7fd721c04c3236fd72d07a3a49254ccdcf621687",
            "09810dbbe5dbc45c17f276332147e892fb545e8c"
          ]
        },
        "recorded_status": "COMPLETE_LOCAL_ADMISSION",
        "scope": "actual five-alpha binding admission; short reviewed window, not economic transfer"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-03",
        "json": {
          "bytes": 9160,
          "path": "docs/mode5/evidence/m5-03.json",
          "sha256": "bb822500528ec2a9a09922f9d33757a16bbb34e9bb8a0537f5d42aa372220e98",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 8666,
          "path": "docs/mode5/M5_03_STATISTICS_REPORT.md",
          "sha256": "c1a2ce2f57266741786c645fb36900fbf1e6371e4dc83f1508dc5b89ffcf4af4",
          "status": "RETAINED"
        },
        "recorded_source": {},
        "recorded_status": "COMPLETE_LOCAL_STATISTICS",
        "scope": "metric/oracle and synthetic financial streams; not a trading performance certificate"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-04",
        "json": {
          "bytes": 2938,
          "path": "docs/mode5/evidence/m5-04-final.json",
          "sha256": "e06c6a488466c6f71d986f61516cec9acdbd47cc65a7602be0ee3a00fa164e1d",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 5419,
          "path": "docs/mode5/M5_04_REUSE_REPORT.md",
          "sha256": "5ccfc229aac777d96420b29f25c04eb43d8fe6f414e3750fe8005997cf243588",
          "status": "RETAINED"
        },
        "recorded_source": {
          "implementation_source_sha": "783994afa5c932546164f56af52c23fbc7bcb9cb"
        },
        "recorded_status": "COMPLETE_LOCAL_REUSE",
        "scope": "planner/cache/rights/audit controls; stored history is not an adaptive rerun"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-05",
        "json": {
          "bytes": 3892,
          "path": "docs/mode5/evidence/m5-05.json",
          "sha256": "50c28bd3dbf4cc29b0ab3da6d5f6dd43beacd48473a5339e20aaee9d9343eeb6",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 5383,
          "path": "docs/mode5/M5_05_ENVIRONMENT_REPORT.md",
          "sha256": "5c998138f46225d47504dca2af8ea06dd7c27d0a90bbf2e1c4d674b220c8a86a",
          "status": "RETAINED"
        },
        "recorded_source": {
          "implementation_source_sha": "b5648eb44f5fc0b55d331891d1f8e94225ff92c1"
        },
        "recorded_status": "COMPLETE_LOCAL_ENVIRONMENTS",
        "scope": "environment rights, continuous attribution and explicit reset controls"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-06",
        "json": {
          "bytes": 11438,
          "path": "docs/mode5/evidence/m5-06.json",
          "sha256": "0d14cd06721dde1a731ed266c3e4ebcd321ceaf35ccdfb4110b7537e82687427",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 8974,
          "path": "docs/mode5/M5_06_GEOMETRY_REPORT.md",
          "sha256": "f1f30631ad7f35ee0264aa4dbf1bb515a805953961277993ddfda3d5738ea715",
          "status": "RETAINED"
        },
        "recorded_source": {
          "implementation_source_sha": "36e9895ba9cb74d3e2a01c203842110663d867ac"
        },
        "recorded_status": "COMPLETE_LOCAL_GEOMETRY",
        "scope": "feasible geometry and finite probes; no all-alpha global sensitivity or basin guarantee"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-07",
        "json": {
          "bytes": 4293,
          "path": "docs/mode5/evidence/m5-07.json",
          "sha256": "845827491cba3cad16dbd276001ebde9183ac7083705d1edaa1ef424d319f846",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 7881,
          "path": "docs/mode5/M5_07_SELECTION_REPORT.md",
          "sha256": "c04d1f9b5e04bc9c7b334526a949ff4bb7aecad506f289b625fb07b73f171b8e",
          "status": "RETAINED"
        },
        "recorded_source": {
          "tested_source_head": "45f5a5a64d62b89c2e7e57557955df76c5eff81d"
        },
        "recorded_status": "COMPLETE_LOCAL_OBJECTIVES",
        "scope": "versioned formulas and selector arithmetic; guide math assertions are not market observations"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-08",
        "json": {
          "bytes": 1411,
          "path": "docs/mode5/evidence/m5-08.json",
          "sha256": "bc8663a3ac44ef5e90236aceeb0eba3b1b21e5890cad649715776efcbc0ba937",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 9814,
          "path": "docs/mode5/M5_08_BATTERY_REPORT.md",
          "sha256": "e9c58e69214801d2f39ea43dae5135d1ee4b0006d3b032ca56f4c6fd237f26ee",
          "status": "RETAINED"
        },
        "recorded_source": {},
        "recorded_status": "COMPLETE_LOCAL_TARGETED_DIAGNOSTICS",
        "scope": "registered targeted diagnostics; later studies have distinct scope and access history"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-09",
        "json": {
          "bytes": 1780,
          "path": "docs/mode5/evidence/m5-09.json",
          "sha256": "66b3e6c4fec5f893927f3f46f77c1cfd07d88a2d90fb9aa8551d99d1ac2640b3",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 6058,
          "path": "docs/mode5/M5_09_DOSSIER_REPORT.md",
          "sha256": "2a8b1babac4c19cdc96441792375a13c939c3f46e6957021f84f65dd8b9a56af",
          "status": "RETAINED"
        },
        "recorded_source": {},
        "recorded_status": "COMPLETE_LOCAL_DOSSIER_GOVERNANCE",
        "scope": "dossier/plan/advisory governance; no automatic router qualification"
      },
      {
        "current_disposition": {
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-10",
        "json": {
          "bytes": 5199,
          "path": "docs/mode5/evidence/m5-10.json",
          "sha256": "440716e1dc09736e8e63daf68f5387dd7e8a823814727529dd7d2abab05a1084",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 14095,
          "path": "docs/mode5/M5_10_PUBLIC_RUNTIME_REPORT.md",
          "sha256": "6d465760f0d223abef9fae7195cab33f9b1718c1be2cf17885c99398072ad38f",
          "status": "RETAINED"
        },
        "recorded_source": {
          "qualified_code_commit": "bf11409895a30d47f08b53bc3d0cf9e1f453c2ba"
        },
        "recorded_status": "COMPLETE_LOCAL_PUBLIC_OPT_IN",
        "scope": "historical opt-in runtime and installed pair; not the ACC-repaired final artifact"
      },
      {
        "current_disposition": {
          "current_coverage_ledger": "docs/mode5/M5_11_RESEARCH_COVERAGE_DISPOSITION.md",
          "evidence": {
            "bytes": 2449,
            "path": "docs/mode5/evidence/m5-11-parent-disposition.json",
            "sha256": "6b5c822c29af2b968b2a770b927f9a6e25981f61c20b239bcb08bd06d262896c"
          },
          "owner_exit": "ACCEPT_COMPLETED_REGISTERED_SCOPES_WITH_LIMITATIONS",
          "scientific_scope": "Original observation and later accepted parent limitations retained",
          "scope": "Registered historical scope; not current installed qualification",
          "task": "VERIFIED_EXISTING"
        },
        "current_installed_certificate": false,
        "id": "M5-11",
        "json": {
          "bytes": 56219,
          "path": "docs/mode5/evidence/m5-11.json",
          "sha256": "4103e4b8b9bd7df7b37c57a6be4e1ff3243f5939da0ecb214d27fc40f17c4ed6",
          "status": "RETAINED"
        },
        "markdown": {
          "bytes": 12813,
          "path": "docs/mode5/M5_11_ECONOMIC_REPORT.md",
          "sha256": "e0749aac023902f7255caaa164c967be0a043a6a7b8c1ae0910e535913b93c8e",
          "status": "RETAINED"
        },
        "recorded_source": {},
        "recorded_status": "COMPLETE_LOCAL_FINITE_PILOT_EXPLORATORY",
        "scope": "historical finite exploratory pilot; accepted parent ledger supplies the subsequent scope disposition"
      },
      {
        "current_disposition": {
          "current_receipts": [
            {
              "bytes": 98252,
              "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-pair-proof.json",
              "sha256": "1eebe38514770b5c51025651810a603e8841559afe9f97d5b84401114264cd90"
            },
            {
              "bytes": 98573,
              "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-sdist-proof.json",
              "sha256": "1f4f123df913169d62101940c0255890bdc85198914d278afba7c185ef25be18"
            }
          ],
          "owner_final_review": "PENDING",
          "scope": "Exact local wheel and sdist with native companion; not remote/public or live authority",
          "task": "IMPLEMENTED_VERIFIED",
          "technical_status": "PARTIAL_TECHNICAL_CLOSURE"
        },
        "current_installed_certificate": false,
        "id": "M5-12",
        "json": null,
        "markdown": null,
        "recorded_status": "MAIN_REPORT_NOT_SUPPLIED",
        "scope": "current-source local qualification"
      }
    ],
    "installed_consumers": [
      {
        "actual_missing_optional_optimizer": {
          "bytes": 626,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/missing-optuna-pair.json",
          "sha256": "d609d4ac9bdc3ae19b3971b945bd4e0f4c7eea79c3c096d660f4875723caec3c"
        },
        "execution_cases": 149,
        "executions": [
          {
            "bytes": 559,
            "log": {
              "bytes": 279,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-preflight.log",
              "sha256": "51966373da804ec806072066ecbb0cb257d3a43c83a43d4422c1052e5cbd3128"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-preflight.json",
            "rss": {
              "bytes": 889,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-preflight-rss.log",
              "sha256": "c946306e3f1e3b319e61ca72ac9fd3c6b80310bf208b2f173d72b19f8842e0c9"
            },
            "seconds": 58.79379047686234,
            "sha256": "50d334a5b64bd7f3b2fddb0e540d57e1fc7dbeecfc816580beadd1d51f39bd6e",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 579,
            "log": {
              "bytes": 5997,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-execution.log",
              "sha256": "b1e410ebd5943a2d474c06598ee1da3c1abf63862e0685552c8a1de797cb3930"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-execution.json",
            "rss": {
              "bytes": 916,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-execution-rss.log",
              "sha256": "6557dc1427f42163f300370a8b05d0a89508799099e5ef249315d70d0d337645"
            },
            "seconds": 397.4253320740536,
            "sha256": "4b8a123cdf1c48425e3e9234c0c6540d940e81416f4772f42f7d212c276d1c56",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 558,
            "log": {
              "bytes": 107,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-pct.log",
              "sha256": "f048c0543ff85c257dddfadaafdcb07c3d1469c8f1326afea5c17d3af7dd18f8"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-pct.json",
            "rss": {
              "bytes": 900,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-pair-pct-rss.log",
              "sha256": "15f320bd6e5b01795ef049f33c3cc887b469786455ecf6a6efc5024d8d60e8a1"
            },
            "seconds": 24.43717524386011,
            "sha256": "71082fd0713cca34dd74dcba02a28647aa587696b66fbed97783c7007ec76a4d",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 557,
            "log": {
              "bytes": 332,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-integrated.log",
              "sha256": "f0db063365a4feb2ee324c0094920f5d862a4302619329d335239d9de5b1da80"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-integrated.json",
            "rss": {
              "bytes": 902,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-integrated-rss.log",
              "sha256": "3de424034dd7149dd3d68adcfa69a14eba30a60bf7becfdc9c80e041aa3e14da"
            },
            "seconds": 282.7143052208703,
            "sha256": "a2059e032804e2f1ae78deee2b5944ee93d547873d5ed8042569583fcd63f345",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 822,
            "log": {
              "bytes": 0,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-four.log",
              "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-four.json",
            "rss": {
              "bytes": 1139,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-four-rss.log",
              "sha256": "5a4e1e4d77ccfaacdaeae81a57ea9e2515f69c5c6d6b28abba18a816f11249b3"
            },
            "seconds": 16.973635267000645,
            "sha256": "7f5fa1bf2e545a3d8873e142d0b36080edc847e2633c71e1d5e6a9b83248f3c2",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 715,
            "log": {
              "bytes": 0,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-rsi.log",
              "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-rsi.json",
            "rss": {
              "bytes": 1033,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-private-rsi-rss.log",
              "sha256": "d1ef8b8e9b6341572ddb6b9c025574b63f734001b58181dceee1ef0ff0b2398d"
            },
            "seconds": 6.782603554893285,
            "sha256": "1465080b70fbcd6ce45f046e3ebe6ce0c7f68035737b7b259f21b185ff89b4a1",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 602,
            "log": {
              "bytes": 202,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-reproduce.log",
              "sha256": "12b2407480967a394843406c89efce8bd5ea1aed865991194ccbe48e711ccf37"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-reproduce.json",
            "rss": {
              "bytes": 949,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-reproduce-rss.log",
              "sha256": "e56f4d5cdd495f9f9d5e52576296c47ebea149929c8b94c6e2f9f166f1c9a384"
            },
            "seconds": 15.106431554071605,
            "sha256": "16f3f0270492555d83a827f946d358b64b9b914a971baf1633c08fad733263fc",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 539,
            "log": {
              "bytes": 598,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-missing-optuna.log",
              "sha256": "0da4537cbf80d65a11d84ac465091e8aa742ca30256d8408cfc7e92dc0e7733a"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-missing-optuna.json",
            "rss": {
              "bytes": 888,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-pair-missing-optuna-rss.log",
              "sha256": "f7384016062e73aae410e099be118a59df541d6d7f4120d5ee844edd1019dfb6"
            },
            "seconds": 7.741138528101146,
            "sha256": "e67a970e4bd023320a21fdba1cf34c2773c8dff89688b9f64f64acc497f9c76b",
            "status": "EXECUTED_EXIT_ZERO"
          }
        ],
        "feature_cases": 44,
        "integrated_families": 8,
        "kind": "pair",
        "pct_cases": 19,
        "private_alpha_controls": 5,
        "private_native_execution_claim": false,
        "private_rsi_direct_check": "Same-kernel wrapper parity, not independent fill ledger",
        "private_scope": "Actual frozen private adapters on bounded synthetic tape; no new long-horizon economic claim",
        "receipts": [
          {
            "bytes": 98252,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-pair-proof.json",
            "sha256": "1eebe38514770b5c51025651810a603e8841559afe9f97d5b84401114264cd90"
          },
          {
            "bytes": 7700,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-execution-pair-proof.json",
            "sha256": "96bc8d3daeaa7552296e2c45dfaeb251c737a8f0732b8d28675c5e3cc44c100f"
          },
          {
            "bytes": 35790,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-pct-pair-proof.json",
            "sha256": "d22858d978b2a168c1d4f665a7325024565042a9b81d4f1475b817c1d80b48cc"
          },
          {
            "bytes": 57050,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/integrated-pair-proof.json",
            "sha256": "2e2310dac870173d536af88ea4f413848d1a1578f0d4c6a80fbde1b115f52562"
          },
          {
            "bytes": 4445,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-adapter-v6-pair/complete.json",
            "sha256": "094d3836fe957b391766d6236c200fc9c1e5225a732a60c55b598c0f6bad18fe"
          },
          {
            "bytes": 3003,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-rsi-pair-03/complete.json",
            "sha256": "ec03031e77987ddda9f160deca66538db31d96d83d6fd903db2a7ed01bde11fe"
          },
          {
            "bytes": 4327,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-pair-03/pair-verified.json",
            "sha256": "7a31c9a62d3d3053e4e12ef9327be69f7ab27689927fd1490a7896a437550378"
          }
        ],
        "representative_reports": 4,
        "reproduction_scope": "Four representative JSON/Markdown views, not reconstruction of all twelve historical reports",
        "snapshot_checks": {
          "baseline": {
            "protocols": [
              "copy",
              "deepcopy",
              "pickle4",
              "pickle5"
            ],
            "query_count": 5
          },
          "challenger": {
            "protocols": [
              "copy",
              "deepcopy",
              "pickle4",
              "pickle5"
            ],
            "query_count": 4
          }
        },
        "status": "PASS_LOCAL_EXACT_ARTIFACT"
      },
      {
        "actual_missing_optional_optimizer": {
          "bytes": 629,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/missing-optuna-sdist.json",
          "sha256": "9d2ddb6f7639398714604e4a029906aaffb491766fea8616fc24392fbad49d51"
        },
        "execution_cases": 149,
        "executions": [
          {
            "bytes": 560,
            "log": {
              "bytes": 282,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-preflight.log",
              "sha256": "8d7cd23bed40ac2c42b59f5758cd2a3e66e7dd853cf40c057b0aa89ea0e42339"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-preflight.json",
            "rss": {
              "bytes": 883,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-preflight-rss.log",
              "sha256": "dd15183137cdc440ce83912be6c756e1b002b7a0d4f271fde59114f8462ebdbe"
            },
            "seconds": 57.34417317411862,
            "sha256": "af9b9848238c396010c3c9569bfed3e5b7f2308bf4fa2dfbaa4578a672106e47",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 581,
            "log": {
              "bytes": 6019,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-execution.log",
              "sha256": "86838ad43dcb6da52150c1e95b0b966eb1ce5b1ebe037f86ae8a8b37e66bc98c"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-execution.json",
            "rss": {
              "bytes": 918,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-execution-rss.log",
              "sha256": "116f1deb3b5a502e994899fee60a21ec3a88e5d762f420a77e654ac69cd1902e"
            },
            "seconds": 408.03356380108744,
            "sha256": "f21c8594321c59f3705678b0188ef56122872208d18f8efa728cd1a7ab665bcb",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 560,
            "log": {
              "bytes": 108,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-pct.log",
              "sha256": "0318971198a9c6004243d8139345853087e44c2efd2ffd4401894ee388962a8f"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-pct.json",
            "rss": {
              "bytes": 899,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-v6-sdist-pct-rss.log",
              "sha256": "87c4e2a4941cdacef6aa6a3c1c8ae06a2c8644f99c1fe3dec38a2c9d6a929511"
            },
            "seconds": 24.631971734808758,
            "sha256": "987fc9f8e758ca7ca5c272c941529969c108d5e337252ff32343a27375015040",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 558,
            "log": {
              "bytes": 340,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-integrated.log",
              "sha256": "2deaa381bc886ad71456bf924feeb1eb3ffb7b9b9235afdafd859ab933e62294"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-integrated.json",
            "rss": {
              "bytes": 903,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-integrated-rss.log",
              "sha256": "ab96f7bb067e757a7c1cc8e39a805007d2ec69a88d651f984e9f2b1437d91d4b"
            },
            "seconds": 288.0993845879566,
            "sha256": "849ccedd876321568227878bf8df141fbe0af972ebb609acb6bc17a00668185c",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 825,
            "log": {
              "bytes": 0,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-four.log",
              "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-four.json",
            "rss": {
              "bytes": 1140,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-four-rss.log",
              "sha256": "ca22418ee06bbd3b573facf28dbac1e03800feae87c9faef1be8cf15069ff762"
            },
            "seconds": 17.015693590976298,
            "sha256": "28ec7395907d9abf5df667d0b0ff01f4b74d9b3b94dbe952f9a6f332ddfa25e1",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 717,
            "log": {
              "bytes": 0,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-rsi.log",
              "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-rsi.json",
            "rss": {
              "bytes": 1033,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-private-rsi-rss.log",
              "sha256": "73f83baaa452dc178fc715a4b92f761eb51ae0bb5e3c14dd25532e15b491d1f5"
            },
            "seconds": 6.981475384905934,
            "sha256": "fd0723a8cf9672167dce40093bdd551eeaa998d925d1076e509668fc58b6d7ba",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 603,
            "log": {
              "bytes": 204,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-reproduce.log",
              "sha256": "8b29bc1f21e24c8bfc9772a0fce1192a8371fbbc3032108a197554c1d1e91078"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-reproduce.json",
            "rss": {
              "bytes": 949,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-reproduce-rss.log",
              "sha256": "adab1738c01ec1163a1c4835d7b120d7301f69bd350af2897cf4873d5519437c"
            },
            "seconds": 15.20894001214765,
            "sha256": "4ead2997678f8037a9a38e32e50eb9023c4bf912f30bdc7d681b959e1b3f8ebc",
            "status": "EXECUTED_EXIT_ZERO"
          },
          {
            "bytes": 541,
            "log": {
              "bytes": 601,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-missing-optuna.log",
              "sha256": "a2b3779da85b5ebf8e34036f8620c6292d8f8fd28b19fd61f589318070f6a621"
            },
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-missing-optuna.json",
            "rss": {
              "bytes": 890,
              "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-sdist-missing-optuna-rss.log",
              "sha256": "cfde6884bd06efffaa2b72521a3ae3443f762bf818f54fbd33c1eea9dd1fa09c"
            },
            "seconds": 7.838133814046159,
            "sha256": "9ad6d9f611dee790dda55f7839684cec24fa5fef57ae17c712fb574d3e41ae94",
            "status": "EXECUTED_EXIT_ZERO"
          }
        ],
        "feature_cases": 44,
        "integrated_families": 8,
        "kind": "sdist",
        "pct_cases": 19,
        "private_alpha_controls": 5,
        "private_native_execution_claim": false,
        "private_rsi_direct_check": "Same-kernel wrapper parity, not independent fill ledger",
        "private_scope": "Actual frozen private adapters on bounded synthetic tape; no new long-horizon economic claim",
        "receipts": [
          {
            "bytes": 98573,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-m5-12-sdist-proof.json",
            "sha256": "1f4f123df913169d62101940c0255890bdc85198914d278afba7c185ef25be18"
          },
          {
            "bytes": 7720,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-execution-sdist-proof.json",
            "sha256": "16370575ece809c1404ea1a0e620fcf63c7cb61a0c046b69b65335bc079dee2b"
          },
          {
            "bytes": 35798,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/installed-pct-sdist-proof.json",
            "sha256": "12e6265a59a96a5f5ac5ece2be8146f30c0f2cd24d36056459f9c0b5a79020b0"
          },
          {
            "bytes": 57111,
            "path": ".maturin/qms08/m5-12-local-v6/cp312/integrated-sdist-proof.json",
            "sha256": "fef505de361f39334ac1a755f3a322df784b6564d79d52bb56d076960300e9ef"
          },
          {
            "bytes": 4450,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-adapter-v6-sdist/complete.json",
            "sha256": "ade1619f46a51d8d8d3559e2bcd550e515ae96685f441cb0cfd14b6ee7e5f7e4"
          },
          {
            "bytes": 3008,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/private-rsi-sdist-03/complete.json",
            "sha256": "a8ea9e51f6684c2b0a974a9aed2ebfb11f7fd2c9c52372ab5cd2e9efb6935b56"
          },
          {
            "bytes": 4341,
            "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-sdist-03/sdist-verified.json",
            "sha256": "b93154d3ec6e1ca1bfd81e21b1ac6cf9bf10e1018a3aeb18e3494a6f40869066"
          }
        ],
        "representative_reports": 4,
        "reproduction_scope": "Four representative JSON/Markdown views, not reconstruction of all twelve historical reports",
        "snapshot_checks": {
          "baseline": {
            "protocols": [
              "copy",
              "deepcopy",
              "pickle4",
              "pickle5"
            ],
            "query_count": 5
          },
          "challenger": {
            "protocols": [
              "copy",
              "deepcopy",
              "pickle4",
              "pickle5"
            ],
            "query_count": 4
          }
        },
        "status": "PASS_LOCAL_EXACT_ARTIFACT"
      }
    ],
    "scientific_scope": "docs/mode5/M5_12_SCIENTIFIC_SCOPE.md",
    "source_regression": {
      "bytes": 187257,
      "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/regression-reconciliation.json",
      "sha256": "27b70430d383720aa4c85044d29a3fba698991671dbe8b95068faaf7e33f1866"
    }
  },
  "numeric_results": [
    {
      "name": "frozen_testcase_records",
      "unit": "retained_invocations_not_independent_N",
      "value": 8468
    },
    {
      "name": "initial_failures_or_errors",
      "unit": "retained_invocations_with_current_dispositions",
      "value": 94
    },
    {
      "name": "retained_skips",
      "unit": "not_passes",
      "value": 43
    },
    {
      "name": "new_long_alpha_economic_optimizers",
      "unit": "studies",
      "value": 0
    }
  ]
}
```

## Economic Interpretation

```json
{
  "economic_interpretation": {
    "alternative_explanations": [
      "Lower IS, inactivity, exposure and search-path differences remain separately explained in the research scope ledger."
    ],
    "inconclusive": [
      "Existing registered inconclusive results remain unchanged."
    ],
    "not_supported": [
      "New independent economic promotion from packaging tests.",
      "Automatic best sampler/selector/donor routing."
    ],
    "supported": [
      "Existing approved research observations retain their source/scope."
    ]
  }
}
```

## Proof Capability

```json
{
  "proof_capability": {
    "coverage": "One exact local core wheel/sdist/native pair; bounded existing software contracts",
    "null_controls": [
      "Stale capability/history/source drift",
      "Future-data/access mutation",
      "Snapshot header mutation",
      "Missing/failed/skipped evidence cannot create PASS"
    ],
    "positive_controls": [
      "Actual installed44/149/19 plus8families/private5/report4 per kind",
      "Native accepted-position expected-value paths",
      "Real absent-Optuna control"
    ],
    "vacuous_checks": [
      "43 optional/inapplicable skips stay skips.",
      "No formal HMA winner is invented.",
      "Four representative renders are not twelve legacy report regenerations."
    ]
  }
}
```

## Potential And Limitations

```json
{
  "blocking_issues": [
    {
      "kind": "OWNER_OPERATIONAL_DISPOSITION",
      "no_runtime_correctness_waiver": true,
      "status": "PENDING"
    }
  ],
  "potential_assessment": {
    "bottlenecks": [
      "Remote Ubuntu22.04/24.04 x CPython3.11..3.13 NOT_RUN and needs owner approval.",
      "Publication and public consumer proof NOT_RUN; native0.4.3/core1.1.2 are local candidate artifacts here.",
      "Owner final local handoff/release review remains pending; no default methodology/model promotion.",
      "Existing seven-alpha economic scope and negative/inconclusive observations are retained; no new independent OOS.",
      "Gross-cross/netting and conservative OHLC liquidation only; unsupported isolated/hedge inventory is explicit."
    ],
    "evidence": [
      "Exact local artifact and current software gates are recorded."
    ],
    "next_falsifiable_actions": [
      "Owner reviews local disposition, then may authorize remote six-row qualification.",
      "Only after approved publication run public consumer proof."
    ]
  }
}
```

## Performance

```json
{
  "performance": {
    "actual_installed_owners": {
      "bytes": 65648,
      "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/v6-cost-origin-proof.json",
      "sha256": "3523c633181bcc0458c270a679487727a285933a5cf88a11c3d44b5e1e17295c"
    },
    "cold_reporting": {
      "evidence": {
        "bytes": 1634,
        "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/cold-report-cost/benchmark.json",
        "sha256": "b067470ab30fc3bf00a1c69cd84a3185d34a44413c3e1668576b835f5495736e"
      },
      "scope": "Retained seven-repeat finance-free checkout report sample before final snapshot repair; not remeasured on V6 or a matched speedup"
    },
    "earlier_v5_cost": "Qualified checkout-source workload, not installed-artifact timing",
    "initial_pair_seconds": {
      "native": 0.11330831097438931,
      "reference": 1.4127927061636
    },
    "p50_p95_inference": false,
    "prior_reporting_regressions_not_erased": "docs/metrics/MET03_PERFORMANCE_REPORT.md",
    "process_rss_pss_samples_mb": [
      {
        "pss_mb": 223.162109375,
        "rss_mb": 230.015625
      }
    ],
    "raw": {
      "bytes": 20610,
      "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/m5t111-v6-phase77-2-smoke.json",
      "sha256": "07bb7a96920b0a14a553902c1a03001fd8eec5cdaad736667948384af7bc92bc"
    },
    "reference_seconds": 0.664071346167475,
    "rust_seconds": 0.11289453995414078,
    "status": "BOUNDED_MATCHED_SINGLE_OBSERVATION_NOT_HEADLINE"
  }
}
```

## Review And Reproduction

```json
{
  "reproduction": {
    "commands": [
      ".venv/bin/python -B -m tools.m5_12_traceability",
      ".venv/bin/python -B -m tools.m5_12_closeout_report --input <canonical-json> --expected-sha256 <seal> --output <new-md>"
    ],
    "receipts": [
      {
        "bytes": 4327,
        "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-pair-03/pair-verified.json",
        "sha256": "7a31c9a62d3d3053e4e12ef9327be69f7ab27689927fd1490a7896a437550378"
      },
      {
        "bytes": 4341,
        "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/installed-reproduction-sdist-03/sdist-verified.json",
        "sha256": "b93154d3ec6e1ca1bfd81e21b1ac6cf9bf10e1018a3aeb18e3494a6f40869066"
      }
    ],
    "scientific_reruns": "NOT_PERFORMED"
  },
  "review": {
    "limitations": [
      "Remote Ubuntu22.04/24.04 x CPython3.11..3.13 NOT_RUN and needs owner approval.",
      "Publication and public consumer proof NOT_RUN; native0.4.3/core1.1.2 are local candidate artifacts here.",
      "Owner final local handoff/release review remains pending; no default methodology/model promotion.",
      "Existing seven-alpha economic scope and negative/inconclusive observations are retained; no new independent OOS.",
      "Gross-cross/netting and conservative OHLC liquidation only; unsupported isolated/hedge inventory is explicit."
    ],
    "local_technical_status": "RECORDED",
    "operational_dispositions": [
      {
        "event": "Original scratch forecast underestimated metadata-fixture growth",
        "evidence": {
          "bytes": 1150,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/cleanup-snapshot-admission.json",
          "sha256": "42b6e83e98e40b41da37ed3507702e08ecc0e1b815abfd2a0c2b8f5ffe6e575c"
        },
        "lowest_recorded_available_bytes": 5304512512,
        "original_gate": "NOT_PASS",
        "recovery": "Admission blocked further work; exact fixture cleanup and per-shard cleanup restored reserve",
        "required_reserve_bytes": 5368709120
      },
      {
        "event": "Owned harness edited during cleanup hash snapshot",
        "original_gate": "FAIL_RETAINED",
        "recovery": {
          "bytes": 1272,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/cleanup-final40-reconciliation.json",
          "sha256": "c9676e01e89660098c559300b809cc74e2e9099165795ea0151264c60ee11d5d"
        }
      },
      {
        "event": "Early cleanup lacked proven host PID namespace",
        "limitation": "Its host_proc_review field does not prove global host inactivity; do not reissue that claim",
        "original_receipt": {
          "bytes": 14787,
          "path": "upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/cleanup-parity-admission.json",
          "sha256": "34f8d347e58c4860e3e897ec34bcbc3d6328326007b66f47abdc00de0a0832b9"
        },
        "recovery": "Subsequent cleanup requires init/systemd host view and verifies host processes, maps and file hashes"
      }
    ],
    "operational_owner_review": "PENDING_EXPLICIT_DISPOSITION",
    "owner_final_review": "PENDING",
    "publication": "NOT_AUTHORIZED",
    "remote": "NOT_RUN"
  }
}
```

## Additional Recorded Evidence

```json
{
  "completion_status": "LOCAL_TECHNICAL_GATES_RECORDED_OPERATIONAL_REVIEW_PENDING",
  "handoff_commit_marker": "docs/mode5/evidence/mode5_upgrade_handoff.json",
  "scientific_scope_disposition": "OWNER_ACCEPTED_REGISTERED_RESEARCH_SCOPE_WITH_LIMITATIONS_NO_NEW_ECONOMIC_CLAIM"
}
```
