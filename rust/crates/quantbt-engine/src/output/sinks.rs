use quantbt_domain::ids::OrderHandle;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OutputMode {
    Score,
    Compact,
    Audit,
}

/// Flat typed output columns. This is the engine representation; nested rows
/// are only a compatibility adaptation at the outer Python boundary.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct FillColumns {
    pub bar: Vec<u32>,
    pub order_handle: Vec<u64>,
    pub external_order_id: Vec<i64>,
    pub symbol: Vec<u32>,
    pub side: Vec<i8>,
    pub qty: Vec<f64>,
    pub price: Vec<f64>,
    pub fee: Vec<f64>,
    pub flags: Vec<u16>,
}

impl FillColumns {
    #[allow(clippy::too_many_arguments)]
    pub fn push(
        &mut self,
        bar: u32,
        handle: OrderHandle,
        external_order_id: i64,
        symbol: u32,
        side: i8,
        qty: f64,
        price: f64,
        fee: f64,
        flags: u16,
    ) {
        self.bar.push(bar);
        self.order_handle.push(handle.pack());
        self.external_order_id.push(external_order_id);
        self.symbol.push(symbol);
        self.side.push(side);
        self.qty.push(qty);
        self.price.push(price);
        self.fee.push(fee);
        self.flags.push(flags);
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.bar.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.bar.is_empty()
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct MetricSummary {
    pub initial_equity: f64,
    pub final_equity: f64,
    pub max_drawdown: f64,
    pub total_fee: f64,
    pub total_funding: f64,
    pub turnover: f64,
    pub fill_count: u64,
    pub event_count: u64,
    pub rejected_count: u64,
    pub canceled_count: u64,
    peak_equity: f64,
}

impl MetricSummary {
    #[must_use]
    pub fn new(initial_equity: f64) -> Self {
        Self {
            initial_equity,
            final_equity: initial_equity,
            peak_equity: initial_equity,
            ..Self::default()
        }
    }

    pub fn on_bar(&mut self, equity: f64) {
        self.final_equity = equity;
        self.peak_equity = self.peak_equity.max(equity);
        if self.peak_equity > 0.0 {
            self.max_drawdown = self
                .max_drawdown
                .max((self.peak_equity - equity) / self.peak_equity);
        }
    }
}

#[derive(Clone, Debug)]
pub struct ScoreSink {
    pub metrics: MetricSummary,
}

impl ScoreSink {
    #[must_use]
    pub fn new(initial_equity: f64) -> Self {
        Self {
            metrics: MetricSummary::new(initial_equity),
        }
    }

    pub fn on_fill(&mut self, fee: f64, turnover: f64) {
        self.metrics.fill_count += 1;
        self.metrics.total_fee += fee;
        self.metrics.turnover += turnover;
    }

    pub fn on_event(&mut self) {
        self.metrics.event_count += 1;
    }
}

#[derive(Clone, Debug)]
pub struct CompactSink {
    pub metrics: MetricSummary,
    pub final_positions: Vec<f64>,
}

impl CompactSink {
    #[must_use]
    pub fn new(initial_equity: f64, n_symbols: usize) -> Self {
        Self {
            metrics: MetricSummary::new(initial_equity),
            final_positions: vec![0.0; n_symbols],
        }
    }
}

#[derive(Clone, Debug)]
pub struct AuditSink {
    pub metrics: MetricSummary,
    pub equity: Vec<f64>,
    pub fills: FillColumns,
    pub max_rows: usize,
}

impl AuditSink {
    #[must_use]
    pub fn with_limit(initial_equity: f64, max_rows: usize) -> Self {
        Self {
            metrics: MetricSummary::new(initial_equity),
            equity: Vec::new(),
            fills: FillColumns::default(),
            max_rows,
        }
    }

    pub fn on_bar(&mut self, equity: f64) {
        self.metrics.on_bar(equity);
        self.equity.push(equity);
    }

    pub fn can_append_detail(&self) -> bool {
        self.fills.len() < self.max_rows
    }
}

#[cfg(test)]
mod tests {
    use super::{AuditSink, FillColumns, MetricSummary, ScoreSink};
    use quantbt_domain::ids::OrderHandle;

    #[test]
    fn score_sink_never_allocates_fill_columns() {
        let mut score = ScoreSink::new(100.0);
        score.on_fill(1.0, 10.0);
        score.metrics.on_bar(110.0);
        assert_eq!(score.metrics.fill_count, 1);
        assert_eq!(score.metrics.final_equity, 110.0);
    }

    #[test]
    fn audit_fill_columns_keep_integer_ids_typed() {
        let mut columns = FillColumns::default();
        columns.push(
            1,
            OrderHandle {
                slot: 3,
                generation: 2,
            },
            7,
            0,
            1,
            1.0,
            100.0,
            0.1,
            0,
        );
        assert_eq!(columns.order_handle[0], (2_u64 << 32) | 3);
        let audit = AuditSink::with_limit(100.0, 1);
        assert!(audit.can_append_detail());
        let _ = MetricSummary::new(100.0);
    }
}
