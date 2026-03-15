// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "HolographicEngine",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "holographic-engine",
            targets: ["HolographicEngine"]
        )
    ],
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.99.0"),
        .package(url: "https://github.com/apple/swift-nio.git", from: "2.65.0")
    ],
    targets: [
        .executableTarget(
            name: "HolographicEngine",
            dependencies: [
                .product(name: "Vapor", package: "vapor"),
                .product(name: "NIOCore", package: "swift-nio"),
                .product(name: "NIOPosix", package: "swift-nio"),
                .product(name: "NIOWebSocket", package: "swift-nio")
            ],
            resources: [
                .process("Holographic.metal"),
                .process("private_consciousness.metal"),
                .process("AffineMapper.metal")
            ]
        )
    ]
)
