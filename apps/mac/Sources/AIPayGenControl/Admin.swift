import AppKit
import Security
import SwiftUI

// Owner controls. They call the /admin routes in src/admin.ts with the admin
// token, which lives only in the macOS Keychain.

enum Keychain {
    private static let base: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "com.aipaygen.control",
        kSecAttrAccount as String: "admin-token",
    ]

    static func read() -> String? {
        var q = base
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    @discardableResult
    static func save(_ token: String) -> Bool {
        SecItemDelete(base as CFDictionary)
        var q = base
        q[kSecValueData as String] = Data(token.utf8)
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }

    static func delete() { SecItemDelete(base as CFDictionary) }
}

struct Overview: Decodable {
    struct Hidden: Decodable, Identifiable {
        let id: String
        let kind: String
        let name: String
    }
    struct LastRun: Decodable { let at: String? }
    struct Reconcile: Decodable {
        struct Missing: Decodable { let source: String; let tx: String; let verdict: String }
        let confirmed: Int
        let problems: Int
        let missing: [Missing]
        let checked_at: String?
    }
    let facilitator_paused: Bool
    let last_run: LastRun?
    let hidden: [Hidden]
    let reconcile: Reconcile?
}

enum AdminError: Error {
    case noToken, unauthorized, failed(String)

    var text: String {
        switch self {
        case .noToken: return "Add your admin token first."
        case .unauthorized: return "The site rejected that admin token."
        case .failed(let why): return why
        }
    }
}

@MainActor
final class Admin: ObservableObject {
    @Published var hasToken = Keychain.read() != nil
    @Published var overview: Overview?
    @Published var busy: String?
    @Published var message: String?
    @Published var failed = false

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 90 // "run update now" does a full pass
        return URLSession(configuration: c)
    }()

    func call(_ method: String, _ path: String, _ body: [String: Any]? = nil) async throws -> Data {
        guard let token = Keychain.read() else { throw AdminError.noToken }
        var req = URLRequest(url: URL(string: Store.base + path)!)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("AIPayGenControl/1.0 (macOS)", forHTTPHeaderField: "User-Agent")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        let data: Data, res: URLResponse
        do { (data, res) = try await Admin.session.data(for: req) } catch { throw AdminError.failed("Couldn't reach aipaygen.com.") }
        let code = (res as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 { throw AdminError.unauthorized }
        guard code == 200 else {
            let why = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw AdminError.failed(why ?? "The site answered \(code).")
        }
        return data
    }

    /// Runs one action, tracking the spinner and the result line.
    func run(_ label: String, _ work: () async throws -> String?) async -> Bool {
        busy = label
        defer { busy = nil }
        do {
            let note = try await work()
            failed = false
            if let note { message = note }
            return true
        } catch {
            failed = true
            message = (error as? AdminError)?.text ?? "Something went wrong."
            return false
        }
    }

    func saveToken(_ raw: String) async {
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { return }
        guard Keychain.save(token) else { failed = true; message = "Couldn't save to the Keychain."; return }
        hasToken = true
        if !(await load(note: "Token saved. Controls are unlocked.")), failed, message == AdminError.unauthorized.text { removeToken(keepMessage: true) }
    }

    func removeToken(keepMessage: Bool = false) {
        Keychain.delete()
        hasToken = false
        overview = nil
        if !keepMessage { message = nil; failed = false }
    }

    @discardableResult
    func load(note: String? = nil) async -> Bool {
        await run("Loading") {
            overview = try JSONDecoder().decode(Overview.self, from: try await call("GET", "/admin/overview"))
            return note
        }
    }

    func setPaused(_ paused: Bool) async {
        if await run(paused ? "Pausing" : "Resuming", {
            _ = try await call("POST", "/admin/facilitator", ["paused": paused])
            return paused ? "Settlements are paused." : "Settlements are back on."
        }) { await load() }
    }

    func runUpdate() async {
        if await run("Updating the catalog", {
            let data = try await call("POST", "/admin/refresh")
            let r = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["result"] as? [String: Any] ?? [:]
            func n(_ job: String, _ field: String) -> Int { (r[job] as? [String: Any])?[field] as? Int ?? 0 }
            return "Checked \(n("health", "checked")) listings (\(n("health", "alive")) up). New: \(n("mcp_registry", "added")) MCP servers, \(n("x402_bazaar", "added")) payable APIs."
        }) { await load() }
    }

    func setHidden(_ id: String, _ hidden: Bool) async -> Bool {
        let ok = await run(hidden ? "Hiding" : "Unhiding") {
            _ = try await call("POST", "/admin/catalog/hide", ["id": id, "hidden": hidden])
            return hidden ? "Hidden from search and listings." : "Listing is visible again."
        }
        if ok { await load() }
        return ok
    }
}

// MARK: - Controls popover

struct ControlsView: View {
    @EnvironmentObject var store: Store
    @EnvironmentObject var admin: Admin
    @State private var token = ""
    @State private var confirmPause = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Controls").font(.system(size: 15, weight: .semibold))
                Spacer()
                if let busy = admin.busy {
                    ProgressView().controlSize(.small)
                    Text(busy + "…").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
            if admin.hasToken { unlocked } else { locked }
            if let m = admin.message {
                Label(m, systemImage: admin.failed ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                    .font(.system(size: 11)).foregroundStyle(admin.failed ? Color.orange : Color.green)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .frame(width: 360)
        .task { if admin.hasToken && admin.overview == nil { await admin.load() } }
    }

    private var locked: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Controls change the live site, so they need your admin token. It's stored only in this Mac's Keychain.")
                .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            SecureField("Admin token", text: $token).textFieldStyle(.roundedBorder).onSubmit(save)
            HStack {
                Button("Unlock", action: save).keyboardShortcut(.defaultAction).disabled(token.isEmpty || admin.busy != nil)
                Spacer()
            }
        }
    }

    private func save() {
        let t = token
        token = ""
        Task { await admin.saveToken(t) }
    }

    private var unlocked: some View {
        VStack(alignment: .leading, spacing: 14) {
            let paused = admin.overview?.facilitator_paused ?? false
            section("PAYMENTS") {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(paused ? "Settlements are paused" : "Settlements are on").font(.system(size: 12, weight: .medium))
                        Text(paused ? "Merchants get a \"retry later\" reply." : "The facilitator settles payments it's asked to.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if paused {
                        Button("Resume") { Task { await admin.setPaused(false); await store.refresh() } }
                    } else {
                        Button("Pause…") { confirmPause = true }
                    }
                }
                .disabled(admin.busy != nil || admin.overview == nil)
                .confirmationDialog("Pause all settlements?", isPresented: $confirmPause) {
                    Button("Pause settlements", role: .destructive) { Task { await admin.setPaused(true); await store.refresh() } }
                } message: {
                    Text("Test and real payments both stop settling until you resume. Verifying payments keeps working.")
                }
            }
            section("PAYMENT CHECKS") {
                let r = admin.overview?.reconcile
                VStack(alignment: .leading, spacing: 2) {
                    Text(r == nil ? "Not run yet" : "\(r!.confirmed) confirmed on-chain, \(r!.problems) problem\(r!.problems == 1 ? "" : "s")")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle((r?.problems ?? 0) > 0 ? Color.orange : Color.primary)
                    Text("Checks hourly that each recorded payment really landed on Base.")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    ForEach(Array((r?.missing ?? []).prefix(3).enumerated()), id: \.offset) { _, m in
                        Link("\(m.verdict.replacingOccurrences(of: "_", with: " ")): \(String(m.tx.prefix(10)))…",
                             destination: URL(string: "https://basescan.org/tx/\(m.tx)")!)
                            .font(.system(size: 11))
                    }
                }
            }
            section("CATALOG") {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Update the catalog now").font(.system(size: 12, weight: .medium))
                        Text(lastRun).font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Run") { Task { await admin.runUpdate(); await store.refresh() } }.disabled(admin.busy != nil)
                }
            }
            section("HIDDEN LISTINGS") {
                let hidden = admin.overview?.hidden ?? []
                if hidden.isEmpty {
                    Text("None. Click a node, then Hide, to remove a listing from search.")
                        .font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                ForEach(hidden.prefix(8)) { h in
                    HStack(spacing: 7) {
                        Circle().fill(kind(h.kind).color).frame(width: 6, height: 6)
                        Text(h.name).font(.system(size: 11)).lineLimit(1)
                        Spacer(minLength: 4)
                        Button("Unhide") { Task { if await admin.setHidden(h.id, false) { await store.refresh() } } }
                            .controlSize(.small).disabled(admin.busy != nil)
                    }
                }
            }
            Button("Remove token from this Mac") { admin.removeToken() }
                .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
        }
    }

    private var lastRun: String {
        guard let at = admin.overview?.last_run?.at else { return "Runs by itself every 10 minutes." }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = f.date(from: at) else { return "Runs by itself every 10 minutes." }
        return "Last ran \(date.formatted(.relative(presentation: .named)))."
    }

    private func section<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.system(size: 10, weight: .semibold)).tracking(1.4).foregroundStyle(.secondary)
            content()
        }
    }
}
