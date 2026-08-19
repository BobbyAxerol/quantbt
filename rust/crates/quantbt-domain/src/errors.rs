use core::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DomainError {
    InvalidEnum {
        field: &'static str,
        value: i64,
    },
    InvalidShape(&'static str),
    InvalidOffset {
        bar: usize,
        value: i64,
    },
    InvalidCommand {
        command: usize,
        reason: &'static str,
    },
    ResourceLimit {
        resource: &'static str,
        limit: usize,
    },
    StaleHandle,
}

impl fmt::Display for DomainError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidEnum { field, value } => write!(formatter, "invalid {field} code {value}"),
            Self::InvalidShape(message) => formatter.write_str(message),
            Self::InvalidOffset { bar, value } => {
                write!(formatter, "invalid command offset {value} at bar {bar}")
            }
            Self::InvalidCommand { command, reason } => {
                write!(formatter, "invalid command {command}: {reason}")
            }
            Self::ResourceLimit { resource, limit } => {
                write!(formatter, "{resource} resource limit {limit} exceeded")
            }
            Self::StaleHandle => formatter.write_str("stale order handle"),
        }
    }
}

impl std::error::Error for DomainError {}
