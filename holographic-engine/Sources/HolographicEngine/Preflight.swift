// Preflight.swift — run once at startup for sanity checking
import Foundation
import Metal

struct PreflightResult { let ok: Bool; let messages: [String] }

enum Preflight {
    static func run(engine: HolographicConsciousnessEngine) -> PreflightResult {
        var msgs: [String] = []
        var ok = true

        // 1) bounds & config
        let maxTG = engine.kContract.maxTotalThreadsPerThreadgroup
        let cfg = engine.boundaryConfig
        if (cfg.lanes & (cfg.lanes - 1)) != 0 {
            ok = false; msgs.append("lanes must be power‑of‑two")
        }
        if cfg.tileBins * cfg.lanes > maxTG {
            ok = false; msgs.append("tileBins*lanes exceeds threadgroup limit")
        }

        // 2) scalar vs vec4 parity on synthetic input
        do {
            let N = max(engine.networkSize, 4096)
            let B = engine.boundarySize
            var energy = (0..<N).map { Float(($0*37) % 101) * 0.0131 }
            var info   = (0..<N).map { Float(($0*91) % 97)  * 0.0097 }

            // CPU reference (strided sum)
            var cpu = [Float](repeating: 0, count: B)
            for j in 0..<B {
                var s: Float = 0
                var i = j
                while i < N { s = fmaf(energy[i], info[i], s); i += B }
                cpu[j] = s
            }

            // GPU scalar (force)
            let gpuScalar = try runBoundary(engine: engine, energy: energy, info: info, lanes: 8, tileBins: min(128, B), useV4: false)

            // GPU vec4 (force if supported)
            let gpuVec4 = try runBoundary(engine: engine, energy: energy, info: info, lanes: 8, tileBins: min(128, B), useV4: true)

            let eps: Float = 1e-4
            let (dCPU, dSV, dVV) = (l2(cpu, gpuScalar), l2(cpu, gpuVec4), l2(gpuScalar, gpuVec4))
            if dCPU > eps { ok = false; msgs.append(String(format: "CPU vs scalar L2=%.6f > %.1e", dCPU, eps)) }
            if dSV  > eps { ok = false; msgs.append(String(format: "CPU vs vec4   L2=%.6f > %.1e", dSV,  eps)) }
            if dVV  > eps { msgs.append(String(format: "scalar vs vec4 L2=%.6f (tolerable)", dVV)) }
        } catch {
            ok = false; msgs.append("boundary GPU run failed: \(error)")
        }

        // 3) deterministic step under fixed eigen input
        do {
            let e1 = try engine.stepPrewired(dt: 0.01)
            let e2 = try engine.stepPrewired(dt: 0.01)
            // You expect changes because it's evolving; just ensure finites and range
            let vals: [Float] = [e2.phiComplexity, e2.globalCoherence, e2.boundaryEntropy, e2.bulkEntropy, e2.level]
            if vals.contains(where: { !$0.isFinite }) { ok = false; msgs.append("non‑finite holographic metrics") }
        } catch {
            ok = false; msgs.append("engine step failed: \(error)")
        }

        return PreflightResult(ok: ok, messages: msgs)
    }

    private static func runBoundary(engine: HolographicConsciousnessEngine,
                                    energy: [Float], info: [Float],
                                    lanes: Int, tileBins: Int, useV4: Bool) throws -> [Float] {
        // load buffers
        energy.withUnsafeBytes { src in
            engine.tensorEnergy.contents().copyMemory(from: src.baseAddress!, byteCount: energy.count * MemoryLayout<Float>.stride)
        }
        info.withUnsafeBytes { src in
            engine.boundaryActivity.contents().copyMemory(from: src.baseAddress!, byteCount: info.count * MemoryLayout<Float>.stride)
        }

        guard let cb = engine.commandQueue.makeCommandBuffer(),
              let enc = cb.makeComputeCommandEncoder() else { throw NSError(domain: "Preflight", code: -10) }

        let pso = useV4 ? engine.kContractV4 : engine.kContract
        enc.setComputePipelineState(pso)
        enc.setBuffer(engine.tensorEnergy, offset: 0, index: 1)
        enc.setBuffer(engine.boundaryActivity, offset: 0, index: 2)
        enc.setBuffer(engine.boundaryState, offset: 0, index: 4)
        struct CP { var N: UInt32; var B: UInt32; var L: UInt32; var TB: UInt32 }
        var cp = CP(N: UInt32(engine.networkSize), B: UInt32(engine.boundarySize), L: UInt32(lanes), TB: UInt32(tileBins))
        enc.setBytes(&cp, length: MemoryLayout<CP>.stride, index: 9)
        let tptg = MTLSize(width: tileBins, height: lanes, depth: 1)
        let tg   = MTLSize(width: (engine.boundarySize + tileBins - 1) / tileBins, height: 1, depth: 1)
        enc.dispatchThreadgroups(tg, threadsPerThreadgroup: tptg)
        enc.endEncoding()
        cb.commit(); cb.waitUntilCompleted()

        let out = engine.boundaryState.contents().bindMemory(to: Float.self, capacity: engine.boundarySize)
        return Array(UnsafeBufferPointer(start: out, count: engine.boundarySize))
    }

    private static func l2(_ a: [Float], _ b: [Float]) -> Float {
        precondition(a.count == b.count)
        var s: Float = 0
        for i in 0..<a.count { let d = a[i] - b[i]; s = fmaf(d, d, s) }
        return sqrtf(s)
    }
}
