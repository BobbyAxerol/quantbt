//! Bounded, deterministic native strategy IR.
//!
//! The IR intentionally does **not** execute arbitrary Python. It compiles a
//! small set of declarative, precomputed-signal strategies into the typed
//! command-tape ABI consumed by `quantbt-engine`. This keeps strategy
//! semantics inspectable and makes Python/reference versus Rust differential
//! testing practical.

use quantbt_domain::commands::{CommandTapeV5, OrderCommandV5};
use quantbt_domain::enums::{ActivationPolicy, CommandAction, OrderType, Side, TimeInForce};
use quantbt_domain::errors::DomainError;
use quantbt_domain::ids::{ExternalOrderId, SymbolId};

pub const STRATEGY_IR_VERSION: u16 = 1;
pub const PARAMETER_WIDTH: usize = 4;
const MAX_INSTRUCTIONS_PER_BAR: u16 = 16;
const MAX_COMMANDS_PER_BAR: u16 = 8;
const EPSILON: f64 = 1e-12;

/// Supported v1 templates cover native precomputed-signal workloads without
/// pretending that arbitrary Python callbacks are native code.
#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum StrategyKind {
    SignalTarget = 0,
    GridLevel = 1,
    DcaPeriodic = 2,
    FixedBracket = 3,
}

impl TryFrom<u8> for StrategyKind {
    type Error = DomainError;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::SignalTarget),
            1 => Ok(Self::GridLevel),
            2 => Ok(Self::DcaPeriodic),
            3 => Ok(Self::FixedBracket),
            _ => Err(DomainError::InvalidEnum {
                field: "strategy_kind",
                value: i64::from(value),
            }),
        }
    }
}

impl StrategyKind {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::SignalTarget => "signal_target",
            Self::GridLevel => "grid_level",
            Self::DcaPeriodic => "dca_periodic",
            Self::FixedBracket => "fixed_bracket",
        }
    }
}

/// Fixed instruction vocabulary. Templates compile into this sequence so
/// disassembly/fingerprint data never depend on a Python callable.
#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum Opcode {
    LoadSignal = 0,
    ThresholdTarget = 1,
    GridTarget = 2,
    DcaState = 3,
    EmitMarketDelta = 4,
    EmitBracket = 5,
}

/// A compact typed instruction record. `a`, `b`, and `imm` are template
/// metadata in v1, reserving a stable extension path for a wider VM.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct Instruction {
    pub opcode: Opcode,
    pub dst: u16,
    pub a: u16,
    pub b: u16,
    pub imm: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProgramLimits {
    pub max_instructions_per_bar: u16,
    pub max_commands_per_bar: u16,
    pub state_slots: u16,
}

impl Default for ProgramLimits {
    fn default() -> Self {
        Self {
            max_instructions_per_bar: MAX_INSTRUCTIONS_PER_BAR,
            max_commands_per_bar: MAX_COMMANDS_PER_BAR,
            state_slots: 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeRequirements {
    pub signal_columns: u16,
    pub needs_close: bool,
    pub needs_position_state: bool,
}

/// Template defaults. A parameter matrix may override the stable order
/// `qty, threshold, take_profit_pct, stop_loss_pct`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StrategyParameters {
    pub quantity: f64,
    pub threshold: f64,
    pub take_profit_pct: f64,
    pub stop_loss_pct: f64,
    pub dca_period: u32,
    pub max_levels: u32,
}

impl StrategyParameters {
    fn validate(self, kind: StrategyKind) -> Result<Self, DomainError> {
        let values = [
            self.quantity,
            self.threshold,
            self.take_profit_pct,
            self.stop_loss_pct,
        ];
        if values.iter().any(|value| !value.is_finite())
            || self.quantity <= 0.0
            || self.threshold < 0.0
        {
            return Err(DomainError::InvalidShape(
                "strategy parameters must be finite with quantity > 0 and threshold >= 0",
            ));
        }
        if matches!(kind, StrategyKind::FixedBracket)
            && (self.take_profit_pct <= 0.0 || self.stop_loss_pct <= 0.0)
        {
            return Err(DomainError::InvalidShape(
                "fixed bracket requires positive take-profit and stop-loss percentages",
            ));
        }
        if matches!(kind, StrategyKind::DcaPeriodic)
            && (self.dca_period == 0 || self.max_levels == 0)
        {
            return Err(DomainError::InvalidShape(
                "periodic DCA requires dca_period and max_levels > 0",
            ));
        }
        Ok(self)
    }

    pub fn with_row(self, row: &[f64]) -> Result<Self, DomainError> {
        if row.len() != PARAMETER_WIDTH {
            return Err(DomainError::InvalidShape(
                "strategy parameter row has an unsupported width",
            ));
        }
        if row.iter().any(|value| !value.is_finite()) {
            return Err(DomainError::InvalidShape(
                "strategy parameter row must be finite",
            ));
        }
        Ok(Self {
            quantity: row[0],
            threshold: row[1],
            take_profit_pct: row[2],
            stop_loss_pct: row[3],
            ..self
        })
    }
}

/// Immutable program suitable for a prepared native runner.
#[derive(Clone, Debug, PartialEq)]
pub struct StrategyProgram {
    version: u16,
    kind: StrategyKind,
    symbol: SymbolId,
    defaults: StrategyParameters,
    instructions: Box<[Instruction]>,
    requirements: NativeRequirements,
    limits: ProgramLimits,
    fingerprint: [u8; 32],
}

impl StrategyProgram {
    pub fn new(
        version: u16,
        kind: StrategyKind,
        symbol: SymbolId,
        defaults: StrategyParameters,
        limits: ProgramLimits,
    ) -> Result<Self, DomainError> {
        if version != STRATEGY_IR_VERSION {
            return Err(DomainError::InvalidShape("unsupported strategy IR version"));
        }
        if limits.max_instructions_per_bar == 0
            || limits.max_instructions_per_bar > MAX_INSTRUCTIONS_PER_BAR
            || limits.max_commands_per_bar == 0
            || limits.max_commands_per_bar > MAX_COMMANDS_PER_BAR
            || limits.state_slots > 8
        {
            return Err(DomainError::ResourceLimit {
                resource: "strategy IR program limits",
                limit: usize::from(MAX_INSTRUCTIONS_PER_BAR),
            });
        }
        let defaults = defaults.validate(kind)?;
        let instructions = template_instructions(kind);
        if instructions.len() > usize::from(limits.max_instructions_per_bar) {
            return Err(DomainError::ResourceLimit {
                resource: "strategy IR instructions per bar",
                limit: usize::from(limits.max_instructions_per_bar),
            });
        }
        let requirements = NativeRequirements {
            signal_columns: 1,
            needs_close: matches!(kind, StrategyKind::FixedBracket),
            needs_position_state: true,
        };
        let fingerprint =
            fingerprint_program(version, kind, symbol, defaults, limits, &instructions);
        Ok(Self {
            version,
            kind,
            symbol,
            defaults,
            instructions: instructions.into_boxed_slice(),
            requirements,
            limits,
            fingerprint,
        })
    }

    #[must_use]
    pub const fn version(&self) -> u16 {
        self.version
    }

    #[must_use]
    pub const fn kind(&self) -> StrategyKind {
        self.kind
    }

    #[must_use]
    pub const fn symbol(&self) -> SymbolId {
        self.symbol
    }

    #[must_use]
    pub const fn defaults(&self) -> StrategyParameters {
        self.defaults
    }

    #[must_use]
    pub const fn requirements(&self) -> NativeRequirements {
        self.requirements
    }

    #[must_use]
    pub const fn limits(&self) -> ProgramLimits {
        self.limits
    }

    #[must_use]
    pub fn instructions(&self) -> &[Instruction] {
        &self.instructions
    }

    #[must_use]
    pub const fn fingerprint(&self) -> [u8; 32] {
        self.fingerprint
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        hex_fingerprint(self.fingerprint)
    }

    #[must_use]
    pub fn disassemble(&self) -> Vec<String> {
        self.instructions
            .iter()
            .enumerate()
            .map(|(pc, instruction)| {
                format!(
                    "{pc:03} {} dst={} a={} b={} imm={}",
                    opcode_name(instruction.opcode),
                    instruction.dst,
                    instruction.a,
                    instruction.b,
                    instruction.imm
                )
            })
            .collect()
    }

    /// Compile one signal column into a typed command tape. `closes` is only
    /// inspected by fixed brackets, but its length is always validated so a
    /// prepared batch cannot accidentally mix unrelated market data.
    pub fn compile_tape(
        &self,
        signals: &[f64],
        closes: &[f64],
        parameter_row: Option<&[f64]>,
    ) -> Result<CommandTapeV5, DomainError> {
        if signals.is_empty() || closes.len() != signals.len() {
            return Err(DomainError::InvalidShape(
                "strategy IR signals and close tape must have the same nonzero length",
            ));
        }
        if signals.iter().any(|value| !value.is_finite())
            || (self.requirements.needs_close
                && closes
                    .iter()
                    .any(|value| !value.is_finite() || *value <= 0.0))
        {
            return Err(DomainError::InvalidShape(
                "strategy IR market inputs are invalid",
            ));
        }
        let parameters = match parameter_row {
            Some(row) => self.defaults.with_row(row)?.validate(self.kind)?,
            None => self.defaults,
        };
        let mut offsets = Vec::with_capacity(signals.len() + 1);
        let mut commands = Vec::new();
        let mut state = StrategyState::default();
        let mut next_id = 0_i64;
        offsets.push(0);
        for (bar, signal) in signals.iter().copied().enumerate() {
            let target = match self.kind {
                StrategyKind::SignalTarget | StrategyKind::FixedBracket => {
                    threshold_target(signal, parameters.quantity, parameters.threshold)
                }
                StrategyKind::GridLevel => grid_target(signal, parameters.quantity)?,
                StrategyKind::DcaPeriodic => dca_target(
                    &mut state,
                    bar,
                    signal,
                    parameters.quantity,
                    parameters.threshold,
                    parameters.dca_period,
                    parameters.max_levels,
                ),
            };
            let before = commands.len();
            if (target - state.target).abs() > EPSILON {
                if matches!(self.kind, StrategyKind::FixedBracket) && state.bracket.is_some() {
                    let bracket = state.bracket.take().expect("checked above");
                    commands.push(cancel_command(bracket.take_profit_id));
                    commands.push(cancel_command(bracket.stop_loss_id));
                }
                let delta = target - state.target;
                if delta.abs() > EPSILON {
                    let parent_id = next_id;
                    next_id += 1;
                    let reduce_only = matches!(self.kind, StrategyKind::FixedBracket)
                        && target.signum() == state.target.signum()
                        && target.abs() < state.target.abs();
                    commands.push(market_command(self.symbol, delta, parent_id, reduce_only));
                    if matches!(self.kind, StrategyKind::FixedBracket) && target.abs() > EPSILON {
                        let take_profit_id = next_id;
                        next_id += 1;
                        let stop_loss_id = next_id;
                        next_id += 1;
                        let oco_id = parent_id;
                        let side = if target > 0.0 { Side::Sell } else { Side::Buy };
                        let close = closes[bar];
                        let (take_profit, stop_loss) = if target > 0.0 {
                            (
                                close * (1.0 + parameters.take_profit_pct),
                                close * (1.0 - parameters.stop_loss_pct),
                            )
                        } else {
                            (
                                close * (1.0 - parameters.take_profit_pct),
                                close * (1.0 + parameters.stop_loss_pct),
                            )
                        };
                        commands.push(limit_child_command(
                            self.symbol,
                            side,
                            target.abs(),
                            take_profit,
                            take_profit_id,
                            parent_id,
                            oco_id,
                        ));
                        commands.push(stop_child_command(
                            self.symbol,
                            side,
                            target.abs(),
                            stop_loss,
                            stop_loss_id,
                            parent_id,
                            oco_id,
                        ));
                        state.bracket = Some(BracketState {
                            take_profit_id,
                            stop_loss_id,
                        });
                    }
                }
                state.target = target;
            }
            if commands.len() - before > usize::from(self.limits.max_commands_per_bar) {
                return Err(DomainError::ResourceLimit {
                    resource: "strategy IR commands per bar",
                    limit: usize::from(self.limits.max_commands_per_bar),
                });
            }
            offsets.push(u32::try_from(commands.len()).map_err(|_| {
                DomainError::ResourceLimit {
                    resource: "strategy IR command tape",
                    limit: u32::MAX as usize,
                }
            })?);
        }
        CommandTapeV5::new(offsets, commands)
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct BracketState {
    take_profit_id: i64,
    stop_loss_id: i64,
}

#[derive(Clone, Copy, Debug, Default)]
struct StrategyState {
    target: f64,
    dca_level: i32,
    dca_side: i8,
    bracket: Option<BracketState>,
}

fn template_instructions(kind: StrategyKind) -> Vec<Instruction> {
    let mut instructions = vec![Instruction {
        opcode: Opcode::LoadSignal,
        dst: 0,
        a: 0,
        b: 0,
        imm: 0,
    }];
    instructions.push(Instruction {
        opcode: match kind {
            StrategyKind::SignalTarget | StrategyKind::FixedBracket => Opcode::ThresholdTarget,
            StrategyKind::GridLevel => Opcode::GridTarget,
            StrategyKind::DcaPeriodic => Opcode::DcaState,
        },
        dst: 1,
        a: 0,
        b: 0,
        imm: 0,
    });
    instructions.push(Instruction {
        opcode: Opcode::EmitMarketDelta,
        dst: 0,
        a: 1,
        b: 0,
        imm: 0,
    });
    if matches!(kind, StrategyKind::FixedBracket) {
        instructions.push(Instruction {
            opcode: Opcode::EmitBracket,
            dst: 0,
            a: 1,
            b: 0,
            imm: 0,
        });
    }
    instructions
}

fn threshold_target(signal: f64, quantity: f64, threshold: f64) -> f64 {
    if signal > threshold {
        quantity
    } else if signal < -threshold {
        -quantity
    } else {
        0.0
    }
}

fn grid_target(signal: f64, quantity: f64) -> Result<f64, DomainError> {
    let level = signal.round();
    if (signal - level).abs() > EPSILON {
        return Err(DomainError::InvalidShape(
            "grid_level signal values must be structural integers",
        ));
    }
    Ok(level * quantity)
}

fn dca_target(
    state: &mut StrategyState,
    bar: usize,
    signal: f64,
    quantity: f64,
    threshold: f64,
    period: u32,
    max_levels: u32,
) -> f64 {
    let side = if signal > threshold {
        1_i8
    } else if signal < -threshold {
        -1_i8
    } else {
        0_i8
    };
    if side == 0 {
        state.dca_level = 0;
        state.dca_side = 0;
        return 0.0;
    }
    if side != state.dca_side {
        state.dca_side = side;
        state.dca_level = 1;
    } else if bar.is_multiple_of(usize::try_from(period).expect("u32 fits usize"))
        && state.dca_level < max_levels as i32
    {
        state.dca_level += 1;
    }
    f64::from(state.dca_level) * quantity * f64::from(side)
}

#[allow(clippy::too_many_arguments)]
fn base_command(
    action: CommandAction,
    symbol: Option<SymbolId>,
    side: Option<Side>,
    order_type: Option<OrderType>,
    qty: f64,
    limit_price: f64,
    stop_price: f64,
    external_id: i64,
    target_id: i64,
    parent_id: i64,
    oco_id: i64,
    activation: Option<ActivationPolicy>,
    reduce_only: bool,
) -> OrderCommandV5 {
    OrderCommandV5 {
        action,
        symbol,
        side,
        order_type,
        tif: Some(TimeInForce::Gtc),
        reduce_only,
        external_id: ExternalOrderId(external_id),
        target_id: ExternalOrderId(target_id),
        parent_id: ExternalOrderId(parent_id),
        group_id: -1,
        oco_id,
        activation,
        command_index: 0,
        qty,
        limit_price,
        stop_price,
        expire_bar: None,
    }
}

fn market_command(
    symbol: SymbolId,
    signed_delta: f64,
    order_id: i64,
    reduce_only: bool,
) -> OrderCommandV5 {
    base_command(
        CommandAction::Place,
        Some(symbol),
        Some(if signed_delta > 0.0 {
            Side::Buy
        } else {
            Side::Sell
        }),
        Some(OrderType::Market),
        signed_delta.abs(),
        0.0,
        0.0,
        order_id,
        -1,
        -1,
        -1,
        Some(ActivationPolicy::Immediate),
        reduce_only,
    )
}

#[allow(clippy::too_many_arguments)]
fn limit_child_command(
    symbol: SymbolId,
    side: Side,
    qty: f64,
    price: f64,
    order_id: i64,
    parent_id: i64,
    oco_id: i64,
) -> OrderCommandV5 {
    base_command(
        CommandAction::Place,
        Some(symbol),
        Some(side),
        Some(OrderType::Limit),
        qty,
        price,
        0.0,
        order_id,
        -1,
        parent_id,
        oco_id,
        Some(ActivationPolicy::OnParentFirstFill),
        true,
    )
}

#[allow(clippy::too_many_arguments)]
fn stop_child_command(
    symbol: SymbolId,
    side: Side,
    qty: f64,
    trigger: f64,
    order_id: i64,
    parent_id: i64,
    oco_id: i64,
) -> OrderCommandV5 {
    base_command(
        CommandAction::Place,
        Some(symbol),
        Some(side),
        Some(OrderType::StopMarket),
        qty,
        0.0,
        trigger,
        order_id,
        -1,
        parent_id,
        oco_id,
        Some(ActivationPolicy::OnParentFirstFill),
        true,
    )
}

fn cancel_command(target_id: i64) -> OrderCommandV5 {
    base_command(
        CommandAction::Cancel,
        None,
        None,
        None,
        0.0,
        0.0,
        0.0,
        -1,
        target_id,
        -1,
        -1,
        None,
        false,
    )
}

fn opcode_name(opcode: Opcode) -> &'static str {
    match opcode {
        Opcode::LoadSignal => "LOAD_SIGNAL",
        Opcode::ThresholdTarget => "THRESHOLD_TARGET",
        Opcode::GridTarget => "GRID_TARGET",
        Opcode::DcaState => "DCA_STATE",
        Opcode::EmitMarketDelta => "EMIT_MARKET_DELTA",
        Opcode::EmitBracket => "EMIT_BRACKET",
    }
}

fn fingerprint_program(
    version: u16,
    kind: StrategyKind,
    symbol: SymbolId,
    parameters: StrategyParameters,
    limits: ProgramLimits,
    instructions: &[Instruction],
) -> [u8; 32] {
    // Four independent FNV-1a lanes are deterministic across platforms and
    // intentionally easy to reproduce in the Python reference compiler.
    let mut lanes = [
        0xcbf2_9ce4_8422_2325_u64,
        0x8422_2325_cbf2_9ce4_u64,
        0x9e37_79b9_7f4a_7c15_u64,
        0x517c_c1b7_2722_0a95_u64,
    ];
    let mut payload = Vec::with_capacity(128 + instructions.len() * 12);
    payload.extend_from_slice(b"quantbt-strategy-ir-v1");
    payload.extend_from_slice(&version.to_le_bytes());
    payload.push(kind as u8);
    payload.extend_from_slice(&symbol.0.to_le_bytes());
    for value in [
        parameters.quantity,
        parameters.threshold,
        parameters.take_profit_pct,
        parameters.stop_loss_pct,
    ] {
        payload.extend_from_slice(&value.to_bits().to_le_bytes());
    }
    payload.extend_from_slice(&parameters.dca_period.to_le_bytes());
    payload.extend_from_slice(&parameters.max_levels.to_le_bytes());
    payload.extend_from_slice(&limits.max_instructions_per_bar.to_le_bytes());
    payload.extend_from_slice(&limits.max_commands_per_bar.to_le_bytes());
    payload.extend_from_slice(&limits.state_slots.to_le_bytes());
    for instruction in instructions {
        payload.push(instruction.opcode as u8);
        payload.extend_from_slice(&instruction.dst.to_le_bytes());
        payload.extend_from_slice(&instruction.a.to_le_bytes());
        payload.extend_from_slice(&instruction.b.to_le_bytes());
        payload.extend_from_slice(&instruction.imm.to_le_bytes());
    }
    for (lane_index, lane) in lanes.iter_mut().enumerate() {
        for byte in &payload {
            *lane ^= u64::from(*byte).wrapping_add((lane_index as u64) << 1);
            *lane = lane.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    let mut fingerprint = [0_u8; 32];
    for (index, lane) in lanes.into_iter().enumerate() {
        fingerprint[index * 8..(index + 1) * 8].copy_from_slice(&lane.to_le_bytes());
    }
    fingerprint
}

fn hex_fingerprint(fingerprint: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in fingerprint {
        output.push(HEX[usize::from(byte >> 4)] as char);
        output.push(HEX[usize::from(byte & 0x0f)] as char);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::{
        ProgramLimits, STRATEGY_IR_VERSION, StrategyKind, StrategyParameters, StrategyProgram,
    };
    use quantbt_domain::ids::SymbolId;

    fn defaults() -> StrategyParameters {
        StrategyParameters {
            quantity: 2.0,
            threshold: 0.0,
            take_profit_pct: 0.02,
            stop_loss_pct: 0.01,
            dca_period: 2,
            max_levels: 3,
        }
    }

    #[test]
    fn program_rejects_unknown_versions_and_invalid_template_bounds() {
        assert!(
            StrategyProgram::new(
                STRATEGY_IR_VERSION + 1,
                StrategyKind::SignalTarget,
                SymbolId(0),
                defaults(),
                ProgramLimits::default(),
            )
            .is_err()
        );
        let limits = ProgramLimits {
            max_commands_per_bar: 0,
            ..ProgramLimits::default()
        };
        assert!(
            StrategyProgram::new(
                STRATEGY_IR_VERSION,
                StrategyKind::SignalTarget,
                SymbolId(0),
                defaults(),
                limits,
            )
            .is_err()
        );
    }

    #[test]
    fn grid_and_dca_tapes_are_bounded_and_deterministic() {
        let grid = StrategyProgram::new(
            STRATEGY_IR_VERSION,
            StrategyKind::GridLevel,
            SymbolId(0),
            defaults(),
            ProgramLimits::default(),
        )
        .unwrap();
        let tape = grid
            .compile_tape(&[0.0, 1.0, 2.0, 1.0, 0.0], &[100.0; 5], None)
            .unwrap();
        assert_eq!(tape.bars(), 5);
        assert_eq!(tape.command_count(), 4);
        assert_eq!(grid.fingerprint_hex().len(), 64);

        let dca = StrategyProgram::new(
            STRATEGY_IR_VERSION,
            StrategyKind::DcaPeriodic,
            SymbolId(0),
            defaults(),
            ProgramLimits::default(),
        )
        .unwrap();
        let first = dca
            .compile_tape(&[0.0, 1.0, 1.0, 1.0, 0.0], &[100.0; 5], None)
            .unwrap();
        let second = dca
            .compile_tape(&[0.0, 1.0, 1.0, 1.0, 0.0], &[100.0; 5], None)
            .unwrap();
        assert_eq!(first, second);
    }

    #[test]
    fn fixed_bracket_emits_parent_and_oco_children() {
        let program = StrategyProgram::new(
            STRATEGY_IR_VERSION,
            StrategyKind::FixedBracket,
            SymbolId(0),
            defaults(),
            ProgramLimits::default(),
        )
        .unwrap();
        let tape = program
            .compile_tape(&[0.0, 1.0, 1.0], &[100.0, 100.0, 100.0], None)
            .unwrap();
        assert_eq!(tape.commands_at(1).len(), 3);
        assert_eq!(
            tape.commands_at(1)[1].parent_id.0,
            tape.commands_at(1)[0].external_id.0
        );
        assert_eq!(tape.commands_at(1)[1].oco_id, tape.commands_at(1)[2].oco_id);
    }
}
