//! Versioned native standard-metric contract and online reducers.
//!
//! The reducer is intentionally presentation-free: it owns no pandas, Python
//! object, or report formatting. Python remains free to calculate arbitrary
//! research metrics from compact/audit paths, while a native score gets a
//! deterministic scalar snapshot from the same authoritative execution pass.

pub const METRIC_CONTRACT_VERSION_V2: u16 = 2;
const NS_PER_DAY: i64 = 86_400_000_000_000;

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReturnFrequencyV2 {
    PerBar = 0,
    Daily = 1,
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ZeroVariancePolicyV2 {
    /// Return a finite zero for undefined ratio metrics. This is the only V2
    /// policy currently certified; infinity is never silently emitted.
    ReturnZero = 0,
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShortRunMetricPolicyV2 {
    /// A sample shorter than the declared DDOF produces finite zero ratios.
    ReturnZero = 0,
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TradeCountDefinitionV2 {
    /// Count committed fills. Partial fills are distinct committed trades.
    CommittedFills = 0,
}

/// Complete standard-metric policy. Changing any field changes the meaning of
/// the result and must therefore be carried with a native result envelope.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MetricContractV2 {
    pub return_frequency: ReturnFrequencyV2,
    pub annualization_factor: f64,
    pub risk_free_rate: f64,
    pub variance_ddof: u8,
    pub zero_variance_policy: ZeroVariancePolicyV2,
    pub short_run_policy: ShortRunMetricPolicyV2,
    pub trade_count_definition: TradeCountDefinitionV2,
}

impl MetricContractV2 {
    pub fn new(
        return_frequency: ReturnFrequencyV2,
        annualization_factor: f64,
        risk_free_rate: f64,
        variance_ddof: u8,
        zero_variance_policy: ZeroVariancePolicyV2,
        short_run_policy: ShortRunMetricPolicyV2,
        trade_count_definition: TradeCountDefinitionV2,
    ) -> Result<Self, String> {
        if !annualization_factor.is_finite()
            || annualization_factor <= 0.0
            || !risk_free_rate.is_finite()
            || variance_ddof > 1
        {
            return Err("native metric contract has invalid annualization/DDOF".to_owned());
        }
        Ok(Self {
            return_frequency,
            annualization_factor,
            risk_free_rate,
            variance_ddof,
            zero_variance_policy,
            short_run_policy,
            trade_count_definition,
        })
    }

    /// Crypto-friendly daily contract matching QuantBT's public default
    /// annualization. Daily sampling is timestamp-based and needs no pandas.
    pub fn crypto_daily() -> Self {
        Self::new(
            ReturnFrequencyV2::Daily,
            365.0,
            0.0,
            1,
            ZeroVariancePolicyV2::ReturnZero,
            ShortRunMetricPolicyV2::ReturnZero,
            TradeCountDefinitionV2::CommittedFills,
        )
        .expect("static crypto metric contract is valid")
    }
}

impl Default for MetricContractV2 {
    fn default() -> Self {
        Self::crypto_daily()
    }
}

/// Scalar snapshot attached to every profile. Paths and audit rows remain
/// profile-specific SoA payloads; this is the common standard metric authority.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct NativeMetricSnapshotV2 {
    pub metric_contract_version: u16,
    pub final_equity: f64,
    pub total_return: f64,
    pub cagr: f64,
    pub mean_return: f64,
    pub variance: f64,
    pub sharpe: f64,
    pub sortino: f64,
    pub max_drawdown: f64,
    pub calmar: f64,
    pub omega: f64,
    /// Return-series profit factor under the public MetricContractV2 clock.
    ///
    /// This intentionally differs from `omega` only for a no-loss sample:
    /// public QuantBT reports `inf` there, whereas Omega keeps its historic
    /// zero-denominator `0.0` convention.
    pub profit_factor: f64,
    pub average_gross_exposure: f64,
    pub turnover: f64,
    pub total_fee: f64,
    pub total_funding: f64,
    pub fill_count: u64,
    pub event_count: u64,
    pub rejected_count: u64,
    pub canceled_count: u64,
    pub sample_count: u64,
    pub liquidated: bool,
}

/// Terminal accounting counters supplied by the session after the last bar.
/// Grouping them preserves a small reducer API without giving the metric layer
/// any mutable account/lifecycle ownership.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MetricFinishInputV2 {
    pub final_equity: f64,
    pub turnover: f64,
    pub total_fee: f64,
    pub total_funding: f64,
    pub fill_count: i64,
    pub event_count: i64,
    pub rejected_count: i64,
    pub canceled_count: i64,
    pub liquidated: bool,
}

#[derive(Clone, Copy, Debug, Default)]
struct OnlineMomentsV1 {
    count: u64,
    mean: f64,
    m2: f64,
}

impl OnlineMomentsV1 {
    fn push(&mut self, value: f64) {
        self.count += 1;
        let delta = value - self.mean;
        self.mean += delta / self.count as f64;
        let delta_next = value - self.mean;
        self.m2 += delta * delta_next;
    }

    #[must_use]
    fn variance(self, ddof: u8) -> f64 {
        let denominator = self.count.saturating_sub(u64::from(ddof));
        if denominator == 0 {
            0.0
        } else {
            (self.m2 / denominator as f64).max(0.0)
        }
    }
}

/// Online metric reducer. It observes exact bar-close account equity after the
/// native lifecycle/accounting step; it never owns or mutates account state.
#[derive(Clone, Debug)]
pub struct OnlineMetricReducerV2 {
    contract: MetricContractV2,
    initial_equity: f64,
    start_timestamp_ns: Option<i64>,
    end_timestamp_ns: Option<i64>,
    previous_sample_equity: Option<f64>,
    active_day: Option<i64>,
    pending_day_equity: Option<f64>,
    moments: OnlineMomentsV1,
    downside_square_sum: f64,
    upside_sum: f64,
    downside_sum: f64,
    peak_equity: f64,
    max_drawdown: f64,
    gross_exposure_sum: f64,
    exposure_observations: u64,
}

impl OnlineMetricReducerV2 {
    pub fn new(contract: MetricContractV2, initial_equity: f64) -> Result<Self, String> {
        if !initial_equity.is_finite() || initial_equity <= 0.0 {
            return Err("native metric reducer needs positive finite initial equity".to_owned());
        }
        // Construction validates values even when a caller deserialized a
        // literal rather than using `MetricContractV2::new`.
        MetricContractV2::new(
            contract.return_frequency,
            contract.annualization_factor,
            contract.risk_free_rate,
            contract.variance_ddof,
            contract.zero_variance_policy,
            contract.short_run_policy,
            contract.trade_count_definition,
        )?;
        Ok(Self {
            contract,
            initial_equity,
            start_timestamp_ns: None,
            end_timestamp_ns: None,
            previous_sample_equity: None,
            active_day: None,
            pending_day_equity: None,
            moments: OnlineMomentsV1::default(),
            downside_square_sum: 0.0,
            upside_sum: 0.0,
            downside_sum: 0.0,
            peak_equity: initial_equity,
            max_drawdown: 0.0,
            gross_exposure_sum: 0.0,
            exposure_observations: 0,
        })
    }

    pub fn observe(
        &mut self,
        timestamp_ns: i64,
        equity: f64,
        gross_exposure: f64,
    ) -> Result<(), String> {
        if !equity.is_finite()
            || equity < 0.0
            || !gross_exposure.is_finite()
            || gross_exposure < 0.0
        {
            return Err("native metric observation must be finite and non-negative".to_owned());
        }
        if self
            .end_timestamp_ns
            .is_some_and(|last| timestamp_ns < last)
        {
            return Err("native metric timestamps must be monotonic".to_owned());
        }
        self.start_timestamp_ns.get_or_insert(timestamp_ns);
        self.end_timestamp_ns = Some(timestamp_ns);
        self.peak_equity = self.peak_equity.max(equity);
        if self.peak_equity > 0.0 {
            self.max_drawdown = self
                .max_drawdown
                .max((self.peak_equity - equity) / self.peak_equity);
        }
        self.gross_exposure_sum += gross_exposure;
        self.exposure_observations += 1;

        match self.contract.return_frequency {
            ReturnFrequencyV2::PerBar => self.observe_sample(equity),
            ReturnFrequencyV2::Daily => {
                let day = timestamp_ns.div_euclid(NS_PER_DAY);
                match self.active_day {
                    None => {
                        self.active_day = Some(day);
                        self.pending_day_equity = Some(equity);
                    }
                    Some(active) if active == day => self.pending_day_equity = Some(equity),
                    Some(_) => {
                        if let Some(day_equity) = self.pending_day_equity {
                            self.observe_sample(day_equity);
                        }
                        self.active_day = Some(day);
                        self.pending_day_equity = Some(equity);
                    }
                }
            }
        }
        Ok(())
    }

    fn observe_sample(&mut self, equity: f64) {
        let Some(previous) = self.previous_sample_equity.replace(equity) else {
            return;
        };
        if previous <= 0.0 {
            return;
        }
        let period_risk_free = self.contract.risk_free_rate / self.contract.annualization_factor;
        let excess = equity / previous - 1.0 - period_risk_free;
        self.moments.push(excess);
        if excess < 0.0 {
            self.downside_square_sum += excess * excess;
            self.downside_sum += -excess;
        } else if excess > 0.0 {
            self.upside_sum += excess;
        }
    }

    /// Complete a run. Daily data flushes its final pending day exactly once.
    #[must_use]
    pub fn finish(mut self, input: MetricFinishInputV2) -> NativeMetricSnapshotV2 {
        if self.contract.return_frequency == ReturnFrequencyV2::Daily
            && let Some(day_equity) = self.pending_day_equity.take()
        {
            self.observe_sample(day_equity);
        }
        let variance = self.moments.variance(self.contract.variance_ddof);
        let std = variance.sqrt();
        let sharpe = if std > 0.0 {
            self.moments.mean / std * self.contract.annualization_factor.sqrt()
        } else {
            0.0
        };
        let downside_denominator = self.moments.count as f64;
        let downside_deviation = if downside_denominator > 0.0 {
            (self.downside_square_sum / downside_denominator).sqrt()
        } else {
            0.0
        };
        let sortino = if downside_deviation > 0.0 {
            self.moments.mean / downside_deviation * self.contract.annualization_factor.sqrt()
        } else {
            0.0
        };
        let omega = if self.downside_sum > 0.0 {
            self.upside_sum / self.downside_sum
        } else {
            0.0
        };
        let profit_factor = if self.downside_sum > 0.0 {
            self.upside_sum / self.downside_sum
        } else {
            f64::INFINITY
        };
        let total_return = input.final_equity / self.initial_equity - 1.0;
        let cagr = match (self.start_timestamp_ns, self.end_timestamp_ns) {
            (Some(start), Some(end)) if end > start && input.final_equity > 0.0 => {
                let years = (end - start) as f64 / (365.25 * NS_PER_DAY as f64);
                if years > 0.0 {
                    (input.final_equity / self.initial_equity).powf(1.0 / years) - 1.0
                } else {
                    total_return
                }
            }
            _ => 0.0,
        };
        NativeMetricSnapshotV2 {
            metric_contract_version: METRIC_CONTRACT_VERSION_V2,
            final_equity: input.final_equity,
            total_return,
            cagr,
            mean_return: self.moments.mean,
            variance,
            sharpe,
            sortino,
            max_drawdown: self.max_drawdown,
            calmar: if self.max_drawdown > 0.0 {
                cagr / self.max_drawdown
            } else {
                0.0
            },
            omega,
            profit_factor,
            average_gross_exposure: if self.exposure_observations > 0 {
                self.gross_exposure_sum / self.exposure_observations as f64
            } else {
                0.0
            },
            turnover: input.turnover,
            total_fee: input.total_fee,
            total_funding: input.total_funding,
            fill_count: input.fill_count.max(0) as u64,
            event_count: input.event_count.max(0) as u64,
            rejected_count: input.rejected_count.max(0) as u64,
            canceled_count: input.canceled_count.max(0) as u64,
            sample_count: self.moments.count,
            liquidated: input.liquidated,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        MetricContractV2, MetricFinishInputV2, OnlineMetricReducerV2, ReturnFrequencyV2,
        ShortRunMetricPolicyV2, TradeCountDefinitionV2, ZeroVariancePolicyV2,
    };

    #[test]
    fn online_per_bar_metrics_are_stable_for_short_and_zero_variance_runs() {
        let contract = MetricContractV2::new(
            ReturnFrequencyV2::PerBar,
            365.0,
            0.0,
            1,
            ZeroVariancePolicyV2::ReturnZero,
            ShortRunMetricPolicyV2::ReturnZero,
            TradeCountDefinitionV2::CommittedFills,
        )
        .unwrap();
        let mut reducer = OnlineMetricReducerV2::new(contract, 100.0).unwrap();
        reducer.observe(0, 100.0, 0.0).unwrap();
        reducer.observe(1, 100.0, 0.0).unwrap();
        let snapshot = reducer.finish(MetricFinishInputV2 {
            final_equity: 100.0,
            turnover: 0.0,
            total_fee: 0.0,
            total_funding: 0.0,
            fill_count: 0,
            event_count: 0,
            rejected_count: 0,
            canceled_count: 0,
            liquidated: false,
        });
        assert_eq!(snapshot.sample_count, 1);
        assert_eq!(snapshot.sharpe, 0.0);
        assert_eq!(snapshot.sortino, 0.0);
        assert_eq!(snapshot.omega, 0.0);
    }

    #[test]
    fn daily_reducer_uses_day_closes_and_tracks_drawdown() {
        let mut reducer =
            OnlineMetricReducerV2::new(MetricContractV2::crypto_daily(), 100.0).unwrap();
        reducer.observe(0, 100.0, 0.5).unwrap();
        reducer.observe(1, 110.0, 0.6).unwrap();
        reducer.observe(86_400_000_000_000, 99.0, 0.4).unwrap();
        reducer.observe(2 * 86_400_000_000_000, 108.9, 0.2).unwrap();
        let snapshot = reducer.finish(MetricFinishInputV2 {
            final_equity: 108.9,
            turnover: 42.0,
            total_fee: 1.0,
            total_funding: 0.5,
            fill_count: 2,
            event_count: 4,
            rejected_count: 1,
            canceled_count: 1,
            liquidated: false,
        });
        assert_eq!(snapshot.sample_count, 2);
        assert!((snapshot.total_return - 0.089).abs() < 1e-12);
        assert!(snapshot.max_drawdown > 0.09);
        assert_eq!(snapshot.fill_count, 2);
        assert_eq!(snapshot.total_fee, 1.0);
    }

    #[test]
    fn per_bar_fixture_matches_manual_return_dispersion_and_downside_math() {
        // Independent hand-worked fixture:
        // equity 100 -> 110 -> 99 gives returns +10% and -10%. With ddof=1,
        // mean=0, variance=0.02, omega=1, and max drawdown=10%.
        let contract = MetricContractV2::new(
            ReturnFrequencyV2::PerBar,
            1.0,
            0.0,
            1,
            ZeroVariancePolicyV2::ReturnZero,
            ShortRunMetricPolicyV2::ReturnZero,
            TradeCountDefinitionV2::CommittedFills,
        )
        .unwrap();
        let mut reducer = OnlineMetricReducerV2::new(contract, 100.0).unwrap();
        reducer.observe(0, 100.0, 0.0).unwrap();
        reducer.observe(1, 110.0, 1.1).unwrap();
        reducer.observe(2, 99.0, 1.0).unwrap();
        let snapshot = reducer.finish(MetricFinishInputV2 {
            final_equity: 99.0,
            turnover: 209.0,
            total_fee: 0.209,
            total_funding: -0.1,
            fill_count: 2,
            event_count: 5,
            rejected_count: 1,
            canceled_count: 1,
            liquidated: false,
        });
        assert_eq!(snapshot.sample_count, 2);
        assert!((snapshot.total_return + 0.01).abs() < 1e-12);
        assert!(snapshot.mean_return.abs() < 1e-12);
        assert!((snapshot.variance - 0.02).abs() < 1e-12);
        assert!(snapshot.sharpe.abs() < 1e-12);
        assert!(snapshot.sortino.abs() < 1e-12);
        assert!((snapshot.omega - 1.0).abs() < 1e-12);
        assert!((snapshot.max_drawdown - 0.1).abs() < 1e-12);
        assert!((snapshot.average_gross_exposure - 0.7).abs() < 1e-12);
        assert_eq!(snapshot.turnover, 209.0);
        assert_eq!(snapshot.total_fee, 0.209);
        assert_eq!(snapshot.total_funding, -0.1);
        assert_eq!(snapshot.fill_count, 2);
        assert_eq!(snapshot.event_count, 5);
        assert_eq!(snapshot.rejected_count, 1);
        assert_eq!(snapshot.canceled_count, 1);
    }
}
