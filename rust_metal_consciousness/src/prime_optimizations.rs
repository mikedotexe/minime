use std::collections::VecDeque;
use std::time::Instant;

/// Prime numbers commonly used in optimizations
pub const PRIMES: &[usize] = &[
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53,
    59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131
];

/// Find the next prime greater than or equal to n
pub fn next_prime(n: usize) -> usize {
    let mut candidate = n;
    while !is_prime(candidate) {
        candidate += 1;
    }
    candidate
}

/// Simple primality test (sufficient for small numbers)
fn is_prime(n: usize) -> bool {
    if n < 2 {
        return false;
    }
    if n == 2 {
        return true;
    }
    if n % 2 == 0 {
        return false;
    }

    let sqrt_n = (n as f64).sqrt() as usize;
    for i in (3..=sqrt_n).step_by(2) {
        if n % i == 0 {
            return false;
        }
    }
    true
}

/// Prime-sized ring buffer for temporal de-aliasing
pub struct PrimeRingBuffer<T: Clone> {
    buffer: VecDeque<T>,
    capacity: usize,  // Always a prime number
    position: usize,
}

impl<T: Clone> PrimeRingBuffer<T> {
    /// Create a new ring buffer with prime capacity
    pub fn new(desired_capacity: usize) -> Self {
        let capacity = next_prime(desired_capacity);
        PrimeRingBuffer {
            buffer: VecDeque::with_capacity(capacity),
            capacity,
            position: 0,
        }
    }

    /// Push an item to the buffer
    pub fn push(&mut self, item: T) {
        if self.buffer.len() < self.capacity {
            self.buffer.push_back(item);
        } else {
            self.buffer[self.position] = item;
        }
        self.position = (self.position + 1) % self.capacity;
    }

    /// Get item at index with coprime stride
    pub fn get_coprime(&self, index: usize, stride: usize) -> Option<&T> {
        if self.buffer.is_empty() {
            return None;
        }
        let actual_index = (index * stride) % self.buffer.len();
        self.buffer.get(actual_index)
    }

    /// Calculate entropy of buffer contents (for floats)
    pub fn entropy(&self) -> f64
    where
        T: Into<f64> + Copy,
    {
        if self.buffer.is_empty() {
            return 0.0;
        }

        // Create histogram with prime number of bins
        const BINS: usize = 17;  // Prime
        let mut histogram = vec![0u32; BINS];

        // Find min/max for normalization
        let values: Vec<f64> = self.buffer.iter().map(|&x| x.into()).collect();
        let min_val = values.iter().fold(f64::INFINITY, |a, &b| a.min(b));
        let max_val = values.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b));
        let range = max_val - min_val;

        if range < 1e-10 {
            return 0.0;  // No variation
        }

        // Build histogram
        for &val in &values {
            let normalized = (val - min_val) / range;
            let bin = ((normalized * (BINS - 1) as f64) as usize).min(BINS - 1);
            histogram[bin] += 1;
        }

        // Calculate entropy
        let total = self.buffer.len() as f64;
        let mut entropy = 0.0;

        for &count in &histogram {
            if count > 0 {
                let p = count as f64 / total;
                entropy -= p * p.ln();
            }
        }

        entropy
    }

    /// Get current fill level
    pub fn len(&self) -> usize {
        self.buffer.len()
    }

    /// Check if buffer is full
    pub fn is_full(&self) -> bool {
        self.buffer.len() == self.capacity
    }

    /// Get capacity (always prime)
    pub fn capacity(&self) -> usize {
        self.capacity
    }
}

/// Halton sequence generator for quasi-random sampling
pub struct HaltonSequence {
    index: u32,
    base1: u32,
    base2: u32,
}

impl HaltonSequence {
    /// Create new Halton sequence with coprime bases
    pub fn new(base1: u32, base2: u32) -> Self {
        assert!(gcd(base1, base2) == 1, "Bases must be coprime");
        HaltonSequence {
            index: 1,
            base1,
            base2,
        }
    }

    /// Get next 2D point in sequence
    pub fn next_2d(&mut self) -> (f32, f32) {
        let point = (
            halton(self.index, self.base1),
            halton(self.index, self.base2),
        );
        self.index += 1;
        point
    }

    /// Get next 1D value using first base
    pub fn next_1d(&mut self) -> f32 {
        let val = halton(self.index, self.base1);
        self.index += 1;
        val
    }

    /// Reset sequence
    pub fn reset(&mut self) {
        self.index = 1;
    }
}

/// Compute Halton sequence value
fn halton(mut index: u32, base: u32) -> f32 {
    let mut result = 0.0;
    let mut f = 1.0 / base as f32;

    while index > 0 {
        result += f * (index % base) as f32;
        index /= base;
        f /= base as f32;
    }

    result
}

/// Compute greatest common divisor
fn gcd(a: u32, b: u32) -> u32 {
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

/// Prime-based index mapping for better distribution
pub struct PrimeHasher {
    multiplier: u64,
    modulus: u64,
}

impl PrimeHasher {
    /// Create hasher with large prime multiplier
    pub fn new(table_size: usize) -> Self {
        // Use a large prime multiplier (FNV prime)
        PrimeHasher {
            multiplier: 1099511628211,  // 2^40 + 2^8 + 0xb3
            modulus: next_prime(table_size) as u64,
        }
    }

    /// Hash an index to a table position
    pub fn hash(&self, index: u64) -> usize {
        ((index.wrapping_mul(self.multiplier)) % self.modulus) as usize
    }

    /// Hash a pair of indices (for resonance detection)
    pub fn hash_pair(&self, i: u32, j: u32) -> usize {
        let combined = ((i as u64) << 32) | (j as u64);
        self.hash(combined)
    }
}

/// Prime diagnostic scheduler
pub struct PrimeDiagnostics {
    intervals: Vec<usize>,  // Different prime intervals
    counters: Vec<usize>,   // Current count for each diagnostic
    last_run: Vec<Instant>, // Last run time for rate limiting
}

impl PrimeDiagnostics {
    pub fn new() -> Self {
        PrimeDiagnostics {
            intervals: vec![97, 113, 127],  // Prime intervals
            counters: vec![0, 0, 0],
            last_run: vec![Instant::now(); 3],
        }
    }

    /// Check if diagnostic should run
    pub fn should_run(&mut self, diagnostic_id: usize, iteration: usize) -> bool {
        if diagnostic_id >= self.intervals.len() {
            return false;
        }

        self.counters[diagnostic_id] = iteration;

        // Check prime interval
        if iteration % self.intervals[diagnostic_id] == 0 {
            // Rate limit to prevent too frequent diagnostics
            let now = Instant::now();
            if now.duration_since(self.last_run[diagnostic_id]).as_secs() >= 1 {
                self.last_run[diagnostic_id] = now;
                return true;
            }
        }

        false
    }

    /// Add a custom prime diagnostic interval
    pub fn add_diagnostic(&mut self, interval: usize) {
        let prime_interval = next_prime(interval);
        self.intervals.push(prime_interval);
        self.counters.push(0);
        self.last_run.push(Instant::now());
    }
}

/// Configuration for prime optimizations
#[derive(Debug, Clone)]
pub struct PrimeConfig {
    /// Use prime-sized buffers
    pub use_prime_buffers: bool,

    /// Use coprime stride in matrix access
    pub use_coprime_stride: bool,

    /// Prime padding for threadgroup memory
    pub use_prime_padding: bool,

    /// Use Halton sequences for initialization
    pub use_halton_init: bool,

    /// Epsilon rotation of accumulation order
    pub use_rotation: bool,

    /// Prime diagnostic intervals
    pub use_prime_diagnostics: bool,

    /// Specific prime values to use
    pub buffer_prime: usize,
    pub stride_prime: usize,
    pub diagnostic_prime: usize,
}

impl Default for PrimeConfig {
    fn default() -> Self {
        PrimeConfig {
            use_prime_buffers: true,
            use_coprime_stride: true,
            use_prime_padding: true,
            use_halton_init: true,
            use_rotation: true,
            use_prime_diagnostics: true,
            buffer_prime: 113,      // Prime ring buffer size
            stride_prime: 97,       // Coprime stride
            diagnostic_prime: 127,  // Diagnostic interval
        }
    }
}

impl PrimeConfig {
    /// Convert to bit flags for GPU
    pub fn to_gpu_flags(&self) -> u32 {
        let mut flags = 0u32;

        if self.use_coprime_stride {
            flags |= 0x1;
        }
        if self.use_prime_padding {
            flags |= 0x2;
        }
        if self.use_halton_init {
            flags |= 0x4;
        }
        if self.use_rotation {
            flags |= 0x8;
        }

        flags
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prime_detection() {
        assert!(is_prime(2));
        assert!(is_prime(3));
        assert!(is_prime(97));
        assert!(is_prime(113));
        assert!(!is_prime(100));
        assert!(!is_prime(1));
    }

    #[test]
    fn test_next_prime() {
        assert_eq!(next_prime(100), 101);
        assert_eq!(next_prime(113), 113);  // Already prime
        assert_eq!(next_prime(114), 127);
    }

    #[test]
    fn test_prime_ring_buffer() {
        let mut buffer = PrimeRingBuffer::new(10);  // Will use 11
        assert_eq!(buffer.capacity(), 11);

        for i in 0..20 {
            buffer.push(i);
        }

        assert_eq!(buffer.len(), 11);
        assert!(buffer.is_full());
    }

    #[test]
    fn test_halton_sequence() {
        let mut seq = HaltonSequence::new(2, 3);

        let (x1, y1) = seq.next_2d();
        let (x2, y2) = seq.next_2d();

        // First few Halton values
        assert!((x1 - 0.5).abs() < 0.01);
        assert!((y1 - 0.333).abs() < 0.01);
        assert!((x2 - 0.25).abs() < 0.01);
        assert!((y2 - 0.666).abs() < 0.01);
    }
}