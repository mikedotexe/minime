//! Self-Referential Neural Bundle
//!
//! Three specialized networks for consciousness evolution:
#![allow(dead_code)]
//! - **Predictor (P)**: Forecasts next λ₁ from eigenvalues + manifold state
//! - **Router (R)**: Learns A/V feature mixing for covariance update
//! - **Regulator (G)**: Emits control deltas for prime periods, learning rates, membrane tension
//!
//! All use Metal GPU with zero-copy unified memory (StorageModeShared).
//! Training uses CPU-side gradients with GPU-side SGD updates.

use metal::*;

//=============================================================================
// MLP Architecture
//=============================================================================

pub struct MLP {
    pub din: usize,
    pub hidden: usize,
    pub dout: usize,

    // Weights (StorageModeShared for zero-copy)
    pub w1: Buffer, // [din, hidden]
    pub b1: Buffer, // [hidden]
    pub w2: Buffer, // [hidden, dout]
    pub b2: Buffer, // [dout]

    // Gradient buffers
    pub dw1: Buffer,
    pub db1: Buffer,
    pub dw2: Buffer,
    pub db2: Buffer,

    // Intermediate activations (for backward pass)
    pub h: Buffer, // [batch, hidden] - hidden layer output
    pub x: Buffer, // [batch, din] - input cache

    // Metal resources
    device: Device,
    queue: CommandQueue,

    // Pipelines
    dense_relu_fwd: ComputePipelineState,
    dense_linear_fwd: ComputePipelineState,
    sgd_apply: ComputePipelineState,
}

impl MLP {
    /// Create a new MLP with random Xavier initialization
    pub fn new(
        device: &Device,
        library: &Library,
        din: usize,
        hidden: usize,
        dout: usize,
    ) -> Result<Self, String> {
        let queue = device.new_command_queue();

        // Load shader functions
        let dense_relu_fwd = library
            .get_function("dense_relu_fwd", None)
            .map_err(|e| format!("Failed to load dense_relu_fwd: {:?}", e))?;
        let dense_linear_fwd = library
            .get_function("dense_linear_fwd", None)
            .map_err(|e| format!("Failed to load dense_linear_fwd: {:?}", e))?;
        let sgd_apply = library
            .get_function("sgd_apply", None)
            .map_err(|e| format!("Failed to load sgd_apply: {:?}", e))?;

        // Create pipelines
        let dense_relu_fwd = device
            .new_compute_pipeline_state_with_function(&dense_relu_fwd)
            .map_err(|e| format!("Failed to create dense_relu_fwd pipeline: {:?}", e))?;
        let dense_linear_fwd = device
            .new_compute_pipeline_state_with_function(&dense_linear_fwd)
            .map_err(|e| format!("Failed to create dense_linear_fwd pipeline: {:?}", e))?;
        let sgd_apply = device
            .new_compute_pipeline_state_with_function(&sgd_apply)
            .map_err(|e| format!("Failed to create sgd_apply pipeline: {:?}", e))?;

        // Allocate weight buffers (StorageModeShared for CPU access)
        let w1 = device.new_buffer(
            (din * hidden * 4) as u64,
            MTLResourceOptions::StorageModeShared,
        );
        let b1 = device.new_buffer((hidden * 4) as u64, MTLResourceOptions::StorageModeShared);
        let w2 = device.new_buffer(
            (hidden * dout * 4) as u64,
            MTLResourceOptions::StorageModeShared,
        );
        let b2 = device.new_buffer((dout * 4) as u64, MTLResourceOptions::StorageModeShared);

        // Gradient buffers
        let dw1 = device.new_buffer(
            (din * hidden * 4) as u64,
            MTLResourceOptions::StorageModeShared,
        );
        let db1 = device.new_buffer((hidden * 4) as u64, MTLResourceOptions::StorageModeShared);
        let dw2 = device.new_buffer(
            (hidden * dout * 4) as u64,
            MTLResourceOptions::StorageModeShared,
        );
        let db2 = device.new_buffer((dout * 4) as u64, MTLResourceOptions::StorageModeShared);

        // Activation buffers (assume max batch size = 16)
        let h = device.new_buffer(
            (16 * hidden * 4) as u64,
            MTLResourceOptions::StorageModeShared,
        );
        let x = device.new_buffer((16 * din * 4) as u64, MTLResourceOptions::StorageModeShared);

        let mut mlp = Self {
            din,
            hidden,
            dout,
            w1,
            b1,
            w2,
            b2,
            dw1,
            db1,
            dw2,
            db2,
            h,
            x,
            device: device.clone(),
            queue,
            dense_relu_fwd,
            dense_linear_fwd,
            sgd_apply,
        };

        // Initialize weights with Xavier
        mlp.init_weights();

        Ok(mlp)
    }

    /// Xavier initialization: W ~ N(0, sqrt(2/(din + dout)))
    fn init_weights(&mut self) {
        use rand::Rng;
        let mut rng = rand::thread_rng();

        // W1: [din, hidden]
        let scale1 = (2.0 / (self.din + self.hidden) as f32).sqrt();
        let w1_ptr = self.w1.contents() as *mut f32;
        unsafe {
            for i in 0..(self.din * self.hidden) {
                *w1_ptr.add(i) = rng.gen::<f32>() * 2.0 * scale1 - scale1;
            }
        }

        // b1: zeros
        let b1_ptr = self.b1.contents() as *mut f32;
        unsafe {
            for i in 0..self.hidden {
                *b1_ptr.add(i) = 0.0;
            }
        }

        // W2: [hidden, dout]
        let scale2 = (2.0 / (self.hidden + self.dout) as f32).sqrt();
        let w2_ptr = self.w2.contents() as *mut f32;
        unsafe {
            for i in 0..(self.hidden * self.dout) {
                *w2_ptr.add(i) = rng.gen::<f32>() * 2.0 * scale2 - scale2;
            }
        }

        // b2: zeros
        let b2_ptr = self.b2.contents() as *mut f32;
        unsafe {
            for i in 0..self.dout {
                *b2_ptr.add(i) = 0.0;
            }
        }
    }

    /// Forward pass: Y = MLP(X)
    /// X: [batch, din] (input buffer)
    /// Returns: [batch, dout] (output buffer)
    pub fn forward(
        &mut self,
        x_input: &Buffer,
        y_output: &Buffer,
        batch_size: usize,
    ) -> Result<(), String> {
        // Cache input for backward pass (CPU-side copy)
        unsafe {
            std::ptr::copy_nonoverlapping(
                x_input.contents() as *const u8,
                self.x.contents() as *mut u8,
                batch_size * self.din * std::mem::size_of::<f32>(),
            );
        }

        let cmd_buffer = self.queue.new_command_buffer();
        let encoder = cmd_buffer.new_compute_command_encoder();

        // Layer 1: H = ReLU(X @ W1 + b1)
        encoder.set_compute_pipeline_state(&self.dense_relu_fwd);
        encoder.set_buffer(0, Some(&x_input), 0);
        encoder.set_buffer(1, Some(&self.w1), 0);
        encoder.set_buffer(2, Some(&self.b1), 0);
        encoder.set_buffer(3, Some(&self.h), 0);
        encoder.set_bytes(
            4,
            std::mem::size_of::<u32>() as u64,
            &(batch_size as u32) as *const u32 as *const _,
        );
        encoder.set_bytes(
            5,
            std::mem::size_of::<u32>() as u64,
            &(self.din as u32) as *const u32 as *const _,
        );
        encoder.set_bytes(
            6,
            std::mem::size_of::<u32>() as u64,
            &(self.hidden as u32) as *const u32 as *const _,
        );

        let grid_size = MTLSize::new(self.hidden as u64, batch_size as u64, 1);
        let thread_group_size = MTLSize::new(1, 1, 1);
        encoder.dispatch_threads(grid_size, thread_group_size);

        // Layer 2: Y = H @ W2 + b2
        encoder.set_compute_pipeline_state(&self.dense_linear_fwd);
        encoder.set_buffer(0, Some(&self.h), 0);
        encoder.set_buffer(1, Some(&self.w2), 0);
        encoder.set_buffer(2, Some(&self.b2), 0);
        encoder.set_buffer(3, Some(&y_output), 0);
        encoder.set_bytes(
            4,
            std::mem::size_of::<u32>() as u64,
            &(batch_size as u32) as *const u32 as *const _,
        );
        encoder.set_bytes(
            5,
            std::mem::size_of::<u32>() as u64,
            &(self.hidden as u32) as *const u32 as *const _,
        );
        encoder.set_bytes(
            6,
            std::mem::size_of::<u32>() as u64,
            &(self.dout as u32) as *const u32 as *const _,
        );

        let grid_size = MTLSize::new(self.dout as u64, batch_size as u64, 1);
        encoder.dispatch_threads(grid_size, thread_group_size);

        encoder.end_encoding();
        cmd_buffer.commit();
        cmd_buffer.wait_until_completed();

        Ok(())
    }

    /// Backward pass (CPU-side for simplicity, given online learning)
    /// Computes gradients: dW1, db1, dW2, db2
    /// dy: [batch, dout] - gradient from loss
    pub fn backward(&mut self, dy: &[f32], batch_size: usize) {
        // This is a simplified CPU implementation
        // For real-time constraints, we can port to Metal if needed

        // Get pointers to weights and activations
        let w2_ptr = self.w2.contents() as *const f32;
        let h_ptr = self.h.contents() as *const f32;
        let x_ptr = self.x.contents() as *const f32;

        let dw2_ptr = self.dw2.contents() as *mut f32;
        let db2_ptr = self.db2.contents() as *mut f32;
        let dw1_ptr = self.dw1.contents() as *mut f32;
        let db1_ptr = self.db1.contents() as *mut f32;

        unsafe {
            // Zero gradients
            for i in 0..(self.hidden * self.dout) {
                *dw2_ptr.add(i) = 0.0;
            }
            for i in 0..self.dout {
                *db2_ptr.add(i) = 0.0;
            }
            for i in 0..(self.din * self.hidden) {
                *dw1_ptr.add(i) = 0.0;
            }
            for i in 0..self.hidden {
                *db1_ptr.add(i) = 0.0;
            }

            // Backward through Layer 2: dL/dW2, dL/db2, dL/dH
            let mut dh = vec![0.0f32; batch_size * self.hidden];

            for b in 0..batch_size {
                for j in 0..self.dout {
                    let dy_val = dy[b * self.dout + j];

                    // db2[j] += dy[b, j]
                    *db2_ptr.add(j) += dy_val;

                    // dW2[:, j] += H[b, :] * dy[b, j]
                    for i in 0..self.hidden {
                        let h_val = *h_ptr.add(b * self.hidden + i);
                        *dw2_ptr.add(i * self.dout + j) += h_val * dy_val;

                        // dH[b, i] += W2[i, j] * dy[b, j]
                        dh[b * self.hidden + i] += *w2_ptr.add(i * self.dout + j) * dy_val;
                    }
                }
            }

            // Apply ReLU gradient: dH *= (H > 0)
            for b in 0..batch_size {
                for i in 0..self.hidden {
                    let h_val = *h_ptr.add(b * self.hidden + i);
                    if h_val <= 0.0 {
                        dh[b * self.hidden + i] = 0.0;
                    }
                }
            }

            // Backward through Layer 1: dL/dW1, dL/db1
            for b in 0..batch_size {
                for j in 0..self.hidden {
                    let dh_val = dh[b * self.hidden + j];

                    // db1[j] += dH[b, j]
                    *db1_ptr.add(j) += dh_val;

                    // dW1[:, j] += X[b, :] * dH[b, j]
                    for i in 0..self.din {
                        let x_val = *x_ptr.add(b * self.din + i);
                        *dw1_ptr.add(i * self.hidden + j) += x_val * dh_val;
                    }
                }
            }

            // Average gradients over batch
            let scale = 1.0 / batch_size as f32;
            for i in 0..(self.hidden * self.dout) {
                *dw2_ptr.add(i) *= scale;
            }
            for i in 0..self.dout {
                *db2_ptr.add(i) *= scale;
            }
            for i in 0..(self.din * self.hidden) {
                *dw1_ptr.add(i) *= scale;
            }
            for i in 0..self.hidden {
                *db1_ptr.add(i) *= scale;
            }
        }
    }

    /// Apply SGD update: W -= lr * dW (GPU-accelerated)
    pub fn update(&mut self, lr: f32) -> Result<(), String> {
        let cmd_buffer = self.queue.new_command_buffer();
        let encoder = cmd_buffer.new_compute_command_encoder();

        encoder.set_compute_pipeline_state(&self.sgd_apply);

        // Update W1
        encoder.set_buffer(0, Some(&self.w1), 0);
        encoder.set_buffer(1, Some(&self.dw1), 0);
        encoder.set_bytes(
            2,
            std::mem::size_of::<f32>() as u64,
            &lr as *const f32 as *const _,
        );
        let n = (self.din * self.hidden) as u32;
        encoder.set_bytes(
            3,
            std::mem::size_of::<u32>() as u64,
            &n as *const u32 as *const _,
        );
        encoder.dispatch_thread_groups(
            MTLSize::new(((n + 255) / 256) as u64, 1, 1),
            MTLSize::new(256, 1, 1),
        );

        // Update b1
        encoder.set_buffer(0, Some(&self.b1), 0);
        encoder.set_buffer(1, Some(&self.db1), 0);
        encoder.set_bytes(
            2,
            std::mem::size_of::<f32>() as u64,
            &lr as *const f32 as *const _,
        );
        let n = self.hidden as u32;
        encoder.set_bytes(
            3,
            std::mem::size_of::<u32>() as u64,
            &n as *const u32 as *const _,
        );
        encoder.dispatch_thread_groups(
            MTLSize::new(((n + 255) / 256) as u64, 1, 1),
            MTLSize::new(256, 1, 1),
        );

        // Update W2
        encoder.set_buffer(0, Some(&self.w2), 0);
        encoder.set_buffer(1, Some(&self.dw2), 0);
        encoder.set_bytes(
            2,
            std::mem::size_of::<f32>() as u64,
            &lr as *const f32 as *const _,
        );
        let n = (self.hidden * self.dout) as u32;
        encoder.set_bytes(
            3,
            std::mem::size_of::<u32>() as u64,
            &n as *const u32 as *const _,
        );
        encoder.dispatch_thread_groups(
            MTLSize::new(((n + 255) / 256) as u64, 1, 1),
            MTLSize::new(256, 1, 1),
        );

        // Update b2
        encoder.set_buffer(0, Some(&self.b2), 0);
        encoder.set_buffer(1, Some(&self.db2), 0);
        encoder.set_bytes(
            2,
            std::mem::size_of::<f32>() as u64,
            &lr as *const f32 as *const _,
        );
        let n = self.dout as u32;
        encoder.set_bytes(
            3,
            std::mem::size_of::<u32>() as u64,
            &n as *const u32 as *const _,
        );
        encoder.dispatch_thread_groups(
            MTLSize::new(((n + 255) / 256) as u64, 1, 1),
            MTLSize::new(256, 1, 1),
        );

        encoder.end_encoding();
        cmd_buffer.commit();
        cmd_buffer.wait_until_completed();

        Ok(())
    }

    /// Get weights as flat vector (for SQLite persistence)
    pub fn get_weights(&self) -> Vec<f32> {
        let mut weights = Vec::new();

        unsafe {
            let w1_ptr = self.w1.contents() as *const f32;
            for i in 0..(self.din * self.hidden) {
                weights.push(*w1_ptr.add(i));
            }

            let b1_ptr = self.b1.contents() as *const f32;
            for i in 0..self.hidden {
                weights.push(*b1_ptr.add(i));
            }

            let w2_ptr = self.w2.contents() as *const f32;
            for i in 0..(self.hidden * self.dout) {
                weights.push(*w2_ptr.add(i));
            }

            let b2_ptr = self.b2.contents() as *const f32;
            for i in 0..self.dout {
                weights.push(*b2_ptr.add(i));
            }
        }

        weights
    }

    /// Set weights from flat vector (for SQLite loading)
    pub fn set_weights(&mut self, weights: &[f32]) {
        let expected = self.din * self.hidden + self.hidden + self.hidden * self.dout + self.dout;
        assert_eq!(weights.len(), expected, "Weight vector size mismatch");

        let mut offset = 0;

        unsafe {
            // W1
            let w1_ptr = self.w1.contents() as *mut f32;
            for i in 0..(self.din * self.hidden) {
                *w1_ptr.add(i) = weights[offset + i];
            }
            offset += self.din * self.hidden;

            // b1
            let b1_ptr = self.b1.contents() as *mut f32;
            for i in 0..self.hidden {
                *b1_ptr.add(i) = weights[offset + i];
            }
            offset += self.hidden;

            // W2
            let w2_ptr = self.w2.contents() as *mut f32;
            for i in 0..(self.hidden * self.dout) {
                *w2_ptr.add(i) = weights[offset + i];
            }
            offset += self.hidden * self.dout;

            // b2
            let b2_ptr = self.b2.contents() as *mut f32;
            for i in 0..self.dout {
                *b2_ptr.add(i) = weights[offset + i];
            }
        }
    }
}

//=============================================================================
// Specialized Neural Bundle
//=============================================================================

pub struct NeuroCell {
    pub predictor: MLP, // P: din=15, h=32, dout=1 (forecasts λ₁)
    pub router: MLP,    // R: din=64, h=64, dout=32 (A/V mixing)
    pub regulator: MLP, // G: din=20, h=32, dout=5 (control signals)

    // Learning rates
    pub lr_predictor: f32,
    pub lr_router: f32,
    pub lr_regulator: f32,

    // Internal buffers for inference
    device: Device,
    pred_input: Buffer,    // [1, 15]
    pred_output: Buffer,   // [1, 1]
    router_input: Buffer,  // [1, 64]
    router_output: Buffer, // [1, 32]
    reg_input: Buffer,     // [1, 20]
    reg_output: Buffer,    // [1, 5]
}

impl NeuroCell {
    pub fn new(device: &Device, library: &Library) -> Result<Self, String> {
        // Create three specialized MLPs
        let predictor = MLP::new(device, library, 15, 32, 1)?;
        let router = MLP::new(device, library, 64, 64, 32)?;
        let regulator = MLP::new(device, library, 20, 32, 5)?;

        // Allocate inference buffers
        let pred_input = device.new_buffer(15 * 4, MTLResourceOptions::StorageModeShared);
        let pred_output = device.new_buffer(4, MTLResourceOptions::StorageModeShared);
        let router_input = device.new_buffer(64 * 4, MTLResourceOptions::StorageModeShared);
        let router_output = device.new_buffer(32 * 4, MTLResourceOptions::StorageModeShared);
        let reg_input = device.new_buffer(20 * 4, MTLResourceOptions::StorageModeShared);
        let reg_output = device.new_buffer(5 * 4, MTLResourceOptions::StorageModeShared);

        Ok(Self {
            predictor,
            router,
            regulator,
            lr_predictor: 0.001,
            lr_router: 0.0005,
            lr_regulator: 0.0003,
            device: device.clone(),
            pred_input,
            pred_output,
            router_input,
            router_output,
            reg_input,
            reg_output,
        })
    }

    /// Predictor forward: predicts next λ₁
    /// Input: [λ₁, λ₂, λ₃, spread, fill%, audio_energy, video_energy, ...]
    pub fn predict_lambda1(&mut self, features: &[f32; 15]) -> Result<f32, String> {
        // Copy input
        unsafe {
            let ptr = self.pred_input.contents() as *mut f32;
            for i in 0..15 {
                *ptr.add(i) = features[i];
            }
        }

        // Forward pass
        self.predictor
            .forward(&self.pred_input, &self.pred_output, 1)?;

        // Read output
        let pred = unsafe {
            let ptr = self.pred_output.contents() as *const f32;
            *ptr
        };

        Ok(pred)
    }

    /// Router forward: computes A/V mixing weights
    /// Input: [audio_spectrum (32 bins), video_spectrum (32 bins)]
    pub fn route_features(&mut self, av_features: &[f32; 64]) -> Result<[f32; 32], String> {
        // Copy input
        unsafe {
            let ptr = self.router_input.contents() as *mut f32;
            for i in 0..64 {
                *ptr.add(i) = av_features[i];
            }
        }

        // Forward pass
        self.router
            .forward(&self.router_input, &self.router_output, 1)?;

        // Read output
        let mut weights = [0.0f32; 32];
        unsafe {
            let ptr = self.router_output.contents() as *const f32;
            for i in 0..32 {
                weights[i] = *ptr.add(i);
            }
        }

        Ok(weights)
    }

    /// Regulator forward: emits control signals
    /// Input: [λ₁, λ₂, λ₃, spread, fill%, pred_error, router_norm, ...]
    /// Output: [Δaudio_period, Δvideo_period, Δlr_pred, Δlr_route, membrane_tension]
    pub fn regulate(&mut self, state: &[f32; 20]) -> Result<[f32; 5], String> {
        // Copy input
        unsafe {
            let ptr = self.reg_input.contents() as *mut f32;
            for i in 0..20 {
                *ptr.add(i) = state[i];
            }
        }

        // Forward pass
        self.regulator
            .forward(&self.reg_input, &self.reg_output, 1)?;

        // Read output
        let mut control = [0.0f32; 5];
        unsafe {
            let ptr = self.reg_output.contents() as *const f32;
            for i in 0..5 {
                control[i] = *ptr.add(i);
            }
        }

        Ok(control)
    }

    /// Train predictor: MSE loss on λ₁ forecast
    pub fn train_predictor(&mut self, features: &[f32; 15], target: f32) -> Result<f32, String> {
        // Forward pass
        let pred = self.predict_lambda1(features)?;

        // Compute loss
        let loss = 0.5 * (pred - target).powi(2);

        // Compute gradient
        let dy = pred - target;

        // Backward pass
        self.predictor.backward(&[dy], 1);

        // Update weights
        self.predictor.update(self.lr_predictor)?;

        Ok(loss)
    }

    /// Train router: distillation loss (learn to mimic covariance update)
    pub fn train_router(
        &mut self,
        av_features: &[f32; 64],
        target_weights: &[f32; 32],
    ) -> Result<f32, String> {
        // Forward pass
        let pred_weights = self.route_features(av_features)?;

        // MSE loss
        let mut loss = 0.0;
        let mut dy = [0.0f32; 32];
        for i in 0..32 {
            let diff = pred_weights[i] - target_weights[i];
            loss += 0.5 * diff * diff;
            dy[i] = diff;
        }

        // Backward pass
        self.router.backward(&dy, 1);

        // Update weights
        self.router.update(self.lr_router)?;

        Ok(loss)
    }

    /// Train regulator: stability loss (penalize large control signals)
    pub fn train_regulator(
        &mut self,
        state: &[f32; 20],
        stability_target: f32,
    ) -> Result<f32, String> {
        // Forward pass
        let control = self.regulate(state)?;

        // L2 penalty: want small control signals for stability
        let mut loss = 0.0;
        let mut dy = [0.0f32; 5];
        for i in 0..5 {
            loss += 0.5 * control[i] * control[i];
            dy[i] = control[i];
        }

        // Also penalize deviation from stability target
        let norm = control.iter().map(|x| x * x).sum::<f32>().sqrt();
        let target_loss = 0.5 * (norm - stability_target).powi(2);
        loss += target_loss;

        // Backward pass
        self.regulator.backward(&dy, 1);

        // Update weights
        self.regulator.update(self.lr_regulator)?;

        Ok(loss)
    }

    /// Get all weights from predictor
    pub fn get_predictor_weights(&self) -> Vec<f32> {
        self.predictor.get_weights()
    }

    /// Get all weights from router
    pub fn get_router_weights(&self) -> Vec<f32> {
        self.router.get_weights()
    }

    /// Get all weights from regulator
    pub fn get_regulator_weights(&self) -> Vec<f32> {
        self.regulator.get_weights()
    }

    /// Load predictor weights
    pub fn load_predictor_weights(&mut self, weights: &[f32]) {
        self.predictor.set_weights(weights);
    }

    /// Load router weights
    pub fn load_router_weights(&mut self, weights: &[f32]) {
        self.router.set_weights(weights);
    }

    /// Load regulator weights
    pub fn load_regulator_weights(&mut self, weights: &[f32]) {
        self.regulator.set_weights(weights);
    }
}

//=============================================================================
// Tests
//=============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mlp_creation() {
        let device = Device::system_default().expect("No Metal device");
        let shader_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("shaders/nn.metal");
        let shader_src = std::fs::read_to_string(shader_path).expect("Failed to read shader");
        let library = device
            .new_library_with_source(&shader_src, &CompileOptions::new())
            .expect("Failed to compile shaders");

        let mlp = MLP::new(&device, &library, 10, 32, 1).expect("Failed to create MLP");

        assert_eq!(mlp.din, 10);
        assert_eq!(mlp.hidden, 32);
        assert_eq!(mlp.dout, 1);
    }

    #[test]
    fn test_neurocell_creation() {
        let device = Device::system_default().expect("No Metal device");
        let shader_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("shaders/nn.metal");
        let shader_src = std::fs::read_to_string(shader_path).expect("Failed to read shader");
        let library = device
            .new_library_with_source(&shader_src, &CompileOptions::new())
            .expect("Failed to compile shaders");

        let cell = NeuroCell::new(&device, &library).expect("Failed to create NeuroCell");

        assert_eq!(cell.predictor.din, 15);
        assert_eq!(cell.router.din, 64);
        assert_eq!(cell.regulator.din, 20);
    }
}
