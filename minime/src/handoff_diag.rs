use std::{hint::black_box, mem::size_of, ptr, time::Instant};

pub const PAGE_BYTES: usize = 16_384;
pub const CACHE_LINE_BYTES: usize = 128;
const LOW_CONFIDENCE_SEQ_US: f64 = 1.0;
const LOW_CONFIDENCE_MIN_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug)]
pub struct HandoffDiagRecord {
    pub t_s: f64,
    pub tick: u64,
    pub stage: &'static str,
    pub buffer: &'static str,
    pub bytes: usize,
    pub prefaulted: bool,
    pub seq_read_us: f64,
    pub random_probe_ns_per_access: Option<f64>,
    pub integrity_ok: Option<bool>,
    pub max_abs_diff: Option<f32>,
    pub small_value_low_confidence: bool,
}

impl HandoffDiagRecord {
    pub fn to_csv_line(&self) -> String {
        format!(
            "{:.6},{},{},{},{},{},{:.3},{},{},{},{}\n",
            self.t_s,
            self.tick,
            self.stage,
            self.buffer,
            self.bytes,
            if self.prefaulted { 1 } else { 0 },
            self.seq_read_us,
            csv_opt_f64(self.random_probe_ns_per_access),
            csv_opt_bool(self.integrity_ok),
            csv_opt_f32(self.max_abs_diff),
            if self.small_value_low_confidence {
                1
            } else {
                0
            },
        )
    }
}

pub fn csv_header() -> &'static str {
    "t_s,tick,stage,buffer,bytes,prefaulted,seq_read_us,random_probe_ns_per_access,integrity_ok,max_abs_diff,small_value_low_confidence\n"
}

pub fn prefault_f32(slice: &[f32]) {
    if slice.is_empty() {
        return;
    }

    let stride = (PAGE_BYTES / size_of::<f32>()).max(1);
    let mut acc = 0.0f32;
    for idx in (0..slice.len()).step_by(stride) {
        acc += unsafe { ptr::read_volatile(&slice[idx]) };
    }
    acc += unsafe { ptr::read_volatile(slice.last().unwrap()) };
    black_box(acc);
}

pub fn sequential_read_us_f32(slice: &[f32]) -> f64 {
    let start = Instant::now();
    let mut acc = 0.0f64;
    for value in slice {
        acc += *value as f64;
    }
    black_box(acc);
    start.elapsed().as_secs_f64() * 1_000_000.0
}

pub fn bit_reversal_order(count: usize) -> Vec<usize> {
    if count == 0 {
        return Vec::new();
    }

    if count == 1 {
        return vec![0];
    }

    let width = usize::BITS as usize - (count - 1).leading_zeros() as usize;
    let mut order = Vec::with_capacity(count);
    let limit = 1usize << width;
    for idx in 0..limit {
        let reversed = idx.reverse_bits() >> (usize::BITS as usize - width);
        if reversed < count {
            order.push(reversed);
        }
    }
    order
}

pub fn random_probe_ns_per_access_f32(slice: &[f32]) -> Option<f64> {
    if slice.is_empty() {
        return None;
    }

    let floats_per_line = (CACHE_LINE_BYTES / size_of::<f32>()).max(1);
    let line_count = (slice.len() + floats_per_line - 1) / floats_per_line;
    let order = bit_reversal_order(line_count);
    if order.is_empty() {
        return None;
    }

    let start = Instant::now();
    let mut acc = 0.0f32;
    for line_idx in order {
        let float_idx = (line_idx * floats_per_line).min(slice.len() - 1);
        acc += unsafe { ptr::read_volatile(&slice[float_idx]) };
    }
    black_box(acc);

    Some(start.elapsed().as_secs_f64() * 1_000_000_000.0 / line_count as f64)
}

pub fn small_value_low_confidence(seq_read_us: f64, bytes: usize) -> bool {
    seq_read_us < LOW_CONFIDENCE_SEQ_US || bytes < LOW_CONFIDENCE_MIN_BYTES
}

pub fn cpu_block_matvec_reference(a: &[f32], x: &[f32], n: usize, k: usize) -> Vec<f32> {
    assert_eq!(a.len(), n * n);
    assert_eq!(x.len(), n * k);

    let mut out = vec![0.0f32; n * k];
    for col in 0..k {
        let x_col = &x[col * n..(col + 1) * n];
        let out_col = &mut out[col * n..(col + 1) * n];
        for row in 0..n {
            let row_slice = &a[row * n..(row + 1) * n];
            let mut acc = 0.0f32;
            for (a_ij, x_j) in row_slice.iter().zip(x_col.iter()) {
                acc += a_ij * x_j;
            }
            out_col[row] = acc;
        }
    }
    out
}

pub fn integrity_check(actual: &[f32], expected: &[f32]) -> (bool, f32) {
    let max_abs_diff = max_abs_diff(actual, expected);
    let scale = expected
        .iter()
        .fold(1.0f32, |acc, value| acc.max(value.abs()));
    let tolerance = 5.0e-3_f32 * scale;
    (max_abs_diff <= tolerance, max_abs_diff)
}

pub fn max_abs_diff(lhs: &[f32], rhs: &[f32]) -> f32 {
    assert_eq!(lhs.len(), rhs.len());
    lhs.iter()
        .zip(rhs.iter())
        .fold(0.0f32, |acc, (l, r)| acc.max((l - r).abs()))
}

fn csv_opt_bool(value: Option<bool>) -> String {
    match value {
        Some(true) => "1".to_string(),
        Some(false) => "0".to_string(),
        None => String::new(),
    }
}

fn csv_opt_f32(value: Option<f32>) -> String {
    value.map(|v| format!("{:.6}", v)).unwrap_or_default()
}

fn csv_opt_f64(value: Option<f64>) -> String {
    value.map(|v| format!("{:.3}", v)).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::{bit_reversal_order, small_value_low_confidence};

    #[test]
    fn bit_reversal_order_matches_expected_pattern_for_power_of_two() {
        assert_eq!(bit_reversal_order(8), vec![0, 4, 2, 6, 1, 5, 3, 7]);
    }

    #[test]
    fn low_confidence_gate_flags_tiny_reads_and_small_buffers() {
        assert!(small_value_low_confidence(0.75, 256 * 1024));
        assert!(small_value_low_confidence(5.0, 16 * 1024));
        assert!(!small_value_low_confidence(5.0, 256 * 1024));
    }
}
