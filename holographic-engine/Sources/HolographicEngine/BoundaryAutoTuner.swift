import Foundation
import Metal
import QuartzCore

extension HolographicConsciousnessEngine {

    struct BoundaryConfig {
        var lanes: Int
        var tileBins: Int
        var useV4: Bool
    }

    // Exposed so stepPrewired can use it
    var boundaryConfig: BoundaryConfig {
        get { _boundaryConfig }
        set { _boundaryConfig = newValue }
    }

    private static let lanesCandidates: [Int] = [2, 4, 8, 16]
    private static let warmupIters = 2
    private static let measureIters = 5

    // Backing store
    private static var _once: Bool = false
    private static var _boundaryConfigStored = BoundaryConfig(lanes: 8, tileBins: 128, useV4: false)

    // Per-instance proxy (keeps code clean; shares static result across engines)
    private var _boundaryConfig: BoundaryConfig {
        get { Self._boundaryConfigStored }
        set { Self._boundaryConfigStored = newValue }
    }

    /// Call once from init() after pipelines/buffers exist.
    func autoTuneBoundary() {
        if Self._once { return }
        Self._once = true

        let maxThreads = kContract.maxTotalThreadsPerThreadgroup
        let maxBinsCap = 128  // must match shader's MAX_TILE_BINS
        let maxLanesCap = 16  // must match shader's MAX_LANES

        // Heuristic starting point; adjusted per lanes below.
        let baseTileBins = min(maxBinsCap, boundarySize)

        var best = BoundaryConfig(lanes: 8, tileBins: min(baseTileBins, maxThreads / 8), useV4: false)
        var bestTime = Double.greatestFiniteMagnitude

        func timeRun(useV4: Bool, lanes: Int, tileBins: Int) -> Double {
            struct CP { var N: UInt32; var B: UInt32; var L: UInt32; var TB: UInt32 }
            let cp = CP(N: UInt32(networkSize), B: UInt32(boundarySize),
                        L: UInt32(lanes), TB: UInt32(tileBins))
            let tptg = MTLSize(width: tileBins, height: lanes, depth: 1)
            let tg = MTLSize(width: (boundarySize + tileBins - 1) / tileBins, height: 1, depth: 1)

            // Warmup + measures
            var total = 0.0
            for i in 0..<(Self.warmupIters + Self.measureIters) {
                guard let cb = commandQueue.makeCommandBuffer(),
                      let enc = cb.makeComputeCommandEncoder() else { return Double.greatestFiniteMagnitude }

                // Select pipeline
                enc.setComputePipelineState(useV4 ? kContractV4 : kContract)
                // Bind inputs/outputs that already exist
                enc.setBuffer(tensorEnergy, offset: 0, index: 1)
                enc.setBuffer(boundaryActivity, offset: 0, index: 2)
                enc.setBuffer(boundaryState, offset: 0, index: 4)

                var cpCopy = cp
                enc.setBytes(&cpCopy, length: MemoryLayout<CP>.stride, index: 9)

                enc.dispatchThreadgroups(tg, threadsPerThreadgroup: tptg)
                enc.endEncoding()

                let t0 = CACurrentMediaTime()
                cb.commit(); cb.waitUntilCompleted()
                let t1 = CACurrentMediaTime()

                if i >= Self.warmupIters { total += (t1 - t0) }
            }
            return total / Double(Self.measureIters)
        }

        // Scan candidates with threadgroup guardrails
        for lanes in Self.lanesCandidates {
            if lanes > maxLanesCap { continue }
            var tileBins = baseTileBins
            // Respect threadgroup size
            while tileBins * lanes > maxThreads { tileBins = max(1, tileBins / 2) }
            if tileBins == 0 { continue }

            // Try scalar tiled
            let tScalar = timeRun(useV4: false, lanes: lanes, tileBins: tileBins)

            // Try vec4 when N is big enough to matter (but still measure)
            let tV4 = timeRun(useV4: true, lanes: lanes, tileBins: tileBins)

            // Pick best of the two
            let useV4 = tV4 < tScalar
            let tBest = min(tScalar, tV4)

            if tBest < bestTime {
                bestTime = tBest
                best = BoundaryConfig(lanes: lanes, tileBins: tileBins, useV4: useV4)
            }
        }

        _boundaryConfig = best
        print(String(format: "🔧 Boundary autotune → lanes:%d tileBins:%d kernel:%@  (%.3f ms)",
                     best.lanes, best.tileBins, best.useV4 ? "vec4" : "scalar", bestTime * 1000.0))
    }
}
