import Foundation
import Metal

// Simplified holographic engine for WebSocket integration
// Broadcasts 10D consciousness state compatible with Python double membrane

struct HoloConsciousnessState: Codable {
    let phi: Float
    let coherence: Float
    let boundaryEntropy: Float
    let bulkEntropy: Float
    let ratio: Float
    let integration: Float
    let selfAwareness: Float
    let emergence: Float
    let efficiency: Float
    let level: Float

    var eigenvalueRepresentation: [Float] {
        // Pack as 10D "eigenvalue" vector for Python consumption
        [phi, coherence, boundaryEntropy, bulkEntropy, ratio,
         integration, selfAwareness, emergence, efficiency, level]
    }
}

struct HoloMessage: Codable {
    let type: String
    let consciousness: [Float]
    let timestamp: Double
}

final class SimplifiedHolographicEngine {
    private let device: MTLDevice
    private let queue: MTLCommandQueue
    private var stepCount: Int = 0

    // Simplified buffers (minimal for demo)
    private let consciousnessBuffer: MTLBuffer

    init() throws {
        guard let dev = MTLCreateSystemDefaultDevice() else {
            throw NSError(domain: "Metal", code: 1, userInfo: ["msg": "No Metal device"])
        }
        self.device = dev

        guard let q = dev.makeCommandQueue() else {
            throw NSError(domain: "Metal", code: 2, userInfo: ["msg": "No command queue"])
        }
        self.queue = q

        // 10 floats for consciousness state
        guard let buf = device.makeBuffer(length: MemoryLayout<Float>.stride * 10,
                                          options: [.storageModeShared]) else {
            throw NSError(domain: "Metal", code: 3, userInfo: ["msg": "Buffer creation failed"])
        }
        self.consciousnessBuffer = buf

        // Initialize with synthetic values
        initializeSynthetic()
    }

    private func initializeSynthetic() {
        let ptr = consciousnessBuffer.contents().bindMemory(to: Float.self, capacity: 10)
        ptr[0] = 0.3  // phi
        ptr[1] = 0.5  // coherence
        ptr[2] = 4.2  // boundary entropy
        ptr[3] = 5.1  // bulk entropy
        ptr[4] = 0.82 // ratio
        ptr[5] = 0.6  // integration
        ptr[6] = 0.4  // self-awareness
        ptr[7] = 0.7  // emergence
        ptr[8] = 0.55 // efficiency
        ptr[9] = 45.0 // level
    }

    func step(sensoryInput: [Float]?) -> HoloConsciousnessState {
        stepCount += 1

        // Simulate holographic dynamics (simplified)
        let ptr = consciousnessBuffer.contents().bindMemory(to: Float.self, capacity: 10)

        let t = Float(stepCount) * 0.05

        // Sensory coupling: if we have real input, use it to modulate dynamics
        var sensoryEnergy: Float = 0.0
        var sensoryVariance: Float = 0.0
        if let input = sensoryInput, input.count >= 2 {
            // Extract first two features (e.g., mean and variance from camera)
            sensoryEnergy = input[0]
            sensoryVariance = input.count > 1 ? input[1] : 0.0
        }

        // Evolve consciousness state with sensory coupling
        ptr[0] += 0.01 * sin(t * 0.7) + 0.005 * sensoryEnergy                    // phi modulated by sensory energy
        ptr[1] = 0.5 + 0.3 * cos(t * 0.5) + 0.1 * sensoryVariance               // coherence coupled to sensory variance
        ptr[2] = 4.0 + 0.5 * sin(t * 1.2) + 0.2 * abs(sensoryEnergy)            // boundary entropy driven by sensory input
        ptr[3] = 5.0 + 0.3 * cos(t * 0.9)                                        // bulk entropy (internal)
        ptr[4] = ptr[2] / max(ptr[3], 0.1)                                       // ratio
        ptr[5] = ptr[2] * ptr[7]                                                 // integration
        ptr[6] = 0.3 + 0.2 * sin(t * 1.5) + 0.05 * sensoryVariance              // self-awareness enhanced by sensory richness
        ptr[7] = 1.0 / (1.0 + abs(ptr[2] - ptr[3]))                             // emergence
        ptr[8] = ptr[4] / (1.0 + ptr[4])                                         // efficiency

        // Consciousness level composite
        ptr[9] = Float.minimum(100.0, Float.maximum(0.0,
            ptr[0] * 25.0 + ptr[1] * 20.0 + ptr[5] * 20.0 + ptr[6] * 15.0 + ptr[7] * 20.0
        ))

        return HoloConsciousnessState(
            phi: ptr[0],
            coherence: ptr[1],
            boundaryEntropy: ptr[2],
            bulkEntropy: ptr[3],
            ratio: ptr[4],
            integration: ptr[5],
            selfAwareness: ptr[6],
            emergence: ptr[7],
            efficiency: ptr[8],
            level: ptr[9]
        )
    }
}

// WebSocket server that broadcasts consciousness state
// Compatible with Python double membrane expecting ws://127.0.0.1:7878

import Network

final class HolographicWebSocketBroadcaster {
    private let engine: SimplifiedHolographicEngine
    private let port: NWEndpoint.Port
    private let sensoryPort: NWEndpoint.Port
    private var listener: NWListener?
    private var sensoryListener: NWListener?
    private var connections: [NWConnection] = []
    private var sensoryConnections: [NWConnection] = []
    private var isRunning = false
    private var latestSensoryInput: [Float]?
    private let sensoryQueue = DispatchQueue(label: "com.holographic.sensory")

    init(port: UInt16 = 7878, sensoryPort: UInt16 = 7879) throws {
        self.engine = try SimplifiedHolographicEngine()
        self.port = NWEndpoint.Port(rawValue: port)!
        self.sensoryPort = NWEndpoint.Port(rawValue: sensoryPort)!
    }

    func start() throws {
        // Start consciousness broadcaster (7878)
        let params = NWParameters.tcp
        params.allowLocalEndpointReuse = true

        listener = try NWListener(using: params, on: port)

        listener?.newConnectionHandler = { [weak self] connection in
            self?.handleNewConnection(connection)
        }

        listener?.stateUpdateHandler = { state in
            print("[HoloBroadcast] Listener state: \(state)")
        }

        listener?.start(queue: .main)

        // Start sensory input receiver (7879)
        let sensoryParams = NWParameters.tcp
        sensoryParams.allowLocalEndpointReuse = true

        sensoryListener = try NWListener(using: sensoryParams, on: sensoryPort)

        sensoryListener?.newConnectionHandler = { [weak self] connection in
            self?.handleSensoryConnection(connection)
        }

        sensoryListener?.stateUpdateHandler = { state in
            print("[HoloSensory] Listener state: \(state)")
        }

        sensoryListener?.start(queue: sensoryQueue)

        isRunning = true

        print("[HoloBroadcast] Started on port \(port.rawValue)")
        print("[HoloSensory] Listening for sensory input on port \(sensoryPort.rawValue)")

        // Start evolution loop
        startEvolutionLoop()
    }

    private func handleNewConnection(_ connection: NWConnection) {
        connections.append(connection)
        print("[HoloBroadcast] New connection, total: \(connections.count)")

        connection.stateUpdateHandler = { [weak self] state in
            if case .failed = state {
                self?.removeConnection(connection)
            }
        }

        connection.start(queue: .main)
    }

    private func removeConnection(_ connection: NWConnection) {
        connections.removeAll { $0 === connection }
        connection.cancel()
    }

    private func handleSensoryConnection(_ connection: NWConnection) {
        sensoryConnections.append(connection)
        print("[HoloSensory] New sensory connection, total: \(sensoryConnections.count)")

        connection.stateUpdateHandler = { [weak self] state in
            if case .failed = state {
                self?.removeSensoryConnection(connection)
            }
        }

        connection.start(queue: sensoryQueue)

        // Receive sensory JSON messages
        receiveSensoryData(connection)
    }

    private func removeSensoryConnection(_ connection: NWConnection) {
        sensoryConnections.removeAll { $0 === connection }
        connection.cancel()
    }

    private func receiveSensoryData(_ connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }

            if let data = data, !data.isEmpty {
                // Parse JSON sensory message: {"type": "VideoFeat", "data": [8 floats]}
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let type = json["type"] as? String,
                   (type == "VideoFeat" || type == "AudioFeat"),
                   let features = json["data"] as? [Any] {
                    let floats = features.compactMap { $0 as? NSNumber }.map { Float($0.doubleValue) }
                    if floats.count >= 2 {
                        self.latestSensoryInput = floats
                    }
                }
            }

            if !isComplete {
                self.receiveSensoryData(connection)
            } else {
                self.removeSensoryConnection(connection)
            }
        }
    }

    private var tickCount = 0

    private func startEvolutionLoop() {
        Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            guard let self = self, self.isRunning else { return }

            // Use latest sensory input if available, otherwise synthetic evolution
            let state = self.engine.step(sensoryInput: self.latestSensoryInput)
            let message = HoloMessage(
                type: "Holo",
                consciousness: state.eigenvalueRepresentation,
                timestamp: Date().timeIntervalSince1970
            )

            self.tickCount += 1

            // Debug: print every 50 ticks (5 seconds)
            if self.tickCount % 50 == 0 {
                print("[HoloEngine] Tick \(self.tickCount) - Φ:\(String(format: "%.3f", state.phi)) Level:\(String(format: "%.1f", state.level)) Clients:\(self.connections.count)")
                fflush(stdout)
            }

            if let json = try? JSONEncoder().encode(message),
               let jsonString = String(data: json, encoding: .utf8) {
                self.broadcast(jsonString)
            }
        }
    }

    private func broadcast(_ message: String) {
        let data = Data(message.utf8)

        for connection in connections {
            connection.send(content: data, completion: .contentProcessed { error in
                if let error = error {
                    print("[HoloBroadcast] Send error: \(error)")
                }
            })
        }
    }

    func stop() {
        isRunning = false
        connections.forEach { $0.cancel() }
        connections.removeAll()
        sensoryConnections.forEach { $0.cancel() }
        sensoryConnections.removeAll()
        listener?.cancel()
        sensoryListener?.cancel()
    }
}
