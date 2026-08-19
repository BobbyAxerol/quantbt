//! Validated native strategy IR boundary.
//!
//! Phase 53A deliberately establishes only the versioned, pure-Rust contract.
//! The executable Grid/DCA/bracket instruction set belongs to Phase 53B. This
//! crate must remain independent of PyO3 and Python strategy objects.

use quantbt_domain::errors::DomainError;

pub const STRATEGY_IR_VERSION: u16 = 1;

/// Opaque, immutable bytecode accepted by a later native strategy runtime.
/// Keeping validation at this boundary prevents a Python callback object from
/// leaking into the event kernel.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StrategyIrProgram {
    version: u16,
    bytecode: Box<[u8]>,
}

impl StrategyIrProgram {
    pub fn new(version: u16, bytecode: Vec<u8>) -> Result<Self, DomainError> {
        if version != STRATEGY_IR_VERSION {
            return Err(DomainError::InvalidShape("unsupported strategy IR version"));
        }
        if bytecode.is_empty() {
            return Err(DomainError::InvalidShape(
                "strategy IR bytecode cannot be empty",
            ));
        }
        Ok(Self {
            version,
            bytecode: bytecode.into_boxed_slice(),
        })
    }

    #[must_use]
    pub const fn version(&self) -> u16 {
        self.version
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytecode
    }
}

#[cfg(test)]
mod tests {
    use super::{STRATEGY_IR_VERSION, StrategyIrProgram};

    #[test]
    fn versioned_program_rejects_empty_or_unknown_input() {
        assert!(StrategyIrProgram::new(STRATEGY_IR_VERSION, vec![1]).is_ok());
        assert!(StrategyIrProgram::new(STRATEGY_IR_VERSION + 1, vec![1]).is_err());
        assert!(StrategyIrProgram::new(STRATEGY_IR_VERSION, Vec::new()).is_err());
    }
}
