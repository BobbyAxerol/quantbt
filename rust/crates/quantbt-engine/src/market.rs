use quantbt_domain::errors::DomainError;

pub const MARKET_FLAG_FUNDING_DUE: u16 = 1 << 0;
pub const MARKET_FLAG_SESSION_OPEN: u16 = 1 << 1;
pub const MARKET_FLAG_SESSION_CLOSE: u16 = 1 << 2;
pub const MARKET_FLAG_MISSING: u16 = 1 << 3;
pub const MARKET_FLAG_STALE: u16 = 1 << 4;

/// Immutable, bar-major market tape owned by Rust. `bar_slice` keeps the
/// event loop on contiguous memory and avoids Python/NumPy lifetime coupling.
#[derive(Clone)]
pub struct BarMajorMarket {
    pub timestamps_ns: Box<[i64]>,
    pub open: Box<[f64]>,
    pub high: Box<[f64]>,
    pub low: Box<[f64]>,
    pub close: Box<[f64]>,
    pub volume: Box<[f64]>,
    pub funding: Box<[f64]>,
    pub flags: Box<[u16]>,
    pub n_bars: usize,
    pub n_symbols: usize,
}

impl BarMajorMarket {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        timestamps_ns: Vec<i64>,
        open: Vec<f64>,
        high: Vec<f64>,
        low: Vec<f64>,
        close: Vec<f64>,
        volume: Vec<f64>,
        funding: Vec<f64>,
        flags: Vec<u16>,
        n_symbols: usize,
    ) -> Result<Self, DomainError> {
        if n_symbols == 0 || timestamps_ns.is_empty() {
            return Err(DomainError::InvalidShape(
                "market tape must contain bars and symbols",
            ));
        }
        let n_bars = timestamps_ns.len();
        let width = n_bars
            .checked_mul(n_symbols)
            .ok_or(DomainError::InvalidShape("market dimensions overflow"))?;
        if [
            open.len(),
            high.len(),
            low.len(),
            close.len(),
            volume.len(),
            funding.len(),
        ]
        .into_iter()
        .any(|length| length != width)
            || flags.len() != n_bars
        {
            return Err(DomainError::InvalidShape(
                "market arrays have inconsistent shapes",
            ));
        }
        Ok(Self {
            timestamps_ns: timestamps_ns.into_boxed_slice(),
            open: open.into_boxed_slice(),
            high: high.into_boxed_slice(),
            low: low.into_boxed_slice(),
            close: close.into_boxed_slice(),
            volume: volume.into_boxed_slice(),
            funding: funding.into_boxed_slice(),
            flags: flags.into_boxed_slice(),
            n_bars,
            n_symbols,
        })
    }

    #[must_use]
    pub fn bar_slice<'a>(&self, field: &'a [f64], bar: usize) -> &'a [f64] {
        let start = bar * self.n_symbols;
        &field[start..start + self.n_symbols]
    }

    #[must_use]
    pub fn at(&self, field: &[f64], bar: usize, symbol: usize) -> f64 {
        self.bar_slice(field, bar)[symbol]
    }
}

/// Per-symbol execution constraints retained with the prepared market tape.
#[derive(Clone)]
pub struct InstrumentTable {
    pub tick_size: Box<[f64]>,
    pub qty_step: Box<[f64]>,
    pub contract_size: Box<[f64]>,
    pub leverage: Box<[f64]>,
    pub fee_rate: Box<[f64]>,
}

impl InstrumentTable {
    pub fn new(
        tick_size: Vec<f64>,
        qty_step: Vec<f64>,
        contract_size: Vec<f64>,
        leverage: Vec<f64>,
        fee_rate: Vec<f64>,
    ) -> Result<Self, DomainError> {
        let count = contract_size.len();
        if count == 0
            || tick_size.len() != count
            || qty_step.len() != count
            || leverage.len() != count
            || fee_rate.len() != count
            || contract_size
                .iter()
                .any(|value| !value.is_finite() || *value <= 0.0)
            || leverage
                .iter()
                .any(|value| !value.is_finite() || *value <= 0.0)
            || fee_rate
                .iter()
                .any(|value| !value.is_finite() || *value < 0.0)
        {
            return Err(DomainError::InvalidShape("instrument table is invalid"));
        }
        Ok(Self {
            tick_size: tick_size.into_boxed_slice(),
            qty_step: qty_step.into_boxed_slice(),
            contract_size: contract_size.into_boxed_slice(),
            leverage: leverage.into_boxed_slice(),
            fee_rate: fee_rate.into_boxed_slice(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{BarMajorMarket, MARKET_FLAG_FUNDING_DUE};

    #[test]
    fn bar_major_market_returns_contiguous_symbol_slice() {
        let market = BarMajorMarket::new(
            vec![1, 2],
            vec![1.0, 2.0, 3.0, 4.0],
            vec![1.0; 4],
            vec![1.0; 4],
            vec![1.0; 4],
            vec![1.0; 4],
            vec![0.0; 4],
            vec![0, MARKET_FLAG_FUNDING_DUE],
            2,
        )
        .unwrap();
        assert_eq!(market.bar_slice(&market.open, 1), &[3.0, 4.0]);
        assert_eq!(market.flags[1], MARKET_FLAG_FUNDING_DUE);
    }
}
