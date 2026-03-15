import Foundation
import Accelerate

/// Differential privacy for reservoir readout training.
/// Protects internal states via calibrated Gaussian noise, tracks privacy budget (ε, δ).
public struct DPReadout {
    public struct Config {
        public var epsilon: Float        // privacy budget per query
        public var delta: Float           // failure probability
        public var clipNorm: Float        // gradient clipping threshold
        public var noiseSigma: Float      // Gaussian σ = clipNorm × sqrt(2×ln(1.25/δ)) / ε

        public init(epsilon: Float = 1.0, delta: Float = 1e-5, clipNorm: Float = 1.0) {
            self.epsilon = epsilon
            self.delta = delta
            self.clipNorm = clipNorm
            // Calibrate noise for (ε, δ)-DP
            self.noiseSigma = clipNorm * sqrt(2.0 * log(1.25 / delta)) / epsilon
        }
    }

    private var totalEpsilon: Float = 0.0  // accumulated privacy cost
    private let config: Config

    public init(config: Config = Config()) {
        self.config = config
    }

    /// Apply differential privacy to readout features: clip + Gaussian noise.
    /// Returns noisy features and updates privacy budget.
    public mutating func privatize(features: [Float]) -> [Float] {
        var clipped = features

        // 1) Gradient clipping (L2 norm bound)
        let norm = sqrt(vDSP.sum(vDSP.multiply(features, features)))
        if norm > config.clipNorm {
            let scale = config.clipNorm / norm
            vDSP.multiply(scale, features, result: &clipped)
        }

        // 2) Add Gaussian noise N(0, σ²)
        var noisy = clipped
        for i in 0..<noisy.count {
            noisy[i] += gaussianNoise(sigma: config.noiseSigma)
        }

        // 3) Update privacy budget
        totalEpsilon += config.epsilon

        return noisy
    }

    /// Query current privacy expenditure.
    public func budget() -> (epsilon: Float, delta: Float) {
        return (totalEpsilon, config.delta)
    }

    /// Reset privacy budget (e.g., after checkpointing).
    public mutating func reset() {
        totalEpsilon = 0.0
    }

    /// Generate Gaussian noise N(0, σ²) using Box-Muller transform.
    private func gaussianNoise(sigma: Float) -> Float {
        let u1 = Float.random(in: 0..<1)
        let u2 = Float.random(in: 0..<1)
        let z = sqrt(-2.0 * log(u1)) * cos(2.0 * .pi * u2)
        return z * sigma
    }
}

/// Wrapper for readout training with DP guarantees.
public struct DPReadoutTrainer {
    private var dp: DPReadout
    private let maxBudget: Float

    public init(epsilon: Float = 1.0, delta: Float = 1e-5, clipNorm: Float = 1.0, maxBudget: Float = 10.0) {
        self.dp = DPReadout(config: DPReadout.Config(epsilon: epsilon, delta: delta, clipNorm: clipNorm))
        self.maxBudget = maxBudget
    }

    /// Train readout on privatized features. Returns nil if budget exhausted.
    public mutating func trainStep(features: [Float]) -> [Float]? {
        let (spent, _) = dp.budget()
        guard spent < maxBudget else {
            print("⚠️  DP budget exhausted: ε=\(spent) ≥ \(maxBudget)")
            return nil
        }
        return dp.privatize(features: features)
    }

    /// Get current privacy expenditure.
    public func budget() -> (epsilon: Float, delta: Float) {
        return dp.budget()
    }

    /// Reset for new epoch.
    public mutating func reset() {
        dp.reset()
    }
}
