use std::collections::HashMap;

use quantbt_domain::ids::OrderHandle;

/// Bidirectional external-ID index for live lifecycle orders.
///
/// The forward mapping preserves the public command contract: an historical
/// replacement alias resolves to the newest live order. The reverse mapping
/// makes terminal cleanup proportional to aliases owned by that order instead
/// of every live alias in the session. Both directions are mutated only here.
#[derive(Debug, Default)]
pub struct ExternalOrderAliases {
    forward: HashMap<i64, OrderHandle>,
    reverse: HashMap<OrderHandle, Vec<i64>>,
}

impl ExternalOrderAliases {
    /// Bind non-negative public aliases to one live order handle.
    ///
    /// A duplicate alias keeps the legacy last-writer-wins behavior. Its old
    /// reverse membership is removed first, so releasing the old order cannot
    /// erase the alias now owned by the newer one.
    pub fn bind_all(&mut self, handle: OrderHandle, aliases: &[i64]) {
        for &alias in aliases {
            if alias < 0 {
                continue;
            }
            let previous = self.forward.insert(alias, handle);
            if let Some(previous) = previous.filter(|previous| *previous != handle) {
                self.remove_reverse_alias(previous, alias);
            }
            let members = self.reverse.entry(handle).or_default();
            if !members.contains(&alias) {
                members.push(alias);
            }
        }
    }

    #[must_use]
    pub fn resolve(&self, alias: i64) -> Option<OrderHandle> {
        self.forward.get(&alias).copied()
    }

    /// Copy only aliases belonging to one handle. Replacement is a command
    /// path, so this keeps its legacy chain semantics without a full-map scan.
    #[must_use]
    pub fn aliases_for(&self, handle: OrderHandle) -> Vec<i64> {
        self.reverse.get(&handle).cloned().unwrap_or_default()
    }

    /// Release all aliases that still resolve to `handle`.
    pub fn release(&mut self, handle: OrderHandle) {
        let Some(aliases) = self.reverse.remove(&handle) else {
            return;
        };
        for alias in aliases {
            if self.forward.get(&alias).copied() == Some(handle) {
                self.forward.remove(&alias);
            }
        }
    }

    pub fn clear(&mut self) {
        self.forward.clear();
        self.reverse.clear();
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.forward.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.forward.is_empty()
    }

    pub fn validate<F>(&self, mut is_live: F) -> Result<(), &'static str>
    where
        F: FnMut(OrderHandle) -> bool,
    {
        for (&alias, &handle) in &self.forward {
            if !is_live(handle) {
                return Err("external alias resolves to a stale handle");
            }
            if !self
                .reverse
                .get(&handle)
                .is_some_and(|aliases| aliases.contains(&alias))
            {
                return Err("external alias is absent from the reverse index");
            }
        }
        for (&handle, aliases) in &self.reverse {
            if !is_live(handle) {
                return Err("reverse alias index contains a stale handle");
            }
            for &alias in aliases {
                if self.forward.get(&alias).copied() != Some(handle) {
                    return Err("reverse alias index disagrees with forward mapping");
                }
            }
        }
        Ok(())
    }

    fn remove_reverse_alias(&mut self, handle: OrderHandle, alias: i64) {
        let remove_handle = if let Some(aliases) = self.reverse.get_mut(&handle) {
            aliases.retain(|candidate| *candidate != alias);
            aliases.is_empty()
        } else {
            false
        };
        if remove_handle {
            self.reverse.remove(&handle);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::ExternalOrderAliases;
    use quantbt_domain::ids::OrderHandle;

    fn handle(slot: u32, generation: u32) -> OrderHandle {
        OrderHandle { slot, generation }
    }

    #[test]
    fn replacement_aliases_move_without_full_index_cleanup() {
        let first = handle(1, 0);
        let replacement = handle(2, 0);
        let mut aliases = ExternalOrderAliases::default();
        aliases.bind_all(first, &[11, 12]);
        aliases.bind_all(replacement, &[11, 12, 13]);

        assert!(aliases.aliases_for(first).is_empty());
        assert_eq!(aliases.aliases_for(replacement), vec![11, 12, 13]);
        aliases.release(first);
        assert_eq!(aliases.resolve(11), Some(replacement));
        assert_eq!(aliases.resolve(12), Some(replacement));
        assert_eq!(aliases.resolve(13), Some(replacement));

        aliases.release(replacement);
        assert_eq!(aliases.len(), 0);
    }

    #[test]
    fn validator_rejects_a_stale_or_non_bidirectional_alias() {
        let live = handle(1, 0);
        let stale = handle(2, 0);
        let mut aliases = ExternalOrderAliases::default();
        aliases.bind_all(live, &[7]);
        assert!(aliases.validate(|handle| handle == live).is_ok());

        aliases.bind_all(stale, &[8]);
        assert_eq!(
            aliases.validate(|handle| handle == live),
            Err("external alias resolves to a stale handle")
        );
    }
}
