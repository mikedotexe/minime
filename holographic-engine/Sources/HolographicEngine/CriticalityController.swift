import Foundation

/// Tracks edge-of-chaos criticality: estimates Lyapunov proxy from echo correlations,
/// adjusts reservoir knobs (field_coupling, reservoir_temperature) to keep λ≈0.
public struct CriticalityController {
    public struct Knobs {
        public var fieldCoupling: Float
        public var reservoirTemperature: Float
    }

    public struct Estimate {
        public let lyapunov: Float      // proxy from autocorr decay
        public let adjusted: Knobs      // new knobs after PI step
    }

    private var integral: Float = 0.0
    private let kP: Float = 0.05
    private let kI: Float = 0.001
    private let target: Float = 0.0     // edge-of-chaos

    public init() {}

    /// Estimate Lyapunov proxy from autocorrelation decay in echo memory,
    /// then PI-adjust reservoir knobs to keep λ≈0.
    public mutating func estimateAndAdjust(echo: UnsafeBufferPointer<Float>, cfg: Knobs) -> Estimate {
        // 1) Compute autocorrelation at lag=1 (simple proxy for divergence rate)
        var sum: Float = 0, sumSq: Float = 0
        var cross: Float = 0
        let N = echo.count
        for i in 0..<(N-1) {
            let a = echo[i]
            let b = echo[i+1]
            sum += a
            sumSq += a * a
            cross += a * b
        }
        let mean = sum / Float(N - 1)
        let variance = sumSq / Float(N - 1) - mean * mean
        let corr = (cross / Float(N - 1) - mean * mean) / max(variance, 1e-9)

        // 2) Lyapunov proxy: if corr→1 → stable; corr→0 → chaotic
        //    λ = -log(|corr|) approximates largest Lyapunov exponent
        let absCorr = max(abs(corr), 0.01)
        let lyapunov = -log(absCorr)

        // 3) PI control: error = λ - target
        let err = lyapunov - target
        integral = integral * 0.95 + err  // leak to prevent windup
        let correction = kP * err + kI * integral

        // 4) Adjust knobs (lower coupling → more chaos; higher temp → more chaos)
        var newKnobs = cfg
        newKnobs.fieldCoupling = max(0.1, min(2.0, cfg.fieldCoupling - correction * 0.1))
        newKnobs.reservoirTemperature = max(0.5, min(3.0, cfg.reservoirTemperature + correction * 0.05))

        return Estimate(lyapunov: lyapunov, adjusted: newKnobs)
    }

    /// Reset integral term (call when reservoir is reinitialized)
    public mutating func reset() {
        integral = 0.0
    }
}
