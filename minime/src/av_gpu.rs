// src/av_gpu.rs
// GPU-first video features w/ unified memory + mem-mode switch.
//
#![allow(dead_code)]
// Public API:
//   let mut av = AvGpu::new("shaders/av_features.metal", MemMode::Shared)?;
//   av.set_frame_size(128, 128)?;
//   let feat = av.process_frame_gray8(&frame_bytes)?; // [f32; 8]
//
// Notes:
// - For MemMode::Managed/Private we add required blit synchronizations.

use anyhow::{bail, Result};
use metal::*;
use std::mem;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum MemMode {
    Shared,
    Managed,
    Private,
}

pub struct AvGpu {
    dev: Device,
    q: CommandQueue,
    pso: ComputePipelineState,
    tex: Texture,
    prev: Buffer,  // NPIX * f32 (StorageMode according to mem-mode)
    accum: Buffer, // 8 atomics (as f32s)
    w: usize,
    h: usize,
    mem_mode: MemMode,
    // For Managed/Private paths:
    blit_q: Option<CommandQueue>,
}

impl AvGpu {
    pub fn new(metal_path: &str, mem_mode: MemMode) -> Result<Self> {
        let dev =
            Device::system_default().ok_or_else(|| anyhow::anyhow!("Metal device unavailable"))?;
        let q = dev.new_command_queue();
        let blit_q = match mem_mode {
            MemMode::Shared => None,
            _ => Some(dev.new_command_queue()),
        };

        // Compile shader
        let src = std::fs::read_to_string(metal_path)?;
        let opts = CompileOptions::new();
        let lib = dev
            .new_library_with_source(&src, &opts)
            .map_err(|_| anyhow::anyhow!("Metal pipeline build failed"))?;
        let kf = lib
            .get_function("av_accumulate_features", None)
            .map_err(|_| anyhow::anyhow!("Metal function 'av_accumulate_features' not found"))?;
        let pso = dev
            .new_compute_pipeline_state_with_function(&kf)
            .map_err(|_| anyhow::anyhow!("Metal pipeline build failed - PSO creation"))?;

        // default frame size 128x128
        let (w, h) = (128usize, 128usize);
        let tex = Self::make_gray_tex(&dev, w as u64, h as u64, mem_mode)?;

        // buffers (page-aligned for SLC fast path)
        let npix = (w * h) as usize;
        let prev = dev.new_buffer(
            Self::page_align((npix * mem::size_of::<f32>()) as u64),
            Self::opts(mem_mode),
        );
        let accum = dev.new_buffer(
            Self::page_align((8 * mem::size_of::<f32>()) as u64),
            Self::opts(MemMode::Shared), // atomics readable on CPU fast
        );

        Ok(Self {
            dev,
            q,
            pso,
            tex,
            prev,
            accum,
            w,
            h,
            mem_mode,
            blit_q,
        })
    }

    pub fn set_frame_size(&mut self, w: usize, h: usize) -> Result<()> {
        self.w = w;
        self.h = h;
        self.tex = Self::make_gray_tex(&self.dev, w as u64, h as u64, self.mem_mode)?;
        self.prev = self.dev.new_buffer(
            Self::page_align((w * h * mem::size_of::<f32>()) as u64),
            Self::opts(self.mem_mode),
        );
        self.accum = self.dev.new_buffer(
            Self::page_align((8 * mem::size_of::<f32>()) as u64),
            Self::opts(MemMode::Shared),
        );
        Ok(())
    }

    fn make_gray_tex(dev: &Device, w: u64, h: u64, mem_mode: MemMode) -> Result<Texture> {
        let desc = TextureDescriptor::new();
        desc.set_pixel_format(MTLPixelFormat::R8Unorm);
        desc.set_texture_type(MTLTextureType::D2);
        desc.set_width(w);
        desc.set_height(h);
        desc.set_storage_mode(match mem_mode {
            MemMode::Shared => MTLStorageMode::Shared,
            MemMode::Managed => MTLStorageMode::Managed,
            MemMode::Private => MTLStorageMode::Private,
        });
        desc.set_usage(MTLTextureUsage::ShaderRead);
        Ok(dev.new_texture(&desc))
    }

    #[inline]
    fn opts(mem_mode: MemMode) -> MTLResourceOptions {
        // Page-align + untracked hazard tracking for MLX-style allocation efficiency.
        // HazardTrackingModeUntracked: we manage barriers manually via separate encoders.
        let untracked = MTLResourceOptions::HazardTrackingModeUntracked;
        match mem_mode {
            MemMode::Shared => MTLResourceOptions::StorageModeShared | untracked,
            MemMode::Managed => MTLResourceOptions::StorageModeManaged | untracked,
            MemMode::Private => MTLResourceOptions::StorageModePrivate | untracked,
        }
    }

    /// Page-aligned allocation (rounds up to 16384 bytes, Apple Silicon vm_page_size)
    #[inline]
    fn page_align(bytes: u64) -> u64 {
        const PAGE_SIZE: u64 = 16384;
        (bytes + PAGE_SIZE - 1) & !(PAGE_SIZE - 1)
    }

    pub fn process_frame_gray8(&mut self, gray: &[u8]) -> Result<[f32; 8]> {
        let want = self.w * self.h;
        if gray.len() != want {
            bail!(
                "frame size mismatch: got {} bytes, want {}",
                gray.len(),
                want
            );
        }

        // Zero atomics
        unsafe {
            std::ptr::write_bytes(
                self.accum.contents() as *mut u8,
                0,
                8 * mem::size_of::<f32>(),
            );
        }

        // Upload pixels → texture
        // For Shared we can replace region directly; for Managed/Private we use blit.
        let bytes_per_row = self.w as u64;
        if self.mem_mode == MemMode::Shared {
            let region = MTLRegion {
                origin: MTLOrigin { x: 0, y: 0, z: 0 },
                size: MTLSize {
                    width: self.w as u64,
                    height: self.h as u64,
                    depth: 1,
                },
            };
            self.tex
                .replace_region(region, 0, gray.as_ptr() as *const _, bytes_per_row);
        } else {
            // Private: stage to a shared buffer then blit to tex
            let stage = self
                .dev
                .new_buffer(gray.len() as u64, MTLResourceOptions::StorageModeShared);
            unsafe {
                std::ptr::copy_nonoverlapping(
                    gray.as_ptr(),
                    stage.contents() as *mut u8,
                    gray.len(),
                );
            }
            let cb = self.blit_q.as_ref().unwrap().new_command_buffer();
            let blit = cb.new_blit_command_encoder();
            let bytes_per_image = gray.len() as u64;
            blit.copy_from_buffer_to_texture(
                &stage,
                0,
                bytes_per_row,
                bytes_per_image,
                MTLSize {
                    width: self.w as u64,
                    height: self.h as u64,
                    depth: 1,
                },
                &self.tex,
                0,
                0,
                MTLOrigin { x: 0, y: 0, z: 0 },
                MTLBlitOption::empty(),
            );
            blit.end_encoding();
            cb.commit();
            cb.wait_until_completed();
        }

        // Dispatch kernel
        let cb = self.q.new_command_buffer();
        let enc = cb.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&self.pso);
        enc.set_texture(0, Some(&self.tex));
        enc.set_buffer(0, Some(&self.accum), 0);
        enc.set_buffer(1, Some(&self.prev), 0);
        let tg = MTLSize {
            width: 16,
            height: 16,
            depth: 1,
        };
        let grid = MTLSize {
            width: self.w as u64,
            height: self.h as u64,
            depth: 1,
        };
        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cb.commit();
        cb.wait_until_completed();

        // Read atomics (zero-copy)
        let acc = unsafe { std::slice::from_raw_parts(self.accum.contents() as *const f32, 8) };
        let npix = (self.w * self.h) as f32;

        let sum = acc[0];
        let sumsq = acc[1];
        let motion = acc[2];
        let edge = acc[3];
        let h0 = acc[4];
        let h1 = acc[5];
        let h2 = acc[6];
        let h3 = acc[7];
        let mean = sum / npix;
        let var = (sumsq / npix) - mean * mean;
        let hsum = (h0 + h1 + h2 + h3).max(1.0);
        let feat = [
            mean,
            var.max(0.0),
            motion / npix, // avg abs ΔI
            edge / npix,   // avg |∇I|
            h0 / hsum,
            h1 / hsum,
            h2 / hsum,
            h3 / hsum,
        ];
        Ok(feat)
    }
}
