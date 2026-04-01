use std::path::Path;

use anyhow::{Context, Result};
use image::{ImageBuffer, Luma};

use crate::telemetry::{splitmix64, unit_from_u64, ControlFrame};

pub const WIDTH: usize = 128;
pub const HEIGHT: usize = 128;

pub struct VideoEngine {
    phase: f32,
    frame_index: u64,
    previous: Vec<u8>,
}

impl VideoEngine {
    #[must_use]
    pub fn new() -> Self {
        Self {
            phase: 0.0,
            frame_index: 0,
            previous: vec![0; WIDTH * HEIGHT],
        }
    }

    #[must_use]
    pub fn render_frame(&mut self, control: &ControlFrame) -> Vec<u8> {
        self.frame_index = self.frame_index.wrapping_add(1);
        self.phase += 0.05 + control.motion * 0.35 + control.snapshot.net_flux * 0.08;

        let group_a = ((control.snapshot.cpu + control.snapshot.net_flux) * 0.5).clamp(0.0, 1.0);
        let group_b = ((control.snapshot.mem + control.snapshot.load) * 0.5).clamp(0.0, 1.0);
        let group_c =
            ((control.snapshot.cpu_imbalance + control.snapshot.disk_flux) * 0.5).clamp(0.0, 1.0);
        let group_d =
            ((control.snapshot.process_density + control.snapshot.swap) * 0.5).clamp(0.0, 1.0);
        let quadrant_targets = [group_a, group_b, group_c, group_d];

        let mut frame = vec![0_u8; WIDTH * HEIGHT];
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                let idx = y * WIDTH + x;
                let nx = x as f32 / (WIDTH - 1) as f32 * 2.0 - 1.0;
                let ny = y as f32 / (HEIGHT - 1) as f32 * 2.0 - 1.0;
                let radial = ((nx * nx + ny * ny).sqrt() * 2.4 - self.phase * 0.6).sin();
                let stripe = ((nx * (2.0 + control.snapshot.cpu * 8.0))
                    + (ny * (1.4 + control.snapshot.load * 6.0))
                    + self.phase)
                    .cos();
                let edge = ((nx * (6.0 + control.edge_bias * 10.0) + self.phase * 1.3).sin().abs()
                    + (ny * (5.0 + control.contrast * 8.0) - self.phase * 0.9).sin().abs())
                    * 0.5;

                let quadrant_idx = match (x >= WIDTH / 2, y >= HEIGHT / 2) {
                    (false, false) => 0,
                    (true, false) => 1,
                    (false, true) => 2,
                    (true, true) => 3,
                };
                let quadrant_bias = quadrant_targets[quadrant_idx];

                let seed = splitmix64(
                    control.root_seed
                        ^ ((idx as u64 + 1).wrapping_mul(0x9e3779b97f4a7c15))
                        ^ self.frame_index.rotate_left(17),
                );
                let noise = unit_from_u64(seed) * 2.0 - 1.0;
                let value = control.brightness
                    + (control.contrast * 0.30 * radial)
                    + (control.contrast * 0.24 * stripe)
                    + (control.edge_bias * 0.18 * edge)
                    + (0.18 * (quadrant_bias - 0.5))
                    + (noise * 0.08 * (0.35 + control.entropy))
                    + (control.motion * 0.08 * ((self.phase + nx * 4.0 + ny * 3.0).sin()));

                let current = (value.clamp(0.0, 1.0) * 255.0) as u8;
                let previous = self.previous[idx] as f32 / 255.0;
                let motion_blend = (0.20 + control.motion * 0.45).clamp(0.0, 0.8);
                let blended = previous * (1.0 - motion_blend) + (current as f32 / 255.0) * motion_blend;
                frame[idx] = (blended.clamp(0.0, 1.0) * 255.0) as u8;
            }
        }
        self.previous.clone_from(&frame);
        frame
    }
}

pub fn save_jpeg(path: &Path, frame: &[u8]) -> Result<()> {
    let image: ImageBuffer<Luma<u8>, Vec<u8>> =
        ImageBuffer::from_vec(WIDTH as u32, HEIGHT as u32, frame.to_vec())
            .context("failed to build grayscale image")?;
    image
        .save(path)
        .with_context(|| format!("failed to save {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::telemetry::{ControlFrame, TelemetrySnapshot};

    fn control(snapshot: TelemetrySnapshot, root_seed: u64) -> ControlFrame {
        ControlFrame {
            snapshot,
            gain: 0.2,
            cutoff_hz: 1_000.0,
            air_mix: 0.02,
            width: 0.5,
            drift_hz: 0.02,
            seed_mix: 0.05,
            entropy: 0.5,
            motion: 0.4,
            brightness: 0.6,
            contrast: 0.5,
            edge_bias: 0.5,
            root_seed,
            voice_weights: [0.25; 4],
            voice_cut_mul: [1.0; 4],
            voice_pan: [-0.4, -0.1, 0.1, 0.4],
            voice_seeds: [1, 2, 3, 4],
        }
    }

    #[test]
    fn frame_size_is_fixed() {
        let mut engine = VideoEngine::new();
        let frame = engine.render_frame(&control(TelemetrySnapshot::default(), 7));
        assert_eq!(frame.len(), WIDTH * HEIGHT);
    }

    #[test]
    fn frame_changes_with_telemetry() {
        let mut engine = VideoEngine::new();
        let low = engine.render_frame(&control(
            TelemetrySnapshot {
                cpu: 0.1,
                mem: 0.2,
                load: 0.1,
                ..TelemetrySnapshot::default()
            },
            1,
        ));
        let high = engine.render_frame(&control(
            TelemetrySnapshot {
                cpu: 0.9,
                mem: 0.8,
                load: 0.9,
                net_flux: 0.7,
                disk_flux: 0.6,
                process_density: 0.8,
                cpu_imbalance: 0.7,
                ..TelemetrySnapshot::default()
            },
            2,
        ));
        assert_ne!(low, high);
    }
}
