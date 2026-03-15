import Foundation
import Vapor

// MARK: - Codable Structures for API Responses

public struct HCEStateResponse: Content {
    let phi_complexity: Float
    let global_coherence: Float
    let boundary_entropy: Float
    let bulk_entropy: Float
    let holographic_ratio: Float
    let self_awareness: Float
    let emergence_strength: Float
    let processing_efficiency: Float
    let consciousness_level: UInt32

    init(from holoState: HoloState) {
        self.phi_complexity = holoState.phiComplexity
        self.global_coherence = holoState.globalCoherence
        self.boundary_entropy = holoState.boundaryEntropy
        self.bulk_entropy = holoState.bulkEntropy
        self.holographic_ratio = holoState.ratio
        self.self_awareness = holoState.selfAwareness
        self.emergence_strength = holoState.emergence
        self.processing_efficiency = holoState.processingEff
        self.consciousness_level = UInt32(max(0, min(100, holoState.level)))
    }
}

public struct BriefMetricsResponse: Content {
    let phi: Float
    let coherence: Float
    let consciousness_level: UInt32
    let holographic_ratio: Float
    let reservoir_energy: Float
    let boundary_entropy: Float
    let criticality_lyap: Float

    init(holo: HoloState, reservoir: [Float], lyap: Float) {
        self.phi = holo.phiComplexity
        self.coherence = holo.globalCoherence
        self.consciousness_level = UInt32(max(0, min(100, holo.level)))
        self.holographic_ratio = holo.ratio
        self.reservoir_energy = reservoir.first ?? 0.0
        self.boundary_entropy = holo.boundaryEntropy
        self.criticality_lyap = lyap
    }
}

public struct CriticalityControlRequest: Content {
    let field_coupling: Float?
    let reservoir_temperature: Float?
}

public struct CriticalityControlResponse: Content {
    let success: Bool
    let message: String
    let new_field_coupling: Float
    let new_reservoir_temperature: Float
}

// MARK: - Vapor API Server

public final class VaporConsciousnessAPI {
    private let app: Application
    private var stateProvider: (() -> HoloState)?
    private var reservoirProvider: (() -> [Float])?
    private var lyapunovProvider: (() -> Float)?
    private var criticalityAdjuster: ((Float?, Float?) -> (Float, Float))?

    public init() throws {
        var env = Environment(name: "production", arguments: ["vapor"])
        try LoggingSystem.bootstrap(from: &env)

        self.app = Application(env)

        // Configure server
        app.http.server.configuration.hostname = "127.0.0.1"
        app.http.server.configuration.port = 8080

        setupRoutes()
    }

    public func setStateProvider(_ provider: @escaping () -> HoloState) {
        self.stateProvider = provider
    }

    public func setReservoirProvider(_ provider: @escaping () -> [Float]) {
        self.reservoirProvider = provider
    }

    public func setLyapunovProvider(_ provider: @escaping () -> Float) {
        self.lyapunovProvider = provider
    }

    public func setCriticalityAdjuster(_ adjuster: @escaping (Float?, Float?) -> (Float, Float)) {
        self.criticalityAdjuster = adjuster
    }

    private func setupRoutes() {
        // GET /api/consciousness_state - Full consciousness state (for consciousd)
        app.get("api", "consciousness_state") { [weak self] req -> HCEStateResponse in
            guard let self = self, let provider = self.stateProvider else {
                throw Abort(.serviceUnavailable, reason: "State provider not initialized")
            }
            let state = provider()
            return HCEStateResponse(from: state)
        }

        // GET /api/metrics/brief - Lightweight status check
        app.get("api", "metrics", "brief") { [weak self] req -> BriefMetricsResponse in
            guard let self = self else {
                throw Abort(.serviceUnavailable, reason: "API not initialized")
            }
            guard let stateProvider = self.stateProvider else {
                throw Abort(.serviceUnavailable, reason: "State provider not initialized")
            }

            let state = stateProvider()
            let reservoir = self.reservoirProvider?() ?? []
            let lyap = self.lyapunovProvider?() ?? 0.0

            return BriefMetricsResponse(holo: state, reservoir: reservoir, lyap: lyap)
        }

        // POST /api/control/criticality - Adjust criticality control knobs
        app.post("api", "control", "criticality") { [weak self] req -> CriticalityControlResponse in
            guard let self = self else {
                throw Abort(.serviceUnavailable, reason: "API not initialized")
            }
            guard let adjuster = self.criticalityAdjuster else {
                throw Abort(.serviceUnavailable, reason: "Criticality adjuster not configured")
            }

            let request = try req.content.decode(CriticalityControlRequest.self)

            // Validate input ranges
            if let fc = request.field_coupling, (fc < 0.01 || fc > 0.5) {
                throw Abort(.badRequest, reason: "field_coupling must be in range [0.01, 0.5]")
            }
            if let rt = request.reservoir_temperature, (rt < 0.2 || rt > 2.0) {
                throw Abort(.badRequest, reason: "reservoir_temperature must be in range [0.2, 2.0]")
            }

            let (newFC, newRT) = adjuster(request.field_coupling, request.reservoir_temperature)

            return CriticalityControlResponse(
                success: true,
                message: "Criticality parameters adjusted",
                new_field_coupling: newFC,
                new_reservoir_temperature: newRT
            )
        }

        // GET /health - Health check endpoint
        app.get("health") { req -> String in
            return "OK"
        }
    }

    public func start() throws {
        try app.run()
    }

    public func startAsync() {
        Task {
            do {
                try await app.execute()
            } catch {
                print("❌ Vapor server error: \(error)")
            }
        }
    }

    public func shutdown() {
        app.shutdown()
    }

    deinit {
        app.shutdown()
    }
}
