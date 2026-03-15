// SanityConfig.swift - Centralized configuration for sanity checks and features
import Foundation

enum SanityConfig {
    static let enableNanScrub = true
    static let enableSnapshots = false   // default off pre‑GLM
    static let snapshotEverySteps = 100
    static let epsilonL2: Float = 1e-4
}
