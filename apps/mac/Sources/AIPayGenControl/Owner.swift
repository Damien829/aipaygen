import AppKit
import SwiftUI
import UserNotifications

// Owner pages: Money, Prices, Keys, Demand. They call the /admin routes in
// src/admin.ts with the admin token from the Keychain (see Admin.swift).
// Every call is made on demand or slowly: the site's database has a daily read quota.

// MARK: - Formatting

func usd(_ micro: Int?) -> String {
    let d = Double(micro ?? 0) / 1_000_000
    if d == 0 { return "$0" }
    return String(format: d < 0.1 ? "$%.3f" : "$%.2f", d)
}

func shortAddress(_ s: String?) -> String {
    guard let s, s.count > 14 else { return s ?? "—" }
    return "\(s.prefix(6))…\(s.suffix(4))"
}

func dateFromMillis(_ ms: Int?) -> Date? { ms.map { Date(timeIntervalSince1970: Double($0) / 1000) } }

// MARK: - API shapes

struct Sale: Decodable, Identifiable, Sendable {
    let id: Int
    let tool: String
    let payment: String
    let payer: String?
    let price_micro: Int
    let tx: String?
    let created_at: Int
}

struct Money: Decodable {
    struct Period: Decodable { let revenue_micro: Int; let calls: Int }
    struct Month: Decodable { let revenue_micro: Int; let calls: Int; let x402_micro: Int; let payers: Int }
    struct ToolRow: Decodable, Identifiable { let tool: String; let calls: Int; let revenue_micro: Int?; var id: String { tool } }
    let pay_to: String
    let network: String
    let today: Period
    let week: Period
    let month: Month
    let by_tool: [ToolRow]
    let recent: [Sale]
}

struct SalesPage: Decodable { let sales: [Sale]; let last_id: Int }

struct PriceRow: Decodable, Identifiable {
    let name: String
    let title: String
    let default_micro: Int
    let price_micro: Int
    let overridden: Bool
    var id: String { name }
}

struct PricesPage: Decodable { let tools: [PriceRow] }

struct KeyInfo: Decodable, Identifiable {
    struct Entry: Decodable, Hashable { let delta_micro: Int; let reason: String; let created_at: Int }
    let id: String
    let key_prefix: String
    let label: String?
    let balance_micro: Int
    let created_at: Int
    let disabled: Bool
    let calls_30d: Int
    let spent_30d_micro: Int
    let last_used: Int?
    let ledger: [Entry]
}

struct KeysPage: Decodable { let keys: [KeyInfo] }

struct Demand: Decodable {
    struct Q: Decodable, Hashable { let query: String; let n: Int; let avg_results: Double? }
    struct Channel: Decodable, Hashable { let channel: String?; let n: Int }
    let window_days: Int
    let top_searches: [Q]
    let unmet_demand: [Q]
    let by_channel: [Channel]
}

// MARK: - Notifications

enum Notifier {
    static func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    static func send(_ title: String, _ body: String) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        c.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}

// MARK: - Owner data

@MainActor
final class Owner: ObservableObject {
    @Published var money: Money?
    @Published var walletUSDC: Double?
    @Published var prices: [PriceRow] = []
    @Published var keys: [KeyInfo] = []
    @Published var demand: Demand?
    @Published var lastSale: Sale?

    @Published var notifySales = UserDefaults.standard.object(forKey: "notifySales") as? Bool ?? true {
        didSet { UserDefaults.standard.set(notifySales, forKey: "notifySales") }
    }
    @Published var notifyGas = UserDefaults.standard.object(forKey: "notifyGas") as? Bool ?? true {
        didSet { UserDefaults.standard.set(notifyGas, forKey: "notifyGas") }
    }
    private var lastSaleId: Int {
        get { UserDefaults.standard.integer(forKey: "lastSaleId") }
        set { UserDefaults.standard.set(newValue, forKey: "lastSaleId") }
    }

    let admin: Admin
    private var polling = false

    init(admin: Admin) { self.admin = admin }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        try JSONDecoder().decode(T.self, from: try await admin.call("GET", path))
    }

    func loadMoney() async {
        _ = await admin.run("Loading earnings") {
            let m: Money = try await get("/admin/money")
            money = m
            walletUSDC = await Owner.usdcBalance(m.pay_to)
            return nil
        }
    }

    /// Same as loadMoney but without the spinner or messages, for background refreshes.
    func refreshMoneyQuietly() async {
        guard admin.hasToken, let m: Money = try? await get("/admin/money") else { return }
        money = m
        if let w = await Owner.usdcBalance(m.pay_to) { walletUSDC = w }
    }

    func loadPrices() async {
        _ = await admin.run("Loading prices") {
            prices = (try await get("/admin/prices") as PricesPage).tools
            return nil
        }
    }

    func setPrice(_ tool: String, dollars: Double?) async {
        let micro: Any = dollars.map { Int(($0 * 1_000_000).rounded()) } ?? NSNull()
        if await admin.run("Saving price", {
            _ = try await admin.call("POST", "/admin/prices", ["tool": tool, "price_micro": micro])
            return dollars == nil ? "\(tool) is back to its default price." : "\(tool) now costs \(usd(micro as? Int)). Agents see it within a minute."
        }) { await loadPrices() }
    }

    func findKeys(_ q: String) async {
        _ = await admin.run("Searching keys") {
            let enc = q.trimmingCharacters(in: .whitespaces).addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            keys = (try await get("/admin/keys?q=\(enc)") as KeysPage).keys
            return keys.isEmpty ? "No keys found." : nil
        }
    }

    func grant(_ id: String, dollars: Double, refresh q: String) async {
        let micro = Int((dollars * 1_000_000).rounded())
        if await admin.run("Adding credits", {
            _ = try await admin.call("POST", "/admin/keys/credit", ["id": id, "amount_micro": micro])
            return "Added \(usd(micro)) in credits."
        }) { await findKeys(q) }
    }

    func setDisabled(_ id: String, _ disabled: Bool, refresh q: String) async {
        if await admin.run(disabled ? "Disabling key" : "Enabling key", {
            _ = try await admin.call("POST", "/admin/keys/disable", ["id": id, "disabled": disabled])
            return disabled ? "Key disabled. Calls with it are refused." : "Key enabled again."
        }) { await findKeys(q) }
    }

    func loadDemand() async {
        _ = await admin.run("Loading demand") {
            demand = try await get("/admin/demand?days=30")
            return nil
        }
    }

    /// Checks for new sales once a minute while the app is open (reads only new rows).
    func startSalePolling() async {
        guard !polling else { return }
        polling = true
        Notifier.requestPermission()
        var ticks = 0
        while !Task.isCancelled {
            var newSales = false
            defer { ticks += 1 }
            if admin.hasToken, let page: SalesPage = try? await get("/admin/sales?after=\(lastSaleId)") {
                if lastSaleId == 0 {
                    lastSaleId = page.last_id // first run: start from now, don't replay history
                } else if !page.sales.isEmpty {
                    lastSaleId = max(lastSaleId, page.sales.map(\.id).max() ?? lastSaleId)
                    lastSale = page.sales.last
                    newSales = true
                    if notifySales {
                        let total = page.sales.reduce(0) { $0 + $1.price_micro }
                        if page.sales.count == 1, let s = page.sales.first {
                            Notifier.send("Sale: \(usd(s.price_micro))", "\(s.tool) · paid with \(s.payment == "x402" ? "USDC" : "credits")")
                        } else {
                            Notifier.send("\(page.sales.count) sales: \(usd(total))", page.sales.map(\.tool).joined(separator: ", "))
                        }
                    }
                }
            }
            // Earnings and the wallet follow new sales right away, and refresh every 5 minutes anyway.
            if newSales || ticks % 5 == 0 { await refreshMoneyQuietly() }
            try? await Task.sleep(nanoseconds: 60_000_000_000)
        }
    }

    /// USDC balance on Base mainnet from free public RPCs, tried in order (no database reads).
    nonisolated static func usdcBalance(_ address: String) async -> Double? {
        for rpc in ["https://base-rpc.publicnode.com", "https://1rpc.io/base", "https://mainnet.base.org"] {
            if let v = await usdcBalance(address, rpc: rpc) { return v }
        }
        return nil
    }

    nonisolated private static func usdcBalance(_ address: String, rpc: String) async -> Double? {
        let hex = address.lowercased().replacingOccurrences(of: "0x", with: "")
        guard hex.count == 40, let url = URL(string: rpc) else { return nil }
        var req = URLRequest(url: url)
        req.timeoutInterval = 10
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let data = "0x70a08231" + String(repeating: "0", count: 24) + hex
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [["to": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "data": data], "latest"],
        ] as [String: Any])
        guard let (out, _) = try? await Store.session.data(for: req),
              let obj = try? JSONSerialization.jsonObject(with: out) as? [String: Any],
              let res = obj["result"] as? String else { return nil }
        var v = 0.0
        for ch in res.dropFirst(2) { v = v * 16 + Double(ch.hexDigitValue ?? 0) }
        return v / 1_000_000
    }
}

// MARK: - Shared pieces

private func caption(_ s: String) -> some View {
    Text(s).font(.system(size: 10, weight: .semibold)).tracking(1.4).foregroundStyle(.white.opacity(0.5))
}

private struct Panel<Content: View>: View {
    let content: Content
    init(@ViewBuilder _ content: () -> Content) { self.content = content() }
    var body: some View {
        content
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color(red: 0.04, green: 0.06, blue: 0.11).opacity(0.92)))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Color.white.opacity(0.08)))
    }
}

private func openURL(_ s: String) { if let u = URL(string: s) { NSWorkspace.shared.open(u) } }

private func copy(_ s: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(s, forType: .string)
}

private struct StatusLine: View {
    @EnvironmentObject var admin: Admin
    var body: some View {
        HStack(spacing: 6) {
            if let busy = admin.busy {
                ProgressView().controlSize(.small)
                Text(busy + "…").font(.system(size: 11)).foregroundStyle(.secondary)
            } else if let m = admin.message {
                Label(m, systemImage: admin.failed ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                    .font(.system(size: 11)).foregroundStyle(admin.failed ? Color.orange : Color.green).lineLimit(2)
            }
            Spacer(minLength: 0)
        }
        .frame(height: 18)
    }
}

/// Shown on owner pages until the admin token is saved.
struct LockedPage: View {
    var body: some View {
        Panel {
            VStack(alignment: .leading, spacing: 8) {
                Label("Owner page", systemImage: "lock.fill").font(.system(size: 14, weight: .semibold))
                Text("Click Controls (top right) and paste your admin token to unlock earnings, prices, API keys and demand.")
                    .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: 460)
    }
}

// MARK: - Money

struct MoneyPage: View {
    @EnvironmentObject var owner: Owner
    @EnvironmentObject var admin: Admin
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                tile("TODAY", owner.money?.today.revenue_micro, "\(owner.money?.today.calls ?? 0) paid calls")
                tile("LAST 7 DAYS", owner.money?.week.revenue_micro, "\(owner.money?.week.calls ?? 0) paid calls")
                tile("LAST 30 DAYS", owner.money?.month.revenue_micro, "\(owner.money?.month.calls ?? 0) calls · \(owner.money?.month.payers ?? 0) customers")
                wallet
            }
            HStack(alignment: .top, spacing: 12) {
                Panel {
                    VStack(alignment: .leading, spacing: 8) {
                        caption("BEST SELLERS · 30 DAYS")
                        let rows = owner.money?.by_tool ?? []
                        let top = max(1, rows.map { $0.revenue_micro ?? 0 }.max() ?? 1)
                        if rows.isEmpty { Text("No sales yet.").font(.system(size: 12)).foregroundStyle(.secondary) }
                        ForEach(rows) { r in
                            VStack(alignment: .leading, spacing: 3) {
                                HStack {
                                    Text(r.tool).font(.system(size: 12, weight: .medium))
                                    Spacer()
                                    Text("\(r.calls) × · \(usd(r.revenue_micro))").font(.system(size: 11).monospacedDigit()).foregroundStyle(.secondary)
                                }
                                GeometryReader { g in
                                    Capsule().fill(Color.green.opacity(0.8)).frame(width: max(3, g.size.width * Double(r.revenue_micro ?? 0) / Double(top)))
                                }
                                .frame(height: 3)
                            }
                        }
                    }
                }
                .frame(width: 330)
                Panel {
                    VStack(alignment: .leading, spacing: 6) {
                        caption("RECENT SALES")
                        let sales = owner.money?.recent ?? []
                        if sales.isEmpty { Text("No sales yet. They appear here, and as Mac notifications.").font(.system(size: 12)).foregroundStyle(.secondary) }
                        ScrollView {
                            VStack(spacing: 2) {
                                ForEach(sales) { s in SaleRow(sale: s) }
                            }
                        }
                        .frame(maxHeight: 330)
                    }
                }
            }
            HStack {
                StatusLine()
                Text("Credits sales were prepaid by card; USDC sales land in your wallet instantly.")
                    .font(.system(size: 10)).foregroundStyle(.white.opacity(0.4))
                Button("Refresh") { Task { await owner.loadMoney() } }.disabled(admin.busy != nil)
            }
        }
        .task { if owner.money == nil { await owner.loadMoney() } }
    }

    private func tile(_ title: String, _ micro: Int?, _ sub: String) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 3) {
                caption(title)
                Text(usd(micro)).font(.system(size: 30, weight: .bold, design: .rounded).monospacedDigit())
                Text(sub).font(.system(size: 11)).foregroundStyle(.white.opacity(0.55)).lineLimit(1)
            }
        }
    }

    private var wallet: some View {
        Panel {
            VStack(alignment: .leading, spacing: 3) {
                caption("YOUR WALLET · USDC ON BASE")
                Text(owner.walletUSDC.map { String(format: $0 < 1 ? "$%.3f" : "$%.2f", $0) } ?? "—")
                    .font(.system(size: 30, weight: .bold, design: .rounded).monospacedDigit()).foregroundStyle(Color.green)
                HStack(spacing: 8) {
                    Text(shortAddress(owner.money?.pay_to)).font(.system(size: 11, design: .monospaced)).foregroundStyle(.white.opacity(0.55))
                    if let a = owner.money?.pay_to {
                        Button("Copy") { copy(a) }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(Color.cyan)
                        Button("BaseScan") { openURL("https://basescan.org/token/0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913?a=\(a)") }
                            .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(Color.cyan)
                    }
                }
            }
        }
    }
}

private struct SaleRow: View {
    let sale: Sale
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: sale.payment == "x402" ? "dollarsign.circle.fill" : "creditcard.fill")
                .foregroundStyle(sale.payment == "x402" ? Color.green : Color.cyan).frame(width: 16)
            Text(sale.tool).font(.system(size: 12)).lineLimit(1)
            Text(sale.payment == "x402" ? "USDC" : "credits").font(.system(size: 10)).foregroundStyle(.secondary)
            Spacer(minLength: 4)
            if let tx = sale.tx {
                Button("tx") { openURL("https://basescan.org/tx/\(tx)") }.buttonStyle(.plain).font(.system(size: 10)).foregroundStyle(Color.cyan)
            }
            Text(usd(sale.price_micro)).font(.system(size: 12, weight: .semibold).monospacedDigit())
            if let d = dateFromMillis(sale.created_at) {
                Text(d.formatted(.relative(presentation: .named))).font(.system(size: 10)).foregroundStyle(.white.opacity(0.4)).frame(width: 90, alignment: .trailing)
            }
        }
        .padding(.vertical, 3)
    }
}

// MARK: - Prices

struct PricesPageView: View {
    @EnvironmentObject var owner: Owner
    @EnvironmentObject var admin: Admin
    @State private var drafts: [String: String] = [:]

    var body: some View {
        VStack(spacing: 12) {
            Panel {
                VStack(alignment: .leading, spacing: 10) {
                    caption("PRICE PER CALL")
                    Text("Changes reach agents within about a minute. Allowed: $0.001 to $10. Free tools aren't listed and stay free.")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    ForEach(owner.prices) { p in row(p) }
                    if owner.prices.isEmpty { Text("Loading…").font(.system(size: 12)).foregroundStyle(.secondary) }
                }
            }
            .frame(maxWidth: 680)
            StatusLine().frame(maxWidth: 680)
        }
        .task { if owner.prices.isEmpty { await owner.loadPrices() } }
    }

    private func row(_ p: PriceRow) -> some View {
        let draft = Binding(get: { drafts[p.name] ?? String(format: "%.3f", Double(p.price_micro) / 1e6) }, set: { drafts[p.name] = $0 })
        let parsed = Double(draft.wrappedValue.replacingOccurrences(of: "$", with: ""))
        let changed = parsed.map { Int(($0 * 1e6).rounded()) != p.price_micro } ?? false
        return HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(p.name).font(.system(size: 12, weight: .medium, design: .monospaced))
                Text(p.overridden ? "default \(usd(p.default_micro))" : "default price").font(.system(size: 10)).foregroundStyle(p.overridden ? Color.orange : .secondary)
            }
            Spacer()
            Text("$").foregroundStyle(.secondary)
            TextField("", text: draft).textFieldStyle(.roundedBorder).frame(width: 80).font(.system(size: 12).monospacedDigit())
            Button("Save") {
                guard let v = parsed else { return }
                drafts[p.name] = nil
                Task { await owner.setPrice(p.name, dollars: v) }
            }
            .disabled(!changed || admin.busy != nil)
            Button("Reset") {
                drafts[p.name] = nil
                Task { await owner.setPrice(p.name, dollars: nil) }
            }
            .disabled(!p.overridden || admin.busy != nil)
        }
        .padding(.vertical, 2)
    }
}

// MARK: - API keys

struct KeysPageView: View {
    @EnvironmentObject var owner: Owner
    @EnvironmentObject var admin: Admin
    @State private var query = ""
    @State private var searched = ""
    @State private var grantFor: KeyInfo?
    @State private var grantAmount = "1.00"
    @State private var confirmDisable: KeyInfo?

    var body: some View {
        VStack(spacing: 12) {
            Panel {
                VStack(alignment: .leading, spacing: 10) {
                    caption("API KEYS")
                    HStack {
                        TextField("Paste a full key (apg_…), its start, id or label. Empty = newest keys", text: $query)
                            .textFieldStyle(.roundedBorder).onSubmit(search)
                        Button("Find", action: search).keyboardShortcut(.defaultAction).disabled(admin.busy != nil)
                    }
                    ScrollView {
                        VStack(spacing: 8) { ForEach(owner.keys) { keyCard($0) } }
                    }
                    .frame(maxHeight: 440)
                }
            }
            .frame(maxWidth: 760)
            StatusLine().frame(maxWidth: 760)
        }
        .task { if owner.keys.isEmpty { search() } }
        .sheet(item: $grantFor) { k in grantSheet(k) }
        .confirmationDialog("Disable this key?", isPresented: Binding(get: { confirmDisable != nil }, set: { if !$0 { confirmDisable = nil } }), presenting: confirmDisable) { k in
            Button("Disable key", role: .destructive) { Task { await owner.setDisabled(k.id, true, refresh: searched) } }
        } message: { k in
            Text("\(k.key_prefix)… stops working right away. Its \(usd(k.balance_micro)) balance is kept, and you can enable it again.")
        }
    }

    private func search() {
        searched = query
        Task { await owner.findKeys(query) }
    }

    private func keyCard(_ k: KeyInfo) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text("\(k.key_prefix)…").font(.system(size: 13, weight: .semibold, design: .monospaced))
                if let l = k.label, !l.isEmpty { Text(l).font(.system(size: 11)).foregroundStyle(.secondary) }
                if k.disabled {
                    Text("DISABLED").font(.system(size: 9, weight: .bold)).padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(Color.red.opacity(0.25))).foregroundStyle(Color.red)
                }
                Spacer()
                Text(usd(k.balance_micro)).font(.system(size: 15, weight: .bold, design: .rounded).monospacedDigit())
                Text("balance").font(.system(size: 10)).foregroundStyle(.secondary)
            }
            HStack(spacing: 14) {
                stat("calls · 30d", "\(k.calls_30d)")
                stat("spent · 30d", usd(k.spent_30d_micro))
                stat("last used", dateFromMillis(k.last_used).map { $0.formatted(.relative(presentation: .named)) } ?? "never")
                stat("created", dateFromMillis(k.created_at).map { $0.formatted(date: .abbreviated, time: .omitted) } ?? "—")
                Spacer()
                Button("Add credits…") { grantAmount = "1.00"; grantFor = k }.disabled(admin.busy != nil)
                if k.disabled {
                    Button("Enable") { Task { await owner.setDisabled(k.id, false, refresh: searched) } }.disabled(admin.busy != nil)
                } else {
                    Button("Disable…") { confirmDisable = k }.disabled(admin.busy != nil)
                }
            }
            if !k.ledger.isEmpty {
                HStack(spacing: 10) {
                    ForEach(k.ledger.prefix(4), id: \.self) { e in
                        Text("\(e.delta_micro >= 0 ? "+" : "−")\(usd(abs(e.delta_micro))) \(e.reason.replacingOccurrences(of: "_", with: " "))")
                            .font(.system(size: 10)).foregroundStyle(e.delta_micro >= 0 ? Color.green.opacity(0.8) : .white.opacity(0.45))
                    }
                }
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.04)))
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value).font(.system(size: 12, weight: .medium).monospacedDigit())
            Text(label).font(.system(size: 9)).foregroundStyle(.secondary)
        }
    }

    private func grantSheet(_ k: KeyInfo) -> some View {
        let amount = Double(grantAmount.replacingOccurrences(of: "$", with: ""))
        let valid = amount.map { $0 > 0 && $0 <= 100 } ?? false
        return VStack(alignment: .leading, spacing: 12) {
            Text("Add free credits to \(k.key_prefix)…").font(.system(size: 14, weight: .semibold))
            Text("Credits are a gift: no payment is taken. Current balance \(usd(k.balance_micro)).").font(.system(size: 11)).foregroundStyle(.secondary)
            HStack {
                ForEach(["0.05", "1.00", "5.00"], id: \.self) { v in Button("$\(v)") { grantAmount = v } }
                Text("$").foregroundStyle(.secondary)
                TextField("", text: $grantAmount).textFieldStyle(.roundedBorder).frame(width: 80)
            }
            HStack {
                Spacer()
                Button("Cancel") { grantFor = nil }.keyboardShortcut(.cancelAction)
                Button("Add credits") {
                    guard let a = amount else { return }
                    grantFor = nil
                    Task { await owner.grant(k.id, dollars: a, refresh: searched) }
                }
                .keyboardShortcut(.defaultAction).disabled(!valid)
            }
        }
        .padding(20)
        .frame(width: 380)
    }
}

// MARK: - Demand and alerts

struct DemandPage: View {
    @EnvironmentObject var owner: Owner
    @EnvironmentObject var admin: Admin

    var body: some View {
        VStack(spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                Panel {
                    VStack(alignment: .leading, spacing: 6) {
                        caption("SEARCHED BUT NOT FOUND · 30 DAYS")
                        Text("Ideas for new tools: agents wanted these and found nothing.").font(.system(size: 11)).foregroundStyle(.secondary)
                        list(owner.demand?.unmet_demand ?? [], color: .orange)
                    }
                }
                Panel {
                    VStack(alignment: .leading, spacing: 6) {
                        caption("TOP SEARCHES · 30 DAYS")
                        Text("What agents look for most.").font(.system(size: 11)).foregroundStyle(.secondary)
                        list(owner.demand?.top_searches ?? [], color: .cyan)
                    }
                }
                Panel {
                    VStack(alignment: .leading, spacing: 10) {
                        caption("ALERTS")
                        Toggle("Notify me about each sale", isOn: $owner.notifySales)
                        Toggle("Notify me when the fee wallet runs low", isOn: $owner.notifyGas)
                        Text("Mac notifications, checked once a minute while this app is open. If none appear, allow them in System Settings → Notifications → AIPayGen Control.")
                            .font(.system(size: 10)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        Button("Send a test notification") { Notifier.send("AIPayGen", "Notifications are working.") }
                        if let s = owner.lastSale {
                            Text("Last sale: \(s.tool) \(usd(s.price_micro))").font(.system(size: 11)).foregroundStyle(Color.green)
                        }
                        if let ch = owner.demand?.by_channel, !ch.isEmpty {
                            caption("SEARCHES BY SOURCE").padding(.top, 6)
                            ForEach(ch, id: \.self) { c in
                                HStack { Text(c.channel ?? "other").font(.system(size: 11)); Spacer(); Text("\(c.n)").font(.system(size: 11).monospacedDigit()) }
                            }
                        }
                    }
                    .font(.system(size: 12))
                }
                .frame(width: 290)
            }
            HStack {
                StatusLine()
                Button("Refresh") { Task { await owner.loadDemand() } }.disabled(admin.busy != nil)
            }
        }
        .task { if owner.demand == nil { await owner.loadDemand() } }
    }

    private func list(_ qs: [Demand.Q], color: Color) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 4) {
                if qs.isEmpty { Text("Nothing yet.").font(.system(size: 12)).foregroundStyle(.secondary) }
                ForEach(qs.prefix(30), id: \.self) { q in
                    HStack {
                        Text(q.query).font(.system(size: 12)).foregroundStyle(color).lineLimit(1).textSelection(.enabled)
                        Spacer()
                        Text("\(q.n)").font(.system(size: 11).monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .frame(maxHeight: 420)
    }
}
