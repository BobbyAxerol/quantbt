//! Streaming metric reducer for reactive scalar-score sessions.
//!
//! The public reactive result keeps its established path/audit surface.  A
//! prepared optimization score, however, must not retain a full account path
//! merely to calculate standard metrics.  This module mirrors the existing
//! `NativeEventScoreRequirements::scalar_score_contract` reducer semantics
//! with fixed-size state plus one position-sized vector.

const NS_PER_DAY: i64 = 86_400_000_000_000;

#[derive(Clone, Copy, Debug, Default)]
struct OnlineMoments {
    count: u64,
    mean: f64,
    m2: f64,
}

impl OnlineMoments {
    #[inline]
    fn push(&mut self, value: f64) {
        self.count = self.count.saturating_add(1);
        let delta = value - self.mean;
        self.mean += delta / self.count as f64;
        self.m2 += delta * (value - self.mean);
    }

    #[inline]
    fn std_ddof_one(self) -> f64 {
        if self.count < 2 || self.m2 <= 0.0 {
            0.0
        } else {
            (self.m2 / (self.count - 1) as f64).sqrt()
        }
    }
}

/// Flat scalar payload shared with the PyO3 cold-path adapter.
///
/// Values intentionally retain the established Python score conventions,
/// including `inf` for no-loss Omega/profit-factor and positive no-downside
/// Sortino.  This is a score contract, not a presentation/report type.
#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct ReactiveScoreSnapshotV1 {
    pub initial_capital: f64,
    pub final_equity: f64,
    pub total_return_pct: f64,
    pub cagr_pct: f64,
    pub sharpe: f64,
    pub sortino: f64,
    pub calmar: f64,
    pub omega: f64,
    pub max_drawdown_pct: f64,
    pub avg_drawdown_pct: f64,
    pub max_dd_duration_days: i64,
    pub avg_dd_duration_days: i64,
    pub profit_factor: f64,
    pub long_hitrate_pct: f64,
    pub short_hitrate_pct: f64,
    pub avg_win_pct: f64,
    pub avg_loss_pct: f64,
    pub expectancy_pct: f64,
    pub num_trades: i64,
    pub max_initial_margin: f64,
    pub max_maintenance_margin: f64,
}

/// One-pass scalar statistics for the historical native-event score contract.
///
/// It owns no market arrays, order rows, pandas values, or O(bars x symbols)
/// accounting path.  `prev_positions` and the hit-rate counters are O(symbols)
/// because the score contract explicitly exposes per-symbol activity metrics.
#[derive(Debug)]
pub(crate) struct ReactiveOnlineScoreV1 {
    initial_capital: f64,
    trading_days: f64,
    bar_annualization: f64,
    tape_start_timestamp_ns: i64,
    tape_end_timestamp_ns: i64,
    first_equity: Option<f64>,
    previous_equity: Option<f64>,
    last_equity: f64,
    peak: f64,
    max_drawdown: f64,
    drawdown_sum: f64,
    drawdown_count: u64,
    bar: OnlineMoments,
    bar_downside_sq: f64,
    bar_downside_count: u64,
    bar_gain: f64,
    bar_loss: f64,
    bar_win_sum: f64,
    bar_win_count: u64,
    bar_loss_sum: f64,
    bar_loss_count: u64,
    daily_day: Option<i64>,
    daily_close: Option<f64>,
    last_daily_close: Option<f64>,
    daily_points: u64,
    daily: OnlineMoments,
    daily_downside_sq: f64,
    daily_downside_count: u64,
    daily_gain: f64,
    daily_loss: f64,
    daily_win_sum: f64,
    daily_win_count: u64,
    daily_loss_sum: f64,
    daily_loss_count: u64,
    daily_peak: Option<f64>,
    daily_dd_run: i64,
    daily_dd_max: i64,
    daily_dd_sum: i64,
    daily_dd_count: i64,
    previous_positions: Vec<f64>,
    trade_count: i64,
    long_total: Vec<i64>,
    short_total: Vec<i64>,
    long_wins: Vec<i64>,
    short_wins: Vec<i64>,
    max_initial_margin: f64,
    max_maintenance_margin: f64,
}

impl ReactiveOnlineScoreV1 {
    pub(crate) fn new(
        initial_capital: f64,
        n_symbols: usize,
        trading_days: i64,
        bar_annualization: f64,
        tape_start_timestamp_ns: i64,
        tape_end_timestamp_ns: i64,
    ) -> Result<Self, String> {
        if !initial_capital.is_finite() || initial_capital <= 0.0 {
            return Err("reactive scalar score needs positive finite initial capital".to_owned());
        }
        if trading_days <= 0 || !bar_annualization.is_finite() || bar_annualization <= 0.0 {
            return Err("reactive scalar score has invalid annualization".to_owned());
        }
        if tape_end_timestamp_ns < tape_start_timestamp_ns {
            return Err("reactive scalar score tape timestamps must be monotonic".to_owned());
        }
        Ok(Self {
            initial_capital,
            trading_days: trading_days as f64,
            bar_annualization,
            tape_start_timestamp_ns,
            tape_end_timestamp_ns,
            first_equity: None,
            previous_equity: None,
            last_equity: initial_capital,
            peak: f64::NEG_INFINITY,
            max_drawdown: 0.0,
            drawdown_sum: 0.0,
            drawdown_count: 0,
            bar: OnlineMoments::default(),
            bar_downside_sq: 0.0,
            bar_downside_count: 0,
            bar_gain: 0.0,
            bar_loss: 0.0,
            bar_win_sum: 0.0,
            bar_win_count: 0,
            bar_loss_sum: 0.0,
            bar_loss_count: 0,
            daily_day: None,
            daily_close: None,
            last_daily_close: None,
            daily_points: 0,
            daily: OnlineMoments::default(),
            daily_downside_sq: 0.0,
            daily_downside_count: 0,
            daily_gain: 0.0,
            daily_loss: 0.0,
            daily_win_sum: 0.0,
            daily_win_count: 0,
            daily_loss_sum: 0.0,
            daily_loss_count: 0,
            daily_peak: None,
            daily_dd_run: 0,
            daily_dd_max: 0,
            daily_dd_sum: 0,
            daily_dd_count: 0,
            previous_positions: vec![0.0; n_symbols],
            // Match `NativeEventScoreRequirements`' historical transition
            // count convention: each symbol contributes its initial state.
            trade_count: n_symbols as i64,
            long_total: vec![0; n_symbols],
            short_total: vec![0; n_symbols],
            long_wins: vec![0; n_symbols],
            short_wins: vec![0; n_symbols],
            max_initial_margin: 0.0,
            max_maintenance_margin: 0.0,
        })
    }

    #[inline]
    fn observe_bar_return(&mut self, value: f64) {
        if !value.is_finite() {
            return;
        }
        self.bar.push(value);
        if value > 0.0 {
            self.bar_gain += value;
            self.bar_win_sum += value;
            self.bar_win_count = self.bar_win_count.saturating_add(1);
        } else if value < 0.0 {
            self.bar_loss += -value;
            self.bar_loss_sum += value;
            self.bar_loss_count = self.bar_loss_count.saturating_add(1);
            self.bar_downside_sq += value * value;
            self.bar_downside_count = self.bar_downside_count.saturating_add(1);
        }
    }

    #[inline]
    fn observe_daily_return(&mut self, value: f64) {
        if !value.is_finite() {
            return;
        }
        self.daily.push(value);
        if value > 0.0 {
            self.daily_gain += value;
            self.daily_win_sum += value;
            self.daily_win_count = self.daily_win_count.saturating_add(1);
        } else if value < 0.0 {
            self.daily_loss += -value;
            self.daily_loss_sum += value;
            self.daily_loss_count = self.daily_loss_count.saturating_add(1);
            self.daily_downside_sq += value * value;
            self.daily_downside_count = self.daily_downside_count.saturating_add(1);
        }
    }

    fn close_day(&mut self) {
        let Some(close) = self.daily_close else {
            return;
        };
        if let Some(previous) = self.last_daily_close {
            let value = if previous != 0.0 {
                (close - previous) / previous
            } else {
                0.0
            };
            self.observe_daily_return(value);
        }
        self.last_daily_close = Some(close);
        self.daily_points = self.daily_points.saturating_add(1);
        let peak = self.daily_peak.map_or(close, |current| current.max(close));
        self.daily_peak = Some(peak);
        if peak != close {
            self.daily_dd_run = self.daily_dd_run.saturating_add(1);
        } else if self.daily_dd_run > 0 {
            self.daily_dd_max = self.daily_dd_max.max(self.daily_dd_run);
            self.daily_dd_sum = self.daily_dd_sum.saturating_add(self.daily_dd_run);
            self.daily_dd_count = self.daily_dd_count.saturating_add(1);
            self.daily_dd_run = 0;
        }
    }

    pub(crate) fn observe(
        &mut self,
        timestamp_ns: i64,
        equity: f64,
        positions: &[f64],
        initial_margin: f64,
        maintenance_margin: f64,
    ) -> Result<(), String> {
        if !equity.is_finite()
            || !initial_margin.is_finite()
            || !maintenance_margin.is_finite()
            || positions.len() != self.previous_positions.len()
            || positions.iter().any(|value| !value.is_finite())
        {
            return Err("reactive scalar score observed invalid accounting state".to_owned());
        }
        // The public Python scalar contract annualizes against the submitted
        // tape, including the post-liquidation terminal segment.  Retain the
        // two immutable endpoints supplied at preparation rather than a path.
        let _ = timestamp_ns;
        self.first_equity.get_or_insert(equity);
        let bar_return = self
            .previous_equity
            .filter(|previous| *previous != 0.0)
            .map_or(0.0, |previous| equity / previous - 1.0);
        self.observe_bar_return(bar_return);

        self.peak = self.peak.max(equity);
        let drawdown = if self.peak != 0.0 {
            (self.peak - equity) / self.peak
        } else {
            0.0
        };
        self.max_drawdown = self.max_drawdown.max(drawdown);
        if drawdown > 0.0 {
            self.drawdown_sum += drawdown;
            self.drawdown_count = self.drawdown_count.saturating_add(1);
        }

        for (index, position) in positions.iter().copied().enumerate() {
            if self.bar.count > 1 && position != self.previous_positions[index] {
                self.trade_count = self.trade_count.saturating_add(1);
            }
            if position > 0.0 {
                self.long_total[index] = self.long_total[index].saturating_add(1);
                if bar_return > 0.0 {
                    self.long_wins[index] = self.long_wins[index].saturating_add(1);
                }
            } else if position < 0.0 {
                self.short_total[index] = self.short_total[index].saturating_add(1);
                if bar_return > 0.0 {
                    self.short_wins[index] = self.short_wins[index].saturating_add(1);
                }
            }
            self.previous_positions[index] = position;
        }
        self.previous_equity = Some(equity);
        self.last_equity = equity;
        self.max_initial_margin = self.max_initial_margin.max(initial_margin);
        self.max_maintenance_margin = self.max_maintenance_margin.max(maintenance_margin);

        let day = timestamp_ns.div_euclid(NS_PER_DAY);
        if self.daily_day.is_some_and(|active| active != day) {
            self.close_day();
        }
        self.daily_day = Some(day);
        self.daily_close = Some(equity);
        Ok(())
    }

    pub(crate) fn finish(&mut self) -> ReactiveScoreSnapshotV1 {
        self.close_day();
        if self.daily_dd_run > 0 {
            self.daily_dd_max = self.daily_dd_max.max(self.daily_dd_run);
            self.daily_dd_sum = self.daily_dd_sum.saturating_add(self.daily_dd_run);
            self.daily_dd_count = self.daily_dd_count.saturating_add(1);
            self.daily_dd_run = 0;
        }

        let use_daily = self.daily_points >= 2;
        let (
            moments,
            downside_sq,
            downside_count,
            gain,
            loss,
            win_sum,
            win_count,
            loss_sum,
            loss_count,
            periods,
        ) = if use_daily {
            (
                self.daily,
                self.daily_downside_sq,
                self.daily_downside_count,
                self.daily_gain,
                self.daily_loss,
                self.daily_win_sum,
                self.daily_win_count,
                self.daily_loss_sum,
                self.daily_loss_count,
                self.trading_days,
            )
        } else {
            (
                self.bar,
                self.bar_downside_sq,
                self.bar_downside_count,
                self.bar_gain,
                self.bar_loss,
                self.bar_win_sum,
                self.bar_win_count,
                self.bar_loss_sum,
                self.bar_loss_count,
                self.bar_annualization,
            )
        };
        let std = moments.std_ddof_one();
        let sharpe = if std > 0.0 {
            moments.mean / std * periods.sqrt()
        } else {
            0.0
        };
        let downside = if downside_count > 0 {
            (downside_sq / downside_count as f64).sqrt()
        } else {
            0.0
        };
        let sortino = if downside > 0.0 {
            moments.mean / downside * periods.sqrt()
        } else if moments.mean > 0.0 {
            f64::INFINITY
        } else {
            0.0
        };
        let omega = if loss > 0.0 {
            gain / loss
        } else {
            f64::INFINITY
        };
        let total_return = (self.last_equity - self.initial_capital) / self.initial_capital;
        let elapsed_days =
            (self.tape_end_timestamp_ns - self.tape_start_timestamp_ns) as f64 / NS_PER_DAY as f64;
        let years = elapsed_days / 365.25;
        let cagr = if elapsed_days > 0.0 && elapsed_days < 1.0 {
            total_return
        } else if years <= 0.0 {
            0.0
        } else if self
            .first_equity
            .is_none_or(|first| first <= 0.0 || self.last_equity / first <= 0.0)
        {
            -1.0
        } else {
            let first = self.first_equity.unwrap_or(self.initial_capital);
            ((self.last_equity / first).ln() / years)
                .clamp(-50.0, 50.0)
                .exp_m1()
        };
        let n_symbols = self.previous_positions.len().max(1) as f64;
        let long_hitrate = self
            .long_wins
            .iter()
            .zip(&self.long_total)
            .map(|(wins, total)| {
                if *total > 0 {
                    *wins as f64 / *total as f64 * 100.0
                } else {
                    0.0
                }
            })
            .sum::<f64>()
            / n_symbols;
        let short_hitrate = self
            .short_wins
            .iter()
            .zip(&self.short_total)
            .map(|(wins, total)| {
                if *total > 0 {
                    *wins as f64 / *total as f64 * 100.0
                } else {
                    0.0
                }
            })
            .sum::<f64>()
            / n_symbols;
        let avg_win = if win_count > 0 {
            win_sum / win_count as f64 * 100.0
        } else {
            0.0
        };
        let avg_loss = if loss_count > 0 {
            loss_sum / loss_count as f64 * 100.0
        } else {
            0.0
        };
        let hit_rate = (long_hitrate + short_hitrate) / 200.0;
        let avg_drawdown = if self.drawdown_count > 0 {
            self.drawdown_sum / self.drawdown_count as f64
        } else {
            0.0
        };
        ReactiveScoreSnapshotV1 {
            initial_capital: self.initial_capital,
            final_equity: self.last_equity,
            total_return_pct: total_return * 100.0,
            cagr_pct: cagr * 100.0,
            sharpe,
            sortino,
            calmar: if self.max_drawdown > 0.0 {
                cagr / self.max_drawdown
            } else {
                0.0
            },
            omega,
            max_drawdown_pct: self.max_drawdown * 100.0,
            avg_drawdown_pct: avg_drawdown * 100.0,
            max_dd_duration_days: self.daily_dd_max,
            avg_dd_duration_days: if self.daily_dd_count > 0 {
                self.daily_dd_sum / self.daily_dd_count
            } else {
                0
            },
            profit_factor: omega,
            long_hitrate_pct: long_hitrate,
            short_hitrate_pct: short_hitrate,
            avg_win_pct: avg_win,
            avg_loss_pct: avg_loss,
            expectancy_pct: hit_rate * avg_win + (1.0 - hit_rate) * avg_loss,
            num_trades: self.trade_count,
            max_initial_margin: self.max_initial_margin,
            max_maintenance_margin: self.max_maintenance_margin,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::ReactiveOnlineScoreV1;

    #[test]
    fn scalar_reducer_uses_constant_memory_and_finishes_daily_statistics() {
        let mut reducer =
            ReactiveOnlineScoreV1::new(100.0, 1, 365, 8_766.0, 0, 172_800_000_000_000).unwrap();
        reducer.observe(0, 100.0, &[0.0], 0.0, 0.0).unwrap();
        reducer
            .observe(86_400_000_000_000, 110.0, &[1.0], 5.0, 1.0)
            .unwrap();
        reducer
            .observe(172_800_000_000_000, 99.0, &[0.0], 0.0, 0.0)
            .unwrap();
        let score = reducer.finish();
        assert_eq!(score.initial_capital, 100.0);
        assert_eq!(score.final_equity, 99.0);
        assert_eq!(score.num_trades, 3);
        assert!(score.max_drawdown_pct > 0.0);
        assert!(score.max_initial_margin >= 5.0);
    }
}
