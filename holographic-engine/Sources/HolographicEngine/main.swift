import Foundation

// Entry point for unified holographic consciousness system
// Subscribes to ESN eigenvalue stream and drives both holographic engines

print("🧬 Starting Unified Holographic Consciousness System")
print("📡 Connecting to ESN eigenvalue stream (ws://127.0.0.1:7878)")
print("🌌 AdS/CFT holographic consciousness + reservoir dynamics")
print("")

do {
    let system = try UnifiedEigenHoloSystem()
    print("✅ Engines initialized")
    print("   • Holographic Consciousness Engine: 1000 nodes")
    print("   • Holographic Reservoir Engine: 64×64×16 tensor field")
    print("")
    print("🔄 Starting eigen-driven evolution loop...")
    print("Press Ctrl+C to stop")
    print("")
    fflush(stdout)

    system.start()
} catch {
    print("❌ Failed to start: \(error)")
    exit(1)
}
