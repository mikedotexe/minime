#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CovarianceUpdateOutcome {
    Skipped,
    Modified,
    ResetRequired,
}

fn rank1_update_inplace_matrix(
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
    for i in 0..n {
        let zi = z[i];
        for j in 0..n {
            let idx = i * n + j;
            a[idx] = keep * a[idx] + gain * zi * z[j];
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

fn decay_covariance_inplace_matrix(a: &mut [f32], n: usize, keep: f32, trace_target: f32) -> bool {
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

fn reset_covariance_inplace(a: &mut [f32], n: usize) {
    assert_eq!(a.len(), n * n);
    a.fill(0.0);
    for i in 0..n {
        a[i * n + i] = 1.0;
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct ActiveModeTelemetry {
    count: usize,
    energy_ratio: f32,
}

fn compute_active_mode_telemetry(
    eigenvalues: &[f32],
    available_modes: usize,
) -> ActiveModeTelemetry {
    let max_available = available_modes.min(eigenvalues.len());
    if max_available == 0 {
        return ActiveModeTelemetry {
            count: 0,
            energy_ratio: 0.0,
        };
    }

    let max_active = max_available.min(6);
    let min_active = max_available.min(2);
    let total_energy: f32 = eigenvalues
        .iter()
        .take(max_available)
        .map(|value| value.max(0.0))
        .sum();

    if total_energy <= 0.0 {
        return ActiveModeTelemetry {
            count: min_active,
            energy_ratio: 0.0,
        };
    }

    let mut cumulative = 0.0_f32;
    let mut needed = 1_usize;
    for ev in eigenvalues.iter().take(max_available) {
        cumulative += ev.max(0.0);
        if cumulative / total_energy >= 0.90 {
            break;
        }
        needed = needed.saturating_add(1);
    }

    let count = needed.clamp(min_active, max_active);
    let selected_energy: f32 = eigenvalues
        .iter()
        .take(count)
        .map(|value| value.max(0.0))
        .sum();

    ActiveModeTelemetry {
        count,
        energy_ratio: (selected_energy / total_energy).clamp(0.0, 1.0),
    }
}

fn capture_top_eigenvectors(y: &[f32], n: usize, count: usize) -> Vec<Vec<f32>> {
    (0..count)
        .filter_map(|mode| {
            let start = mode * n;
            let end = start + n;
            (end <= y.len()).then(|| y[start..end].to_vec())
        })
        .collect()
}

fn vector_norm(values: &[f32]) -> f32 {
    values.iter().map(|value| value * value).sum::<f32>().sqrt()
}

fn cosine_similarity(lhs: &[f32], rhs: &[f32]) -> Option<f32> {
    if lhs.len() != rhs.len() || lhs.is_empty() {
        return None;
    }
    let dot = lhs
        .iter()
        .zip(rhs.iter())
        .map(|(left, right)| left * right)
        .sum::<f32>();
    let denom = vector_norm(lhs) * vector_norm(rhs);
    if denom > 1.0e-8 && dot.is_finite() {
        Some((dot / denom).clamp(-1.0, 1.0))
    } else {
        None
    }
}

fn top_eigenvector_components(vector: &[f32], limit: usize) -> Vec<serde_json::Value> {
    let mut components = vector
        .iter()
        .enumerate()
        .filter(|(_, value)| value.is_finite())
        .map(|(index, value)| (index, *value, value.abs()))
        .collect::<Vec<_>>();
    components.sort_unstable_by(|left, right| {
        right
            .2
            .partial_cmp(&left.2)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    components
        .iter()
        .take(limit)
        .map(|(index, value, abs_value)| {
            serde_json::json!({
                "index": index,
                "value": value,
                "abs": abs_value,
            })
        })
        .collect()
}

fn concentration_top_k(vector: &[f32], top_k: usize) -> f32 {
    let norm_sq = vector.iter().map(|value| value * value).sum::<f32>();
    if norm_sq <= 1.0e-8 || !norm_sq.is_finite() {
        return 0.0;
    }
    let mut squares = vector
        .iter()
        .filter(|value| value.is_finite())
        .map(|value| value * value)
        .collect::<Vec<_>>();
    squares.sort_unstable_by(|left, right| {
        right.partial_cmp(left).unwrap_or(std::cmp::Ordering::Equal)
    });
    (squares.iter().take(top_k).sum::<f32>() / norm_sq).clamp(0.0, 1.0)
}

fn compute_eigenvector_field(
    eigenvalues: &[f32],
    y: &[f32],
    n: usize,
    k: usize,
    previous_modes: &[Vec<f32>],
) -> serde_json::Value {
    let mode_count = k.min(eigenvalues.len()).min(4);
    let modes = capture_top_eigenvectors(y, n, mode_count);
    let total_energy = eigenvalues
        .iter()
        .take(mode_count)
        .map(|value| value.abs())
        .sum::<f32>()
        .max(1.0e-8);
    let mode_payload = modes
        .iter()
        .enumerate()
        .map(|(index, vector)| {
            let previous_overlap = previous_modes
                .get(index)
                .and_then(|previous| cosine_similarity(vector, previous));
            let orientation_delta = previous_overlap
                .map(|overlap| 1.0 - overlap.abs())
                .unwrap_or(0.0);
            serde_json::json!({
                "index": index + 1,
                "eigenvalue": eigenvalues.get(index).copied().unwrap_or_default(),
                "energy_share": eigenvalues
                    .get(index)
                    .map(|value| (value.abs() / total_energy).clamp(0.0, 1.0))
                    .unwrap_or(0.0),
                "norm": vector_norm(vector),
                "concentration_top4": concentration_top_k(vector, 4),
                "top_components": top_eigenvector_components(vector, 8),
                "overlap_with_previous": previous_overlap,
                "orientation_delta": orientation_delta,
            })
        })
        .collect::<Vec<_>>();

    let mut pairwise = Vec::new();
    for left in 0..modes.len() {
        for right in (left + 1)..modes.len() {
            if let Some(cosine) = cosine_similarity(&modes[left], &modes[right]) {
                pairwise.push(serde_json::json!({
                    "left": left + 1,
                    "right": right + 1,
                    "cosine": cosine,
                    "abs_cosine": cosine.abs(),
                }));
            }
        }
    }
    let mean_orientation_delta = if mode_payload.is_empty() {
        0.0
    } else {
        mode_payload
            .iter()
            .filter_map(|mode| {
                mode.get("orientation_delta")
                    .and_then(|value| value.as_f64())
            })
            .map(|value| value as f32)
            .sum::<f32>()
            / mode_payload.len() as f32
    };
    let max_pairwise_overlap = pairwise
        .iter()
        .filter_map(|item| item.get("abs_cosine").and_then(|value| value.as_f64()))
        .fold(0.0_f64, f64::max) as f32;

    serde_json::json!({
        "policy": "eigenvector_field_v1",
        "direct_eigenvectors_available": !modes.is_empty(),
        "raw_vectors_exported": false,
        "export_note": "Top component landmarks and overlaps are computed directly from Minime's live eigenvectors; full raw vectors are intentionally not dumped into telemetry.",
        "reservoir_dim": n,
        "mode_count": modes.len(),
        "component_limit": 8,
        "modes": mode_payload,
        "pairwise_overlaps": pairwise,
        "summary": {
            "mean_orientation_delta": mean_orientation_delta,
            "max_pairwise_overlap": max_pairwise_overlap,
            "previous_overlap_available": !previous_modes.is_empty(),
        },
    })
}

/// Compute a 32D spectral fingerprint from eigenvectors and eigenvalues.
///
/// Layout:
///   [0..8]   eigenvalues (padded with 0 if k < 8)
///   [8..16]  eigenvector concentration (sum of squared top-4 components per vector)
///   [16..24] inter-mode cosine similarities (top 8 by magnitude from k*(k-1)/2 pairs)
///   [24]     spectral entropy: -sum(p_i * ln(p_i))
///   [25]     λ₁/λ₂ gap ratio
///   [26]     eigenvector rotation rate: cosine similarity between current and previous v1
///   [27]     geometric radius relative to baseline
///   [28..32] spectral gap ratios λ_i/λ_{i+1} for i=0..3
fn compute_spectral_fingerprint(
    eigenvalues: &[f32],
    y: &[f32],       // column-major eigenvectors: y[i*n..(i+1)*n] for eigenvector i
    n: usize,        // reservoir dimension
    k: usize,        // number of eigenvectors
    prev_v1: &[f32], // previous top eigenvector for rotation detection
    geom_rel: f32,   // geometric radius relative to baseline
) -> Vec<f32> {
    let mut fp = vec![0.0f32; 32];

    // [0..8] Eigenvalues (padded)
    for (i, &ev) in eigenvalues.iter().take(8).enumerate() {
        fp[i] = if ev.is_finite() { ev } else { 0.0 };
    }

    // [8..16] Eigenvector concentration: for each vector, sum of squared top-4 components.
    // High concentration = eigenvector is peaked on few reservoir dimensions.
    // Low concentration = eigenvector is spread across many dimensions.
    for vi in 0..k.min(8) {
        let start = vi * n;
        let end = start + n;
        if end > y.len() {
            break;
        }
        let vec_slice = &y[start..end];
        // Get squared components, partially sort for top 4
        let mut sq: Vec<f32> = vec_slice.iter().map(|v| v * v).collect();
        sq.sort_unstable_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
        let top4_sum: f32 = sq.iter().take(4).sum();
        fp[8 + vi] = if top4_sum.is_finite() { top4_sum } else { 0.0 };
    }

    // [16..24] Inter-mode cosine similarities (top 8 by magnitude)
    let mut cos_sims: Vec<f32> = Vec::new();
    for i in 0..k.min(8) {
        for j in (i + 1)..k.min(8) {
            let si = i * n;
            let sj = j * n;
            if si + n > y.len() || sj + n > y.len() {
                continue;
            }
            let dot: f32 = (0..n).map(|d| y[si + d] * y[sj + d]).sum();
            if dot.is_finite() {
                cos_sims.push(dot);
            }
        }
    }
    cos_sims.sort_unstable_by(|a, b| {
        b.abs()
            .partial_cmp(&a.abs())
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    for (i, &cs) in cos_sims.iter().take(8).enumerate() {
        fp[16 + i] = cs;
    }

    // [24] Spectral entropy: -sum(p_i * ln(p_i)) where p_i = |λ_i| / sum(|λ|)
    let total_ev: f32 = eigenvalues.iter().map(|v| v.abs()).sum();
    if total_ev > 1e-10 {
        let entropy: f32 = eigenvalues
            .iter()
            .map(|v| {
                let p = v.abs() / total_ev;
                if p > 1e-10 {
                    -p * p.ln()
                } else {
                    0.0
                }
            })
            .sum();
        // Normalize by ln(k) to get 0..1 range
        let max_entropy = (eigenvalues.len() as f32).ln();
        fp[24] = if max_entropy > 0.0 && entropy.is_finite() {
            (entropy / max_entropy).clamp(0.0, 1.0)
        } else {
            0.0
        };
    }

    // [25] λ₁/λ₂ gap ratio
    let l1 = eigenvalues.first().copied().unwrap_or(0.0);
    let l2 = eigenvalues.get(1).copied().unwrap_or(0.0);
    fp[25] = if l2.abs() > 1e-6 && l1.is_finite() && l2.is_finite() {
        (l1 / l2).clamp(0.0, 100.0)
    } else {
        0.0
    };

    // [26] Eigenvector rotation rate: cosine similarity between current v1 and prev_v1
    if prev_v1.len() == n && y.len() >= n {
        let dot: f32 = (0..n).map(|i| prev_v1[i] * y[i]).sum();
        let norm_prev: f32 = prev_v1.iter().map(|v| v * v).sum::<f32>().sqrt();
        let norm_curr: f32 = y[..n].iter().map(|v| v * v).sum::<f32>().sqrt();
        let denom = norm_prev * norm_curr;
        fp[26] = if denom > 1e-8 && dot.is_finite() {
            (dot / denom).clamp(-1.0, 1.0)
        } else {
            1.0 // no rotation if we can't compute
        };
    } else {
        fp[26] = 1.0; // first tick or dimension mismatch: assume stable
    }

    // [27] Geometric radius relative to baseline
    fp[27] = if geom_rel.is_finite() {
        geom_rel.clamp(0.0, 4.0)
    } else {
        1.0
    };

    // [28..32] Spectral gap ratios λ_i/λ_{i+1} for i=0..3
    for i in 0..4 {
        let li = eigenvalues.get(i).copied().unwrap_or(0.0);
        let li1 = eigenvalues.get(i + 1).copied().unwrap_or(0.0);
        fp[28 + i] = if li1.abs() > 1e-6 && li.is_finite() && li1.is_finite() {
            (li / li1).clamp(0.0, 100.0)
        } else {
            0.0
        };
    }

    fp
}

/// Structural diversity derived from the live eigenvector geometry.
///
/// Unlike spectral entropy (which measures how eigenvalue energy is distributed),
/// this looks at whether the *shape* of the leading eigenvectors is peaked,
/// evenly spread, or highly coupled. Low values imply narrow, rigid geometry;
/// high values imply distributed, differentiated structure.
fn compute_structural_entropy(fingerprint: &[f32]) -> f32 {
    let concentrations: Vec<f32> = fingerprint
        .iter()
        .skip(8)
        .take(8)
        .copied()
        .filter(|value| value.is_finite() && *value > 1.0e-6)
        .collect();
    if concentrations.is_empty() {
        return 0.0;
    }

    let avg_concentration = concentrations.iter().sum::<f32>() / concentrations.len() as f32;
    let distribution_score = (1.0 - avg_concentration).clamp(0.0, 1.0);

    let total_concentration = concentrations.iter().sum::<f32>();
    let concentration_entropy = if total_concentration > 1.0e-6 {
        let entropy: f32 = concentrations
            .iter()
            .map(|value| {
                let p = *value / total_concentration;
                if p > 1.0e-6 {
                    -p * p.ln()
                } else {
                    0.0
                }
            })
            .sum();
        let max_entropy = (concentrations.len() as f32).ln();
        if max_entropy > 0.0 && entropy.is_finite() {
            (entropy / max_entropy).clamp(0.0, 1.0)
        } else {
            0.0
        }
    } else {
        0.0
    };

    let couplings: Vec<f32> = fingerprint
        .iter()
        .skip(16)
        .take(8)
        .copied()
        .filter(|value| value.is_finite() && value.abs() > 1.0e-6)
        .collect();
    let orthogonality = if couplings.is_empty() {
        1.0
    } else {
        let mean_abs =
            couplings.iter().map(|value| value.abs()).sum::<f32>() / couplings.len() as f32;
        (1.0 - mean_abs).clamp(0.0, 1.0)
    };

    (0.45 * distribution_score + 0.35 * concentration_entropy + 0.20 * orthogonality)
        .clamp(0.0, 1.0)
}

fn normalized_energy_shares(eigenvalues: &[f32]) -> Vec<f32> {
    let positive = eigenvalues
        .iter()
        .copied()
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let total = positive.iter().sum::<f32>();
    if total <= 1.0e-6 {
        return Vec::new();
    }
    positive
        .iter()
        .map(|value| (*value / total).clamp(0.0, 1.0))
        .collect()
}

fn normalized_entropy_from_shares(shares: &[f32]) -> f32 {
    if shares.len() <= 1 {
        return 0.0;
    }
    let entropy = shares
        .iter()
        .map(|share| {
            if *share > 1.0e-6 {
                -share * share.ln()
            } else {
                0.0
            }
        })
        .sum::<f32>();
    let max_entropy = (shares.len() as f32).ln();
    if max_entropy > 0.0 && entropy.is_finite() {
        (entropy / max_entropy).clamp(0.0, 1.0)
    } else {
        0.0
    }
}

fn share_temporal_persistence(current_shares: &[f32], previous_eigenvalues: Option<&[f32]>) -> f32 {
    let Some(previous_eigenvalues) = previous_eigenvalues else {
        return 0.5;
    };
    let previous_shares = normalized_energy_shares(previous_eigenvalues);
    if current_shares.is_empty() || previous_shares.is_empty() {
        return 0.5;
    }
    let len = current_shares.len().max(previous_shares.len());
    let distance = (0..len)
        .map(|index| {
            let current = current_shares.get(index).copied().unwrap_or(0.0);
            let previous = previous_shares.get(index).copied().unwrap_or(0.0);
            (current - previous).abs()
        })
        .sum::<f32>();
    (1.0 - 0.5 * distance).clamp(0.0, 1.0)
}
