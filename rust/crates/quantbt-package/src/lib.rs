//! Multi-leg package execution contract.
//!
//! Phase 53A only establishes typed package ownership. Reserve/commit/abort
//! semantics remain deliberately unimplemented until Phase 53B so no partial
//! package behavior is accidentally advertised through the public API.

use quantbt_domain::ids::ExternalOrderId;

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct PackageId(pub u64);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackagePolicy {
    Sequential,
    BestEffort,
    AtomicBarSimulation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PackageLegRef {
    pub order_id: ExternalOrderId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PackagePlan {
    pub id: PackageId,
    pub policy: PackagePolicy,
    pub legs: Box<[PackageLegRef]>,
}

impl PackagePlan {
    #[must_use]
    pub fn is_multi_leg(&self) -> bool {
        self.legs.len() > 1
    }
}
