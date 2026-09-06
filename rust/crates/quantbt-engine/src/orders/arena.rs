use quantbt_domain::errors::DomainError;
use quantbt_domain::ids::OrderHandle;

#[derive(Debug)]
struct Slot<T> {
    generation: u32,
    value: Option<T>,
}

/// Generation-safe slot arena. Terminal order detail belongs in a sink before
/// `remove`; no hot compaction is needed and stale handles cannot alias a slot
/// reused by a later order.
#[derive(Debug)]
pub struct OrderArena<T> {
    slots: Vec<Slot<T>>,
    free_slots: Vec<u32>,
    live: usize,
    total_created: u64,
    max_live: usize,
    max_total_created: u64,
    high_water_live: usize,
    retired_slots: usize,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArenaStats {
    pub slots: usize,
    pub live: usize,
    pub free: usize,
    /// Slots deliberately retired after their generation reaches `u32::MAX`.
    /// They are never recycled, so a stale handle cannot become valid again
    /// through generation wraparound.
    pub retired: usize,
    pub total_created: u64,
    pub high_water_live: usize,
}

impl<T> OrderArena<T> {
    #[must_use]
    pub fn new(max_live: usize, max_total_created: u64) -> Self {
        Self {
            slots: Vec::new(),
            free_slots: Vec::new(),
            live: 0,
            total_created: 0,
            max_live,
            max_total_created,
            high_water_live: 0,
            retired_slots: 0,
        }
    }

    pub fn insert(&mut self, value: T) -> Result<OrderHandle, DomainError> {
        if self.live >= self.max_live {
            return Err(DomainError::ResourceLimit {
                resource: "live orders",
                limit: self.max_live,
            });
        }
        if self.total_created >= self.max_total_created {
            return Err(DomainError::ResourceLimit {
                resource: "total orders",
                limit: self.max_total_created as usize,
            });
        }
        self.total_created += 1;
        self.live += 1;
        self.high_water_live = self.high_water_live.max(self.live);
        if let Some(slot) = self.free_slots.pop() {
            let entry = &mut self.slots[slot as usize];
            debug_assert!(entry.value.is_none());
            entry.value = Some(value);
            return Ok(OrderHandle {
                slot,
                generation: entry.generation,
            });
        }
        let slot = u32::try_from(self.slots.len()).map_err(|_| DomainError::ResourceLimit {
            resource: "arena slots",
            limit: u32::MAX as usize,
        })?;
        self.slots.push(Slot {
            generation: 0,
            value: Some(value),
        });
        Ok(OrderHandle {
            slot,
            generation: 0,
        })
    }

    #[must_use]
    pub fn get(&self, handle: OrderHandle) -> Option<&T> {
        let slot = self.slots.get(handle.slot as usize)?;
        (slot.generation == handle.generation)
            .then_some(())
            .and(slot.value.as_ref())
    }

    pub fn get_mut(&mut self, handle: OrderHandle) -> Option<&mut T> {
        let slot = self.slots.get_mut(handle.slot as usize)?;
        (slot.generation == handle.generation)
            .then_some(())
            .and(slot.value.as_mut())
    }

    pub fn remove(&mut self, handle: OrderHandle) -> Result<T, DomainError> {
        let slot = self
            .slots
            .get_mut(handle.slot as usize)
            .ok_or(DomainError::StaleHandle)?;
        if slot.generation != handle.generation {
            return Err(DomainError::StaleHandle);
        }
        let value = slot.value.take().ok_or(DomainError::StaleHandle)?;
        // Do not wrap an arena generation. A stale handle from `u32::MAX`
        // must never alias a future order in this slot. Retiring this one
        // slot is an explicit, bounded safety fallback; a service may rebuild
        // its session when retention pressure matters more than reuse.
        if slot.generation != u32::MAX {
            slot.generation += 1;
            self.free_slots.push(handle.slot);
        } else {
            self.retired_slots = self.retired_slots.saturating_add(1);
        }
        self.live = self.live.saturating_sub(1);
        Ok(value)
    }

    #[must_use]
    pub fn contains(&self, handle: OrderHandle) -> bool {
        self.get(handle).is_some()
    }

    pub fn iter(&self) -> impl Iterator<Item = (OrderHandle, &T)> {
        self.slots.iter().enumerate().filter_map(|(slot, entry)| {
            entry.value.as_ref().map(|value| {
                (
                    OrderHandle {
                        slot: slot as u32,
                        generation: entry.generation,
                    },
                    value,
                )
            })
        })
    }

    #[must_use]
    pub fn stats(&self) -> ArenaStats {
        ArenaStats {
            slots: self.slots.len(),
            live: self.live,
            free: self.free_slots.len(),
            retired: self.retired_slots,
            total_created: self.total_created,
            high_water_live: self.high_water_live,
        }
    }

    #[must_use]
    pub fn slot_capacity(&self) -> usize {
        self.slots.capacity()
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.live
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.live == 0
    }

    pub fn clear(&mut self) {
        // The common prepared-runner path has already released every terminal
        // order. In that case `free_slots` is authoritative and a full scan of
        // a high-water arena adds reset work without changing state.
        if self.live == 0 {
            self.total_created = 0;
            self.high_water_live = 0;
            return;
        }
        self.free_slots.clear();
        for (slot, entry) in self.slots.iter_mut().enumerate() {
            if entry.value.take().is_some() {
                if entry.generation != u32::MAX {
                    entry.generation += 1;
                } else {
                    self.retired_slots = self.retired_slots.saturating_add(1);
                }
            }
            if entry.generation != u32::MAX {
                self.free_slots.push(slot as u32);
            }
        }
        self.live = 0;
        self.total_created = 0;
        self.high_water_live = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::OrderArena;
    use quantbt_domain::errors::DomainError;
    use quantbt_domain::ids::OrderHandle;

    #[test]
    fn stale_handle_never_aliases_reused_slot() {
        let mut arena = OrderArena::new(2, 4);
        let first = arena.insert("first").unwrap();
        assert_eq!(arena.remove(first).unwrap(), "first");
        let second = arena.insert("second").unwrap();
        assert_eq!(first.slot, second.slot);
        assert_ne!(first.generation, second.generation);
        assert!(arena.get(first).is_none());
        assert_eq!(arena.remove(first), Err(DomainError::StaleHandle));
        assert_eq!(arena.get(second), Some(&"second"));
    }

    #[test]
    fn arena_enforces_explicit_resource_limits() {
        let mut arena = OrderArena::new(1, 1);
        let _ = arena.insert(1_u8).unwrap();
        assert!(matches!(
            arena.insert(2_u8),
            Err(DomainError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn retired_generation_slot_never_revalidates_a_stale_handle() {
        let mut arena = OrderArena::new(4, 8);
        let first = arena.insert("first").unwrap();
        // Force the terminal generation boundary deterministically. This is
        // the same branch a long-lived service would reach only after an
        // impractically large number of reuse cycles.
        arena.slots[first.slot as usize].generation = u32::MAX;
        let stale = OrderHandle {
            slot: first.slot,
            generation: u32::MAX,
        };
        assert_eq!(arena.remove(stale).unwrap(), "first");
        assert_eq!(arena.stats().retired, 1);
        let next = arena.insert("next").unwrap();
        assert_ne!(next.slot, stale.slot);
        assert!(arena.get(stale).is_none());

        arena.clear();
        let after_reset = arena.insert("after-reset").unwrap();
        assert_ne!(after_reset.slot, stale.slot);
        assert!(arena.get(stale).is_none());
    }
}
