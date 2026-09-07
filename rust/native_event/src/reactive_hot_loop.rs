//! Allocation-stable numeric state used by reactive R2/R3 runners.
//!
//! A wake decision compares the current canonical account/market state with
//! the immediately preceding bar.  Keeping those two observations in native
//! reusable buffers avoids allocating two symbol-sized vectors for every bar
//! while preserving the exact chronological wake contract.

use quantbt_engine::{FullSession, FullStepResult};

#[derive(Clone, Debug)]
pub(crate) struct ReusableWakeObservationV1 {
    pub(crate) closes: Vec<f64>,
    pub(crate) positions: Vec<f64>,
    pub(crate) equity: f64,
    pub(crate) initial_margin: f64,
    pub(crate) maintenance_margin: f64,
    pub(crate) liquidated: bool,
}

impl ReusableWakeObservationV1 {
    pub(crate) fn with_symbols(symbol_count: usize) -> Self {
        Self {
            closes: vec![0.0; symbol_count],
            positions: vec![0.0; symbol_count],
            equity: 0.0,
            initial_margin: 0.0,
            maintenance_margin: 0.0,
            liquidated: false,
        }
    }

    /// Refresh in place from the single authoritative Rust account/session.
    ///
    /// The returned error is deliberately a plain native error because this
    /// function may execute inside a detached GIL-free gap. Python-facing
    /// callers adapt it only at the outer callback boundary.
    pub(crate) fn refresh(
        &mut self,
        session: &FullSession,
        bar: usize,
        step: &FullStepResult,
    ) -> Result<(), String> {
        if self.closes.len() != session.market.n_symbols
            || self.positions.len() != session.market.n_symbols
        {
            return Err("reactive wake observation symbol shape changed during a run".to_owned());
        }
        for symbol in 0..session.market.n_symbols {
            self.closes[symbol] = session.close_price_at(bar, symbol)?;
        }
        self.positions.copy_from_slice(&session.positions);
        self.equity = step.equity;
        self.initial_margin = step.initial_margin;
        self.maintenance_margin = step.maintenance_margin;
        self.liquidated = step.liquidated;
        Ok(())
    }
}
