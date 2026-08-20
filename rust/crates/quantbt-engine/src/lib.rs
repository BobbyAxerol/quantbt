//! Pure Rust execution core for QuantBT native event execution.
//!
//! The API 0.4 PyO3 extension is deliberately an outer adapter. This crate
//! owns market/account state, lifecycle storage and result sinks without any
//! dependency on Python or NumPy. Typed command translation belongs to the
//! lower `quantbt-domain` boundary; the P0-compatible static reader remains
//! available while its complete ABI 0.5 execution migration is certified.

pub mod account;
pub mod legacy;
pub mod market;
pub mod orders;
pub mod output;
pub mod session;

pub mod generated_contracts {
    pub use quantbt_domain::generated_contracts::*;
}

pub use output::{
    NATIVE_EXECUTION_OUTPUT_VERSION_V1, NativeAuditOutputV1, NativeCompactOutputV1,
    NativeEventOutputV1, NativeExecutionOutputV1, NativeFillOutputV1, NativePathOutputV1,
    NativeScoreOutputV1, OutputRequirementsV1, StaticOutputProfile, StaticTapeOutput,
};
// API 0.4 binding imports these public compatibility types while the internal
// implementation evolves behind ABI 0.5 structures. Keeping this re-export at
// the engine boundary avoids any execution logic in the PyO3 crate.
pub use session::*;
