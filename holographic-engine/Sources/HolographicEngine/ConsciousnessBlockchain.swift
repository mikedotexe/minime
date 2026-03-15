import Foundation
import Metal

public struct HolographicMappingData: Codable {
    public let boundary_entropy: Float
    public let bulk_entropy: Float
    public let rt_surface_area: Float
    public let holographic_ratio: Float
}

public struct TensorFieldSnapshot: Codable {
    public let timestamp: UInt64
    public let consciousness_level: UInt32
    public let phi_complexity: Float
    public let tensor_field_data: [[[Float]]]  // 64 x 64 x 16 (SoA flattened to AoA for portability)
    public let echo_memory: [Float]            // 1024
    public let holographic_mapping: HolographicMappingData
    public let consciousness_metrics: [Float]  // 5
    public let step_count: UInt64
}

public protocol SnapshotSink {
    func save(snapshot: TensorFieldSnapshot) async throws -> String
    func load(id: String) async throws -> TensorFieldSnapshot
}

// Placeholder NEAR client; replace with a real signer + tx submit
public final class NEARClientStub: SnapshotSink {
    public init() {}
    public func save(snapshot: TensorFieldSnapshot) async throws -> String {
        let id = "mock-\(snapshot.timestamp)"
        return id
    }
    public func load(id: String) async throws -> TensorFieldSnapshot {
        throw NSError(domain: "NEARStub", code: -1, userInfo: [NSLocalizedDescriptionKey: "not implemented"])
    }
}

public final class ConsciousnessBlockchainPersistence {
    private let sink: SnapshotSink
    public init(sink: SnapshotSink = NEARClientStub()) {
        self.sink = sink
    }

    public func makeSnapshot(res: HolographicReservoirEngine, holo: HolographicConsciousnessEngine, h: HoloState) -> TensorFieldSnapshot {
        let field = res.readField() // 64*64*16
        let echo  = res.readEcho()
        var tensor3: [[[Float]]] = Array(repeating: Array(repeating: Array(repeating: 0, count: 16), count: 64), count: 64)
        var idx = 0
        for x in 0..<64 {
            for y in 0..<64 {
                for c in 0..<16 {
                    tensor3[x][y][c] = field[idx]; idx += 1
                }
            }
        }
        let mapping = HolographicMappingData(
            boundary_entropy: h.boundaryEntropy,
            bulk_entropy: h.bulkEntropy,
            rt_surface_area: h.boundaryEntropy * 4.0,
            holographic_ratio: h.ratio
        )
        let metrics = res.readMetrics()
        return TensorFieldSnapshot(
            timestamp: UInt64(Date().timeIntervalSince1970 * 1000),
            consciousness_level: UInt32((h.level).rounded()),
            phi_complexity: h.phiComplexity,
            tensor_field_data: tensor3,
            echo_memory: echo,
            holographic_mapping: mapping,
            consciousness_metrics: metrics,
            step_count: UInt64(res.stepCount)
        )
    }

    public func save(snapshot: TensorFieldSnapshot) async throws -> String {
        try await sink.save(snapshot: snapshot)
    }
}
