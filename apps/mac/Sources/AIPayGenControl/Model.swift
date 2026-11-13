import AppKit
import SwiftUI

// MARK: - Catalog kinds

struct Kind: Identifiable, Hashable {
    let id: String
    let label: String
    let hex: UInt32
    var ns: NSColor { NSColor(hex: hex) }
    var color: Color { Color(nsColor: ns) }
}

let kinds: [Kind] = [
    Kind(id: "mcp", label: "MCP servers", hex: 0x35D8FF),
    Kind(id: "api", label: "APIs", hex: 0x4DFFA6),
    Kind(id: "skill", label: "Skills", hex: 0xB07CFF),
    Kind(id: "agent", label: "Agents", hex: 0xFF9D4D),
    Kind(id: "service", label: "Services", hex: 0xFF5FA8),
    Kind(id: "listing", label: "Listings", hex: 0xFFD84D),
]

func kind(_ id: String) -> Kind { kinds.first { $0.id == id } ?? kinds[0] }

extension NSColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}

// MARK: - API shapes (public aipaygen.com endpoints)

struct CatalogItem: Decodable, Identifiable, Sendable, Equatable {
    let id: String
    let kind: String
    let name: String
    let description: String?
    let url: String?
    let x402: Bool?
}

struct SearchResponse: Decodable, Sendable {
    let total: Int
    let items: [CatalogItem]
}

/// GET /v1/catalog/summary: every count and the sample nodes in one edge-cached call.
struct Summary: Decodable, Sendable {
    let counts: [String: Int]
    let nodes: [CatalogItem]
}

struct Health: Decodable, Sendable {
    let ok: Bool
    let version: String?
    let tools: Int?
}

struct NetStats: Decodable, Sendable {
    let settlements: Int
    let merchants: Int
    let payers: Int
    let volume_usdc: String
    let merchants_waiting_7d: Int?
}

struct Facilitator: Decodable, Sendable {
    struct Stats: Decodable, Sendable {
        let mainnet: NetStats
        let testnet: NetStats
    }
    let enabled: Bool
    let paused: Bool?
    let networks: [String]
    let stats: Stats?
}

struct Wanted: Decodable, Sendable {
    struct Q: Decodable, Sendable, Hashable {
        let query: String
        let searches: Int?
    }
    let unmet: [Q]
    let popular: [Q]
}

struct Event: Identifiable {
    let id = UUID()
    let date = Date()
    let text: String
    let symbol: String
    let color: Color
}

// MARK: - Store

let mainnetWallet = "0xca2d033D527fA368a90997be4FD39a5f080231BB"
let testnetWallet = "0xdD8B60012177222d8891D6b518045d033bBF7dB7"
/// Below this the site pauses real settlements (MIN_GAS_WEI in src/facilitator.ts).
let minGasEth = 0.00002

@MainActor
final class Store: ObservableObject {
    @Published var counts: [String: Int] = [:]
    @Published var items: [CatalogItem] = []
    @Published var health: Health?
    @Published var fac: Facilitator?
    @Published var wanted: Wanted?
    @Published var mainnetGas: Double?
    @Published var testnetGas: Double?
    @Published var events: [Event] = []
    @Published var lastUpdated: Date?
    @Published var online = false
    @Published var loading = false
    @Published var selected: CatalogItem?
    @Published var results: [CatalogItem] = []
    @Published var query = "" { didSet { search() } }

    let network = NetworkScene()
    private var searchTask: Task<Void, Never>?
    private var lastSettlements: Int?
    private var started = false

    var total: Int { counts.values.reduce(0, +) }
    var ownerPaused: Bool { fac?.paused == true }
    var mainnetLive: Bool { !ownerPaused && (fac?.networks.contains("eip155:8453") ?? false) && (mainnetGas ?? 0) >= minGasEth }

    static let base = "https://aipaygen.com"
    static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 15
        c.httpAdditionalHeaders = ["User-Agent": "AIPayGenControl/1.0 (macOS)", "Accept": "application/json"]
        return URLSession(configuration: c)
    }()

    nonisolated func get<T: Decodable>(_ path: String) async throws -> T {
        guard let url = URL(string: Store.base + path) else { throw URLError(.badURL) }
        let (data, res) = try await Store.session.data(from: url)
        guard (res as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(T.self, from: data)
    }

    /// ETH balance from a public Base RPC.
    nonisolated func gas(_ rpc: String, _ address: String) async -> Double? {
        guard let url = URL(string: rpc) else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]] as [String: Any])
        guard let (data, _) = try? await Store.session.data(for: req),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let hex = obj["result"] as? String else { return nil }
        var wei = 0.0
        for ch in hex.dropFirst(2) { wei = wei * 16 + Double(ch.hexDigitValue ?? 0) }
        return wei / 1e18
    }

    func start() async {
        guard !started else { return }
        started = true
        while !Task.isCancelled {
            await refresh()
            // Slow on purpose. The site's database has a daily read quota (D1 free plan),
            // and the summary is edge-cached for 30 minutes anyway.
            try? await Task.sleep(nanoseconds: 120_000_000_000)
        }
    }

    func refresh() async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        async let h: Health? = try? get("/health")
        async let f: Facilitator? = try? get("/facilitator")
        async let w: Wanted? = try? get("/v1/catalog/wanted")
        async let mg = gas("https://mainnet.base.org", mainnetWallet)
        async let tg = gas("https://sepolia.base.org", testnetWallet)
        async let sm: Summary? = try? get("/v1/catalog/summary")
        let (health, fac, wanted, mainGas, testGas, summary) = await (h, f, w, mg, tg, sm)

        let wasOnline = online
        online = health?.ok == true
        if online && !wasOnline { log("Connected to aipaygen.com", "bolt.horizontal.circle.fill", .green) }
        if !online && (wasOnline || lastUpdated == nil) { log("Can't reach aipaygen.com", "wifi.exclamationmark", .red) }
        guard online else { lastUpdated = Date(); return }

        let old = counts
        var newCounts = counts
        var newItems: [CatalogItem] = []
        if let summary {
            newItems = summary.nodes
            for k in kinds {
                let n = summary.counts[k.id] ?? 0
                newCounts[k.id] = n
                if let before = old[k.id], n > before {
                    log("+\(n - before) new \(k.label.lowercased())", "plus.circle.fill", k.color)
                    network.pulse(k.id)
                }
            }
        } else {
            newItems = items // keep what we had; the next refresh will retry
        }
        let settlements = fac.flatMap { $0.stats }.map { $0.mainnet.settlements + $0.testnet.settlements }
        if let s = settlements, let before = lastSettlements, s > before {
            log("\(s - before) payment\(s - before == 1 ? "" : "s") settled", "checkmark.seal.fill", .green)
            for i in 0..<min(s - before, 5) { network.payment(after: Double(i) * 0.5) }
        }
        if let s = settlements { lastSettlements = s }
        if let g = mainGas, let before = mainnetGas, (g >= minGasEth) != (before >= minGasEth) {
            log(g >= minGasEth ? "Fee wallet funded: real payments on" : "Fee wallet low: real payments paused", "fuelpump.fill", g >= minGasEth ? .green : .orange)
        }

        withAnimation(.spring(response: 0.6, dampingFraction: 0.85)) {
            self.health = health
            if let fac { self.fac = fac }
            if let wanted { self.wanted = wanted }
            if let mainGas { self.mainnetGas = mainGas }
            if let testGas { self.testnetGas = testGas }
            self.counts = newCounts
        }
        items = newItems
        network.update(items: newItems)
        network.ripple()
        lastUpdated = Date()
    }

    func pick(_ id: String?) {
        let item = id.flatMap { id in items.first { $0.id == id } ?? results.first { $0.id == id } }
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) { selected = item }
        network.highlight(item?.id)
    }

    private func search() {
        searchTask?.cancel()
        let q = query.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2 else { results = []; return }
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled, let enc = q.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return }
            let r: SearchResponse? = try? await get("/v1/catalog/search?q=\(enc)&limit=8")
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.2)) { results = r?.items ?? [] }
        }
    }

    private func log(_ text: String, _ symbol: String, _ color: Color) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
            events.insert(Event(text: text, symbol: symbol, color: color), at: 0)
            if events.count > 30 { events.removeLast() }
        }
    }
}
