use serde::Serialize;

const ACTIVE_EPSILON: f32 = 1.0e-6;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SensoryInterferenceError {
    EmptyInput,
    ShapeMismatch,
    NonFiniteInput,
}

/// Read-only comparison of two candidate sensory vectors before either one is
/// admitted to the live bus.
///
/// The review distinguishes aligned reinforcement, distinct non-cancelling
/// input, and opposition/cancellation. It neither merges the candidates nor
/// chooses which one should be admitted.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SensoryInterferenceReviewV1 {
    pub schema_version: u8,
    pub policy: &'static str,
    pub dimension_count: usize,
    pub left_rms: f32,
    pub right_rms: f32,
    pub combined_rms: f32,
    pub conflict_rms: f32,
    pub cosine_alignment: f32,
    pub mean_abs_delta: f32,
    pub jointly_active_dimensions: usize,
    pub opposed_dimensions: usize,
    pub opposed_fraction: f32,
    pub cancellation_ratio: f32,
    pub classification: &'static str,
    pub suggested_route: &'static str,
    pub live_runtime_mutation: bool,
    pub live_control_write: bool,
    pub authority: &'static str,
}

pub fn review_sensory_interference_v1(
    left: &[f32],
    right: &[f32],
) -> Result<SensoryInterferenceReviewV1, SensoryInterferenceError> {
    if left.is_empty() || right.is_empty() {
        return Err(SensoryInterferenceError::EmptyInput);
    }
    if left.len() != right.len() {
        return Err(SensoryInterferenceError::ShapeMismatch);
    }
    if !left.iter().chain(right).all(|value| value.is_finite()) {
        return Err(SensoryInterferenceError::NonFiniteInput);
    }

    let mut left_sum_sq = 0.0f32;
    let mut right_sum_sq = 0.0f32;
    let mut combined_sum_sq = 0.0f32;
    let mut conflict_sum_sq = 0.0f32;
    let mut dot = 0.0f32;
    let mut abs_delta_sum = 0.0f32;
    let mut jointly_active_dimensions = 0usize;
    let mut opposed_dimensions = 0usize;

    for (&left_value, &right_value) in left.iter().zip(right) {
        left_sum_sq += left_value * left_value;
        right_sum_sq += right_value * right_value;
        dot += left_value * right_value;

        let combined = (left_value + right_value) * 0.5;
        let conflict = (left_value - right_value) * 0.5;
        combined_sum_sq += combined * combined;
        conflict_sum_sq += conflict * conflict;
        abs_delta_sum += (left_value - right_value).abs();

        if left_value.abs() > ACTIVE_EPSILON && right_value.abs() > ACTIVE_EPSILON {
            jointly_active_dimensions += 1;
            if left_value.is_sign_positive() != right_value.is_sign_positive() {
                opposed_dimensions += 1;
            }
        }
    }

    let dimension_count = left.len();
    let dimensions = dimension_count as f32;
    let left_rms = (left_sum_sq / dimensions).sqrt();
    let right_rms = (right_sum_sq / dimensions).sqrt();
    let combined_rms = (combined_sum_sq / dimensions).sqrt();
    let conflict_rms = (conflict_sum_sq / dimensions).sqrt();
    let mean_abs_delta = abs_delta_sum / dimensions;
    let norm_product = left_sum_sq.sqrt() * right_sum_sq.sqrt();
    let cosine_alignment = if norm_product > ACTIVE_EPSILON {
        (dot / norm_product).clamp(-1.0, 1.0)
    } else {
        0.0
    };
    let opposed_fraction = if jointly_active_dimensions == 0 {
        0.0
    } else {
        opposed_dimensions as f32 / jointly_active_dimensions as f32
    };
    let reference_rms = (left_rms + right_rms) * 0.5;
    let cancellation_ratio = if reference_rms > ACTIVE_EPSILON {
        (1.0 - combined_rms / reference_rms).clamp(0.0, 1.0)
    } else {
        0.0
    };

    let classification = if reference_rms <= ACTIVE_EPSILON {
        "no_signal"
    } else if cancellation_ratio >= 0.70 && opposed_fraction >= 0.50 {
        "strong_opposition_cancellation"
    } else if cancellation_ratio >= 0.35 || cosine_alignment <= -0.25 {
        "mixed_opposition"
    } else if cosine_alignment >= 0.75 && cancellation_ratio <= 0.15 {
        "aligned_reinforcement"
    } else {
        "distinct_non_cancelling"
    };
    let suggested_route = match classification {
        "strong_opposition_cancellation" => {
            "retain_both_candidates_and_compare_before_any_live_merge"
        }
        "mixed_opposition" => "inspect_pairwise_difference_in_offline_replay",
        "aligned_reinforcement" => "no_pairwise_collision_signal",
        "distinct_non_cancelling" => "retain_separate_candidates_for_downstream_replay",
        _ => "collect_nonzero_candidate_pair",
    };

    Ok(SensoryInterferenceReviewV1 {
        schema_version: 1,
        policy: "sensory_interference_review_v1",
        dimension_count,
        left_rms,
        right_rms,
        combined_rms,
        conflict_rms,
        cosine_alignment,
        mean_abs_delta,
        jointly_active_dimensions,
        opposed_dimensions,
        opposed_fraction,
        cancellation_ratio,
        classification,
        suggested_route,
        live_runtime_mutation: false,
        live_control_write: false,
        authority: "offline_pair_review_not_sensory_admission_shadow_or_regulator_authority",
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opposite_candidates_report_cancellation_without_merging_inputs() {
        let left = vec![0.8; 66];
        let right = vec![-0.8; 66];
        let left_before = left.clone();
        let right_before = right.clone();

        let review =
            review_sensory_interference_v1(&left, &right).expect("finite equal-width pair");

        assert_eq!(review.classification, "strong_opposition_cancellation");
        assert_eq!(review.dimension_count, 66);
        assert_eq!(review.jointly_active_dimensions, 66);
        assert_eq!(review.opposed_dimensions, 66);
        assert!((review.opposed_fraction - 1.0).abs() < 1.0e-6);
        assert!((review.cancellation_ratio - 1.0).abs() < 1.0e-6);
        assert!(review.combined_rms < 1.0e-6);
        assert!(review.conflict_rms > 0.79);
        assert!(!review.live_runtime_mutation);
        assert!(!review.live_control_write);
        assert_eq!(left, left_before);
        assert_eq!(right, right_before);
    }

    #[test]
    fn aligned_candidates_report_reinforcement() {
        let left = vec![0.35; 48];
        let right = left.clone();

        let review =
            review_sensory_interference_v1(&left, &right).expect("finite equal-width pair");

        assert_eq!(review.classification, "aligned_reinforcement");
        assert!((review.cosine_alignment - 1.0).abs() < 1.0e-6);
        assert!(review.cancellation_ratio < 1.0e-6);
        assert!(review.conflict_rms < 1.0e-6);
        assert_eq!(review.opposed_dimensions, 0);
    }

    #[test]
    fn orthogonal_candidates_remain_distinct_instead_of_becoming_collision() {
        let mut left = vec![0.0; 48];
        let mut right = vec![0.0; 48];
        left[..24].fill(0.5);
        right[24..].fill(0.5);

        let review =
            review_sensory_interference_v1(&left, &right).expect("finite equal-width pair");

        assert_eq!(review.classification, "distinct_non_cancelling");
        assert_eq!(review.jointly_active_dimensions, 0);
        assert_eq!(review.opposed_dimensions, 0);
        assert!(review.cosine_alignment.abs() < 1.0e-6);
    }

    #[test]
    fn empty_mismatched_and_non_finite_pairs_fail_closed() {
        assert_eq!(
            review_sensory_interference_v1(&[], &[]),
            Err(SensoryInterferenceError::EmptyInput)
        );
        assert_eq!(
            review_sensory_interference_v1(&[0.0], &[0.0, 0.0]),
            Err(SensoryInterferenceError::ShapeMismatch)
        );
        assert_eq!(
            review_sensory_interference_v1(&[f32::NAN], &[0.0]),
            Err(SensoryInterferenceError::NonFiniteInput)
        );
    }
}
