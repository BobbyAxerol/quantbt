//! Frozen API-0.3/R1/R2 compatibility constants.
//!
//! The historical R1/R2 session implementation is deliberately no longer a
//! compiled execution route. The PyO3 compatibility facade translates this
//! ABI into [`crate::session::FullSession`], which is the single Rust owner of
//! market/account/order/lifecycle state. Keeping the integer constants here
//! avoids breaking the legacy public row layout while preventing a second
//! state machine from entering a native build.

pub mod types;
