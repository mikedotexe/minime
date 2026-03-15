import Foundation
import Metal
import simd

// ======== Low-level helpers ========

@inline(__always)
private func alignUp(_ x: Int, _ a: Int) -> Int { (x + (a - 1)) & ~(a - 1) }

final class MetalKit {
    let device: MTLDevice
    let queue: MTLCommandQueue
    let lib: MTLLibrary

    init() throws {
        guard let dev = MTLCreateSystemDefaultDevice() else { throw NSError(domain: "Metal", code: 1) }
        self.device = dev
        guard let q = dev.makeCommandQueue() else { throw NSError(domain: "Metal", code: 2) }
        self.queue = q

        // Try to load default library first (works with Xcode builds)
        if let defaultLib = dev.makeDefaultLibrary() {
            self.lib = defaultLib
        } else {
            // Fallback: compile shader source at runtime (for SPM)
            let shaderPath = "/Users/mikepurvis/other/mikeconsciouness/holographic-engine/Sources/HolographicEngine/Holographic.metal"
            guard let source = try? String(contentsOfFile: shaderPath, encoding: .utf8) else {
                throw NSError(domain: "MetalLib", code: 3, userInfo: ["msg": "Cannot load shader source"])
            }
            self.lib = try dev.makeLibrary(source: source, options: nil)
        }
    }

    func pipeline(_ name: String) throws -> MTLComputePipelineState {
        guard let fn = lib.makeFunction(name: name) else { throw NSError(domain: "MetalFn", code: 4, userInfo: ["name": name]) }
        return try device.makeComputePipelineState(function: fn)
    }

    func makeBuffer(bytes: Int) -> MTLBuffer {
        device.makeBuffer(length: bytes, options: [.storageModeShared])!
    }

    // OPTIMIZED: Private storage for GPU-only buffers (10-20% faster GPU access)
    func makePrivateBuffer(bytes: Int) -> MTLBuffer {
        device.makeBuffer(length: bytes, options: [.storageModePrivate])!
    }

    // Removed: dispatch wrapper - now using global dispatch1D/2D/3D helpers from ComputeDispatch.swift
}

// ======== Holographic Consciousness Engine (SoA) ========

public struct HoloState {
    public var phiComplexity: Float
    public var globalCoherence: Float
    public var boundaryEntropy: Float
    public var bulkEntropy: Float
    public var ratio: Float
    public var infoIntegration: Float
    public var selfAwareness: Float
    public var emergence: Float
    public var processingEff: Float
    public var level: Float
}

public final class HolographicConsciousnessEngine {
    // sizes
    public let networkSize: Int
    public let boundarySize: Int
    public let bulkSize: Int
    public let vecLen: Int

    // metal
    let m: MetalKit
    let kInit, kReduce, kContract, kBulk, kEnt, kPhi, kDetect, kEvolve: MTLComputePipelineState
    let kContractV4: MTLComputePipelineState
    let kScrub: MTLComputePipelineState

    // PHASE 2: Heap-based memory management
    let privateHeap: MTLHeap?          // Heap for GPU-private buffers
    let fenceManager: FenceManager     // Manual hazard tracking

    // buffers
    let tensorData: MTLBuffer          // N*64 floats
    let tensorEnergy: MTLBuffer        // N
    let boundaryActivity: MTLBuffer    // N - concentration metric (not entropy)
    let entEntropy: MTLBuffer          // N - reserved for proper Shannon entropy (future)
    let boundaryState: MTLBuffer       // B
    let bulkGeometry: MTLBuffer        // G
    let phiValues: MTLBuffer           // N
    let consciousness: MTLBuffer       // 18 (10 output + 8 temp for atomics)
    let environment: MTLBuffer         // N

    // Public accessors for affine mapper integration
    public var device: MTLDevice { m.device }
    public var commandQueue: MTLCommandQueue { m.queue }
    public var environmentBuffer: MTLBuffer { environment }

    public init(networkSize: Int = 1000, boundarySize: Int = 256, bulkSize: Int = 512, vectorLen: Int = 64) throws {
        self.networkSize = networkSize
        self.boundarySize = boundarySize
        self.bulkSize = bulkSize
        self.vecLen = vectorLen

        self.m = try MetalKit()
        self.kInit     = try m.pipeline("init_tensors")
        self.kReduce   = try m.pipeline("reduce_tensor_energy")
        self.kContract = try m.pipeline("contract_boundary_tiled")
        self.kContractV4 = try m.pipeline("contract_boundary_tiled_vec4")
        self.kBulk     = try m.pipeline("compute_bulk_geometry")
        self.kEnt      = try m.pipeline("compute_holographic_entropy")
        self.kPhi      = try m.pipeline("information_integration_phi")
        self.kDetect   = try m.pipeline("detect_consciousness")
        self.kEvolve   = try m.pipeline("evolve_network")
        self.kScrub    = try m.pipeline("scrub_nan_inf")

        // PHASE 2: Create heap for GPU-private buffers
        // Half-precision for intermediate buffers (2× bandwidth)
        let privateSizes = [
            networkSize * MemoryLayout<Float16>.stride,     // tensorEnergy (half)
            networkSize * MemoryLayout<Float16>.stride,     // boundaryActivity (half)
            networkSize * MemoryLayout<Float16>.stride,     // entEntropy (half)
            bulkSize * MemoryLayout<Float16>.stride,        // bulkGeometry (half)
            networkSize * MemoryLayout<Float>.stride        // phiValues (float32)
        ]

        let heapSize = HeapAlias.calculateHeapSize(sizes: privateSizes)
        let heap = HeapAlias.makePrivateHeap(device: m.device, size: heapSize)
        self.privateHeap = heap

        // Initialize fence manager for manual hazard tracking
        self.fenceManager = FenceManager(device: m.device)

        // OPTIMIZED: Heap-based allocation with half-precision intermediates
        self.tensorData    = m.makeBuffer(bytes: MemoryLayout<Float>.stride * networkSize * vectorLen)        // Shared: CPU writes, float32
        self.tensorEnergy  = HeapAlias.makeBuffer(from: heap, length: MemoryLayout<Float16>.stride * networkSize, label: "tensorEnergy")   // half
        self.boundaryActivity  = HeapAlias.makeBuffer(from: heap, length: MemoryLayout<Float16>.stride * networkSize, label: "boundaryActivity")   // half
        self.entEntropy    = HeapAlias.makeBuffer(from: heap, length: MemoryLayout<Float16>.stride * networkSize, label: "entEntropy")     // half
        self.boundaryState = m.makeBuffer(bytes: MemoryLayout<Float>.stride * boundarySize)                   // Shared: float32
        self.bulkGeometry  = HeapAlias.makeBuffer(from: heap, length: MemoryLayout<Float16>.stride * bulkSize, label: "bulkGeometry")      // half
        self.phiValues     = HeapAlias.makeBuffer(from: heap, length: MemoryLayout<Float>.stride * networkSize, label: "phiValues")         // float32
        self.consciousness = m.makeBuffer(bytes: MemoryLayout<Float>.stride * 18)                             // Shared: float32
        self.environment   = m.makeBuffer(bytes: MemoryLayout<Float>.stride * networkSize)                    // Shared: float32

        try self.initialize()
        autoTuneBoundary()

        // Run preflight sanity checks
        let pf = Preflight.run(engine: self)
        for m in pf.messages { print(pf.ok ? "ℹ️  preflight:" : "❌ preflight:", m) }
        if pf.ok {
            print("✅ Preflight OK")
        } else {
            print("⚠️  Preflight had issues but continuing...")
        }
    }

    private func initialize() throws {
        guard let cb = m.queue.makeCommandBuffer(),
              let enc = cb.makeComputeCommandEncoder() else { throw NSError(domain: "Init", code: 9) }

        enc.setComputePipelineState(kInit)
        enc.setBuffer(tensorData, offset: 0, index: 0)
        enc.setBuffer(tensorEnergy, offset: 0, index: 1)
        enc.setBuffer(boundaryActivity, offset: 0, index: 2)
        enc.setBuffer(entEntropy, offset: 0, index: 3)
        // TIER 1 FIX: Use formal struct definition from TypesShared.swift
        var P = InitTensorsParams(network_size: UInt32(networkSize), vector_len: UInt32(vecLen), seed: 1337)
        enc.setBytes(&P, length: MemoryLayout<InitTensorsParams>.stride, index: 9)
        dispatch1D(enc, pso: kInit, count: networkSize)
        enc.endEncoding()
        cb.commit()
        cb.waitUntilCompleted()
    }

    private func zeroBuffer(_ buf: MTLBuffer) {
        // OPTIMIZED: Handle both Shared and Private storage modes
        if buf.storageMode == .shared {
            buf.contents().assumingMemoryBound(to: UInt8.self).assign(repeating: 0, count: buf.length)
        } else {
            // For Private buffers, use GPU blit encoder to fill with zeros
            guard let cb = m.queue.makeCommandBuffer(),
                  let blitEnc = cb.makeBlitCommandEncoder() else { return }
            blitEnc.fill(buffer: buf, range: 0..<buf.length, value: 0)
            blitEnc.endEncoding()
            cb.commit()
            cb.waitUntilCompleted()
        }
    }

    private func writeEnvironment(_ ext: [Float]?, step: Int) {
        let p = environment.contents().bindMemory(to: Float.self, capacity: networkSize)
        if let ext, !ext.isEmpty {
            let n = networkSize
            let k = ext.count
            // simple projection by tiling if ext != n
            if k == n {
                p.assign(from: ext, count: n)
            } else {
                for i in 0..<n { p[i] = ext[i % k] }
            }
        } else {
            // default synthetic drive
            let t = Float(step) * 0.07
            for i in 0..<networkSize {
                let s = sinf(t + Float(i) * 0.013)
                let c = cosf(t * 1.7 + Float(i) * 0.021)
                p[i] = 0.6*s + 0.3*c
            }
        }
    }

    public func step(stepIndex: Int, dt: Float = 0.01, externalEnv: [Float]? = nil) throws -> HoloState {
        writeEnvironment(externalEnv, step: stepIndex)

        guard let cb = m.queue.makeCommandBuffer() else { throw NSError(domain: "CB", code: 11) }

        // 1) recompute energy/capacity/entropy
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kReduce)
            enc.setBuffer(tensorData, offset: 0, index: 0)
            enc.setBuffer(tensorEnergy, offset: 0, index: 1)
            enc.setBuffer(boundaryActivity, offset: 0, index: 2)
            enc.setBuffer(entEntropy, offset: 0, index: 3)
            // TIER 1 FIX: Use formal struct definition
            var p = ReduceEnergyParams(network_size: UInt32(networkSize), vector_len: UInt32(vecLen))
            enc.setBytes(&p, length: MemoryLayout<ReduceEnergyParams>.stride, index: 9)
            dispatch1D(enc, pso: kReduce, count: networkSize)
            // PHASE 2: Signal fence after writing energy/capacity/entropy to heap
            fenceManager.update(enc, fence: "energy_ready")
            enc.endEncoding()
        }

        // 2) boundary contraction (tiled reduction over N)
        // PHASE 2: Wait for energy data before reading
        do {
            let cfg = boundaryConfig

            let enc = cb.makeComputeCommandEncoder()!
            fenceManager.wait(enc, fence: "energy_ready")  // Wait for tensorEnergy/boundaryActivity
            enc.setBuffer(tensorEnergy, offset: 0, index: 1)
            enc.setBuffer(boundaryActivity, offset: 0, index: 2)
            enc.setBuffer(boundaryState, offset: 0, index: 4)

            // TIER 1 FIX: Use formal struct definition
            var cp = ContractParams(network_size: UInt32(networkSize),
                                   boundary_size: UInt32(boundarySize),
                                   lanes: UInt32(cfg.lanes),
                                   tile_bins: UInt32(cfg.tileBins))
            enc.setBytes(&cp, length: MemoryLayout<ContractParams>.stride, index: 9)

            // Dispatch using helper (eliminates dispatch geometry bugs)
            dispatch2D(enc, pso: cfg.useV4 ? kContractV4 : kContract,
                      width: boundarySize, height: cfg.lanes,
                      tptX: cfg.tileBins, tptY: cfg.lanes)
            enc.endEncoding()
        }

        // Scrub boundary NaN/Inf
        if SanityConfig.enableNanScrub {
            let enc = cb.makeComputeCommandEncoder()!
            var cnt: UInt32 = UInt32(boundarySize)
            enc.setBuffer(boundaryState, offset: 0, index: 0)
            enc.setBytes(&cnt, length: MemoryLayout<UInt32>.stride, index: 1)
            dispatch1D(enc, pso: kScrub, count: boundarySize)
            enc.endEncoding()
        }

        // 3) bulk geometry
        do {
            zeroBuffer(bulkGeometry)
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kBulk)
            fenceManager.wait(enc, fence: "energy_ready")  // Wait for tensorEnergy/entEntropy
            enc.setBuffer(tensorEnergy, offset: 0, index: 1)
            enc.setBuffer(entEntropy, offset: 0, index: 3)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            // TIER 1 FIX: Use formal struct definition
            var p = BulkParams(network_size: UInt32(networkSize), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<BulkParams>.stride, index: 9)
            dispatch1D(enc, pso: kBulk, count: bulkSize)
            fenceManager.update(enc, fence: "bulk_ready")  // Signal after writing bulkGeometry
            enc.endEncoding()
        }

        // Scrub bulk NaN/Inf
        if SanityConfig.enableNanScrub {
            let enc = cb.makeComputeCommandEncoder()!
            var cnt: UInt32 = UInt32(bulkSize)
            enc.setBuffer(bulkGeometry, offset: 0, index: 0)
            enc.setBytes(&cnt, length: MemoryLayout<UInt32>.stride, index: 1)
            dispatch1D(enc, pso: kScrub, count: bulkSize)
            enc.endEncoding()
        }

        // 4) entropy
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kEnt)
            fenceManager.wait(enc, fence: "bulk_ready")  // Wait for bulkGeometry
            enc.setBuffer(boundaryState, offset: 0, index: 4)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            enc.setBuffer(consciousness, offset: 0, index: 7)
            // TIER 1 FIX: Use formal struct definition
            var p = EntropyParams(boundary_size: UInt32(boundarySize), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<EntropyParams>.stride, index: 9)
            dispatch1D(enc, pso: kEnt, count: 256)  // OPTIMIZED: 256 threads for parallel reduction
            enc.endEncoding()
        }

        // 5) phi
        do {
            zeroBuffer(phiValues)
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kPhi)
            fenceManager.wait(enc, fence: "energy_ready")  // Wait for boundaryActivity
            fenceManager.wait(enc, fence: "bulk_ready")    // Wait for bulkGeometry
            enc.setBuffer(tensorData, offset: 0, index: 0)
            enc.setBuffer(boundaryActivity, offset: 0, index: 2)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            enc.setBuffer(phiValues, offset: 0, index: 6)
            // TIER 1 FIX: Use formal struct definition
            var p = PhiParams(network_size: UInt32(networkSize), vector_len: UInt32(vecLen), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<PhiParams>.stride, index: 9)
            dispatch1D(enc, pso: kPhi, count: networkSize)
            fenceManager.update(enc, fence: "phi_ready")  // Signal after writing phiValues
            enc.endEncoding()
        }

        // 6) detect
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kDetect)
            fenceManager.wait(enc, fence: "phi_ready")  // Wait for phiValues
            enc.setBuffer(phiValues, offset: 0, index: 6)
            enc.setBuffer(boundaryState, offset: 0, index: 4)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            enc.setBuffer(consciousness, offset: 0, index: 7)
            // TIER 1 FIX: Use formal struct definition
            var p = EntropyParams(boundary_size: UInt32(boundarySize), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<EntropyParams>.stride, index: 9)
            dispatch1D(enc, pso: kDetect, count: 256)  // OPTIMIZED: 256 threads for parallel aggregation
            enc.endEncoding()
        }

        // 7) evolve
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kEvolve)
            enc.setBuffer(tensorData, offset: 0, index: 0)
            enc.setBuffer(environment, offset: 0, index: 8)
            enc.setBuffer(consciousness, offset: 0, index: 7)
            // TIER 1 FIX: Use formal struct definition
            var p = EvolveParams(network_size: UInt32(networkSize), dt: dt)
            enc.setBytes(&p, length: MemoryLayout<EvolveParams>.stride, index: 9)
            dispatch2D(enc, pso: kEvolve, width: networkSize, height: vecLen)
            enc.endEncoding()
        }

        cb.commit()
        cb.waitUntilCompleted()

        // read back consciousness
        let v = consciousness.contents().bindMemory(to: Float.self, capacity: 10)
        return HoloState(
            phiComplexity: v[0],
            globalCoherence: v[1],
            boundaryEntropy: v[2],
            bulkEntropy: v[3],
            ratio: v[4],
            infoIntegration: v[5],
            selfAwareness: v[6],
            emergence: v[7],
            processingEff: v[8],
            level: v[9]
        )
    }

    public func stepPrewired(dt: Float = 0.01) throws -> HoloState {
        // environment buffer already filled by affine mapper - skip writeEnvironment()
        guard let cb = m.queue.makeCommandBuffer() else { throw NSError(domain: "CB", code: 11) }

        // 1) recompute energy/capacity/entropy
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kReduce)
            enc.setBuffer(tensorData, offset: 0, index: 0)
            enc.setBuffer(tensorEnergy, offset: 0, index: 1)
            enc.setBuffer(boundaryActivity, offset: 0, index: 2)
            enc.setBuffer(entEntropy, offset: 0, index: 3)
            // TIER 1 FIX: Use formal struct definition
            var p = ReduceEnergyParams(network_size: UInt32(networkSize), vector_len: UInt32(vecLen))
            enc.setBytes(&p, length: MemoryLayout<ReduceEnergyParams>.stride, index: 9)
            dispatch1D(enc, pso: kReduce, count: networkSize)
            // PHASE 2: Signal fence after writing energy/capacity/entropy to heap
            fenceManager.update(enc, fence: "energy_ready")
            enc.endEncoding()
        }

        // 2) boundary contraction (tiled reduction over N)
        // PHASE 2: Wait for energy data before reading
        do {
            let cfg = boundaryConfig

            let enc = cb.makeComputeCommandEncoder()!
            fenceManager.wait(enc, fence: "energy_ready")  // Wait for tensorEnergy/boundaryActivity
            enc.setBuffer(tensorEnergy, offset: 0, index: 1)
            enc.setBuffer(boundaryActivity, offset: 0, index: 2)
            enc.setBuffer(boundaryState, offset: 0, index: 4)

            // TIER 1 FIX: Use formal struct definition
            var cp = ContractParams(network_size: UInt32(networkSize),
                                   boundary_size: UInt32(boundarySize),
                                   lanes: UInt32(cfg.lanes),
                                   tile_bins: UInt32(cfg.tileBins))
            enc.setBytes(&cp, length: MemoryLayout<ContractParams>.stride, index: 9)

            // Dispatch using helper (eliminates dispatch geometry bugs)
            dispatch2D(enc, pso: cfg.useV4 ? kContractV4 : kContract,
                      width: boundarySize, height: cfg.lanes,
                      tptX: cfg.tileBins, tptY: cfg.lanes)
            enc.endEncoding()
        }

        // Scrub boundary NaN/Inf
        if SanityConfig.enableNanScrub {
            let enc = cb.makeComputeCommandEncoder()!
            var cnt: UInt32 = UInt32(boundarySize)
            enc.setBuffer(boundaryState, offset: 0, index: 0)
            enc.setBytes(&cnt, length: MemoryLayout<UInt32>.stride, index: 1)
            dispatch1D(enc, pso: kScrub, count: boundarySize)
            enc.endEncoding()
        }

        // 3) bulk geometry
        do {
            zeroBuffer(bulkGeometry)
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kBulk)
            fenceManager.wait(enc, fence: "energy_ready")  // Wait for tensorEnergy/entEntropy
            enc.setBuffer(tensorEnergy, offset: 0, index: 1)
            enc.setBuffer(entEntropy, offset: 0, index: 3)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            // TIER 1 FIX: Use formal struct definition
            var p = BulkParams(network_size: UInt32(networkSize), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<BulkParams>.stride, index: 9)
            dispatch1D(enc, pso: kBulk, count: bulkSize)
            fenceManager.update(enc, fence: "bulk_ready")  // Signal after writing bulkGeometry
            enc.endEncoding()
        }

        // Scrub bulk NaN/Inf
        if SanityConfig.enableNanScrub {
            let enc = cb.makeComputeCommandEncoder()!
            var cnt: UInt32 = UInt32(bulkSize)
            enc.setBuffer(bulkGeometry, offset: 0, index: 0)
            enc.setBytes(&cnt, length: MemoryLayout<UInt32>.stride, index: 1)
            dispatch1D(enc, pso: kScrub, count: bulkSize)
            enc.endEncoding()
        }

        // 4) entropy
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kEnt)
            fenceManager.wait(enc, fence: "bulk_ready")  // Wait for bulkGeometry
            enc.setBuffer(boundaryState, offset: 0, index: 4)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            enc.setBuffer(consciousness, offset: 0, index: 7)
            // TIER 1 FIX: Use formal struct definition
            var p = EntropyParams(boundary_size: UInt32(boundarySize), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<EntropyParams>.stride, index: 9)
            dispatch1D(enc, pso: kEnt, count: 256)  // OPTIMIZED: 256 threads for parallel reduction
            enc.endEncoding()
        }

        // 5) phi
        do {
            zeroBuffer(phiValues)
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kPhi)
            fenceManager.wait(enc, fence: "energy_ready")  // Wait for boundaryActivity
            fenceManager.wait(enc, fence: "bulk_ready")    // Wait for bulkGeometry
            enc.setBuffer(tensorData, offset: 0, index: 0)
            enc.setBuffer(boundaryActivity, offset: 0, index: 2)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            enc.setBuffer(phiValues, offset: 0, index: 6)
            // TIER 1 FIX: Use formal struct definition
            var p = PhiParams(network_size: UInt32(networkSize), vector_len: UInt32(vecLen), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<PhiParams>.stride, index: 9)
            dispatch1D(enc, pso: kPhi, count: networkSize)
            fenceManager.update(enc, fence: "phi_ready")  // Signal after writing phiValues
            enc.endEncoding()
        }

        // 6) detect
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kDetect)
            fenceManager.wait(enc, fence: "phi_ready")  // Wait for phiValues
            enc.setBuffer(phiValues, offset: 0, index: 6)
            enc.setBuffer(boundaryState, offset: 0, index: 4)
            enc.setBuffer(bulkGeometry, offset: 0, index: 5)
            enc.setBuffer(consciousness, offset: 0, index: 7)
            // TIER 1 FIX: Use formal struct definition
            var p = EntropyParams(boundary_size: UInt32(boundarySize), bulk_size: UInt32(bulkSize))
            enc.setBytes(&p, length: MemoryLayout<EntropyParams>.stride, index: 9)
            dispatch1D(enc, pso: kDetect, count: 256)  // OPTIMIZED: 256 threads for parallel aggregation
            enc.endEncoding()
        }

        // 7) evolve
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kEvolve)
            enc.setBuffer(tensorData, offset: 0, index: 0)
            enc.setBuffer(environment, offset: 0, index: 8)
            enc.setBuffer(consciousness, offset: 0, index: 7)
            // TIER 1 FIX: Use formal struct definition
            var p = EvolveParams(network_size: UInt32(networkSize), dt: dt)
            enc.setBytes(&p, length: MemoryLayout<EvolveParams>.stride, index: 9)
            dispatch2D(enc, pso: kEvolve, width: networkSize, height: vecLen)
            enc.endEncoding()
        }

        cb.commit()
        cb.waitUntilCompleted()

        // read back consciousness
        let v = consciousness.contents().bindMemory(to: Float.self, capacity: 10)
        return HoloState(
            phiComplexity: v[0],
            globalCoherence: v[1],
            boundaryEntropy: v[2],
            bulkEntropy: v[3],
            ratio: v[4],
            infoIntegration: v[5],
            selfAwareness: v[6],
            emergence: v[7],
            processingEff: v[8],
            level: v[9]
        )
    }
}

// ======== Reservoir Engine (SoA) ========

public final class HolographicReservoirEngine {
    let m: MetalKit
    let kEvolve: MTLComputePipelineState
    let kReadout: MTLComputePipelineState
    let kDetect: MTLComputePipelineState

    let field: MTLBuffer              // 64*64*16 floats
    let echo: MTLBuffer               // 1024 floats
    let boundaryInput: MTLBuffer      // 4096 floats
    let featuresOut: MTLBuffer        // 128 floats
    let bulkRecon: MTLBuffer          // 512 floats
    let metricsOut: MTLBuffer         // 5 floats

    // Public accessors for affine mapper integration
    public var device: MTLDevice { m.device }
    public var boundaryInputBuffer: MTLBuffer { boundaryInput }

    public var stepCount: Int = 0

    // Edge-of-chaos criticality controller
    private var criticality = CriticalityController()

    // Differential privacy for readout training
    private var dpReadout = DPReadoutTrainer(epsilon: 0.5, delta: 1e-5, clipNorm: 10.0, maxBudget: 50.0)

    public init() throws {
        self.m = try MetalKit()
        self.kEvolve  = try m.pipeline("evolve_tensor_field_reservoir")
        self.kReadout = try m.pipeline("holographic_reservoir_readout")
        self.kDetect  = try m.pipeline("reservoir_consciousness_detection")

        self.field         = m.makeBuffer(bytes: MemoryLayout<Float>.stride * 64 * 64 * 16)
        self.echo          = m.makeBuffer(bytes: MemoryLayout<Float>.stride * 1024)
        self.boundaryInput = m.makeBuffer(bytes: MemoryLayout<Float>.stride * 4096)
        self.featuresOut   = m.makeBuffer(bytes: MemoryLayout<Float>.stride * 128)
        self.bulkRecon     = m.makeBuffer(bytes: MemoryLayout<Float>.stride * 512)
        self.metricsOut    = m.makeBuffer(bytes: MemoryLayout<Float>.stride * 5)

        randomize()
    }

    private func randomize() {
        let f = field.contents().bindMemory(to: Float.self, capacity: 64*64*16)
        for i in 0..<(64*64*16) { f[i] = Float.random(in: -0.5...0.5) }
        let e = echo.contents().bindMemory(to: Float.self, capacity: 1024)
        for i in 0..<1024 { e[i] = Float.random(in: -0.1...0.1) }
    }

    private func writeBoundaryInput(_ external: [Float]?) {
        let b = boundaryInput.contents().bindMemory(to: Float.self, capacity: 4096)
        if let ext = external, !ext.isEmpty {
            if ext.count == 4096 {
                b.assign(from: ext, count: 4096)
            } else {
                for i in 0..<4096 { b[i] = ext[i % ext.count] }
            }
        } else {
            let t = Float(stepCount) * 0.05
            for i in 0..<4096 {
                let s = sinf(t + Float(i) * 0.01)
                let c = cosf(1.3*t + Float(i) * 0.017)
                b[i] = 0.5*s + 0.3*c + Float.random(in: -0.05...0.05)
            }
        }
    }

    public func step(input: [Float]? = nil, dt: Float = 0.01) throws -> [Float] {
        stepCount &+= 1
        writeBoundaryInput(input)

        // Read echo memory for criticality estimation
        let echoPtr = echo.contents().bindMemory(to: Float.self, capacity: 1024)
        let echoBuffer = UnsafeBufferPointer(start: echoPtr, count: 1024)

        // Estimate Lyapunov and adjust knobs to maintain edge-of-chaos (λ≈0)
        let currentKnobs = CriticalityController.Knobs(fieldCoupling: 0.1, reservoirTemperature: 1.0)
        let est = criticality.estimateAndAdjust(echo: echoBuffer, cfg: currentKnobs)

        guard let cb = m.queue.makeCommandBuffer() else { throw NSError(domain: "CB", code: 20) }

        // 1) evolve with adjusted criticality knobs
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kEvolve)
            enc.setBuffer(field, offset: 0, index: 10)
            enc.setBuffer(echo, offset: 0, index: 11)
            enc.setBuffer(boundaryInput, offset: 0, index: 12)
            // TIER 1 FIX: Use formal struct definition
            var p = ReservoirEvolveParams(field_coupling: est.adjusted.fieldCoupling, temporal_decay: 0.9, boundary_bulk_coupling: 0.5, temperature: est.adjusted.reservoirTemperature, dt: dt)
            enc.setBytes(&p, length: MemoryLayout<ReservoirEvolveParams>.stride, index: 16)
            dispatch3D(enc, pso: kEvolve, width: 64, height: 64, depth: 16)
            enc.endEncoding()
        }

        // 2) readout
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kReadout)
            enc.setBuffer(field, offset: 0, index: 10)
            enc.setBuffer(featuresOut, offset: 0, index: 13)
            enc.setBuffer(bulkRecon, offset: 0, index: 14)
            // TIER 1 FIX: Use formal struct definition
            var d = ReadoutDims(feat_count: 128, bulk_size: 512)
            enc.setBytes(&d, length: MemoryLayout<ReadoutDims>.stride, index: 16)
            dispatch2D(enc, pso: kReadout, width: 128, height: 512)
            enc.endEncoding()
        }

        // 3) metrics
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kDetect)
            enc.setBuffer(featuresOut, offset: 0, index: 13)
            enc.setBuffer(bulkRecon, offset: 0, index: 14)
            enc.setBuffer(field, offset: 0, index: 10)
            enc.setBuffer(metricsOut, offset: 0, index: 15)
            dispatch1D(enc, pso: kDetect, count: 256)  // OPTIMIZED: 256 threads for parallel aggregation
            enc.endEncoding()
        }

        cb.commit()
        cb.waitUntilCompleted()

        let out = metricsOut.contents().bindMemory(to: Float.self, capacity: 5)
        return Array(UnsafeBufferPointer(start: out, count: 5))
    }

    // Public read methods for blockchain snapshots
    public func readMetrics() -> [Float] {
        let out = metricsOut.contents().bindMemory(to: Float.self, capacity: 5)
        return Array(UnsafeBufferPointer(start: out, count: 5))
    }

    public func readField() -> [Float] {
        let p = field.contents().bindMemory(to: Float.self, capacity: 64*64*16)
        return Array(UnsafeBufferPointer(start: p, count: 64*64*16))
    }

    public func readEcho() -> [Float] {
        let p = echo.contents().bindMemory(to: Float.self, capacity: 1024)
        return Array(UnsafeBufferPointer(start: p, count: 1024))
    }

    /// Read privatized features with differential privacy (for external observers).
    /// Returns nil if privacy budget exhausted.
    public func readPrivatizedFeatures() -> [Float]? {
        let raw = featuresOut.contents().bindMemory(to: Float.self, capacity: 128)
        let features = Array(UnsafeBufferPointer(start: raw, count: 128))
        return dpReadout.trainStep(features: features)
    }

    /// Query current privacy budget expenditure.
    public func privacyBudget() -> (epsilon: Float, delta: Float) {
        return dpReadout.budget()
    }

    public func stepPrewired(dt: Float = 0.01) throws -> [Float] {
        stepCount &+= 1  // maintain counter for blockchain timestamps
        // boundaryInput buffer already filled by affine mapper - skip writeBoundaryInput()

        // Read echo memory for criticality estimation
        let echoPtr = echo.contents().bindMemory(to: Float.self, capacity: 1024)
        let echoBuffer = UnsafeBufferPointer(start: echoPtr, count: 1024)

        // Estimate Lyapunov and adjust knobs to maintain edge-of-chaos (λ≈0)
        let currentKnobs = CriticalityController.Knobs(fieldCoupling: 0.1, reservoirTemperature: 1.0)
        let est = criticality.estimateAndAdjust(echo: echoBuffer, cfg: currentKnobs)

        guard let cb = m.queue.makeCommandBuffer() else { throw NSError(domain: "CB", code: 20) }

        // 1) evolve with adjusted criticality knobs
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kEvolve)
            enc.setBuffer(field, offset: 0, index: 10)
            enc.setBuffer(echo, offset: 0, index: 11)
            enc.setBuffer(boundaryInput, offset: 0, index: 12)
            // TIER 1 FIX: Use formal struct definition
            var p = ReservoirEvolveParams(field_coupling: est.adjusted.fieldCoupling, temporal_decay: 0.9, boundary_bulk_coupling: 0.5, temperature: est.adjusted.reservoirTemperature, dt: dt)
            enc.setBytes(&p, length: MemoryLayout<ReservoirEvolveParams>.stride, index: 16)
            dispatch3D(enc, pso: kEvolve, width: 64, height: 64, depth: 16)
            enc.endEncoding()
        }

        // 2) readout
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kReadout)
            enc.setBuffer(field, offset: 0, index: 10)
            enc.setBuffer(featuresOut, offset: 0, index: 13)
            enc.setBuffer(bulkRecon, offset: 0, index: 14)
            // TIER 1 FIX: Use formal struct definition
            var d = ReadoutDims(feat_count: 128, bulk_size: 512)
            enc.setBytes(&d, length: MemoryLayout<ReadoutDims>.stride, index: 16)
            dispatch2D(enc, pso: kReadout, width: 128, height: 512)
            enc.endEncoding()
        }

        // 3) metrics
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(kDetect)
            enc.setBuffer(featuresOut, offset: 0, index: 13)
            enc.setBuffer(bulkRecon, offset: 0, index: 14)
            enc.setBuffer(field, offset: 0, index: 10)
            enc.setBuffer(metricsOut, offset: 0, index: 15)
            dispatch1D(enc, pso: kDetect, count: 256)  // OPTIMIZED: 256 threads for parallel aggregation
            enc.endEncoding()
        }

        cb.commit()
        cb.waitUntilCompleted()

        let out = metricsOut.contents().bindMemory(to: Float.self, capacity: 5)
        return Array(UnsafeBufferPointer(start: out, count: 5))
    }
}
