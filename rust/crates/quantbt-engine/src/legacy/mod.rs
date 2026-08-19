//! API 0.4 reactive compatibility primitives.
//!
//! They remain pure Rust and are re-exported only for the legacy PyO3 facade.
//! New full-contract execution uses [`crate::session::FullSession`].

pub mod accounting;
pub mod matching;
pub mod session;
pub mod types;

pub use session::{PreparedMarketData, ReactiveSession};
