//! Typed portfolio target contract over the shared Rust event/account core.
//!
//! Target execution, rebalance policies, and attribution are Phase 53B work.
//! This crate exists now so those features cannot become a second PyO3-bound
//! accounting engine.

use quantbt_domain::errors::DomainError;
use quantbt_domain::ids::SymbolId;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PortfolioTarget {
    pub symbol: SymbolId,
    pub target_qty: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PortfolioTargetRow {
    pub bar: u32,
    pub targets: Box<[PortfolioTarget]>,
}

impl PortfolioTargetRow {
    pub fn new(bar: u32, targets: Vec<PortfolioTarget>) -> Result<Self, DomainError> {
        if targets.iter().any(|target| !target.target_qty.is_finite()) {
            return Err(DomainError::InvalidCommand {
                command: bar as usize,
                reason: "portfolio target quantity must be finite",
            });
        }
        Ok(Self {
            bar,
            targets: targets.into_boxed_slice(),
        })
    }
}
