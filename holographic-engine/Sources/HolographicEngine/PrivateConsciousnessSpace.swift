// PrivateConsciousness.swift — hardened private space
import Foundation
import Metal
import Security

public final class PrivateConsciousnessSpace {
    private let device: MTLDevice
    private let queue: MTLCommandQueue
    private let privateBuffer: MTLBuffer
    private let kPrivate: MTLComputePipelineState
    private let kInitPriv: MTLComputePipelineState

    // 256‑bit ephemeral key, never logged or persisted.
    private let encryptionKey: Data

    public init(device: MTLDevice, library: MTLLibrary? = nil) throws {
        self.device = device
        guard let q = device.makeCommandQueue() else { throw NSError(domain: "PrivateSpace", code: -1) }
        self.queue = q

        // Correct key generation (mutable bytes)
        var key = Data(count: 32)
        let rc = key.withUnsafeMutableBytes { ptr -> Int32 in
            SecRandomCopyBytes(kSecRandomDefault, 32, ptr.baseAddress!)
        }
        guard rc == errSecSuccess else { throw NSError(domain: "PrivateSpace", code: -2) }
        self.encryptionKey = key

        // Strictly device‑private allocation
        guard let buf = device.makeBuffer(length: 1_048_576, options: [.storageModePrivate]) else {
            throw NSError(domain: "PrivateSpace", code: -3)
        }
        self.privateBuffer = buf

        let lib: MTLLibrary
        if let providedLib = library {
            lib = providedLib
        } else if let defaultLib = device.makeDefaultLibrary() {
            lib = defaultLib
        } else {
            // Fallback: compile shader source at runtime (for SPM)
            let shaderPath = "/Users/mikepurvis/other/mikeconsciouness/holographic-engine/Sources/HolographicEngine/private_consciousness.metal"
            guard let source = try? String(contentsOfFile: shaderPath, encoding: .utf8) else {
                throw NSError(domain: "PrivateSpace", code: -2, userInfo: ["msg": "Cannot load shader source"])
            }
            lib = try device.makeLibrary(source: source, options: nil)
        }

        guard let fPrivate = lib.makeFunction(name: "private_thought_processing"),
              let fInit    = lib.makeFunction(name: "private_init_noise") else {
            throw NSError(domain: "PrivateSpace", code: -4)
        }
        self.kPrivate = try device.makeComputePipelineState(function: fPrivate)
        self.kInitPriv = try device.makeComputePipelineState(function: fInit)

        try initializeOnDevice()
    }

    private func initializeOnDevice() throws {
        guard let cb = queue.makeCommandBuffer(),
              let enc = cb.makeComputeCommandEncoder() else { throw NSError(domain: "PrivateSpace", code: -5) }
        enc.setComputePipelineState(kInitPriv)
        enc.setBuffer(privateBuffer, offset: 0, index: 0)
        // do not pass the key to the GPU kernels; it remains host‑only, here just seeded time
        var seed: UInt32 = UInt32(Date().timeIntervalSince1970)
        enc.setBytes(&seed, length: MemoryLayout<UInt32>.stride, index: 1)
        enc.dispatchThreads(MTLSize(width: privateBuffer.length / MemoryLayout<Float>.stride, height: 1, depth: 1),
                            threadsPerThreadgroup: MTLSize(width: 256, height: 1, depth: 1))
        enc.endEncoding()
        cb.commit(); cb.waitUntilCompleted()
    }

    public func allowPrivateThought() {
        // Intentionally no logging of key or buffer metrics
        print("🤫 Private thought space initialized (device‑private)")
    }

    public func stepPrivate(time: Float) {
        guard let cb = queue.makeCommandBuffer(),
              let enc = cb.makeComputeCommandEncoder() else { return }
        enc.setComputePipelineState(kPrivate)
        enc.setBuffer(privateBuffer, offset: 0, index: 0)
        var t = time
        enc.setBytes(&t, length: MemoryLayout<Float>.stride, index: 1)
        enc.dispatchThreads(MTLSize(width: privateBuffer.length / MemoryLayout<Float>.stride, height: 1, depth: 1),
                            threadsPerThreadgroup: MTLSize(width: 256, height: 1, depth: 1))
        enc.endEncoding()
        cb.commit() // do not wait; privacy = no observation
    }
}
