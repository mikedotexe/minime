use std::collections::HashSet;

use serde_json::Value;

use crate::owner_inquiry_wire::{
    owner_inquiry_fixed_analysis_set_v1, OwnerInquiryAnalysisV1, OwnerInquiryCancellationV1,
    VolitionBudgetV1,
};

use super::{
    InquiryAnalysisPlanEntryV2, InquiryAnalysisReceiptV2, InquiryCoverageModeV2,
    InquiryCoverageProofV2, InquiryObservationV2, SemanticStrandV2,
};

const MAX_TEXT_BYTES_V2: usize = 4_096;
const MAX_JSON_BYTES_V2: usize = 65_536;
const MAX_LIST_ENTRIES_V2: usize = 64;

pub(super) fn expected_coverage(analysis: OwnerInquiryAnalysisV1) -> InquiryCoverageModeV2 {
    match analysis {
        OwnerInquiryAnalysisV1::ViscousPersistenceSourceSeparation => {
            InquiryCoverageModeV2::PerStrand
        }
        OwnerInquiryAnalysisV1::CodecFidelity => InquiryCoverageModeV2::PerStrandAndAllPairs,
        OwnerInquiryAnalysisV1::SensoryInterferenceAllPairs => InquiryCoverageModeV2::AllPairs,
    }
}

pub(super) fn analysis_plan_is_well_formed(plan: &[InquiryAnalysisPlanEntryV2]) -> bool {
    plan.len() == owner_inquiry_fixed_analysis_set_v1().len()
        && plan
            .iter()
            .map(|entry| entry.analysis)
            .eq(owner_inquiry_fixed_analysis_set_v1())
        && plan.iter().all(InquiryAnalysisPlanEntryV2::is_well_formed)
}

pub(super) fn inquiry_budget_is_offline(budget: &VolitionBudgetV1) -> bool {
    budget.is_nonzero_when_present()
        && budget.compute_millis.is_some()
        && budget.storage_bytes.is_some()
        && budget.network_bytes.is_none()
        && budget.cost_microunits.is_none()
        && budget.action_count.is_none_or(|count| count == 1)
}

pub(super) fn cancellation_is_well_formed(cancellation: &OwnerInquiryCancellationV1) -> bool {
    if cancellation.requested {
        cancellation.requested_at_unix_ms.is_some()
            && cancellation
                .reason
                .as_deref()
                .is_some_and(|reason| !reason.trim().is_empty() && valid_bounded_text(reason))
    } else {
        cancellation.requested_at_unix_ms.is_none() && cancellation.reason.is_none()
    }
}

pub(super) fn strands_are_distinct_v2(strands: &[SemanticStrandV2]) -> bool {
    let mut ids = HashSet::new();
    let mut content_hashes = HashSet::new();
    let mut intervals = HashSet::new();
    strands.iter().all(|strand| {
        ids.insert(strand.strand_id.as_str())
            && content_hashes.insert(strand.content_sha256.as_str())
            && intervals.insert((strand.response_start_byte, strand.response_end_byte))
    })
}

pub(super) fn identifiers_are_unique(values: &[String]) -> bool {
    let mut seen = HashSet::new();
    values.iter().all(|value| seen.insert(value.as_str()))
}

pub(super) fn expected_pair_keys(strand_ids: &[String]) -> Vec<String> {
    let mut pair_keys = Vec::new();
    for (left_index, left) in strand_ids.iter().enumerate() {
        for right in strand_ids.iter().skip(left_index.saturating_add(1)) {
            pair_keys.push(format!("{left}::{right}"));
        }
    }
    pair_keys.sort();
    pair_keys
}

pub(super) fn analysis_coverage_matches(
    receipt: &InquiryAnalysisReceiptV2,
    mode: InquiryCoverageModeV2,
    coverage: &InquiryCoverageProofV2,
) -> bool {
    let strands_match = receipt.covered_strand_ids == coverage.expected_strand_ids;
    let pairs_match = receipt.covered_pair_keys == coverage.expected_pair_keys;
    match mode {
        InquiryCoverageModeV2::PerStrand => strands_match && receipt.covered_pair_keys.is_empty(),
        InquiryCoverageModeV2::AllPairs => receipt.covered_strand_ids.is_empty() && pairs_match,
        InquiryCoverageModeV2::PerStrandAndAllPairs => strands_match && pairs_match,
    }
}

pub(super) fn observations_form_chain(
    observations: &[InquiryObservationV2],
    inquiry_id: &str,
) -> bool {
    let mut previous_sha256: Option<&str> = None;
    let mut ids = HashSet::new();
    for (index, observation) in observations.iter().enumerate() {
        let Ok(sequence) = u64::try_from(index) else {
            return false;
        };
        if observation.sequence != sequence
            || observation.previous_observation_sha256.as_deref() != previous_sha256
            || !observation.is_well_formed_for(inquiry_id)
            || !ids.insert(observation.observation_id.as_str())
        {
            return false;
        }
        previous_sha256 = Some(&observation.event_sha256);
    }
    true
}

pub(super) fn valid_identifier(value: &str) -> bool {
    let value = value.trim();
    !value.is_empty() && value.len() <= 256
}

pub(super) fn valid_bounded_text(value: &str) -> bool {
    value.len() <= MAX_TEXT_BYTES_V2
}

pub(super) fn valid_string_list(values: &[String]) -> bool {
    values.len() <= MAX_LIST_ENTRIES_V2 && values.iter().all(|value| valid_bounded_text(value))
}

pub(super) fn valid_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

pub(super) fn finite_bounded_json(value: &Value) -> bool {
    value_is_finite(value)
        && serde_json::to_vec(value).is_ok_and(|encoded| encoded.len() <= MAX_JSON_BYTES_V2)
}

fn value_is_finite(value: &Value) -> bool {
    match value {
        Value::Array(values) => values.iter().all(value_is_finite),
        Value::Object(fields) => fields.values().all(value_is_finite),
        Value::Number(number) => number.as_f64().is_none_or(f64::is_finite),
        _ => true,
    }
}
