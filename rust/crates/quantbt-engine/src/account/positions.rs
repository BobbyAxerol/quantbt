use quantbt_domain::enums::Side;
use quantbt_domain::ids::SymbolId;

/// Pure, deterministic result of changing a linear position. It gives the
/// execution layer a preview before margin reservation is committed.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct PositionDelta {
    pub new_qty: f64,
    pub new_avg_entry: f64,
    pub realized_pnl: f64,
    pub closed_qty: f64,
    pub opened_qty: f64,
    pub notional_delta: f64,
}

#[must_use]
pub fn preview_position_delta(
    old_qty: f64,
    old_avg_entry: f64,
    side: Side,
    fill_qty: f64,
    fill_price: f64,
    contract_size: f64,
) -> PositionDelta {
    let signed_fill = fill_qty * side as i8 as f64;
    let new_qty = old_qty + signed_fill;
    let same_direction = old_qty == 0.0 || old_qty.signum() == signed_fill.signum();
    if same_direction {
        let new_avg_entry = if new_qty == 0.0 {
            0.0
        } else if old_qty == 0.0 {
            fill_price
        } else {
            ((old_qty.abs() * old_avg_entry) + (fill_qty * fill_price)) / new_qty.abs()
        };
        return PositionDelta {
            new_qty,
            new_avg_entry,
            opened_qty: fill_qty,
            notional_delta: signed_fill * fill_price * contract_size,
            ..PositionDelta::default()
        };
    }

    let closed_qty = old_qty.abs().min(fill_qty);
    let realized_pnl = closed_qty * (fill_price - old_avg_entry) * old_qty.signum() * contract_size;
    let opened_qty = (fill_qty - closed_qty).max(0.0);
    let new_avg_entry = if new_qty == 0.0 {
        0.0
    } else if opened_qty > 0.0 {
        fill_price
    } else {
        old_avg_entry
    };
    PositionDelta {
        new_qty,
        new_avg_entry,
        realized_pnl,
        closed_qty,
        opened_qty,
        notional_delta: signed_fill * fill_price * contract_size,
    }
}

/// Structure-of-arrays position state plus an active-symbol list. Sparse
/// accounts therefore mark only symbols that can affect equity/margin.
#[derive(Clone, Debug)]
pub struct PositionBook {
    pub qty: Vec<f64>,
    pub avg_entry: Vec<f64>,
    pub mark: Vec<f64>,
    pub realized: Vec<f64>,
    pub unrealized: Vec<f64>,
    pub notional: Vec<f64>,
    pub initial_margin: Vec<f64>,
    pub maintenance_margin: Vec<f64>,
    active_symbols: Vec<SymbolId>,
    active_position: Vec<Option<usize>>,
}

impl PositionBook {
    #[must_use]
    pub fn new(n_symbols: usize) -> Self {
        Self {
            qty: vec![0.0; n_symbols],
            avg_entry: vec![0.0; n_symbols],
            mark: vec![0.0; n_symbols],
            realized: vec![0.0; n_symbols],
            unrealized: vec![0.0; n_symbols],
            notional: vec![0.0; n_symbols],
            initial_margin: vec![0.0; n_symbols],
            maintenance_margin: vec![0.0; n_symbols],
            active_symbols: Vec::new(),
            active_position: vec![None; n_symbols],
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn apply_fill(
        &mut self,
        symbol: SymbolId,
        side: Side,
        qty: f64,
        price: f64,
        contract_size: f64,
    ) -> PositionDelta {
        let index = symbol.0 as usize;
        let delta = preview_position_delta(
            self.qty[index],
            self.avg_entry[index],
            side,
            qty,
            price,
            contract_size,
        );
        self.qty[index] = normalize_zero(delta.new_qty);
        self.avg_entry[index] = delta.new_avg_entry;
        self.realized[index] += delta.realized_pnl;
        self.update_active(symbol);
        delta
    }

    pub fn mark_symbol(
        &mut self,
        symbol: SymbolId,
        price: f64,
        contract_size: f64,
        leverage: f64,
        maintenance_ratio: f64,
    ) -> f64 {
        let index = symbol.0 as usize;
        let previous_mark = self.mark[index];
        let qty = self.qty[index];
        let mtm = if previous_mark == 0.0 {
            0.0
        } else {
            qty * (price - previous_mark) * contract_size
        };
        self.mark[index] = price;
        self.unrealized[index] = qty * (price - self.avg_entry[index]) * contract_size;
        let notional = qty.abs() * price * contract_size;
        self.notional[index] = notional;
        self.initial_margin[index] = notional / leverage;
        self.maintenance_margin[index] = notional * maintenance_ratio;
        mtm
    }

    #[must_use]
    pub fn active_symbols(&self) -> &[SymbolId] {
        &self.active_symbols
    }

    pub fn reset(&mut self) {
        for values in [
            &mut self.qty,
            &mut self.avg_entry,
            &mut self.mark,
            &mut self.realized,
            &mut self.unrealized,
            &mut self.notional,
            &mut self.initial_margin,
            &mut self.maintenance_margin,
        ] {
            values.fill(0.0);
        }
        self.active_symbols.clear();
        self.active_position.fill(None);
    }

    fn update_active(&mut self, symbol: SymbolId) {
        let index = symbol.0 as usize;
        if self.qty[index] == 0.0 {
            if let Some(position) = self.active_position[index].take() {
                self.active_symbols.swap_remove(position);
                if position < self.active_symbols.len() {
                    let moved = self.active_symbols[position];
                    self.active_position[moved.0 as usize] = Some(position);
                }
            }
        } else if self.active_position[index].is_none() {
            self.active_position[index] = Some(self.active_symbols.len());
            self.active_symbols.push(symbol);
        }
    }
}

#[derive(Clone, Debug)]
pub struct AccountState {
    pub initial_capital: f64,
    pub equity: f64,
    pub fees: f64,
    pub funding: f64,
    pub positions: PositionBook,
}

impl AccountState {
    #[must_use]
    pub fn new(initial_capital: f64, n_symbols: usize) -> Self {
        Self {
            initial_capital,
            equity: initial_capital,
            fees: 0.0,
            funding: 0.0,
            positions: PositionBook::new(n_symbols),
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn apply_fill(
        &mut self,
        symbol: SymbolId,
        side: Side,
        qty: f64,
        fill_price: f64,
        mark_price: f64,
        contract_size: f64,
        fee: f64,
    ) -> PositionDelta {
        let signed_qty = qty * side as i8 as f64;
        self.equity += signed_qty * (mark_price - fill_price) * contract_size - fee;
        self.fees += fee;
        self.positions
            .apply_fill(symbol, side, qty, fill_price, contract_size)
    }

    pub fn apply_funding(&mut self, amount: f64) {
        self.equity -= amount;
        self.funding += amount;
    }

    pub fn reset(&mut self) {
        self.equity = self.initial_capital;
        self.fees = 0.0;
        self.funding = 0.0;
        self.positions.reset();
    }
}

#[inline]
fn normalize_zero(value: f64) -> f64 {
    if value.abs() <= f64::EPSILON {
        0.0
    } else {
        value
    }
}

#[cfg(test)]
mod tests {
    use super::{AccountState, preview_position_delta};
    use quantbt_domain::enums::Side;
    use quantbt_domain::ids::SymbolId;

    #[test]
    fn position_preview_handles_open_reduce_close_and_reverse() {
        let open = preview_position_delta(0.0, 0.0, Side::Buy, 2.0, 100.0, 1.0);
        assert_eq!(open.new_qty, 2.0);
        assert_eq!(open.new_avg_entry, 100.0);
        let reduce = preview_position_delta(2.0, 100.0, Side::Sell, 1.0, 110.0, 1.0);
        assert_eq!(reduce.new_qty, 1.0);
        assert_eq!(reduce.realized_pnl, 10.0);
        let reverse = preview_position_delta(1.0, 100.0, Side::Sell, 3.0, 90.0, 1.0);
        assert_eq!(reverse.new_qty, -2.0);
        assert_eq!(reverse.new_avg_entry, 90.0);
        assert_eq!(reverse.realized_pnl, -10.0);
    }

    #[test]
    fn active_position_index_tracks_zero_crossing() {
        let mut account = AccountState::new(1_000.0, 2);
        account.apply_fill(SymbolId(1), Side::Buy, 1.0, 100.0, 100.0, 1.0, 0.0);
        assert_eq!(account.positions.active_symbols(), &[SymbolId(1)]);
        account.apply_fill(SymbolId(1), Side::Sell, 1.0, 100.0, 100.0, 1.0, 0.0);
        assert!(account.positions.active_symbols().is_empty());
    }
}
