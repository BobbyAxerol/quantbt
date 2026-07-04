# Security Policy

QuantBT is a backtesting and research package. Security issues can still matter,
especially around data loading, file export, notebooks, optional dependencies,
and external engine adapters.

## Reporting a Vulnerability

Please do not open a public issue for a suspected security vulnerability.

Report it privately through GitHub Security Advisories when available, or
contact the maintainer through GitHub with:

- affected version or commit;
- reproduction steps;
- expected impact;
- suggested mitigation, if known.

## Scope

Security reports may include:

- arbitrary file writes or path traversal;
- unsafe deserialization;
- dependency-related vulnerabilities;
- credential leakage in examples, configs, logs, or notebooks;
- unsafe behavior in adapters or data loaders.

Backtest result differences, financial losses, strategy performance, and market
risk are not security vulnerabilities. Please report those as regular bugs with
a reproducible example.
