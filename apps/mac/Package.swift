// swift-tools-version:5.8
import PackageDescription

let package = Package(
    name: "AIPayGenControl",
    platforms: [.macOS(.v13)],
    targets: [.executableTarget(name: "AIPayGenControl", path: "Sources/AIPayGenControl")]
)
