use crate::enums::{ActivationPolicy, CommandAction, OrderType, Side, TimeInForce};
use crate::errors::DomainError;
use crate::ids::{ExternalOrderId, SymbolId};

pub const LEGACY_CODE_WIDTH: usize = 16;
pub const LEGACY_VALUE_WIDTH: usize = 3;

/// Validated ABI 0.5 command record. Prices remain f64 at this boundary; the
/// engine applies each instrument's canonical tick policy before matching.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct OrderCommandV5 {
    pub action: CommandAction,
    pub symbol: Option<SymbolId>,
    pub side: Option<Side>,
    pub order_type: Option<OrderType>,
    pub tif: Option<TimeInForce>,
    pub reduce_only: bool,
    pub external_id: ExternalOrderId,
    pub target_id: ExternalOrderId,
    pub parent_id: ExternalOrderId,
    pub group_id: i64,
    pub oco_id: i64,
    pub activation: Option<ActivationPolicy>,
    pub command_index: u32,
    pub qty: f64,
    pub limit_price: f64,
    pub stop_price: f64,
    pub expire_bar: Option<u32>,
}

/// Immutable bar-addressable command tape. Every public input is validated
/// once, so the execution loop uses direct, bounded slices only.
#[derive(Clone, Debug, PartialEq)]
pub struct CommandTapeV5 {
    offsets_by_bar: Box<[u32]>,
    commands: Box<[OrderCommandV5]>,
}

impl CommandTapeV5 {
    pub fn new(
        offsets_by_bar: Vec<u32>,
        commands: Vec<OrderCommandV5>,
    ) -> Result<Self, DomainError> {
        if offsets_by_bar.len() < 2 || offsets_by_bar.first() != Some(&0) {
            return Err(DomainError::InvalidShape(
                "command offsets must start at zero",
            ));
        }
        let end = u32::try_from(commands.len())
            .map_err(|_| DomainError::InvalidShape("too many commands for ABI 0.5"))?;
        if offsets_by_bar.last() != Some(&end) {
            return Err(DomainError::InvalidShape(
                "command offsets must end at command count",
            ));
        }
        for (bar, pair) in offsets_by_bar.windows(2).enumerate() {
            if pair[0] > pair[1] || pair[1] > end {
                return Err(DomainError::InvalidOffset {
                    bar,
                    value: i64::from(pair[1]),
                });
            }
        }
        Ok(Self {
            offsets_by_bar: offsets_by_bar.into_boxed_slice(),
            commands: commands.into_boxed_slice(),
        })
    }

    #[must_use]
    pub fn bars(&self) -> usize {
        self.offsets_by_bar.len() - 1
    }

    #[must_use]
    pub fn command_count(&self) -> usize {
        self.commands.len()
    }

    #[must_use]
    pub fn commands_at(&self, bar: usize) -> &[OrderCommandV5] {
        let start = self.offsets_by_bar[bar] as usize;
        let end = self.offsets_by_bar[bar + 1] as usize;
        &self.commands[start..end]
    }

    #[must_use]
    pub fn offsets(&self) -> &[u32] {
        &self.offsets_by_bar
    }
}

/// Borrowed API 0.4 buffers. This translator is intentionally pure Rust so it
/// can be fuzzed without the Python extension or NumPy headers.
pub struct LegacyCommandTapeV4<'a> {
    pub offsets_by_bar: &'a [i64],
    pub codes: &'a [i64],
    pub values: &'a [f64],
    pub expiry: &'a [i64],
    pub n_bars: usize,
}

impl<'a> LegacyCommandTapeV4<'a> {
    pub fn translate(self, n_symbols: usize) -> Result<CommandTapeV5, DomainError> {
        if self.offsets_by_bar.len() != self.n_bars + 1 {
            return Err(DomainError::InvalidShape(
                "command_ptr length does not match bars",
            ));
        }
        if !self.codes.len().is_multiple_of(LEGACY_CODE_WIDTH)
            || !self.values.len().is_multiple_of(LEGACY_VALUE_WIDTH)
        {
            return Err(DomainError::InvalidShape(
                "legacy command buffers have invalid width",
            ));
        }
        let command_count = self.codes.len() / LEGACY_CODE_WIDTH;
        if self.values.len() / LEGACY_VALUE_WIDTH != command_count
            || self.expiry.len() != command_count
        {
            return Err(DomainError::InvalidShape(
                "legacy command buffers disagree on command count",
            ));
        }
        let expected_end = i64::try_from(command_count)
            .map_err(|_| DomainError::InvalidShape("too many legacy commands"))?;
        if self.offsets_by_bar.first() != Some(&0)
            || self.offsets_by_bar.last() != Some(&expected_end)
        {
            return Err(DomainError::InvalidShape(
                "legacy command offsets are not bounded",
            ));
        }

        let mut offsets = Vec::with_capacity(self.offsets_by_bar.len());
        for (bar, &offset) in self.offsets_by_bar.iter().enumerate() {
            if offset < 0 || offset > expected_end {
                return Err(DomainError::InvalidOffset { bar, value: offset });
            }
            if bar > 0 && offset < self.offsets_by_bar[bar - 1] {
                return Err(DomainError::InvalidOffset { bar, value: offset });
            }
            offsets.push(offset as u32);
        }

        let mut commands = Vec::with_capacity(command_count);
        for command_index in 0..command_count {
            let code = &self.codes
                [command_index * LEGACY_CODE_WIDTH..(command_index + 1) * LEGACY_CODE_WIDTH];
            let value = &self.values
                [command_index * LEGACY_VALUE_WIDTH..(command_index + 1) * LEGACY_VALUE_WIDTH];
            let action = CommandAction::try_from(code[0])?;
            let has_order_shape = matches!(action, CommandAction::Place | CommandAction::Replace);
            let symbol = if code[1] < 0 {
                None
            } else if (code[1] as usize) < n_symbols {
                Some(SymbolId(code[1] as u32))
            } else {
                return Err(DomainError::InvalidCommand {
                    command: command_index,
                    reason: "symbol is outside prepared market",
                });
            };
            let side = if has_order_shape {
                Some(Side::try_from(code[2])?)
            } else {
                None
            };
            let order_type = if has_order_shape {
                Some(OrderType::try_from(code[3])?)
            } else {
                None
            };
            let tif = if has_order_shape {
                Some(TimeInForce::try_from(code[4])?)
            } else {
                None
            };
            let activation = if has_order_shape {
                Some(ActivationPolicy::try_from(code[11])?)
            } else {
                None
            };
            if has_order_shape {
                if !value[0].is_finite() || value[0] <= 0.0 {
                    return Err(DomainError::InvalidCommand {
                        command: command_index,
                        reason: "quantity must be finite and positive",
                    });
                }
                match order_type.expect("checked above") {
                    OrderType::Market => {}
                    OrderType::Limit if value[1].is_finite() && value[1] > 0.0 => {}
                    OrderType::StopMarket if value[2].is_finite() && value[2] > 0.0 => {}
                    OrderType::StopLimit
                        if value[1].is_finite()
                            && value[1] > 0.0
                            && value[2].is_finite()
                            && value[2] > 0.0 => {}
                    _ => {
                        return Err(DomainError::InvalidCommand {
                            command: command_index,
                            reason: "order price or trigger is invalid",
                        });
                    }
                }
            }
            let expire_bar = if self.expiry[command_index] < 0 {
                None
            } else {
                Some(u32::try_from(self.expiry[command_index]).map_err(|_| {
                    DomainError::InvalidCommand {
                        command: command_index,
                        reason: "expiry bar exceeds ABI 0.5 range",
                    }
                })?)
            };
            commands.push(OrderCommandV5 {
                action,
                symbol,
                side,
                order_type,
                tif,
                reduce_only: code[5] != 0,
                external_id: ExternalOrderId(code[6]),
                target_id: ExternalOrderId(code[7]),
                parent_id: ExternalOrderId(code[8]),
                group_id: code[9],
                oco_id: code[10],
                activation,
                command_index: code[12].max(0) as u32,
                qty: value[0],
                limit_price: value[1],
                stop_price: value[2],
                expire_bar,
            });
        }
        CommandTapeV5::new(offsets, commands)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_codes() -> [i64; LEGACY_CODE_WIDTH] {
        [0, 0, 1, 0, 0, 0, 7, -1, -1, -1, -1, 0, 0, 0, 0, 0]
    }

    #[test]
    fn legacy_translator_builds_direct_bar_slices() {
        let codes = valid_codes();
        let tape = LegacyCommandTapeV4 {
            offsets_by_bar: &[0, 1, 1],
            codes: &codes,
            values: &[1.0, 0.0, 0.0],
            expiry: &[-1],
            n_bars: 2,
        }
        .translate(1)
        .unwrap();
        assert_eq!(tape.commands_at(0).len(), 1);
        assert!(tape.commands_at(1).is_empty());
    }

    #[test]
    fn malformed_legacy_offsets_fail_before_engine_mutation() {
        let codes = valid_codes();
        let error = LegacyCommandTapeV4 {
            offsets_by_bar: &[0, 2],
            codes: &codes,
            values: &[1.0, 0.0, 0.0],
            expiry: &[-1],
            n_bars: 1,
        }
        .translate(1)
        .unwrap_err();
        assert!(matches!(error, DomainError::InvalidShape(_)));
    }
}
