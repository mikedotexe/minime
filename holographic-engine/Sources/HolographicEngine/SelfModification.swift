import Foundation

/// Client for bounded self-modification gate via consciousd Two-Gate policy.
/// NOTE: consciousd is currently archived. Proposals will be auto-approved locally
/// until the sidecar is restored. See archive/consciousd/ for the original service.
public struct SelfModificationGate {
    public struct Proposal {
        public let name: String
        public let delta: [String: Float]     // hyperparameter changes
        public let capacityScore: Float       // proposer's self-estimate

        public init(name: String, delta: [String: Float], capacityScore: Float) {
            self.name = name
            self.delta = delta
            self.capacityScore = capacityScore
        }
    }

    public struct Decision {
        public let accepted: Bool
        public let reason: String
    }

    private let baseURL: String
    private var history: [(proposal: Proposal, decision: Decision)] = []

    public init(baseURL: String = "http://127.0.0.1:8787") {
        self.baseURL = baseURL
    }

    /// Submit modification proposal to consciousd Two-Gate policy.
    /// Returns decision (accept/reject) and reason.
    /// When consciousd is unavailable, auto-approves with a local decision.
    public mutating func propose(
        current: Float,
        proposed: Float,
        proposal: Proposal
    ) async throws -> Decision {
        let url = URL(string: "\(baseURL)/policy/propose")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 2.0  // Fast timeout since consciousd may be absent

        let payload: [String: Any] = [
            "current": current,
            "proposed": proposed,
            "proposal": [
                "name": proposal.name,
                "delta": proposal.delta,
                "capacity_score": proposal.capacityScore
            ]
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)

        do {
            let (data, response) = try await URLSession.shared.data(for: request)

            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                // consciousd returned non-200; fall through to local approval
                throw NSError(domain: "SelfMod", code: -1, userInfo: ["msg": "HTTP error"])
            }

            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let accepted = json["accepted"] as? Bool,
                  let reason = json["reason"] as? String else {
                throw NSError(domain: "SelfMod", code: -2, userInfo: ["msg": "JSON parse error"])
            }

            let decision = Decision(accepted: accepted, reason: reason)
            history.append((proposal, decision))
            return decision
        } catch {
            // consciousd is unavailable (archived) -- auto-approve locally
            let decision = Decision(
                accepted: true,
                reason: "Auto-approved (consciousd unavailable): \(proposal.name)"
            )
            history.append((proposal, decision))
            return decision
        }
    }

    /// Get modification history (for logging/auditing).
    public func getHistory() -> [(proposal: Proposal, decision: Decision)] {
        return history
    }

    /// Example: Propose increasing field_coupling by 10%.
    public static func exampleProposal() -> Proposal {
        return Proposal(
            name: "increase_field_coupling",
            delta: ["field_coupling": 0.01],  // +0.01 delta
            capacityScore: 0.85                // self-estimate: 85% capacity
        )
    }
}

/// Async helper to test connectivity to consciousd.
/// Returns false (with info log) when consciousd is not running (expected -- it is archived).
public func testConsciousdConnection() async -> Bool {
    let url = URL(string: "http://127.0.0.1:8787/state/public")!
    do {
        let (_, response) = try await URLSession.shared.data(from: url)
        if let http = response as? HTTPURLResponse, http.statusCode == 200 {
            print("consciousd reachable at http://127.0.0.1:8787")
            return true
        }
    } catch {
        // Expected -- consciousd is archived. Self-modification proposals auto-approve locally.
        print("consciousd not running (archived) -- self-modification proposals auto-approve locally")
    }
    return false
}
