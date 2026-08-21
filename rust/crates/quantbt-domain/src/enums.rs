use crate::errors::DomainError;

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum CommandAction {
    Place = 0,
    Cancel = 1,
    Replace = 2,
    Amend = 3,
    CancelAll = 4,
}

impl TryFrom<i64> for CommandAction {
    type Error = DomainError;

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Place),
            1 => Ok(Self::Cancel),
            2 => Ok(Self::Replace),
            3 => Ok(Self::Amend),
            4 => Ok(Self::CancelAll),
            _ => Err(DomainError::InvalidEnum {
                field: "action",
                value,
            }),
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum OrderType {
    Market = 0,
    Limit = 1,
    StopMarket = 2,
    StopLimit = 3,
}

impl TryFrom<i64> for OrderType {
    type Error = DomainError;

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Market),
            1 => Ok(Self::Limit),
            2 => Ok(Self::StopMarket),
            3 => Ok(Self::StopLimit),
            _ => Err(DomainError::InvalidEnum {
                field: "order_type",
                value,
            }),
        }
    }
}

#[repr(i8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum Side {
    Sell = -1,
    Buy = 1,
}

impl TryFrom<i64> for Side {
    type Error = DomainError;

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            -1 => Ok(Self::Sell),
            1 => Ok(Self::Buy),
            _ => Err(DomainError::InvalidEnum {
                field: "side",
                value,
            }),
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum TimeInForce {
    Gtc = 0,
    Ioc = 1,
    Fok = 2,
    Gtd = 3,
}

impl TryFrom<i64> for TimeInForce {
    type Error = DomainError;

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Gtc),
            1 => Ok(Self::Ioc),
            2 => Ok(Self::Fok),
            3 => Ok(Self::Gtd),
            _ => Err(DomainError::InvalidEnum {
                field: "time_in_force",
                value,
            }),
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum ActivationPolicy {
    Immediate = 0,
    OnParentFirstFill = 1,
    OnParentFullFill = 2,
}

impl TryFrom<i64> for ActivationPolicy {
    type Error = DomainError;

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Immediate),
            1 => Ok(Self::OnParentFirstFill),
            2 => Ok(Self::OnParentFullFill),
            _ => Err(DomainError::InvalidEnum {
                field: "activation",
                value,
            }),
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum OrderStatus {
    WaitingParent = 0,
    Active = 1,
    Filled = 2,
    Canceled = 3,
    Rejected = 4,
    Expired = 5,
}

impl OrderStatus {
    #[must_use]
    pub const fn is_live(self) -> bool {
        matches!(self, Self::WaitingParent | Self::Active)
    }
}
