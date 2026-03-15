import Foundation
import Network

// MARK: - Telemetry Message Structure

public struct HoloTelemetry: Codable {
    let phi: Float
    let coherence: Float
    let consciousness_level: UInt32
    let boundary_entropy: Float
    let bulk_entropy: Float
    let holographic_ratio: Float
    let self_awareness: Float
    let emergence: Float
    let processing_efficiency: Float
    let criticality_lyap: Float
    let timestamp: Double

    public init(holo: HoloState, lyap: Float) {
        self.phi = holo.phiComplexity
        self.coherence = holo.globalCoherence
        self.consciousness_level = UInt32(max(0, min(100, holo.level)))
        self.boundary_entropy = holo.boundaryEntropy
        self.bulk_entropy = holo.bulkEntropy
        self.holographic_ratio = holo.ratio
        self.self_awareness = holo.selfAwareness
        self.emergence = holo.emergence
        self.processing_efficiency = holo.processingEff
        self.criticality_lyap = lyap
        self.timestamp = Date().timeIntervalSince1970
    }
}

// MARK: - WebSocket Broadcaster

public final class HoloBroadcaster {
    public struct Config: Sendable {
        public var port: UInt16
        public var maxClients: Int
        public init(port: UInt16 = 8787, maxClients: Int = 128) {
            self.port = port
            self.maxClients = maxClients
        }
    }

    private let queue = DispatchQueue(label: "HoloBroadcaster.queue", qos: .userInitiated)
    private var listener: NWListener?
    private var clients: [ObjectIdentifier: NWConnection] = [:]
    private let config: Config
    private let lock = NSLock()

    public init(config: Config = .init()) throws {
        self.config = config
        var params = NWParameters(tls: nil, tcp: NWProtocolTCP.Options())
        let ws = NWProtocolWebSocket.Options()
        ws.autoReplyPing = true
        params.defaultProtocolStack.applicationProtocols.insert(ws, at: 0)

        let port = NWEndpoint.Port(rawValue: config.port)!
        self.listener = try NWListener(using: params, on: port)
    }

    public func start() {
        guard let listener = listener else { return }
        listener.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready: print("HoloBroadcaster: ws://localhost:\(self?.config.port ?? 0) ready")
            case .failed(let err):
                print("HoloBroadcaster failed: \(err)")
                self?.stop()
            default: break
            }
        }
        listener.newConnectionHandler = { [weak self] conn in
            self?.accept(conn)
        }
        listener.start(queue: queue)
    }

    public func stop() {
        lock.lock()
        let conns = clients.values
        clients.removeAll()
        lock.unlock()
        conns.forEach { $0.cancel() }
        listener?.cancel()
        listener = nil
    }

    public func broadcast(text: String) {
        guard let data = text.data(using: .utf8) else { return }
        broadcast(data: data, opcode: .text)
    }

    public func broadcastJSON<T: Encodable>(_ value: T) {
        do {
            let data = try JSONEncoder().encode(value)
            broadcast(data: data, opcode: .text)
        } catch {
            print("HoloBroadcaster JSON encode error: \(error)")
        }
    }

    public func broadcastBinary(_ data: Data) {
        broadcast(data: data, opcode: .binary)
    }

    public func broadcast(_ telemetry: HoloTelemetry) {
        broadcastJSON(telemetry)
    }

    private func accept(_ conn: NWConnection) {
        lock.lock()
        if clients.count >= config.maxClients {
            lock.unlock()
            conn.cancel()
            return
        }
        clients[ObjectIdentifier(conn)] = conn
        lock.unlock()

        conn.stateUpdateHandler = { [weak self] state in
            switch state {
            case .failed, .cancelled:
                self?.remove(conn)
            default: break
            }
        }
        receiveLoop(conn)
        conn.start(queue: queue)
    }

    private func remove(_ conn: NWConnection) {
        lock.lock()
        clients.removeValue(forKey: ObjectIdentifier(conn))
        lock.unlock()
    }

    private func receiveLoop(_ conn: NWConnection) {
        conn.receiveMessage { [weak self] _, _, _, error in
            if let error = error {
                // Client likely disconnected.
                self?.remove(conn)
                print("HoloBroadcaster recv error: \(error)")
                return
            }
            // Ignore inbound; this is a broadcast‑only channel.
            self?.receiveLoop(conn)
        }
    }

    private func broadcast(data: Data, opcode: NWProtocolWebSocket.Opcode) {
        lock.lock()
        let conns = Array(clients.values)
        lock.unlock()

        guard !conns.isEmpty else { return }
        let meta = NWProtocolWebSocket.Metadata(opcode: opcode)
        let ctx = NWConnection.ContentContext(identifier: "holo.broadcast", metadata: [meta])

        for c in conns {
            c.send(content: data, contentContext: ctx, isComplete: true, completion: .contentProcessed { err in
                if let err = err {
                    // On failure, drop the client.
                    self.remove(c)
                    print("HoloBroadcaster send error: \(err)")
                }
            })
        }
    }
}
