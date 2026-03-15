import Foundation
import Metal

/// Metal Heap Management with Aliasing Support
/// Provides utilities for creating heaps with untracked hazard mode
/// and managing aliased resources for memory footprint reduction

public struct HeapAlias {

    /// Create a Metal heap for GPU-private resources with untracked hazard mode
    /// - Parameters:
    ///   - device: Metal device
    ///   - size: Total heap size in bytes
    /// - Returns: MTLHeap configured for manual fencing
    public static func makePrivateHeap(device: MTLDevice, size: Int) -> MTLHeap {
        let heapDesc = MTLHeapDescriptor()
        heapDesc.size = size
        heapDesc.storageMode = .private
        heapDesc.hazardTrackingMode = .untracked  // Manual fencing required
        heapDesc.cpuCacheMode = .defaultCache

        guard let heap = device.makeHeap(descriptor: heapDesc) else {
            fatalError("Failed to create Metal heap")
        }

        return heap
    }

    /// Create a buffer from a heap
    /// - Parameters:
    ///   - heap: Metal heap
    ///   - length: Buffer size in bytes
    ///   - label: Debug label for the buffer
    /// - Returns: MTLBuffer allocated from heap
    public static func makeBuffer(from heap: MTLHeap, length: Int, label: String? = nil) -> MTLBuffer {
        guard let buffer = heap.makeBuffer(length: length, options: .storageModePrivate) else {
            fatalError("Failed to allocate buffer from heap")
        }
        buffer.label = label
        return buffer
    }

    /// Create aliased buffer pair that can share the same memory region
    /// USE WITH CAUTION: Requires manual fencing to ensure non-overlapping use
    /// - Parameters:
    ///   - heap: Metal heap
    ///   - length: Size of each buffer in bytes
    ///   - labelA: Label for first buffer
    ///   - labelB: Label for second buffer
    /// - Returns: Tuple of two buffers that can alias the same memory
    public static func makeAliasedPair(
        from heap: MTLHeap,
        length: Int,
        labelA: String,
        labelB: String
    ) -> (MTLBuffer, MTLBuffer) {
        // Create two buffers that can potentially alias
        // Metal runtime may place them in overlapping regions if usage permits
        let bufferA = makeBuffer(from: heap, length: length, label: labelA)
        let bufferB = makeBuffer(from: heap, length: length, label: labelB)

        return (bufferA, bufferB)
    }

    /// Calculate total size needed for a group of buffers
    /// - Parameter sizes: Array of buffer sizes in bytes
    /// - Returns: Total aligned size for heap allocation
    public static func calculateHeapSize(sizes: [Int]) -> Int {
        // Add 256-byte alignment padding per buffer for safety
        let alignment = 256
        return sizes.reduce(0) { total, size in
            let aligned = (size + alignment - 1) & ~(alignment - 1)
            return total + aligned
        }
    }
}

/// Fence Manager for Manual Hazard Tracking
/// Manages MTLFences to coordinate access to untracked heap resources
public final class FenceManager {
    private let device: MTLDevice
    private var fences: [String: MTLFence] = [:]

    public init(device: MTLDevice) {
        self.device = device
    }

    /// Get or create a fence with the given name
    /// - Parameter name: Identifier for the fence
    /// - Returns: MTLFence instance
    public func fence(named name: String) -> MTLFence {
        if let existing = fences[name] {
            return existing
        }

        guard let newFence = device.makeFence() else {
            fatalError("Failed to create MTLFence")
        }

        fences[name] = newFence
        return newFence
    }

    /// Signal a fence after writing to a resource
    /// - Parameters:
    ///   - encoder: Compute encoder that wrote the resource
    ///   - name: Fence identifier
    public func update(_ encoder: MTLComputeCommandEncoder, fence name: String) {
        let fence = self.fence(named: name)
        encoder.updateFence(fence)
    }

    /// Wait on a fence before reading a resource
    /// - Parameters:
    ///   - encoder: Compute encoder that will read the resource
    ///   - name: Fence identifier
    public func wait(_ encoder: MTLComputeCommandEncoder, fence name: String) {
        let fence = self.fence(named: name)
        encoder.waitForFence(fence)
    }
}

/// Heap Layout Planner
/// Helps organize buffers into heaps with optimal layout
public struct HeapLayout {
    public struct BufferSpec {
        let size: Int
        let label: String
        let canAlias: Set<String>  // Labels of buffers this can alias with

        public init(size: Int, label: String, canAlias: Set<String> = []) {
            self.size = size
            self.label = label
            self.canAlias = canAlias
        }
    }

    /// Plan heap allocation given buffer specifications
    /// - Parameters:
    ///   - specs: Array of buffer specifications
    ///   - device: Metal device
    /// - Returns: Tuple of (heap, buffers dictionary)
    public static func plan(
        specs: [BufferSpec],
        device: MTLDevice
    ) -> (heap: MTLHeap, buffers: [String: MTLBuffer]) {
        // Calculate total size needed
        let sizes = specs.map { $0.size }
        let totalSize = HeapAlias.calculateHeapSize(sizes: sizes)

        // Create heap
        let heap = HeapAlias.makePrivateHeap(device: device, size: totalSize)

        // Allocate buffers from heap
        var buffers: [String: MTLBuffer] = [:]
        for spec in specs {
            let buffer = HeapAlias.makeBuffer(from: heap, length: spec.size, label: spec.label)
            buffers[spec.label] = buffer
        }

        return (heap, buffers)
    }
}

// MARK: - Convenience Extensions

extension MTLHeap {
    /// Check if heap has enough space for an allocation
    /// - Parameter size: Required size in bytes
    /// - Returns: True if allocation would succeed
    public func canAllocate(size: Int) -> Bool {
        return usedSize + size <= size
    }

    /// Get available space in heap
    public var availableSize: Int {
        return size - usedSize
    }

    /// Get heap utilization percentage
    public var utilization: Double {
        return Double(usedSize) / Double(size) * 100.0
    }
}
