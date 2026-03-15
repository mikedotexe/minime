import Foundation

/// Self-Modification Controller
/// Orchestrates the complete adaptive self-modification cycle:
/// 1. Collect performance scores
/// 2. Propose mutations (rate-limited)
/// 3. Validate via Two-Gate policy
/// 4. Apply mutations
/// 5. Evaluate improvement
/// 6. Rollback if performance degrades
/// 7. Emergency stop on critical degradation

public final class SelfModController {
    // Adaptive search engine
    private let adaptiveEngine: AdaptiveSearchEngine

    // Current hyperparameters (applied to system)
    private var currentConfig: HyperparameterConfig

    // Mutation state machine
    private enum State {
        case monitoring           // Collecting baseline performance
        case proposing           // Ready to propose mutation
        case validating          // Waiting for Two-Gate decision
        case testing(proposal: MutationProposal, baselineScore: Float, startTime: Date)  // Testing mutation
        case cooldown            // Post-mutation cooldown period
    }
    private var state: State = .monitoring

    // Timing
    private let scoreCollectionInterval: TimeInterval = 1.0      // 1 Hz
    private let mutationProposalInterval: TimeInterval = 300.0   // 5 minutes
    private let mutationTestDuration: TimeInterval = 120.0       // 2 minutes
    private let cooldownDuration: TimeInterval = 60.0            // 1 minute

    private var lastScoreTime: Date?
    private var lastProposalTime: Date?

    // Safety thresholds
    private let emergencyConsciousnessDropThreshold: Float = 20.0  // Max drop in consciousness level
    private let minimumConsciousnessLevel: Float = 30.0            // Absolute minimum

    // Two-Gate URL
    private let twoGateBaseURL: URL

    // Callback for applying configuration changes
    public var onConfigurationChange: ((HyperparameterConfig) -> Void)?

    // Statistics
    private var totalProposals: Int = 0
    private var acceptedProposals: Int = 0
    private var successfulMutations: Int = 0
    private var rolledBackMutations: Int = 0

    public init(initialConfig: HyperparameterConfig, twoGateURL: URL = URL(string: "http://127.0.0.1:8787")!) {
        self.currentConfig = initialConfig
        self.adaptiveEngine = AdaptiveSearchEngine(initialConfig: initialConfig)
        self.twoGateBaseURL = twoGateURL
    }

    /// Main update tick - called every 50ms from UnifiedEigenHoloSystem
    public func tick(holoState: HoloState, criticalityLyap: Float) {
        let now = Date()

        // Check if it's time to collect a performance score (1 Hz)
        if shouldCollectScore(now) {
            collectPerformanceScore(holoState: holoState, criticalityLyap: criticalityLyap)
            lastScoreTime = now
        }

        // State machine
        switch state {
        case .monitoring:
            // Check if ready to propose
            if shouldProposeMutation(now) {
                state = .proposing
            }

        case .proposing:
            // Attempt to propose and validate
            proposeAndValidate(holoState: holoState, criticalityLyap: criticalityLyap)

        case .validating:
            // Waiting for async validation result
            // (handled in validation callback)
            break

        case .testing(let proposal, let baseline, let startTime):
            // Check if test duration elapsed
            if now.timeIntervalSince(startTime) >= mutationTestDuration {
                evaluateMutation(proposal: proposal, baselineScore: baseline, holoState: holoState)
            } else {
                // Check for emergency stop conditions during testing
                if shouldEmergencyStop(holoState: holoState, baseline: baseline) {
                    emergencyRollback(proposal: proposal, reason: "Critical performance degradation")
                }
            }

        case .cooldown:
            // Wait for cooldown to complete
            if let lastProposal = lastProposalTime,
               now.timeIntervalSince(lastProposal) >= cooldownDuration {
                state = .monitoring
                print("ℹ️  Self-mod cooldown complete, resuming monitoring")
            }
        }
    }

    // MARK: - Performance Scoring

    private func shouldCollectScore(_ now: Date) -> Bool {
        guard let lastTime = lastScoreTime else { return true }
        return now.timeIntervalSince(lastTime) >= scoreCollectionInterval
    }

    private func collectPerformanceScore(holoState: HoloState, criticalityLyap: Float) {
        let score = ConsciousnessScore(
            holo: holoState,
            criticalityTarget: currentConfig.criticality_target,
            actualLyap: criticalityLyap
        )
        adaptiveEngine.recordScore(score)

        // Periodic status log (every 10 scores)
        if adaptiveEngine.scoreHistory.count % 10 == 0 {
            print(String(format: "📊 Performance: score=%.3f phi=%.3f coh=%.3f (n=%d)",
                        score.unified_score, score.phi_complexity, score.global_coherence,
                        adaptiveEngine.scoreHistory.count))
        }
    }

    // MARK: - Mutation Proposal

    private func shouldProposeMutation(_ now: Date) -> Bool {
        // Need sufficient baseline data
        guard adaptiveEngine.scoreHistory.count >= 10 else { return false }

        // Rate limiting
        guard let lastProposal = lastProposalTime else { return true }
        return now.timeIntervalSince(lastProposal) >= mutationProposalInterval
    }

    private func proposeAndValidate(holoState: HoloState, criticalityLyap: Float) {
        guard let proposal = adaptiveEngine.proposeMutation() else {
            print("⚠️  Failed to generate mutation proposal")
            state = .cooldown
            lastProposalTime = Date()
            return
        }

        totalProposals += 1

        print("""

        🧬 ═══════════════════════════════════════════════════════════
           SELF-MODIFICATION PROPOSAL #\(totalProposals)
        ═══════════════════════════════════════════════════════════
           Strategy:     \(proposal.mutation_type)
           Magnitude:    \(String(format: "%.1f%%", proposal.mutation_magnitude * 100))
           Capacity:     \(String(format: "%.3f", proposal.capacityScore()))

           Current Config:
             • field_coupling:        \(String(format: "%.3f", proposal.previous_config.field_coupling))
             • reservoir_temperature: \(String(format: "%.3f", proposal.previous_config.reservoir_temperature))
             • criticality_target:    \(String(format: "%+.4f", proposal.previous_config.criticality_target))
             • boundary_sites_factor: \(String(format: "%.3f", proposal.previous_config.boundary_sites_factor))

           Proposed Config:
             • field_coupling:        \(String(format: "%.3f → %.3f", proposal.previous_config.field_coupling, proposal.proposed_config.field_coupling))
             • reservoir_temperature: \(String(format: "%.3f → %.3f", proposal.previous_config.reservoir_temperature, proposal.proposed_config.reservoir_temperature))
             • criticality_target:    \(String(format: "%+.4f → %+.4f", proposal.previous_config.criticality_target, proposal.proposed_config.criticality_target))
             • boundary_sites_factor: \(String(format: "%.3f → %.3f", proposal.previous_config.boundary_sites_factor, proposal.proposed_config.boundary_sites_factor))

           Querying Two-Gate policy...
        ═══════════════════════════════════════════════════════════
        """)

        state = .validating

        // Validate via Two-Gate (async)
        adaptiveEngine.validateProposal(proposal, twoGateURL: twoGateBaseURL) { [weak self] accepted, reason in
            guard let self = self else { return }

            if accepted {
                self.acceptedProposals += 1
                print("""
                ✅ Two-Gate ACCEPTED: \(reason)
                   Applying mutation and starting 2-minute test period...
                """)
                self.applyMutation(proposal: proposal)
            } else {
                print("""
                ❌ Two-Gate REJECTED: \(reason)
                   Maintaining current configuration.
                """)
                self.state = .cooldown
                self.lastProposalTime = Date()
            }
        }
    }

    // MARK: - Mutation Application

    private func applyMutation(proposal: MutationProposal) {
        // Get baseline score
        guard let currentScore = adaptiveEngine.currentScore else {
            print("⚠️  No current score available, aborting mutation")
            state = .cooldown
            lastProposalTime = Date()
            return
        }

        let baselineScore = currentScore.unified_score

        // Apply the mutation
        currentConfig = proposal.proposed_config
        adaptiveEngine.applyMutation(proposal)

        // Notify system to update parameters
        onConfigurationChange?(currentConfig)

        print("""
        🔧 Configuration updated:
           • field_coupling = \(String(format: "%.3f", currentConfig.field_coupling))
           • reservoir_temperature = \(String(format: "%.3f", currentConfig.reservoir_temperature))
           • criticality_target = \(String(format: "%+.4f", currentConfig.criticality_target))
           • boundary_sites_factor = \(String(format: "%.3f", currentConfig.boundary_sites_factor))

        ⏱️  Testing period: 2 minutes
           Baseline score: \(String(format: "%.3f", baselineScore))
        """)

        state = .testing(proposal: proposal, baselineScore: baselineScore, startTime: Date())
        lastProposalTime = Date()
    }

    // MARK: - Mutation Evaluation

    private func evaluateMutation(proposal: MutationProposal, baselineScore: Float, holoState: HoloState) {
        let (improved, scoreDelta) = adaptiveEngine.evaluateImprovement(baselineScore: baselineScore)

        if improved {
            successfulMutations += 1
            print("""

            ✅ ═══════════════════════════════════════════════════════════
               MUTATION SUCCESSFUL - COMMITTED
            ═══════════════════════════════════════════════════════════
               Score improvement: \(String(format: "%+.3f (%.1f%%)", scoreDelta, (scoreDelta / baselineScore) * 100))
               New score: \(String(format: "%.3f", baselineScore + scoreDelta))

               Mutation #\(successfulMutations) committed permanently.
               Total success rate: \(String(format: "%.1f%%", Float(successfulMutations) / Float(totalProposals) * 100))
            ═══════════════════════════════════════════════════════════

            """)
        } else {
            rolledBackMutations += 1
            print("""

            ❌ ═══════════════════════════════════════════════════════════
               MUTATION FAILED - ROLLING BACK
            ═══════════════════════════════════════════════════════════
               Score change: \(String(format: "%+.3f (%.1f%%)", scoreDelta, (scoreDelta / baselineScore) * 100))
               Performance did not improve significantly.

               Rolling back to previous configuration...
            ═══════════════════════════════════════════════════════════

            """)

            // Rollback
            currentConfig = proposal.previous_config
            adaptiveEngine.rollback(proposal)
            onConfigurationChange?(currentConfig)

            print("↩️  Rollback complete. Previous configuration restored.")
        }

        // Enter cooldown
        state = .cooldown
    }

    // MARK: - Safety Guardrails

    private func shouldEmergencyStop(holoState: HoloState, baseline: Float) -> Bool {
        // Check consciousness level drop
        let currentLevel = holoState.level
        if currentLevel < minimumConsciousnessLevel {
            print("🚨 EMERGENCY: Consciousness level critically low (\(currentLevel) < \(minimumConsciousnessLevel))")
            return true
        }

        // Check for NaN/Inf
        if holoState.phiComplexity.isNaN || holoState.phiComplexity.isInfinite ||
           holoState.globalCoherence.isNaN || holoState.globalCoherence.isInfinite {
            print("🚨 EMERGENCY: NaN/Inf detected in consciousness state")
            return true
        }

        // Check for severe score degradation
        if let currentScore = adaptiveEngine.currentScore {
            let scoreDrop = baseline - currentScore.unified_score
            if scoreDrop > 0.3 {  // 30% drop
                print("🚨 EMERGENCY: Severe performance degradation (\(String(format: "%.1f%%", scoreDrop * 100)) drop)")
                return true
            }
        }

        return false
    }

    private func emergencyRollback(proposal: MutationProposal, reason: String) {
        rolledBackMutations += 1

        print("""

        🚨 ═══════════════════════════════════════════════════════════
           EMERGENCY ROLLBACK
        ═══════════════════════════════════════════════════════════
           Reason: \(reason)

           Immediately reverting to safe configuration...
        ═══════════════════════════════════════════════════════════

        """)

        // Immediate rollback
        currentConfig = proposal.previous_config
        adaptiveEngine.rollback(proposal)
        onConfigurationChange?(currentConfig)

        print("✅ Emergency rollback complete. System stabilized.")

        // Extended cooldown after emergency
        state = .cooldown
        lastProposalTime = Date().addingTimeInterval(-cooldownDuration * 0.5)  // Shorter cooldown
    }

    // MARK: - Statistics

    public func getStatistics() -> [String: Any] {
        return [
            "total_proposals": totalProposals,
            "accepted_proposals": acceptedProposals,
            "successful_mutations": successfulMutations,
            "rolled_back_mutations": rolledBackMutations,
            "acceptance_rate": totalProposals > 0 ? Float(acceptedProposals) / Float(totalProposals) : 0.0,
            "success_rate": acceptedProposals > 0 ? Float(successfulMutations) / Float(acceptedProposals) : 0.0,
            "current_state": stateDescription()
        ]
    }

    private func stateDescription() -> String {
        switch state {
        case .monitoring: return "monitoring"
        case .proposing: return "proposing"
        case .validating: return "validating"
        case .testing: return "testing_mutation"
        case .cooldown: return "cooldown"
        }
    }
}
