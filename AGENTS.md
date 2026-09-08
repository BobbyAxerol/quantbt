# QuantBT Workspace Rules

- Work only inside this `quantbt` repository unless the user explicitly expands scope.
- Use `dev` for research and implementation work. Do not make code changes or commits on `main`.
- Keep `main` protected with the configured pre-commit hook.
- Before committing, check `git status` and stage only files changed for the current task.
- After each coherent change is implemented and verified, create a commit immediately.
- Preserve unrelated dirty changes; do not revert or include them without explicit user approval.

## Shared Architecture And Future WFO Methodology

- These rules govern implementation quality, not the choice of mathematical
  methodology. Future objectives, models, validation designs and sampling
  methods remain open research decisions. Extend shared contracts when a new
  method needs new capabilities; do not distort the method to fit today's
  interfaces or require a separate performance retrofit after implementation.
- Before an approved upgrade phase, read its section in `upgrade/implement.md`
  and every linked detailed guide. Record the agreed scope, tests, exit gates,
  evidence and remaining limitations in that plan; do not silently expand it.
- Keep public endpoints stable. New WFO modes, objectives, selectors and ML
  adapters must integrate through existing preparation, planning, evaluation,
  execution, result and audit contracts. Avoid a new endpoint, account engine,
  prepared cache or Python/Rust bridge for each research method.
- Preserve the ownership rules in `docs/architecture/execution-plan.md`,
  `docs/adr/ADR-RP-002-strategy-engine-boundary.md` and
  `docs/adr/ADR-RP-005-wfo-optimizer-schedules.md`. Extend their contracts
  explicitly when needed; do not infer equivalent economics from similar inputs.
- Separate fold/data-access policy, optimizer scheduling, financial execution,
  metric reduction, objective/selection policy and report rendering. A new
  methodology should declare its required metrics/paths and causal permissions,
  not duplicate simulation or derive its own inconsistent account metrics.
- Share typed, versioned requests/results, immutable market ownership and
  capability metadata across supported workloads. Domain-specific kernels may
  remain specialized; a common interface must not erase their timing, sizing,
  lifecycle, margin, funding or fold-account differences. Unsupported contracts
  must produce the documented explicit error or observable compatible fallback.
- Prefer measured Rust batching for QuantBT-owned numeric hot paths. Keep
  Numba or Python where the matched public workload justifies it or where the
  user strategy/model requires it. Language choice alone is not a performance
  gate, and arbitrary Python/ML callbacks must not be advertised as Rust-owned.
- Prepare immutable market/calendar state once per declared lifetime. Minimize
  Python/Rust transfers and per-bar object construction; declare ownership,
  cancellation, reset and release behavior. Do not reuse mutable strategy/model,
  account, order or RNG state across independent candidates or folds.
- ML adapters must declare fit/transform/predict data roles and availability
  cutoffs, including learned preprocessing and feature/label horizons. Keep
  fitting and selection within the selected schedule's permitted data. Any
  warm start or cache requires explicit model/parameter/data/role/cutoff identity
  and tests that future-data changes cannot affect earlier causal decisions.
- Keep performance-only changes separate from methodology changes. Preserve
  existing RNG draws, optimizer observation order, objective values, tie-breaks,
  selected parameters, accounting and traces under their declared contracts.
  New mathematical behavior requires an explicit version/option, independent
  expected-value tests, metadata and migration documentation.
- Add new responsibilities in focused modules with small typed interfaces;
  use cohesive objects where they own state or lifecycle. Avoid growing a
  monolithic WFO/FFI module or imposing an unrelated codebase-wide OOP rewrite.
- Benchmark full public WFO studies and reactive runs as well as isolated
  kernels: same data, candidates/schedule, CPU budget and retained outputs.
  Measure fresh versus prepared runs and RSS separately. Never claim speedups
  by dropping requested audit data, changing the search, or comparing different
  contracts. Gate all affected mode/schedule/domain paths before promotion.
- Make extensions discoverable through the shared capability surface, endpoint
  docs, methodology docs, runnable examples and audit provenance. Record remaining
  bottlenecks honestly; completing a phase does not mean all possible future
  optimization has been exhausted.
