//! Typed, Python-independent domain contract for QuantBT native engines.
//!
//! This crate intentionally contains no PyO3, NumPy, pandas, reporting, or
//! Python error concepts. It provides the pure-Rust translation path from the
//! public API 0.4 command arrays into the typed ABI 0.5 representation. The
//! P0-compatible static reader remains on the established API 0.4 wire tape
//! until its complete SoA migration is certified in a later execution phase.

pub mod commands;
pub mod enums;
pub mod errors;
pub mod generated_contracts;
pub mod generated_product_contracts;
pub mod ids;
pub mod numeric;
pub mod trace_v2;

pub use commands::{CommandTapeV5, LegacyCommandTapeV4, OrderCommandV5};
pub use enums::{ActivationPolicy, CommandAction, OrderStatus, OrderType, Side, TimeInForce};
pub use errors::DomainError;
pub use ids::{
    AccountId, BarIndex, ExternalOrderId, OrderHandle, PackageId, SymbolId, TimestampNs,
};
pub use trace_v2::{
    CanonicalEventKindV2, CanonicalTraceRowV2, TerminalFingerprintV2, TraceHashV2,
    TraceToleranceV2, canonical_trace_hash_v2,
};
