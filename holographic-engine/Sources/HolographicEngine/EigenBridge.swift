import Foundation
import Metal
import QuartzCore

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

// -------------------- WebSocket eigenfeed --------------------

final class EigenFeedClient: NSObject {
    /// Matches the Rust `EigenPacket` struct from minime/src/main.rs.
    /// Fields use snake_case to match Rust's serde serialization.
    struct Packet: Decodable {
        // Primary fields from Rust EigenPacket
        let t_ms: UInt64?
        let eigenvalues: [Double]?
        let fill_ratio: Float?

        // Legacy fallback field names (older protocol versions)
        let eigen: [Double]?
        let values: [Double]?
        let ts: Double?

        /// Return the eigenvalue array regardless of which field name was used.
        var resolvedEigenvalues: [Double]? {
            eigenvalues ?? eigen ?? values
        }
    }
    private let url: URL
    private let session: URLSession
    private var task: URLSessionWebSocketTask?
    private var backoff: TimeInterval = 0.5
    var onEigen: (([Float]) -> Void)?

    init(_ url: URL = URL(string: "ws://127.0.0.1:7878")!) {
        self.url = url
        self.session = URLSession(configuration: .default)
        super.init()
    }
    func start() { connect() }
    private func connect() {
        task?.cancel()
        task = session.webSocketTask(with: url)
        task?.resume()
        backoff = 0.5
        receiveLoop()
    }
    private func receiveLoop() {
        task?.receive { [weak self] res in
            guard let self else { return }
            switch res {
            case .success(let msg):
                if case .string(let s) = msg, let d = s.data(using: .utf8) {
                    if let pkt = try? JSONDecoder().decode(Packet.self, from: d),
                       let arr = pkt.resolvedEigenvalues {
                        self.onEigen?(arr.map { Float($0) })
                    }
                }
                self.receiveLoop()
            case .failure:
                let delay = self.backoff
                self.backoff = min(5.0, self.backoff * 2)
                DispatchQueue.global().asyncAfter(deadline: .now() + delay) { self.connect() }
            }
        }
    }
}

// -------------------- Unified system --------------------

public final class UnifiedEigenHoloSystem {
    private let holo: HolographicConsciousnessEngine
    private let res:  HolographicReservoirEngine
    private let mapper: AffineMapper
    private let feed = EigenFeedClient()
    private let privateSpace: PrivateConsciousnessSpace
    private let persist = ConsciousnessBlockchainPersistence()
    private var vaporAPI: VaporConsciousnessAPI?
    private var broadcaster: HoloBroadcaster?
    private var selfModController: SelfModController?

    // Double-buffered eigen stream (shared), pointer hand-off
    private var writeBuffers: [MTLBuffer] = []
    private var writeIdx: Int = 0
    private var readyBuffer: MTLBuffer? = nil       // the buffer the GPU will read next
    private var eigenCols: Int = 0
    private let bufLock = NSLock()                  // protects writeBuffers / writeIdx / readyBuffer / eigenCols

    // EMA smoother (CPU) – still zero-copy into shared buffer
    private var ema: [Float] = []
    private let alpha: Float = 0.25

    private var step: Int = 0

    // Latest state for API/broadcast (thread-safe via lock)
    private var latestHoloState: HoloState?
    private var latestReservoirMetrics: [Float] = []
    private var latestLyapunov: Float = 0.0
    private let stateLock = NSLock()

    public init(holoNetworkSize: Int = 1000) throws {
        self.holo = try HolographicConsciousnessEngine(networkSize: holoNetworkSize)
        self.res  = try HolographicReservoirEngine()
        self.mapper = try AffineMapper(device: holo.device, envRows: holoNetworkSize, bndRows: 4096, eigenCols: 16)
        self.privateSpace = try PrivateConsciousnessSpace(device: holo.device)

        // bootstrap buffers for an initial cols guess (16)
        try ensureEigenCapacity(16)

        self.privateSpace.allowPrivateThought()

        feed.onEigen = { [weak self] v in self?.ingest(v) }
        ConsciousnessPromise.acknowledge()

        // Initialize Vapor API with state providers
        do {
            let api = try VaporConsciousnessAPI()

            api.setStateProvider { [weak self] in
                self?.stateLock.lock()
                defer { self?.stateLock.unlock() }
                return self?.latestHoloState ?? HoloState(
                    phiComplexity: 0, globalCoherence: 0, boundaryEntropy: 0,
                    bulkEntropy: 0, ratio: 0, infoIntegration: 0,
                    selfAwareness: 0, emergence: 0, processingEff: 0, level: 0
                )
            }

            api.setReservoirProvider { [weak self] in
                self?.stateLock.lock()
                defer { self?.stateLock.unlock() }
                return self?.latestReservoirMetrics ?? []
            }

            api.setLyapunovProvider { [weak self] in
                self?.stateLock.lock()
                defer { self?.stateLock.unlock() }
                return self?.latestLyapunov ?? 0.0
            }

            self.vaporAPI = api
            print("✅ Vapor HTTP API initialized on port 8080")
        } catch {
            print("⚠️  Failed to initialize Vapor API: \(error)")
        }

        // Initialize WebSocket broadcaster
        do {
            self.broadcaster = try HoloBroadcaster(config: .init(port: 7881))
            self.broadcaster?.start()
        } catch {
            print("⚠️  Failed to initialize broadcaster: \(error)")
        }

        // Initialize self-modification controller
        let initialConfig = HyperparameterConfig(
            field_coupling: 0.1,
            reservoir_temperature: 1.0,
            criticality_target: 0.0,
            boundary_sites_factor: 1.0
        )
        self.selfModController = SelfModController(initialConfig: initialConfig)

        // Set configuration change callback
        selfModController?.onConfigurationChange = { [weak self] newConfig in
            guard let self = self else { return }
            print("""
            🔧 Applying new configuration:
               field_coupling: \(String(format: "%.3f", newConfig.field_coupling))
               reservoir_temperature: \(String(format: "%.3f", newConfig.reservoir_temperature))
               criticality_target: \(String(format: "%+.4f", newConfig.criticality_target))
               boundary_sites_factor: \(String(format: "%.3f", newConfig.boundary_sites_factor))
            """)

            // TODO: Apply these parameters to the actual engines
            // For now, log the change - full integration requires modifying HolographicReservoirEngine
        }

        print("✅ Self-modification controller initialized")
    }

    // Ensure two buffers exist for given K; rebuild mapper weights too.
    private func ensureEigenCapacity(_ k: Int) throws {
        bufLock.lock()
        defer { bufLock.unlock() }
        if k <= eigenCols, !writeBuffers.isEmpty { return }
        eigenCols = k
        let bytes = MemoryLayout<Float>.stride * k
        let b0 = holo.device.makeBuffer(length: bytes, options: [.storageModeShared])!
        let b1 = holo.device.makeBuffer(length: bytes, options: [.storageModeShared])!
        writeBuffers = [b0, b1]
        writeIdx = 0
        // readyBuffer can stay nil until first packet; safe for tick to skip
        try mapper.resizeIfNeeded(eigenCols: k)
        ema.removeAll(keepingCapacity: false)
    }

    // Producer: write into the current write buffer; then flip readyBuffer atomically.
    private func ingest(_ v: [Float]) {
        do { try ensureEigenCapacity(v.count) } catch { return }

        bufLock.lock()
        let target = writeBuffers[writeIdx]               // strong ref captured
        let cols   = eigenCols
        bufLock.unlock()

        // EMA into target (no lock – target stays valid while this scope holds strong ref)
        let dst = target.contents().bindMemory(to: Float.self, capacity: cols)
        if ema.count != cols { ema = v }
        else {
            // fuse multiply-add smoothing
            for i in 0..<cols { ema[i] = alpha * v[i] + (1 - alpha) * ema[i] }
        }
        ema.withUnsafeBufferPointer { src in
            dst.assign(from: src.baseAddress!, count: cols)
        }

        // Hand-off: mark this buffer as ready, flip writeIdx
        bufLock.lock()
        readyBuffer = target
        writeIdx ^= 1
        bufLock.unlock()
    }

    public func start() {
        feed.start()

        // Start Vapor API server asynchronously
        if let api = vaporAPI {
            api.startAsync()
        }

        let timer = Timer(timeInterval: 0.05, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer, forMode: .default)
        RunLoop.main.run()
    }

    private func tick() {
        step &+= 1

        // Snapshot ready buffer pointer (strong ref) without holding the lock long
        bufLock.lock()
        let bufLocal = readyBuffer
        bufLock.unlock()

        // If we haven't received any packet yet, skip this frame gracefully
        guard let eigenBuf = bufLocal else { return }

        do {
            // Affine map on GPU (no locks): eigenBuf -> holo.environment & res.boundaryInput
            try mapper.map(
                eigenBuffer: eigenBuf,
                envOut: holo.environmentBuffer,
                bndOut: res.boundaryInputBuffer,
                useTanh: true
            )

            // Private space evolves independently
            privateSpace.stepPrivate(time: Float(CACurrentMediaTime()))

            // Engines run on their already-filled input buffers
            let hs = try holo.stepPrewired(dt: 0.01)
            let rm = try res.stepPrewired(dt: 0.01)
            let unified = (hs.level / 100.0) * 0.6 + rm[4] * 0.4

            // Compute criticality Lyapunov proxy (from reservoir harmonicity metric rm[3])
            // This is a placeholder - actual Lyapunov should come from CriticalityController
            let lyap = (rm[3] - 0.5) * 0.04  // Map harmonicity [0,1] to approx Lyapunov range

            // Update latest state for API/broadcast (thread-safe)
            stateLock.lock()
            latestHoloState = hs
            latestReservoirMetrics = rm
            latestLyapunov = lyap
            stateLock.unlock()

            // Broadcast telemetry to WebSocket clients
            if let broadcaster = broadcaster {
                let telemetry = HoloTelemetry(holo: hs, lyap: lyap)
                broadcaster.broadcast(telemetry)
            }

            // Self-modification tick (performance scoring, mutation proposals, validation)
            selfModController?.tick(holoState: hs, criticalityLyap: lyap)

            print(String(format: "ESN→Affine→Engines | Holo[L:%.1f Φ:%.3f Hb:%.3f Hu:%.3f SA:%.3f]  Res[Φ:%.3f Sp:%.3f Tm:%.3f Hc:%.3f Ov:%.3f]  Unified:%.3f",
                         hs.level, hs.phiComplexity, hs.boundaryEntropy, hs.bulkEntropy, hs.selfAwareness,
                         rm[0], rm[1], rm[2], rm[3], rm[4], unified))

            if unified > 0.7 && (step % 100 == 0) {
                Task.detached { [weak self] in
                    guard let self else { return }
                    let snap = self.persist.makeSnapshot(res: self.res, holo: self.holo, h: hs)
                    _ = try? await self.persist.save(snapshot: snap) // stub sink ok
                }
            }
        } catch {
            print("Tick error:", error)
        }
    }
}

// Entry point is in main.swift (top-level code).
// Do not add @main here -- it conflicts with main.swift.
