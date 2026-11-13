import AppKit
import SceneKit
import SwiftUI

/// The 3D view: AIPayGen is the core; each catalog kind is an orbit of nodes.
/// Orbits and the core "breathing" are decoration. Ripples, pulses and payment
/// bolts fire only on real events (a refresh, new listings, a settled payment).
final class NetworkScene {
    let scene = SCNScene()
    let cameraNode = SCNNode()
    private let core = SCNNode()
    private var spinners: [String: SCNNode] = [:]
    private var ringIDs: [String: [String]] = [:]
    private var nodes: [String: SCNNode] = [:]
    private var geometry: [String: SCNGeometry] = [:]
    private var highlighted: SCNNode?
    private let accent = NSColor(hex: 0x35D8FF)

    init() {
        scene.background.contents = NSColor(srgbRed: 0.012, green: 0.02, blue: 0.05, alpha: 1)

        let camera = SCNCamera()
        camera.fieldOfView = 52
        camera.zFar = 300
        camera.wantsHDR = true
        camera.bloomIntensity = 1.4
        camera.bloomThreshold = 0.35
        camera.bloomBlurRadius = 14
        camera.vignettingIntensity = 0.7
        camera.vignettingPower = 1.2
        cameraNode.camera = camera
        cameraNode.position = SCNVector3(0, 7.5, 19)
        cameraNode.look(at: SCNVector3(0, 0, 0))
        scene.rootNode.addChildNode(cameraNode)

        let ambient = SCNLight()
        ambient.type = .ambient
        ambient.intensity = 250
        let ambientNode = SCNNode()
        ambientNode.light = ambient
        scene.rootNode.addChildNode(ambientNode)

        buildCore()
        buildStars()
        for (i, k) in kinds.enumerated() { buildRing(k, index: i) }
    }

    private func glow(_ color: NSColor, alpha: CGFloat = 1) -> SCNMaterial {
        let m = SCNMaterial()
        m.lightingModel = .constant
        m.diffuse.contents = NSColor.black
        m.emission.contents = color.withAlphaComponent(alpha)
        m.transparency = alpha
        m.isDoubleSided = true
        return m
    }

    private func buildCore() {
        let sphere = SCNSphere(radius: 1.05)
        sphere.segmentCount = 64
        sphere.materials = [glow(accent)]
        core.geometry = sphere
        core.runAction(.repeatForever(.sequence([.scale(to: 1.07, duration: 2.2), .scale(to: 0.96, duration: 2.2)])))
        scene.rootNode.addChildNode(core)

        for (radius, segments, alpha, duration) in [(1.55, 14, 0.5, 26.0), (2.05, 9, 0.22, -40.0)] {
            let cage = SCNSphere(radius: CGFloat(radius))
            cage.isGeodesic = true
            cage.segmentCount = segments
            let m = glow(accent, alpha: CGFloat(alpha))
            m.fillMode = .lines
            cage.materials = [m]
            let n = SCNNode(geometry: cage)
            n.runAction(.repeatForever(.rotateBy(x: 0.6, y: CGFloat(2 * Double.pi), z: 0.3, duration: abs(duration))))
            if duration < 0 { n.eulerAngles.x = 1 }
            scene.rootNode.addChildNode(n)
        }

        let light = SCNLight()
        light.type = .omni
        light.color = accent
        light.intensity = 900
        let ln = SCNNode()
        ln.light = light
        scene.rootNode.addChildNode(ln)
    }

    private func buildStars() {
        var points: [SCNVector3] = []
        for _ in 0..<1400 {
            let r = Double.random(in: 45...110)
            let t = Double.random(in: 0..<(2 * Double.pi))
            let p = acos(Double.random(in: -1...1))
            points.append(SCNVector3(r * sin(p) * cos(t), r * cos(p), r * sin(p) * sin(t)))
        }
        let element = SCNGeometryElement(indices: (0..<UInt32(points.count)).map { $0 }, primitiveType: .point)
        element.pointSize = 2
        element.minimumPointScreenSpaceRadius = 0.6
        element.maximumPointScreenSpaceRadius = 2.2
        let g = SCNGeometry(sources: [SCNGeometrySource(vertices: points)], elements: [element])
        g.materials = [glow(NSColor(hex: 0xBFD8FF), alpha: 0.8)]
        let stars = SCNNode(geometry: g)
        stars.runAction(.repeatForever(.rotateBy(x: 0, y: CGFloat(2 * Double.pi), z: 0, duration: 600)))
        scene.rootNode.addChildNode(stars)
    }

    private func radius(_ index: Int) -> Double { 3.4 + Double(index) * 1.3 }

    private func buildRing(_ k: Kind, index: Int) {
        let holder = SCNNode()
        holder.eulerAngles = SCNVector3((index % 2 == 0 ? 1.0 : -1.0) * (0.10 + Double(index) * 0.045), 0, (index % 3 == 0 ? -1.0 : 1.0) * Double(index) * 0.035)
        let torus = SCNTorus(ringRadius: CGFloat(radius(index)), pipeRadius: 0.012)
        torus.ringSegmentCount = 160
        torus.materials = [glow(k.ns, alpha: 0.3)]
        holder.addChildNode(SCNNode(geometry: torus))
        let spinner = SCNNode()
        let direction: Double = index % 2 == 0 ? 1 : -1
        spinner.runAction(.repeatForever(.rotateBy(x: 0, y: CGFloat(direction * 2 * Double.pi), z: 0, duration: 70 + Double(index) * 22)))
        holder.addChildNode(spinner)
        scene.rootNode.addChildNode(holder)
        spinners[k.id] = spinner

        for (suffix, r) in [("", 0.12), ("+", 0.17)] {
            let s = SCNSphere(radius: CGFloat(r))
            s.segmentCount = 18
            s.materials = [glow(k.ns)]
            geometry[k.id + suffix] = s
        }
    }

    /// Rebuild only the orbits whose listings changed.
    func update(items: [CatalogItem]) {
        for (index, k) in kinds.enumerated() {
            let mine = items.filter { $0.kind == k.id }
            let ids = mine.map(\.id)
            guard ids != ringIDs[k.id], let spinner = spinners[k.id] else { continue }
            let firstBuild = ringIDs[k.id] == nil
            ringIDs[k.id] = ids
            for old in spinner.childNodes {
                if let name = old.name { nodes[name] = nil }
                old.runAction(.sequence([.scale(to: 0.01, duration: 0.3), .removeFromParentNode()]))
            }
            let r = radius(index)
            for (i, item) in mine.enumerated() {
                let a = Double(i) / Double(max(mine.count, 1)) * 2 * Double.pi
                // x402 (payable) listings are drawn larger.
                let node = SCNNode(geometry: geometry[k.id + (item.x402 == true ? "+" : "")])
                node.name = item.id
                node.position = SCNVector3(r * cos(a), 0, r * sin(a))
                node.scale = SCNVector3(0.01, 0.01, 0.01)
                let grow = SCNAction.scale(to: 1, duration: 0.5)
                grow.timingMode = .easeOut
                node.runAction(.sequence([.wait(duration: (firstBuild ? Double(index) * 0.25 : 0.3) + Double(i) * 0.03), grow]))
                spinner.addChildNode(node)
                nodes[item.id] = node
            }
        }
    }

    /// A ring expanding from the core: one per data refresh.
    func ripple(color: NSColor? = nil) {
        let torus = SCNTorus(ringRadius: 1.3, pipeRadius: 0.018)
        torus.ringSegmentCount = 120
        torus.materials = [glow(color ?? accent, alpha: 0.9)]
        let n = SCNNode(geometry: torus)
        scene.rootNode.addChildNode(n)
        let grow = SCNAction.scale(to: 9, duration: 2.6)
        grow.timingMode = .easeOut
        n.runAction(.sequence([.group([grow, .fadeOut(duration: 2.6)]), .removeFromParentNode()]))
    }

    /// Flash one orbit (new listings of that kind, or the pointer is over its card).
    func pulse(_ kindID: String) {
        guard let spinner = spinners[kindID] else { return }
        for (i, n) in spinner.childNodes.enumerated() where n !== highlighted {
            n.runAction(.sequence([.wait(duration: Double(i) * 0.012), .scale(to: 1.9, duration: 0.18), .scale(to: 1, duration: 0.35)]))
        }
    }

    /// A bolt from a payable node into the core: one per settled payment.
    func payment(after delay: Double = 0) {
        let payable = nodes.values.filter { ($0.geometry as? SCNSphere)?.radius ?? 0 > 0.15 }
        guard let from = (payable.isEmpty ? Array(nodes.values) : payable).randomElement() else { return }
        let green = NSColor(hex: 0x7CFFB2)
        let s = SCNSphere(radius: 0.16)
        s.materials = [glow(green)]
        let bolt = SCNNode(geometry: s)
        bolt.opacity = 0
        scene.rootNode.addChildNode(bolt)
        let fly = SCNAction.move(to: SCNVector3(0, 0, 0), duration: 1.1)
        fly.timingMode = .easeIn
        bolt.runAction(.sequence([
            .wait(duration: delay),
            .run { n in n.position = from.presentation.worldPosition; n.opacity = 1 },
            fly,
            .run { [weak self] _ in
                self?.ripple(color: green)
                self?.core.runAction(.sequence([.scale(to: 1.3, duration: 0.12), .scale(to: 1, duration: 0.4)]))
            },
            .removeFromParentNode(),
        ]))
    }

    func highlight(_ id: String?) {
        highlighted?.runAction(.scale(to: 1, duration: 0.25))
        highlighted = id.flatMap { nodes[$0] }
        highlighted?.runAction(.scale(to: 2.6, duration: 0.25))
    }
}

// MARK: - SwiftUI wrapper

struct NetworkView: NSViewRepresentable {
    let controller: NetworkScene
    let onPick: (String?) -> Void

    func makeNSView(context: Context) -> SCNView {
        let v = PickingView()
        v.scene = controller.scene
        v.pointOfView = controller.cameraNode
        v.allowsCameraControl = true
        v.defaultCameraController.interactionMode = .orbitTurntable
        v.defaultCameraController.maximumVerticalAngle = 80
        v.defaultCameraController.minimumVerticalAngle = -30
        v.antialiasingMode = .multisampling4X
        v.backgroundColor = .black
        v.rendersContinuously = true
        v.isPlaying = true
        v.onPick = onPick
        return v
    }

    func updateNSView(_ view: SCNView, context: Context) {}
}

/// A click that isn't a drag selects the node under the pointer.
final class PickingView: SCNView {
    var onPick: ((String?) -> Void)?
    private var down = NSPoint.zero

    override func mouseDown(with event: NSEvent) {
        down = convert(event.locationInWindow, from: nil)
        super.mouseDown(with: event)
    }

    override func mouseUp(with event: NSEvent) {
        super.mouseUp(with: event)
        let p = convert(event.locationInWindow, from: nil)
        guard hypot(p.x - down.x, p.y - down.y) < 4 else { return }
        let hits = hitTest(p, options: [.searchMode: NSNumber(value: SCNHitTestSearchMode.all.rawValue), .boundingBoxOnly: true])
        onPick?(hits.first { $0.node.name?.contains(":") == true }?.node.name)
    }
}
