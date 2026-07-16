// === TEMPORAL QUEUE: "Disneyland line" with natural decay ===
// Legacy SensoryQueue system removed - using SensoryBus for all sensory input

/* LEGACY TRAIT IMPLEMENTATIONS - NO LONGER NEEDED WITH FIX PACK

// Implement PIRegulator trait for PIRegState
impl homeostasis::PIRegulator for regulator::PIRegState {
    fn step(&mut self, eigenfill_pct: f32, lambda1_rel: f32) {
        // Call the existing step method
        self.step(eigenfill_pct, lambda1_rel);
    }

    fn gate(&self) -> f32 {
        self.gate
    }

    fn filt(&self) -> f32 {
        self.filt
    }
}

// Implement SpectralSource trait for spectral monitor
// Wrapper for spectral state computed in main loop
*/
struct MainLoopSpectralSource {
    eigenfill_pct: std::cell::Cell<f32>,
    lambda1: std::cell::Cell<f32>,
    covariance: std::cell::RefCell<Vec<f32>>,
    dim: usize,
    // ESN eigenvalues (real consciousness state)
    esn_eig: std::cell::Cell<f32>,
    esn_baseline: std::cell::Cell<f32>,
}

impl MainLoopSpectralSource {
    fn new(dim: usize) -> Self {
        Self {
            eigenfill_pct: std::cell::Cell::new(0.0),
            lambda1: std::cell::Cell::new(0.0),
            covariance: std::cell::RefCell::new(vec![0.0f32; dim * dim]),
            dim,
            esn_eig: std::cell::Cell::new(0.0),
            esn_baseline: std::cell::Cell::new(0.0), // Will be set by ESN after warmup
        }
    }

    fn update(&self, eigenfill_pct: f32, lambda1: f32, cov: &[f32]) {
        self.eigenfill_pct.set(eigenfill_pct);
        self.lambda1.set(lambda1);
        *self.covariance.borrow_mut() = cov.to_vec();
    }

    fn update_esn(&self, eig: f32, baseline: f32) {
        self.esn_eig.set(eig);
        if baseline > 0.0 {
            self.esn_baseline.set(baseline);
        }
    }

    fn get_covariance_f32(&self) -> (usize, Vec<f32>) {
        (self.dim, self.covariance.borrow().clone())
    }

    fn read_spectral(&self) -> (f32, f32) {
        // Use covariance-based EigenFillEstimator for fill (stable, well-calibrated).
        // ESN-derived fill is unreliable because the adaptive baseline tracks the
        // eigenvalue too closely, making fill → 0 over time.
        // Lambda1 comes from ESN if available (for λ₁_rel computation), else covariance.
        let esn_eig = self.esn_eig.get();
        let eigenfill_pct = self.eigenfill_pct.get();
        let lambda1 = if esn_eig > 0.0 {
            esn_eig
        } else {
            self.lambda1.get()
        };

        (eigenfill_pct, lambda1)
    }
}

/*
// Implement SensoryBus trait for our SensoryBus struct - NO LONGER NEEDED
impl homeostasis::SensoryBus for sensory_bus::SensoryBus {
    fn fill_sensory_vector(&mut self) -> Option<(Vec<f32>, u64)> {
        if let Some(sample) = sensory_bus::SensoryBus::fill_sensory_vector(self) {
            // Calculate average age from metadata
            let age_ms = ((sample.meta.audio_age_ms + sample.meta.video_age_ms) / 2) as u64;
            Some((sample.vec, age_ms))
        } else {
            None
        }
    }

    fn submit_filtered_vector(&mut self, z_filtered: Vec<f32>, age_ms: u64) {
        // Create metadata for the filtered vector
        let meta = sensory_bus::SensoryMeta {
            ts: std::time::Instant::now(),
            audio_age_ms: age_ms as u32,
            video_age_ms: age_ms as u32,
            aux_age_ms: age_ms as u32,
            admit_fraction: 1.0, // Already filtered/admitted
            accepted: true,
            has_real_audio: true,  // Assume real when bypassing SensoryBus
            has_real_video: true,
        };
        let _ = sensory_bus::SensoryBus::submit_filtered_vector(self, &z_filtered, &meta);
    }

    fn set_admit_fraction(&mut self, frac: f32) {
        sensory_bus::SensoryBus::set_admit_fraction(self, frac);
    }
}
*/
