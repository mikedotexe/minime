//! Deterministic repair of the measurement basis, not of the covariance matrix.
use serde::Serialize;

const RELATIVE_RANK_TOLERANCE: f64 = 8.0 * f32::EPSILON as f64;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[must_use]
pub struct BasisReport {
    pub recipe: &'static str,
    pub repaired_columns: Vec<usize>,
    pub nonfinite_columns: Vec<usize>,
}

impl BasisReport {
    pub fn input_finite(&self) -> bool {
        self.nonfinite_columns.is_empty()
    }
}

fn norm(vector: &[f64]) -> f64 {
    vector.iter().map(|v| v * v).sum::<f64>().sqrt()
}

fn remove_projections(vector: &mut [f64], accepted: &[Vec<f64>]) {
    // Reorthogonalization prevents cancellation error from becoming a new direction.
    for _ in 0..2 {
        for basis in accepted {
            let dot = vector.iter().zip(basis).map(|(a, b)| a * b).sum::<f64>();
            for (value, component) in vector.iter_mut().zip(basis) {
                *value -= dot * component;
            }
        }
    }
}

/// Retain independent finite directions, then fill missing directions from their
/// orthogonal complement. A repaired nonfinite input must not count as a valid
/// measurement of this iteration; the report keeps that distinction explicit.
pub fn orthonormalize(x: &mut [f32], n: usize, k: usize) -> BasisReport {
    assert!(n > 0 && k <= n, "invalid measurement basis dimensions");
    assert_eq!(n.checked_mul(k), Some(x.len()));
    let mut report = BasisReport {
        recipe: "measurement-basis-repair-v1",
        repaired_columns: Vec::new(),
        nonfinite_columns: Vec::new(),
    };
    let mut accepted = Vec::with_capacity(k);
    let mut columns = vec![Vec::new(); k];
    for (index, source) in x.chunks_exact(n).enumerate() {
        let mut vector: Vec<f64> = source.iter().map(|&v| f64::from(v)).collect();
        if !source.iter().all(|v| v.is_finite()) {
            report.nonfinite_columns.push(index);
            report.repaired_columns.push(index);
            continue;
        }
        let original_norm = norm(&vector);
        remove_projections(&mut vector, &accepted);
        let residual_norm = norm(&vector);
        if residual_norm <= RELATIVE_RANK_TOLERANCE * original_norm {
            report.repaired_columns.push(index);
            continue;
        }
        for value in &mut vector {
            *value /= residual_norm;
        }
        columns[index] = vector.clone();
        accepted.push(vector);
    }
    // Delay replacements until every usable original column is retained. An
    // earlier missing column must not steal a later independent direction.
    for &index in &report.repaired_columns {
        let mut axis = 0;
        let mut best = f64::NEG_INFINITY;
        for candidate in 0..n {
            let residual = 1.0 - accepted.iter().map(|v| v[candidate].powi(2)).sum::<f64>();
            if residual > best {
                best = residual;
                axis = candidate;
            }
        }
        let mut vector = vec![0.0; n];
        vector[axis] = 1.0;
        remove_projections(&mut vector, &accepted);
        let residual_norm = norm(&vector);
        assert!(residual_norm > RELATIVE_RANK_TOLERANCE);
        for value in &mut vector {
            *value /= residual_norm;
        }
        columns[index] = vector.clone();
        accepted.push(vector);
    }
    for (target, vector) in x.chunks_exact_mut(n).zip(columns) {
        for (value, component) in target.iter_mut().zip(vector) {
            *value = component as f32;
        }
    }
    report
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_basis(x: &[f32], n: usize) {
        for (i, a) in x.chunks_exact(n).enumerate() {
            for (j, b) in x.chunks_exact(n).enumerate() {
                let dot = a
                    .iter()
                    .zip(b)
                    .map(|(&a, &b)| f64::from(a) * f64::from(b))
                    .sum::<f64>();
                assert!(
                    (dot - if i == j { 1.0 } else { 0.0 }).abs() < 2e-6,
                    "{i},{j}: {dot}"
                );
            }
        }
    }

    #[test]
    fn zero_duplicate_and_near_dependent_columns_are_replaced() {
        for epsilon in [0.0, 1e-8] {
            let mut x = vec![1.0, 0.0, 0.0, 1.0, epsilon, 0.0, 0.0, 0.0, 0.0];
            let report = orthonormalize(&mut x, 3, 3);
            assert_eq!(report.repaired_columns, [1, 2]);
            assert!(report.input_finite());
            assert_basis(&x, 3);
        }
    }

    #[test]
    fn missing_first_column_does_not_replace_later_valid_direction() {
        let mut x = vec![0.0, 0.0, 1.0, 0.0];
        assert_eq!(orthonormalize(&mut x, 2, 2).repaired_columns, [0]);
        assert_eq!(x, [0.0, 1.0, 1.0, 0.0]);
    }

    #[test]
    fn finite_full_rank_is_scale_independent_and_preserves_orientation() {
        for scale in [1e-30, 1.0, 1e30] {
            let mut x = vec![-scale, 0.0, 0.0, scale];
            assert!(orthonormalize(&mut x, 2, 2).repaired_columns.is_empty());
            assert_eq!(x, [-1.0, 0.0, 0.0, 1.0]);
        }
    }

    #[test]
    fn nonfinite_input_is_flagged_despite_finite_replacement() {
        for invalid in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            let mut x = vec![invalid, 0.0, 0.0, 1.0];
            let report = orthonormalize(&mut x, 2, 2);
            assert!(!report.input_finite());
            assert_eq!(report.nonfinite_columns, [0]);
            assert_basis(&x, 2);
        }
    }

    #[test]
    fn production_dimensions_are_repeatable_and_orthonormal() {
        for (n, k) in [(8, 8), (32, 8), (512, 8)] {
            for seed in 0..64 {
                let mut rng = fastrand::Rng::with_seed(seed);
                let mut x = (0..n * k).map(|_| rng.f32() - 0.5).collect::<Vec<_>>();
                x[..n].fill(0.0);
                let mut copy = x.clone();
                assert_eq!(
                    orthonormalize(&mut x, n, k),
                    orthonormalize(&mut copy, n, k)
                );
                assert_eq!(x, copy);
                assert_basis(&x, n);
            }
        }
    }

    #[test]
    #[should_panic(expected = "invalid measurement basis dimensions")]
    fn impossible_rank_is_rejected() {
        let _ = orthonormalize(&mut [0.0; 6], 2, 3);
    }
}
