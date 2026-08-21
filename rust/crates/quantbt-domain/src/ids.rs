use core::fmt;

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct SymbolId(pub u32);

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct InstrumentId(pub u32);

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct VenueId(pub u16);

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct CurrencyId(pub u16);

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct ExternalOrderId(pub i64);

/// A generation-checked reference into an engine-owned order arena.
///
/// The packed representation is used only at narrow FFI boundaries. Core code
/// always carries the typed handle so a slot reuse cannot mutate a newer order.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct OrderHandle {
    pub slot: u32,
    pub generation: u32,
}

impl OrderHandle {
    #[must_use]
    pub const fn pack(self) -> u64 {
        ((self.generation as u64) << 32) | self.slot as u64
    }

    #[must_use]
    pub const fn unpack(value: u64) -> Self {
        Self {
            slot: value as u32,
            generation: (value >> 32) as u32,
        }
    }
}

impl fmt::Display for OrderHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}:{}", self.slot, self.generation)
    }
}

#[cfg(test)]
mod tests {
    use super::OrderHandle;

    #[test]
    fn packed_handle_round_trips_without_aliasing_bits() {
        let handle = OrderHandle {
            slot: u32::MAX,
            generation: 42,
        };
        assert_eq!(OrderHandle::unpack(handle.pack()), handle);
    }
}
