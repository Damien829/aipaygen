// swift-tools-version:5.9
import PackageDescription

var products: [Product] = [.library(name: "EdgeCore", targets: ["EdgeCore"])]
var targets: [Target] = [
    .target(name: "EdgeCore"),
    .testTarget(name: "EdgeCoreTests", dependencies: ["EdgeCore"]),
]

// The SwiftUI app only builds on macOS; the analytics core builds anywhere.
#if os(macOS)
products.append(.executable(name: "StreakEdge", targets: ["StreakEdge"]))
targets.append(.executableTarget(name: "StreakEdge", dependencies: ["EdgeCore"]))
#endif

let package = Package(
    name: "StreakEdge",
    platforms: [.macOS(.v13)],
    products: products,
    targets: targets
)
