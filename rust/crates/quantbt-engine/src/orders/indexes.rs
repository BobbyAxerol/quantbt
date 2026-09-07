use std::collections::{BTreeMap, HashMap, HashSet};

use quantbt_domain::ids::{ExternalOrderId, OrderHandle, SymbolId};

/// Minimal state required for lifecycle index validation. It deliberately
/// contains no account/PyO3 types and may be assembled from any order layout.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IndexOrderState {
    pub symbol: SymbolId,
    pub active: bool,
    pub waiting_parent: bool,
    pub sequence: u64,
    pub parent_id: ExternalOrderId,
    pub oco_id: i64,
    pub expire_bar: Option<u32>,
}

/// Indexes all live orders, not order history. Matching uses stable sequence
/// priority; expiry/parent/OCO operations visit only their relevant members.
#[derive(Default)]
pub struct LifecycleIndexes {
    active_by_symbol: Vec<Vec<OrderHandle>>,
    active_by_sequence: BTreeMap<u64, OrderHandle>,
    live_by_sequence: BTreeMap<u64, OrderHandle>,
    expiry_by_bar: BTreeMap<u32, Vec<OrderHandle>>,
    children_by_parent: HashMap<ExternalOrderId, Vec<OrderHandle>>,
    oco_groups: HashMap<i64, Vec<OrderHandle>>,
    states: HashMap<OrderHandle, IndexOrderState>,
}

impl LifecycleIndexes {
    #[must_use]
    pub fn with_symbols(n_symbols: usize) -> Self {
        Self {
            active_by_symbol: (0..n_symbols).map(|_| Vec::new()).collect(),
            ..Self::default()
        }
    }

    pub fn insert(&mut self, handle: OrderHandle, state: IndexOrderState) {
        self.live_by_sequence.insert(state.sequence, handle);
        if state.active {
            self.add_active(handle, state.symbol, state.sequence);
        }
        if let Some(expire_bar) = state.expire_bar {
            self.expiry_by_bar
                .entry(expire_bar)
                .or_default()
                .push(handle);
        }
        if state.parent_id.0 >= 0 {
            self.children_by_parent
                .entry(state.parent_id)
                .or_default()
                .push(handle);
        }
        if state.oco_id >= 0 {
            self.oco_groups
                .entry(state.oco_id)
                .or_default()
                .push(handle);
        }
        self.states.insert(handle, state);
    }

    pub fn set_active(&mut self, handle: OrderHandle, active: bool) {
        self.set_activation(handle, active, false);
    }

    pub fn set_activation(&mut self, handle: OrderHandle, active: bool, waiting_parent: bool) {
        let Some(state) = self.states.get_mut(&handle) else {
            return;
        };
        let symbol = state.symbol;
        let sequence = state.sequence;
        let previous_active = state.active;
        state.active = active;
        state.waiting_parent = waiting_parent;
        if previous_active == active {
            return;
        }
        if active {
            self.add_active(handle, symbol, sequence);
        } else {
            self.remove_active(handle, symbol, sequence);
        }
    }

    pub fn remove(&mut self, handle: OrderHandle) {
        let Some(state) = self.states.remove(&handle) else {
            return;
        };
        self.live_by_sequence.remove(&state.sequence);
        if state.active {
            self.remove_active(handle, state.symbol, state.sequence);
        }
        if let Some(expire_bar) = state.expire_bar {
            Self::remove_member(&mut self.expiry_by_bar, &expire_bar, handle);
        }
        if state.parent_id.0 >= 0 {
            Self::remove_member(&mut self.children_by_parent, &state.parent_id, handle);
        }
        if state.oco_id >= 0 {
            Self::remove_member(&mut self.oco_groups, &state.oco_id, handle);
        }
    }

    #[must_use]
    pub fn active_priority_handles(&self) -> Vec<OrderHandle> {
        let mut handles = Vec::with_capacity(self.active_by_sequence.len());
        self.append_active_priority_handles(&mut handles);
        handles
    }

    #[must_use]
    pub fn live_priority_handles(&self) -> Vec<OrderHandle> {
        let mut handles = Vec::with_capacity(self.live_by_sequence.len());
        self.append_live_priority_handles(&mut handles);
        handles
    }

    #[must_use]
    pub fn due_expiry_handles(&self, bar: u32) -> Vec<OrderHandle> {
        let mut handles = Vec::new();
        self.append_due_expiry_handles(bar, &mut handles);
        handles
    }

    #[must_use]
    pub fn children_of(&self, parent_id: ExternalOrderId) -> Vec<OrderHandle> {
        let mut handles = Vec::new();
        self.append_children_of(parent_id, &mut handles);
        handles
    }

    #[must_use]
    pub fn oco_members(&self, oco_id: i64) -> Vec<OrderHandle> {
        let mut handles = Vec::new();
        self.append_oco_members(oco_id, &mut handles);
        handles
    }

    /// Append priority-ordered active handles to caller-owned scratch.
    ///
    /// `FullSession` clears and reuses this buffer once per bar, avoiding a
    /// fresh candidate allocation while preserving the exact sequence order.
    pub fn append_active_priority_handles(&self, output: &mut Vec<OrderHandle>) {
        output.extend(self.active_by_sequence.values().copied());
    }

    pub fn active_priority_iter(&self) -> impl Iterator<Item = OrderHandle> + '_ {
        self.active_by_sequence.values().copied()
    }

    /// Append priority-ordered live handles to caller-owned scratch.
    pub fn append_live_priority_handles(&self, output: &mut Vec<OrderHandle>) {
        output.extend(self.live_by_sequence.values().copied());
    }

    pub fn live_priority_iter(&self) -> impl Iterator<Item = OrderHandle> + '_ {
        self.live_by_sequence.values().copied()
    }

    /// Append only expiry entries due at `bar` to caller-owned scratch.
    pub fn append_due_expiry_handles(&self, bar: u32, output: &mut Vec<OrderHandle>) {
        output.extend(
            self.expiry_by_bar
                .range(..=bar)
                .flat_map(|(_, handles)| handles.iter().copied()),
        );
    }

    /// Append children for one parent to caller-owned scratch.
    pub fn append_children_of(&self, parent_id: ExternalOrderId, output: &mut Vec<OrderHandle>) {
        if let Some(handles) = self.children_by_parent.get(&parent_id) {
            output.extend(handles.iter().copied());
        }
    }

    /// Append one OCO group to caller-owned scratch.
    pub fn append_oco_members(&self, oco_id: i64, output: &mut Vec<OrderHandle>) {
        if let Some(handles) = self.oco_groups.get(&oco_id) {
            output.extend(handles.iter().copied());
        }
    }

    #[must_use]
    pub fn active_for_symbol(&self, symbol: SymbolId) -> &[OrderHandle] {
        self.active_by_symbol
            .get(symbol.0 as usize)
            .map_or(&[], Vec::as_slice)
    }

    #[must_use]
    pub fn active_count(&self) -> usize {
        self.active_by_sequence.len()
    }

    pub fn clear(&mut self) {
        for handles in &mut self.active_by_symbol {
            handles.clear();
        }
        self.active_by_sequence.clear();
        self.live_by_sequence.clear();
        self.expiry_by_bar.clear();
        self.children_by_parent.clear();
        self.oco_groups.clear();
        self.states.clear();
    }

    pub fn validate<F>(&self, mut state_of: F) -> Result<(), &'static str>
    where
        F: FnMut(OrderHandle) -> Option<IndexOrderState>,
    {
        let mut seen_active = HashSet::new();
        for (symbol, handles) in self.active_by_symbol.iter().enumerate() {
            for &handle in handles {
                let state = state_of(handle).ok_or("active index points to stale handle")?;
                if !state.active || state.symbol.0 as usize != symbol {
                    return Err("active symbol index disagrees with order state");
                }
                if !seen_active.insert(handle) {
                    return Err("active order appears more than once");
                }
            }
        }
        if seen_active.len() != self.active_by_sequence.len() {
            return Err("active sequence index disagrees with active symbol index");
        }
        for (&sequence, &handle) in &self.active_by_sequence {
            let state = state_of(handle).ok_or("priority index points to stale handle")?;
            if !state.active || state.sequence != sequence {
                return Err("priority index disagrees with order state");
            }
        }
        for (&handle, &state) in &self.states {
            let observed = state_of(handle).ok_or("state registry points to stale handle")?;
            if observed != state {
                return Err("state registry disagrees with order state");
            }
            if state.active != self.active_by_sequence.contains_key(&state.sequence) {
                return Err("active state missing from priority index");
            }
        }
        Ok(())
    }

    /// Debug/test differential guard against a reference full arena scan.
    ///
    /// The supplied iterator is the arena's authoritative live set. This
    /// catches a missing indexed candidate and an accidental priority drift;
    /// neither error can be detected by checking index internals alone.
    pub fn validate_complete<I>(&self, states: I) -> Result<(), &'static str>
    where
        I: IntoIterator<Item = (OrderHandle, IndexOrderState)>,
    {
        let expected: HashMap<_, _> = states.into_iter().collect();
        if expected.len() != self.states.len() {
            return Err("lifecycle index live-set cardinality disagrees with arena");
        }
        for (&handle, &state) in &expected {
            if self.states.get(&handle) != Some(&state) {
                return Err("lifecycle index state disagrees with arena");
            }
        }
        let mut reference_active = expected
            .iter()
            .filter_map(|(&handle, state)| state.active.then_some((state.sequence, handle)))
            .collect::<Vec<_>>();
        reference_active.sort_unstable_by_key(|(sequence, _)| *sequence);
        let reference_active = reference_active
            .into_iter()
            .map(|(_, handle)| handle)
            .collect::<Vec<_>>();
        if self.active_priority_handles() != reference_active {
            return Err("active priority index disagrees with full arena scan");
        }
        Ok(())
    }

    fn add_active(&mut self, handle: OrderHandle, symbol: SymbolId, sequence: u64) {
        let symbol_index = symbol.0 as usize;
        if symbol_index >= self.active_by_symbol.len() {
            self.active_by_symbol
                .resize_with(symbol_index + 1, Vec::new);
        }
        self.active_by_symbol[symbol_index].push(handle);
        self.active_by_sequence.insert(sequence, handle);
    }

    fn remove_active(&mut self, handle: OrderHandle, symbol: SymbolId, sequence: u64) {
        if let Some(handles) = self.active_by_symbol.get_mut(symbol.0 as usize)
            && let Some(index) = handles.iter().position(|candidate| *candidate == handle)
        {
            handles.swap_remove(index);
        }
        self.active_by_sequence.remove(&sequence);
    }

    fn remove_member<K: Eq + std::hash::Hash + Ord + Copy>(
        map: &mut impl MemberMap<K>,
        key: &K,
        handle: OrderHandle,
    ) {
        map.remove_member(key, handle);
    }
}

trait MemberMap<K> {
    fn remove_member(&mut self, key: &K, handle: OrderHandle);
}

impl<K: Eq + std::hash::Hash + Copy> MemberMap<K> for HashMap<K, Vec<OrderHandle>> {
    fn remove_member(&mut self, key: &K, handle: OrderHandle) {
        let remove_key = if let Some(handles) = self.get_mut(key) {
            handles.retain(|candidate| *candidate != handle);
            handles.is_empty()
        } else {
            false
        };
        if remove_key {
            self.remove(key);
        }
    }
}

impl<K: Ord + Copy> MemberMap<K> for BTreeMap<K, Vec<OrderHandle>> {
    fn remove_member(&mut self, key: &K, handle: OrderHandle) {
        let remove_key = if let Some(handles) = self.get_mut(key) {
            handles.retain(|candidate| *candidate != handle);
            handles.is_empty()
        } else {
            false
        };
        if remove_key {
            self.remove(key);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{IndexOrderState, LifecycleIndexes};
    use quantbt_domain::ids::{ExternalOrderId, OrderHandle, SymbolId};
    use std::collections::HashMap;

    fn state(sequence: u64, active: bool) -> IndexOrderState {
        IndexOrderState {
            symbol: SymbolId(0),
            active,
            waiting_parent: !active,
            sequence,
            parent_id: ExternalOrderId(1),
            oco_id: 9,
            expire_bar: Some(3),
        }
    }

    #[test]
    fn lifecycle_indexes_visit_only_related_handles() {
        let first = OrderHandle {
            slot: 0,
            generation: 0,
        };
        let second = OrderHandle {
            slot: 1,
            generation: 0,
        };
        let mut indexes = LifecycleIndexes::with_symbols(1);
        indexes.insert(first, state(3, true));
        indexes.insert(second, state(4, false));
        assert_eq!(indexes.active_priority_handles(), vec![first]);
        assert_eq!(indexes.children_of(ExternalOrderId(1)), vec![first, second]);
        assert_eq!(indexes.due_expiry_handles(2), Vec::<OrderHandle>::new());
        assert_eq!(indexes.due_expiry_handles(3), vec![first, second]);
        let states = HashMap::from([(first, state(3, true)), (second, state(4, false))]);
        assert!(
            indexes
                .validate(|handle| states.get(&handle).copied())
                .is_ok()
        );
        assert!(
            indexes
                .validate_complete(states.iter().map(|(&handle, &state)| (handle, state)))
                .is_ok()
        );
    }

    #[test]
    fn complete_validator_detects_missing_candidate_and_priority_mutation() {
        let first = OrderHandle {
            slot: 0,
            generation: 0,
        };
        let second = OrderHandle {
            slot: 1,
            generation: 0,
        };
        let mut indexes = LifecycleIndexes::with_symbols(1);
        indexes.insert(first, state(3, true));
        indexes.insert(second, state(4, true));
        let expected = HashMap::from([(first, state(3, true)), (second, state(4, true))]);
        assert!(
            indexes
                .validate_complete(expected.iter().map(|(&handle, &state)| (handle, state)))
                .is_ok()
        );

        // This is the failure a broad-phase optimization must never hide:
        // the arena still has an eligible order but the matcher candidate
        // index no longer contains it.
        indexes.active_by_sequence.remove(&3);
        assert_eq!(
            indexes.validate_complete(expected.iter().map(|(&handle, &state)| (handle, state))),
            Err("active priority index disagrees with full arena scan")
        );
    }
}
