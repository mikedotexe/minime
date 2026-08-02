use serde::{Deserialize, Serialize};

use crate::self_control_wire::{SelfControlFamilyV2, SelfControlValuesV2};

use super::{
    canonical_sha256, identifiers_are_unique, valid_identifier, valid_sha256, valid_string_list,
    OWNER_CANARY_MAX_DURATION_SECS_V2, OWNER_CANARY_MIN_DURATION_SECS_V2,
    OWNER_CANARY_PLAN_SCHEMA_V2,
};

const OWNER_CANARY_MAX_CONTROLS_V2: usize = 10;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OwnerCanaryControlV2 {
    pub family: SelfControlFamilyV2,
    pub exact_values: SelfControlValuesV2,
    pub exact_values_sha256: String,
    pub expected_revision: u64,
}

impl OwnerCanaryControlV2 {
    #[must_use]
    pub fn new(
        family: SelfControlFamilyV2,
        exact_values: SelfControlValuesV2,
        expected_revision: u64,
    ) -> Self {
        let exact_values_sha256 = canonical_sha256(&exact_values);
        Self {
            family,
            exact_values,
            exact_values_sha256,
            expected_revision,
        }
    }

    pub(super) fn is_well_formed(&self) -> bool {
        self.exact_values.field_count() > 0
            && self.exact_values.is_well_formed()
            && self.exact_values.matches_family(self.family)
            && !self.exact_values.requires_one_shot()
            && !self.exact_values.includes_shared_coupling()
            && self.exact_values_sha256 == canonical_sha256(&self.exact_values)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OwnerCanaryRollbackPlanV2 {
    #[serde(default)]
    pub baseline_receipt_ids: Vec<String>,
    pub rollback_on_setup_failure: bool,
    pub rollback_on_evidence_failure: bool,
    pub rollback_on_expiry: bool,
    pub rollback_on_withdrawal: bool,
    pub rollback_on_silence: bool,
    pub post_rollback_verification_required: bool,
    pub promotion_requires_fresh_owner_intent: bool,
}

impl OwnerCanaryRollbackPlanV2 {
    #[must_use]
    pub fn strict(baseline_receipt_ids: Vec<String>) -> Self {
        Self {
            baseline_receipt_ids,
            rollback_on_setup_failure: true,
            rollback_on_evidence_failure: true,
            rollback_on_expiry: true,
            rollback_on_withdrawal: true,
            rollback_on_silence: true,
            post_rollback_verification_required: true,
            promotion_requires_fresh_owner_intent: true,
        }
    }

    fn is_well_formed(&self) -> bool {
        valid_string_list(&self.baseline_receipt_ids)
            && identifiers_are_unique(&self.baseline_receipt_ids)
            && self.rollback_on_setup_failure
            && self.rollback_on_evidence_failure
            && self.rollback_on_expiry
            && self.rollback_on_withdrawal
            && self.rollback_on_silence
            && self.post_rollback_verification_required
            && self.promotion_requires_fresh_owner_intent
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OwnerCanaryPlanV2 {
    pub schema: String,
    pub canary_plan_id: String,
    pub inquiry_id: String,
    pub inquiry_receipt_id: String,
    pub inquiry_receipt_sha256: String,
    pub owner_being: String,
    pub source_attestation_id: String,
    pub idempotency_key: String,
    pub duration_secs: u64,
    pub controls: Vec<OwnerCanaryControlV2>,
    pub controls_sha256: String,
    pub apply_atomically: bool,
    pub telemetry_selected_values: bool,
    pub operator_substituted_values: bool,
    pub safety_may_only_hold_or_revert: bool,
    pub felt_review_required: bool,
    pub rollback: OwnerCanaryRollbackPlanV2,
    pub created_at_unix_ms: u64,
    pub command_expires_at_unix_ms: u64,
}

impl OwnerCanaryPlanV2 {
    #[must_use]
    pub fn is_well_formed(&self) -> bool {
        let mut families = Vec::new();
        self.schema == OWNER_CANARY_PLAN_SCHEMA_V2
            && valid_identifier(&self.canary_plan_id)
            && valid_identifier(&self.inquiry_id)
            && valid_identifier(&self.inquiry_receipt_id)
            && valid_sha256(&self.inquiry_receipt_sha256)
            && valid_identifier(&self.owner_being)
            && valid_identifier(&self.source_attestation_id)
            && valid_identifier(&self.idempotency_key)
            && (OWNER_CANARY_MIN_DURATION_SECS_V2..=OWNER_CANARY_MAX_DURATION_SECS_V2)
                .contains(&self.duration_secs)
            && !self.controls.is_empty()
            && self.controls.len() <= OWNER_CANARY_MAX_CONTROLS_V2
            && self.controls.iter().all(|control| {
                let unique = !families.contains(&control.family);
                if unique {
                    families.push(control.family);
                }
                control.is_well_formed() && unique
            })
            && self.controls_sha256 == canonical_sha256(&self.controls)
            && self.apply_atomically
            && !self.telemetry_selected_values
            && !self.operator_substituted_values
            && self.safety_may_only_hold_or_revert
            && !self.felt_review_required
            && self.rollback.is_well_formed()
            && self.command_expires_at_unix_ms > self.created_at_unix_ms
    }
}
