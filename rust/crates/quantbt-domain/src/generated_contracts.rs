//! Generated from contracts/native_event_contract_registry.json; do not edit.
#![allow(dead_code)]

pub const CONTRACT_REGISTRY_FINGERPRINT: &str =
    "601d639f1c398ac81f3c8231c30d067372c80e71ae4e5f097182f00c5c91f05d";
pub const CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE: i64 = 2;
pub const CONTRACT_ID_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE: &str = "event_lifecycle_v2_next_bar_close";
pub const CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN: i64 = 3;
pub const CONTRACT_ID_EVENT_LIFECYCLE_V3_NEXT_OPEN: &str = "event_lifecycle_v3_next_open";
pub const COMMAND_OUTCOME_ACCEPTED: i64 = 0;
pub const COMMAND_OUTCOME_REJECTED: i64 = 1;
pub const COMMAND_OUTCOME_NOOP: i64 = 2;
pub const COMMAND_OUTCOME_OUTSIDE_TAPE: i64 = 3;
pub const ORDER_STATUS_CREATED: i64 = 0;
pub const ORDER_STATUS_WAITING_PARENT: i64 = 1;
pub const ORDER_STATUS_ACTIVE: i64 = 2;
pub const ORDER_STATUS_PARTIALLY_FILLED: i64 = 3;
pub const ORDER_STATUS_FILLED: i64 = 4;
pub const ORDER_STATUS_CANCELED: i64 = 5;
pub const ORDER_STATUS_EXPIRED: i64 = 6;
pub const ORDER_STATUS_REJECTED: i64 = 7;
pub const ORDER_STATUS_LIQUIDATED: i64 = 8;
pub const LIFECYCLE_EVENT_KIND_PLACE: i64 = 0;
pub const LIFECYCLE_EVENT_KIND_ACTIVATE: i64 = 1;
pub const LIFECYCLE_EVENT_KIND_AMEND: i64 = 2;
pub const LIFECYCLE_EVENT_KIND_REPLACE: i64 = 3;
pub const LIFECYCLE_EVENT_KIND_CANCEL: i64 = 4;
pub const LIFECYCLE_EVENT_KIND_EXPIRE: i64 = 5;
pub const LIFECYCLE_EVENT_KIND_FILL: i64 = 6;
pub const LIFECYCLE_EVENT_KIND_REJECT: i64 = 7;
pub const LIFECYCLE_EVENT_KIND_LIQUIDATE: i64 = 8;
pub const LIFECYCLE_EVENT_KIND_PACKAGE_COMMIT: i64 = 9;
pub const LIFECYCLE_EVENT_KIND_PACKAGE_ABORT: i64 = 10;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LifecycleTransition {
    pub action: &'static str,
    pub from_status: &'static str,
    pub to_status: &'static str,
    pub outcome: i64,
    pub reason: &'static str,
}

pub const LIFECYCLE_TRANSITIONS: &[LifecycleTransition] = &[
    LifecycleTransition {
        action: "PLACE",
        from_status: "NONE",
        to_status: "ACTIVE",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "PLACED_ACTIVE",
    },
    LifecycleTransition {
        action: "PLACE",
        from_status: "NONE",
        to_status: "WAITING_PARENT",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "PLACED_WAITING_PARENT",
    },
    LifecycleTransition {
        action: "PLACE",
        from_status: "ACTIVE",
        to_status: "ACTIVE",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "DUPLICATE_ORDER_ID",
    },
    LifecycleTransition {
        action: "ACTIVATE",
        from_status: "WAITING_PARENT",
        to_status: "ACTIVE",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "PARENT_FILLED",
    },
    LifecycleTransition {
        action: "AMEND",
        from_status: "ACTIVE",
        to_status: "ACTIVE",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "AMENDED",
    },
    LifecycleTransition {
        action: "AMEND",
        from_status: "WAITING_PARENT",
        to_status: "WAITING_PARENT",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "AMENDED",
    },
    LifecycleTransition {
        action: "REPLACE",
        from_status: "ACTIVE",
        to_status: "CANCELED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "REPLACED",
    },
    LifecycleTransition {
        action: "REPLACE",
        from_status: "WAITING_PARENT",
        to_status: "CANCELED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "REPLACED",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "ACTIVE",
        to_status: "CANCELED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "CANCELED",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "WAITING_PARENT",
        to_status: "CANCELED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "CANCELED",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "PARTIALLY_FILLED",
        to_status: "CANCELED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "CANCELED_REMAINDER",
    },
    LifecycleTransition {
        action: "EXPIRE",
        from_status: "ACTIVE",
        to_status: "EXPIRED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "TIME_IN_FORCE_EXPIRED",
    },
    LifecycleTransition {
        action: "EXPIRE",
        from_status: "WAITING_PARENT",
        to_status: "EXPIRED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "TIME_IN_FORCE_EXPIRED",
    },
    LifecycleTransition {
        action: "FILL",
        from_status: "ACTIVE",
        to_status: "FILLED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "FULL_FILL",
    },
    LifecycleTransition {
        action: "FILL",
        from_status: "ACTIVE",
        to_status: "PARTIALLY_FILLED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "PARTIAL_FILL",
    },
    LifecycleTransition {
        action: "FILL",
        from_status: "PARTIALLY_FILLED",
        to_status: "FILLED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "FULL_FILL",
    },
    LifecycleTransition {
        action: "FILL",
        from_status: "PARTIALLY_FILLED",
        to_status: "PARTIALLY_FILLED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "PARTIAL_FILL",
    },
    LifecycleTransition {
        action: "REJECT",
        from_status: "CREATED",
        to_status: "REJECTED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "VALIDATION_REJECTED",
    },
    LifecycleTransition {
        action: "REJECT",
        from_status: "ACTIVE",
        to_status: "REJECTED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "EXECUTION_REJECTED",
    },
    LifecycleTransition {
        action: "REJECT",
        from_status: "WAITING_PARENT",
        to_status: "REJECTED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "RELATIONSHIP_REJECTED",
    },
    LifecycleTransition {
        action: "LIQUIDATE",
        from_status: "ACTIVE",
        to_status: "LIQUIDATED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "ACCOUNT_LIQUIDATED",
    },
    LifecycleTransition {
        action: "LIQUIDATE",
        from_status: "PARTIALLY_FILLED",
        to_status: "LIQUIDATED",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "ACCOUNT_LIQUIDATED",
    },
    LifecycleTransition {
        action: "PACKAGE_COMMIT",
        from_status: "NONE",
        to_status: "NONE",
        outcome: COMMAND_OUTCOME_ACCEPTED,
        reason: "PACKAGE_COMMITTED",
    },
    LifecycleTransition {
        action: "PACKAGE_ABORT",
        from_status: "NONE",
        to_status: "NONE",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "PACKAGE_ABORTED",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "FILLED",
        to_status: "FILLED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "ORDER_TERMINAL",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "CANCELED",
        to_status: "CANCELED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "ORDER_TERMINAL",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "EXPIRED",
        to_status: "EXPIRED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "ORDER_TERMINAL",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "REJECTED",
        to_status: "REJECTED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "ORDER_TERMINAL",
    },
    LifecycleTransition {
        action: "CANCEL",
        from_status: "LIQUIDATED",
        to_status: "LIQUIDATED",
        outcome: COMMAND_OUTCOME_REJECTED,
        reason: "ORDER_TERMINAL",
    },
];

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn generated_contract_ids_are_stable() {
        assert_eq!(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, 2);
        assert_eq!(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN, 3);
        assert_eq!(CONTRACT_REGISTRY_FINGERPRINT.len(), 64);
    }

    #[test]
    fn lifecycle_transition_keys_are_unique() {
        let mut keys = HashSet::new();
        for item in LIFECYCLE_TRANSITIONS {
            assert!(keys.insert((item.action, item.from_status, item.to_status)));
        }
        assert!(LIFECYCLE_TRANSITIONS.len() >= 25);
    }
}
