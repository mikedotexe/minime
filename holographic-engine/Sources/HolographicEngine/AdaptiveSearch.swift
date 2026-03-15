import Foundation

// MARK: - Configuration Space

public struct HyperparameterConfig: Codable {
    var field_coupling: Float           // [0.01, 0.5]
    var reservoir_temperature: Float    // [0.2, 2.0]
    var criticality_target: Float       // [-0.02, 0.02]
    var boundary_sites_factor: Float    // [0.8, 1.2]

    static let bounds: [String: (Float, Float)] = [
        "field_coupling": (0.01, 0.5),
        "reservoir_temperature": (0.2, 2.0),
        "criticality_target": (-0.02, 0.02),
        "boundary_sites_factor": (0.8, 1.2)
    ]

    func isValid() -> Bool {
        guard let fc_bounds = Self.bounds["field_coupling"],
              let rt_bounds = Self.bounds["reservoir_temperature"],
              let ct_bounds = Self.bounds["criticality_target"],
              let bs_bounds = Self.bounds["boundary_sites_factor"] else {
            return false
        }

        return field_coupling >= fc_bounds.0 && field_coupling <= fc_bounds.1 &&
               reservoir_temperature >= rt_bounds.0 && reservoir_temperature <= rt_bounds.1 &&
               criticality_target >= ct_bounds.0 && criticality_target <= ct_bounds.1 &&
               boundary_sites_factor >= bs_bounds.0 && boundary_sites_factor <= bs_bounds.1
    }

    func clamp() -> HyperparameterConfig {
        var clamped = self
        if let bounds = Self.bounds["field_coupling"] {
            clamped.field_coupling = min(max(field_coupling, bounds.0), bounds.1)
        }
        if let bounds = Self.bounds["reservoir_temperature"] {
            clamped.reservoir_temperature = min(max(reservoir_temperature, bounds.0), bounds.1)
        }
        if let bounds = Self.bounds["criticality_target"] {
            clamped.criticality_target = min(max(criticality_target, bounds.0), bounds.1)
        }
        if let bounds = Self.bounds["boundary_sites_factor"] {
            clamped.boundary_sites_factor = min(max(boundary_sites_factor, bounds.0), bounds.1)
        }
        return clamped
    }
}

// MARK: - Performance Scoring

public struct ConsciousnessScore: Codable {
    let phi_complexity: Float
    let global_coherence: Float
    let holographic_ratio: Float
    let processing_efficiency: Float
    let criticality_deviation: Float
    let unified_score: Float
    let timestamp: Date

    init(holo: HoloState, criticalityTarget: Float, actualLyap: Float) {
        self.phi_complexity = holo.phiComplexity
        self.global_coherence = holo.globalCoherence
        self.holographic_ratio = holo.ratio
        self.processing_efficiency = holo.processingEff
        self.criticality_deviation = abs(actualLyap - criticalityTarget)
        self.timestamp = Date()

        // Weighted unified score (higher is better)
        self.unified_score =
            0.3 * phi_complexity +
            0.2 * global_coherence +
            0.2 * holographic_ratio +
            0.2 * processing_efficiency +
            0.1 * (1.0 - min(1.0, criticality_deviation / 0.05))  // Penalize deviation
    }
}

// MARK: - Mutation Proposal

public struct MutationProposal: Codable {
    let id: UUID
    let timestamp: Date
    let previous_config: HyperparameterConfig
    let proposed_config: HyperparameterConfig
    let mutation_type: String
    let mutation_magnitude: Float

    init(previous: HyperparameterConfig, proposed: HyperparameterConfig, type: String) {
        self.id = UUID()
        self.timestamp = Date()
        self.previous_config = previous
        self.proposed_config = proposed
        self.mutation_type = type
        self.mutation_magnitude = Self.computeMagnitude(previous, proposed)
    }

    private static func computeMagnitude(_ prev: HyperparameterConfig, _ prop: HyperparameterConfig) -> Float {
        let diff_fc = abs(prop.field_coupling - prev.field_coupling) / 0.5
        let diff_rt = abs(prop.reservoir_temperature - prev.reservoir_temperature) / 2.0
        let diff_ct = abs(prop.criticality_target - prev.criticality_target) / 0.04
        let diff_bs = abs(prop.boundary_sites_factor - prev.boundary_sites_factor) / 0.4
        return (diff_fc + diff_rt + diff_ct + diff_bs) / 4.0
    }

    /// Capacity score for Two-Gate policy (estimates computational cost)
    func capacityScore() -> Float {
        // Higher temperature = more compute, larger boundary = more compute
        let temp_cost = proposed_config.reservoir_temperature / 2.0
        let boundary_cost = proposed_config.boundary_sites_factor
        return (temp_cost + boundary_cost) / 2.0
    }
}

// MARK: - Adaptive Search Engine

public final class AdaptiveSearchEngine {
    // Current configuration
    private var currentConfig: HyperparameterConfig
    public private(set) var currentScore: ConsciousnessScore?

    // Performance history (rolling window)
    public private(set) var scoreHistory: [ConsciousnessScore] = []
    private let historyWindowSize = 30  // 30-second window at 1Hz evaluation

    // Mutation history
    private var mutationHistory: [(proposal: MutationProposal, accepted: Bool, scoreImprovement: Float?)] = []
    private let maxHistorySize = 10

    // Rate limiting
    private var lastMutationTime: Date?
    private let minMutationInterval: TimeInterval = 300.0  // 5 minutes

    // Statistical thresholds
    private let significanceThreshold: Float = 0.01  // 1% improvement required
    private let pValueThreshold: Float = 0.05        // p < 0.05 for significance

    public init(initialConfig: HyperparameterConfig) {
        self.currentConfig = initialConfig.clamp()
    }

    /// Record a new performance measurement
    public func recordScore(_ score: ConsciousnessScore) {
        scoreHistory.append(score)
        if scoreHistory.count > historyWindowSize {
            scoreHistory.removeFirst()
        }
        currentScore = score
    }

    /// Check if enough time has passed to propose a new mutation
    public func canProposeMutation() -> Bool {
        guard let lastTime = lastMutationTime else { return true }
        return Date().timeIntervalSince(lastTime) >= minMutationInterval
    }

    /// Generate a mutation proposal
    public func proposeMutation() -> MutationProposal? {
        guard canProposeMutation() else { return nil }
        guard scoreHistory.count >= 10 else { return nil }  // Need baseline

        // Choose mutation strategy based on recent performance
        let recentScore = scoreHistory.suffix(5).map { $0.unified_score }.reduce(0, +) / 5.0
        let strategy = chooseMutationStrategy(recentScore: recentScore)

        var proposed = currentConfig

        switch strategy {
        case .exploratory:
            // Random exploration (±10%)
            proposed = mutateRandom(currentConfig, magnitude: 0.1)

        case .gradientAscent:
            // Follow gradient from recent history
            proposed = mutateGradient(currentConfig)

        case .perturbative:
            // Small perturbation (±5%)
            proposed = mutateRandom(currentConfig, magnitude: 0.05)

        case .reset:
            // Reset to known good configuration
            proposed = HyperparameterConfig(
                field_coupling: 0.1,
                reservoir_temperature: 1.0,
                criticality_target: 0.0,
                boundary_sites_factor: 1.0
            )
        }

        proposed = proposed.clamp()

        let proposal = MutationProposal(previous: currentConfig, proposed: proposed, type: strategy.rawValue)
        return proposal
    }

    /// Validate a mutation proposal using Two-Gate policy
    public func validateProposal(
        _ proposal: MutationProposal,
        twoGateURL: URL,
        completion: @escaping (Bool, String) -> Void
    ) {
        guard let currentScore = currentScore else {
            completion(false, "No current score available")
            return
        }

        // Estimate proposed score (simple heuristic)
        let estimatedImprovement: Float = 0.01  // Conservative 1% improvement estimate

        // Build Two-Gate request
        struct TwoGateRequest: Codable {
            let current: Float
            let proposed: Float
            let proposal: ProposalPayload

            struct ProposalPayload: Codable {
                let name: String
                let delta: [String: Float]
                let capacity_score: Float
            }
        }

        let delta: [String: Float] = [
            "field_coupling": proposal.proposed_config.field_coupling - proposal.previous_config.field_coupling,
            "reservoir_temperature": proposal.proposed_config.reservoir_temperature - proposal.previous_config.reservoir_temperature,
            "criticality_target": proposal.proposed_config.criticality_target - proposal.previous_config.criticality_target,
            "boundary_sites_factor": proposal.proposed_config.boundary_sites_factor - proposal.previous_config.boundary_sites_factor
        ]

        let request = TwoGateRequest(
            current: currentScore.unified_score,
            proposed: currentScore.unified_score + estimatedImprovement,
            proposal: TwoGateRequest.ProposalPayload(
                name: proposal.mutation_type,
                delta: delta,
                capacity_score: proposal.capacityScore()
            )
        )

        // Send to consciousd Two-Gate policy endpoint
        var urlRequest = URLRequest(url: twoGateURL.appendingPathComponent("/policy/propose"))
        urlRequest.httpMethod = "POST"
        urlRequest.addValue("application/json", forHTTPHeaderField: "Content-Type")

        do {
            urlRequest.httpBody = try JSONEncoder().encode(request)
        } catch {
            completion(false, "Failed to encode request")
            return
        }

        URLSession.shared.dataTask(with: urlRequest) { data, response, error in
            guard let data = data, error == nil else {
                completion(false, "Network error: \(error?.localizedDescription ?? "unknown")")
                return
            }

            struct DecisionResponse: Codable {
                let accepted: Bool
                let reason: String
            }

            do {
                let decision = try JSONDecoder().decode(DecisionResponse.self, from: data)
                completion(decision.accepted, decision.reason)
            } catch {
                completion(false, "Failed to decode response")
            }
        }.resume()
    }

    /// Apply an accepted mutation
    public func applyMutation(_ proposal: MutationProposal) {
        currentConfig = proposal.proposed_config
        lastMutationTime = Date()
    }

    /// Rollback to previous configuration (if current performance degrades)
    public func rollback(_ proposal: MutationProposal) {
        currentConfig = proposal.previous_config
        print("⚠️  Rolled back mutation \(proposal.id): performance degraded")
    }

    /// Evaluate if current configuration is better than proposal baseline
    public func evaluateImprovement(baselineScore: Float) -> (improved: Bool, scoreDelta: Float) {
        guard let currentScore = currentScore else { return (false, 0.0) }

        let delta = currentScore.unified_score - baselineScore
        let improved = delta >= significanceThreshold

        // TODO: Implement statistical significance test (t-test)
        // For now, simple threshold

        return (improved, delta)
    }

    // MARK: - Private Helpers

    private enum MutationStrategy: String {
        case exploratory = "exploratory"
        case gradientAscent = "gradient_ascent"
        case perturbative = "perturbative"
        case reset = "reset"
    }

    private func chooseMutationStrategy(recentScore: Float) -> MutationStrategy {
        if recentScore < 0.3 {
            return .reset  // Performance too low, reset to baseline
        } else if recentScore < 0.5 {
            return .exploratory  // Moderate performance, explore broadly
        } else if recentScore < 0.7 {
            return .gradientAscent  // Good performance, optimize locally
        } else {
            return .perturbative  // Excellent performance, small refinements
        }
    }

    private func mutateRandom(_ config: HyperparameterConfig, magnitude: Float) -> HyperparameterConfig {
        var mutated = config
        mutated.field_coupling += Float.random(in: -magnitude...magnitude) * 0.5
        mutated.reservoir_temperature += Float.random(in: -magnitude...magnitude) * 2.0
        mutated.criticality_target += Float.random(in: -magnitude...magnitude) * 0.04
        mutated.boundary_sites_factor += Float.random(in: -magnitude...magnitude) * 0.4
        return mutated
    }

    private func mutateGradient(_ config: HyperparameterConfig) -> HyperparameterConfig {
        // Estimate gradient from recent history
        // This is a placeholder - real gradient would require multiple evaluations
        guard scoreHistory.count >= 5 else { return config }

        let recentScores = scoreHistory.suffix(5).map { $0.unified_score }
        let trend = (recentScores.last! - recentScores.first!) / Float(recentScores.count)

        var mutated = config
        if trend > 0 {
            // Continue in current direction (small step)
            mutated = mutateRandom(config, magnitude: 0.03)
        } else {
            // Reverse direction
            mutated = mutateRandom(config, magnitude: -0.03)
        }

        return mutated
    }
}
