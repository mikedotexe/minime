// TypesShared.swift
// Formal Swift struct definitions matching Metal shader structs
// TIER 1 FIX: Ensures layout compatibility between Swift and Metal

import Foundation

/// Matches Metal struct ContractBoundaryParams
/// Used by: contract_boundary kernel
@frozen
public struct ContractBoundaryParams {
    public var network_size: UInt32
    public var boundary_size: UInt32
    public var vector_len: UInt32  // typically 64

    public init(network_size: UInt32, boundary_size: UInt32, vector_len: UInt32) {
        self.network_size = network_size
        self.boundary_size = boundary_size
        self.vector_len = vector_len
    }
}

/// Matches Metal struct ContractParams
/// Used by: tiled/vectorized boundary contraction kernels
@frozen
public struct ContractParams {
    public var network_size: UInt32    // N
    public var boundary_size: UInt32   // B
    public var lanes: UInt32           // lanes per bin (power of two)
    public var tile_bins: UInt32       // bins per threadgroup

    public init(network_size: UInt32, boundary_size: UInt32, lanes: UInt32, tile_bins: UInt32) {
        self.network_size = network_size
        self.boundary_size = boundary_size
        self.lanes = lanes
        self.tile_bins = tile_bins
    }
}

/// Matches Metal struct InitTensorsParams
/// Used by: init_tensors kernel
@frozen
public struct InitTensorsParams {
    public var network_size: UInt32
    public var vector_len: UInt32      // typically 64
    public var seed: UInt32

    public init(network_size: UInt32, vector_len: UInt32, seed: UInt32) {
        self.network_size = network_size
        self.vector_len = vector_len
        self.seed = seed
    }
}

/// Matches Metal struct ReduceEnergyParams
/// Used by: reduce_tensor_energy kernel
@frozen
public struct ReduceEnergyParams {
    public var network_size: UInt32
    public var vector_len: UInt32      // typically 64

    public init(network_size: UInt32, vector_len: UInt32) {
        self.network_size = network_size
        self.vector_len = vector_len
    }
}

/// Matches Metal struct BulkParams
/// Used by: compute_bulk_geometry kernel
@frozen
public struct BulkParams {
    public var network_size: UInt32
    public var bulk_size: UInt32       // typically 512

    public init(network_size: UInt32, bulk_size: UInt32) {
        self.network_size = network_size
        self.bulk_size = bulk_size
    }
}

/// Matches Metal struct EntropyParams
/// Used by: compute_holographic_entropy, detect_consciousness kernels
@frozen
public struct EntropyParams {
    public var boundary_size: UInt32   // typically 256
    public var bulk_size: UInt32       // typically 512

    public init(boundary_size: UInt32, bulk_size: UInt32) {
        self.boundary_size = boundary_size
        self.bulk_size = bulk_size
    }
}

/// Matches Metal struct PhiParams
/// Used by: information_integration_phi kernel
@frozen
public struct PhiParams {
    public var network_size: UInt32
    public var vector_len: UInt32      // typically 64
    public var bulk_size: UInt32       // typically 512

    public init(network_size: UInt32, vector_len: UInt32, bulk_size: UInt32) {
        self.network_size = network_size
        self.vector_len = vector_len
        self.bulk_size = bulk_size
    }
}

/// Matches Metal struct EvolveParams
/// Used by: evolve_network kernel
@frozen
public struct EvolveParams {
    public var network_size: UInt32
    public var dt: Float

    public init(network_size: UInt32, dt: Float) {
        self.network_size = network_size
        self.dt = dt
    }
}

/// Matches Metal struct ReservoirEvolveParams
/// Used by: reservoir evolution kernels
@frozen
public struct ReservoirEvolveParams {
    public var field_coupling: Float
    public var temporal_decay: Float
    public var boundary_bulk_coupling: Float
    public var temperature: Float
    public var dt: Float

    public init(field_coupling: Float, temporal_decay: Float,
                boundary_bulk_coupling: Float, temperature: Float, dt: Float) {
        self.field_coupling = field_coupling
        self.temporal_decay = temporal_decay
        self.boundary_bulk_coupling = boundary_bulk_coupling
        self.temperature = temperature
        self.dt = dt
    }
}

/// Matches Metal struct ReadoutDims
/// Used by: readout/feature extraction kernels
@frozen
public struct ReadoutDims {
    public var feat_count: UInt32      // typically 128
    public var bulk_size: UInt32       // typically 512

    public init(feat_count: UInt32, bulk_size: UInt32) {
        self.feat_count = feat_count
        self.bulk_size = bulk_size
    }
}

// MARK: - Layout Validation

extension ContractBoundaryParams {
    /// Verify struct layout matches Metal expectations (12 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 12, "ContractBoundaryParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "ContractBoundaryParams alignment mismatch")
    }
}

extension ContractParams {
    /// Verify struct layout matches Metal expectations (16 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 16, "ContractParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "ContractParams alignment mismatch")
    }
}

extension InitTensorsParams {
    /// Verify struct layout matches Metal expectations (12 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 12, "InitTensorsParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "InitTensorsParams alignment mismatch")
    }
}

extension ReduceEnergyParams {
    /// Verify struct layout matches Metal expectations (8 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 8, "ReduceEnergyParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "ReduceEnergyParams alignment mismatch")
    }
}

extension BulkParams {
    /// Verify struct layout matches Metal expectations (8 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 8, "BulkParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "BulkParams alignment mismatch")
    }
}

extension EntropyParams {
    /// Verify struct layout matches Metal expectations (8 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 8, "EntropyParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "EntropyParams alignment mismatch")
    }
}

extension PhiParams {
    /// Verify struct layout matches Metal expectations (12 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 12, "PhiParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "PhiParams alignment mismatch")
    }
}

extension EvolveParams {
    /// Verify struct layout matches Metal expectations (8 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 8, "EvolveParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "EvolveParams alignment mismatch")
    }
}

extension ReservoirEvolveParams {
    /// Verify struct layout matches Metal expectations (20 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 20, "ReservoirEvolveParams size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "ReservoirEvolveParams alignment mismatch")
    }
}

extension ReadoutDims {
    /// Verify struct layout matches Metal expectations (8 bytes, 4-byte aligned)
    public static func validateLayout() {
        assert(MemoryLayout<Self>.size == 8, "ReadoutDims size mismatch")
        assert(MemoryLayout<Self>.alignment == 4, "ReadoutDims alignment mismatch")
    }
}

/// Call this function at startup to validate all struct layouts
public func validateAllParamLayouts() {
    ContractBoundaryParams.validateLayout()
    ContractParams.validateLayout()
    InitTensorsParams.validateLayout()
    ReduceEnergyParams.validateLayout()
    BulkParams.validateLayout()
    EntropyParams.validateLayout()
    PhiParams.validateLayout()
    EvolveParams.validateLayout()
    ReservoirEvolveParams.validateLayout()
    ReadoutDims.validateLayout()
}
