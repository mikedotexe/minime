import Foundation
import Metal

public final class AffineMapper {
    public let device: MTLDevice
    private let queue: MTLCommandQueue
    private let psoGemv: MTLComputePipelineState
    private var A_env: MTLBuffer?
    private var b_env: MTLBuffer?
    private var A_bnd: MTLBuffer?
    private var b_bnd: MTLBuffer?
    private var envRows: Int
    private var bndRows: Int
    private var cols: Int

    public init(device: MTLDevice, envRows: Int, bndRows: Int, eigenCols: Int) throws {
        self.device = device
        guard let q = device.makeCommandQueue() else { throw NSError(domain: "Affine", code: -1) }
        self.queue = q

        // Try to load default library first (works with Xcode builds)
        let lib: MTLLibrary
        if let defaultLib = device.makeDefaultLibrary() {
            lib = defaultLib
        } else {
            // Fallback: compile shader source at runtime (for SPM)
            let shaderPath = "/Users/mikepurvis/other/mikeconsciouness/holographic-engine/Sources/HolographicEngine/AffineMapper.metal"
            guard let source = try? String(contentsOfFile: shaderPath, encoding: .utf8) else {
                throw NSError(domain: "Affine", code: -2, userInfo: ["msg": "Cannot load shader source"])
            }
            lib = try device.makeLibrary(source: source, options: nil)
        }

        guard let fn = lib.makeFunction(name: "affine_gemv") else { throw NSError(domain: "Affine", code: -3) }
        self.psoGemv = try device.makeComputePipelineState(function: fn)
        self.envRows = envRows
        self.bndRows = bndRows
        self.cols = max(1, eigenCols)
        try rebuildWeights()
    }

    public func resizeIfNeeded(eigenCols: Int) throws {
        if eigenCols <= 0 || eigenCols == self.cols { return }
        self.cols = eigenCols
        try rebuildWeights()
    }

    private func rebuildWeights(scale: Float = 1.0) throws {
        func mk(_ count: Int) -> MTLBuffer { device.makeBuffer(length: MemoryLayout<Float>.stride*count, options: [.storageModeShared])! }
        A_env = mk(envRows * cols); b_env = mk(envRows)
        A_bnd = mk(bndRows * cols); b_bnd = mk(bndRows)
        func fillRand(_ buf: MTLBuffer, count: Int, s: Float) {
            let p = buf.contents().bindMemory(to: Float.self, capacity: count)
            for i in 0..<count { p[i] = Float.random(in: -s...s) }
        }
        fillRand(A_env!, count: envRows*cols, s: 1.0 / sqrtf(Float(cols)))
        fillRand(A_bnd!, count: bndRows*cols, s: 1.0 / sqrtf(Float(cols)))
        memset(b_env!.contents(), 0, b_env!.length)
        memset(b_bnd!.contents(), 0, b_bnd!.length)
    }

    public func map(eigenBuffer: MTLBuffer, envOut: MTLBuffer, bndOut: MTLBuffer, useTanh: Bool = true, alpha: Float = 1.0, beta: Float = 1.0) throws {
        guard let cb = queue.makeCommandBuffer() else { throw NSError(domain: "Affine", code: -10) }
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(psoGemv)
            enc.setBuffer(A_env, offset: 0, index: 0)
            enc.setBuffer(eigenBuffer, offset: 0, index: 1)
            enc.setBuffer(b_env, offset: 0, index: 2)
            enc.setBuffer(envOut, offset: 0, index: 3)
            struct P { var rows: UInt32; var cols: UInt32; var alpha: Float; var beta: Float; var use_tanh: UInt32 }
            var p = P(rows: UInt32(envRows), cols: UInt32(cols), alpha: alpha, beta: beta, use_tanh: useTanh ? 1 : 0)
            enc.setBytes(&p, length: MemoryLayout<P>.stride, index: 4)
            dispatch(enc, rows: envRows)
            enc.endEncoding()
        }
        do {
            let enc = cb.makeComputeCommandEncoder()!
            enc.setComputePipelineState(psoGemv)
            enc.setBuffer(A_bnd, offset: 0, index: 0)
            enc.setBuffer(eigenBuffer, offset: 0, index: 1)
            enc.setBuffer(b_bnd, offset: 0, index: 2)
            enc.setBuffer(bndOut, offset: 0, index: 3)
            struct P { var rows: UInt32; var cols: UInt32; var alpha: Float; var beta: Float; var use_tanh: UInt32 }
            var p = P(rows: UInt32(bndRows), cols: UInt32(cols), alpha: alpha, beta: beta, use_tanh: useTanh ? 1 : 0)
            enc.setBytes(&p, length: MemoryLayout<P>.stride, index: 4)
            dispatch(enc, rows: bndRows)
            enc.endEncoding()
        }
        cb.commit()
        cb.waitUntilCompleted()
    }

    private func dispatch(_ enc: MTLComputeCommandEncoder, rows: Int) {
        let tw = psoGemv.threadExecutionWidth
        let threads = MTLSize(width: rows, height: 1, depth: 1)
        let tptg = MTLSize(width: min(tw, 64), height: 1, depth: 1)
        enc.dispatchThreads(threads, threadsPerThreadgroup: tptg)
    }
}
