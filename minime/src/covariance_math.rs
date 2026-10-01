//! Production covariance updates, shared by the runtime and isolated qualification.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CovarianceUpdateOutcome {
    Skipped,
    Modified,
    ResetRequired,
}

pub fn rank1_update_inplace_matrix(
    a: &mut [f32],
    z: &[f32],
    n: usize,
    keep: f32,
    trace_target: f32,
) -> CovarianceUpdateOutcome {
    assert_eq!(a.len(), n * n);
    assert_eq!(z.len(), n);

    if z.iter().any(|v| !v.is_finite()) {
        return CovarianceUpdateOutcome::Skipped;
    }

    if !a.iter().all(|v| v.is_finite()) {
        return CovarianceUpdateOutcome::ResetRequired;
    }

    let keep = keep.clamp(0.0, 0.9999);
    let gain = 1.0 - keep;
    for (i, &zi) in z.iter().enumerate() {
        for (j, &zj) in z.iter().enumerate() {
            let idx = i * n + j;
            a[idx] = keep * a[idx] + gain * zi * zj;
        }
    }

    let target_trace = trace_target.max(1.0);
    let trace: f32 = (0..n).map(|i| a[i * n + i]).sum();
    if !trace.is_finite() || trace <= 1e-6 {
        return CovarianceUpdateOutcome::ResetRequired;
    }

    let scale = (target_trace / trace).clamp(0.0, 2.0);
    for val in a.iter_mut() {
        *val *= scale;
    }

    if a.iter().all(|v| v.is_finite()) {
        CovarianceUpdateOutcome::Modified
    } else {
        CovarianceUpdateOutcome::ResetRequired
    }
}

pub fn decay_covariance_inplace_matrix(
    a: &mut [f32],
    n: usize,
    keep: f32,
    trace_target: f32,
) -> bool {
    assert_eq!(a.len(), n * n);

    let keep = keep.clamp(0.0, 0.9999);
    if !a.iter().all(|v| v.is_finite()) {
        return false;
    }
    for val in a.iter_mut() {
        *val *= keep;
    }
    let trace: f32 = (0..n).map(|i| a[i * n + i]).sum();
    if !trace.is_finite() || trace <= 1e-6 {
        return false;
    }

    let target_trace = trace_target.max(1.0);
    let scale = (target_trace / trace).min(1.0);
    for val in a.iter_mut() {
        *val *= scale;
    }

    a.iter().all(|v| v.is_finite())
}

pub fn reset_covariance_inplace(a: &mut [f32], n: usize) {
    assert_eq!(a.len(), n * n);
    a.fill(0.0);
    for i in 0..n {
        a[i * n + i] = 1.0;
    }
}
