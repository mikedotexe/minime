// src/buffer_pool.rs
// Simple buffer pool for transient Metal allocations, modeled on MLX's BufferCache.
// Eliminates per-call new_buffer/new_shared in hot paths by recycling buffers keyed by size.

use metal::*;
use std::collections::BTreeMap;

pub struct BufferPool {
    dev: Device,
    free: BTreeMap<u64, Vec<Buffer>>,
}

impl BufferPool {
    pub fn new(dev: Device) -> Self {
        Self {
            dev,
            free: BTreeMap::new(),
        }
    }

    /// Acquire a buffer of at least `bytes` size (StorageModeShared, page-aligned).
    /// Reuses a cached buffer if one exists for this aligned size.
    pub fn acquire(&mut self, bytes: u64) -> Buffer {
        let aligned = Self::page_align(bytes);
        if let Some(list) = self.free.get_mut(&aligned) {
            if let Some(buf) = list.pop() {
                return buf;
            }
        }
        self.dev.new_buffer(
            aligned,
            MTLResourceOptions::StorageModeShared | MTLResourceOptions::HazardTrackingModeUntracked,
        )
    }

    /// Round up to 16384-byte page boundary (Apple Silicon vm_page_size).
    #[inline]
    fn page_align(bytes: u64) -> u64 {
        const PAGE_SIZE: u64 = 16384;
        (bytes + PAGE_SIZE - 1) & !(PAGE_SIZE - 1)
    }

    /// Return a buffer to the pool for reuse.
    pub fn release(&mut self, buf: Buffer) {
        let size = buf.length();
        self.free.entry(size).or_default().push(buf);
    }
}
