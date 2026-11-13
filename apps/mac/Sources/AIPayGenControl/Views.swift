import AppKit
import SwiftUI

@main
struct AIPayGenControlApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var store = Store()
    @StateObject private var admin = Admin()

    var body: some Scene {
        WindowGroup("AIPayGen Control") {
            RootView()
                .environmentObject(store)
                .environmentObject(admin)
                .frame(minWidth: 1180, minHeight: 740)
                .preferredColorScheme(.dark)
        }
        .windowStyle(.hiddenTitleBar)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

// MARK: - Styling

private let accent = Color(nsColor: NSColor(hex: 0x35D8FF))

private struct Card: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color(red: 0.04, green: 0.06, blue: 0.11).opacity(0.8)))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Color.white.opacity(0.08)))
    }
}

private extension View {
    func card() -> some View { modifier(Card()) }
    func caption() -> some View { font(.system(size: 10, weight: .semibold)).tracking(1.4).foregroundStyle(.white.opacity(0.5)) }
}

private struct Chip: View {
    let text: String
    let color: Color
    var body: some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold))
            .padding(.horizontal, 7).padding(.vertical, 3)
            .background(Capsule().fill(color.opacity(0.18)))
            .overlay(Capsule().stroke(color.opacity(0.5)))
            .foregroundStyle(color)
    }
}

// MARK: - Root

struct RootView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        ZStack {
            NetworkView(controller: store.network) { store.pick($0) }
                .ignoresSafeArea()
            LinearGradient(stops: [.init(color: .black.opacity(0.7), location: 0), .init(color: .clear, location: 0.28), .init(color: .clear, location: 0.72), .init(color: .black.opacity(0.7), location: 1)], startPoint: .leading, endPoint: .trailing)
                .allowsHitTesting(false)
                .ignoresSafeArea()
            VStack(spacing: 14) {
                Header()
                HStack(alignment: .top, spacing: 0) {
                    LeftPanel().frame(width: 250)
                    Spacer(minLength: 0)
                    RightPanel().frame(width: 310)
                }
                Spacer(minLength: 0)
            }
            .padding(16)
            VStack {
                Spacer()
                if let item = store.selected {
                    DetailCard(item: item).transition(.move(edge: .bottom).combined(with: .opacity))
                } else {
                    Text("Drag to orbit · scroll to zoom · click a node")
                        .font(.system(size: 11)).foregroundStyle(.white.opacity(0.35))
                }
            }
            .padding(.bottom, 18)
        }
        .background(Color.black)
        .task { await store.start() }
    }
}

private struct Header: View {
    @EnvironmentObject var store: Store
    @EnvironmentObject var admin: Admin
    @State private var beat = false
    @State private var showControls = false

    var body: some View {
        HStack(spacing: 12) {
            Text("AIPAYGEN").font(.system(size: 15, weight: .heavy)).tracking(3)
            Text("CONTROL").font(.system(size: 15, weight: .light)).tracking(3).foregroundStyle(accent)
            Spacer()
            Circle()
                .fill(store.online ? Color.green : Color.red)
                .frame(width: 8, height: 8)
                .shadow(color: store.online ? .green : .red, radius: beat ? 7 : 2)
                .onAppear { withAnimation(.easeInOut(duration: 1.1).repeatForever()) { beat = true } }
            Text(store.online ? "Live" : "Offline").font(.system(size: 12, weight: .semibold))
            if let v = store.health?.version { Text("v\(v)").font(.system(size: 11)).foregroundStyle(.white.opacity(0.5)) }
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                Text(store.lastUpdated.map { "updated \(max(0, Int(ctx.date.timeIntervalSince($0))))s ago" } ?? "connecting…")
                    .font(.system(size: 11).monospacedDigit()).foregroundStyle(.white.opacity(0.5))
            }
            Button { Task { await store.refresh() } } label: {
                Image(systemName: "arrow.clockwise")
                    .rotationEffect(.degrees(store.loading ? 360 : 0))
                    .animation(store.loading ? .linear(duration: 0.9).repeatForever(autoreverses: false) : .default, value: store.loading)
            }
            .buttonStyle(.plain).help("Refresh now")
            Button { showControls.toggle() } label: {
                Label("Controls", systemImage: admin.hasToken ? "slider.horizontal.3" : "lock.fill")
                    .font(.system(size: 11, weight: .semibold))
                    .padding(.horizontal, 9).padding(.vertical, 4)
                    .background(Capsule().fill(Color.white.opacity(0.1)))
            }
            .buttonStyle(.plain)
            .popover(isPresented: $showControls, arrowEdge: .bottom) {
                ControlsView().environmentObject(store).environmentObject(admin)
            }
        }
        .padding(.leading, 70)
        .frame(height: 22)
    }
}

// MARK: - Left: the marketplace

private struct LeftPanel: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("MARKETPLACE").caption()
                Text(store.total.formatted())
                    .font(.system(size: 40, weight: .bold, design: .rounded).monospacedDigit())
                    .contentTransition(.numericText())
                Text("things agents can find and use").font(.system(size: 11)).foregroundStyle(.white.opacity(0.55))
            }
            .card()
            VStack(spacing: 4) {
                ForEach(kinds) { KindRow(kind: $0) }
            }
            .card()
            if let popular = store.wanted?.popular, !popular.isEmpty {
                VStack(alignment: .leading, spacing: 7) {
                    Text("AGENTS ARE SEARCHING FOR").caption()
                    ForEach(popular.prefix(5), id: \.self) { q in
                        HStack {
                            Text(q.query).font(.system(size: 12))
                            Spacer()
                            if let n = q.searches { Text("\(n)").font(.system(size: 11).monospacedDigit()).foregroundStyle(.white.opacity(0.5)) }
                        }
                    }
                    if let unmet = store.wanted?.unmet, !unmet.isEmpty {
                        Text("NOT FOUND YET").caption().padding(.top, 4)
                        ForEach(unmet.prefix(4), id: \.self) { Text($0.query).font(.system(size: 12)).foregroundStyle(.orange) }
                    }
                }
                .card()
            }
        }
    }
}

private struct KindRow: View {
    @EnvironmentObject var store: Store
    let kind: Kind
    @State private var hover = false

    var body: some View {
        let n = store.counts[kind.id] ?? 0
        let share = store.total > 0 ? Double(n) / Double(store.total) : 0
        VStack(spacing: 4) {
            HStack(spacing: 8) {
                Circle().fill(kind.color).frame(width: 8, height: 8).shadow(color: kind.color, radius: 4)
                Text(kind.label).font(.system(size: 12, weight: .medium))
                Spacer()
                Text(n.formatted()).font(.system(size: 13, weight: .semibold).monospacedDigit()).contentTransition(.numericText())
            }
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.06))
                    Capsule().fill(kind.color).frame(width: max(3, g.size.width * share))
                }
            }
            .frame(height: 3)
        }
        .padding(.vertical, 5).padding(.horizontal, 6)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(hover ? 0.07 : 0)))
        .contentShape(Rectangle())
        .onHover { inside in
            hover = inside
            if inside { store.network.pulse(kind.id) }
        }
        .help("Point here to light up this orbit")
    }
}

// MARK: - Right: payments, wallet, search, activity

private struct RightPanel: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(spacing: 10) {
            FacilitatorCard()
            WalletCard()
            SearchCard()
            ActivityCard()
        }
    }
}

private struct FacilitatorCard: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("X402 FACILITATOR").caption()
                Spacer()
                Chip(text: store.ownerPaused ? "PAUSED BY YOU" : store.fac?.enabled == true ? "ON" : "OFF", color: store.ownerPaused ? .orange : store.fac?.enabled == true ? .green : .gray)
            }
            HStack(alignment: .top, spacing: 10) {
                net("Base mainnet", "real money", store.fac?.stats?.mainnet, live: store.mainnetLive, pausedLabel: "PAUSED")
                Divider().frame(height: 62)
                net("Base Sepolia", "test network", store.fac?.stats?.testnet, live: !store.ownerPaused && (store.fac?.networks.contains("eip155:84532") ?? false), pausedLabel: store.ownerPaused ? "PAUSED" : "OFF")
            }
            if let waiting = store.fac?.stats?.mainnet.merchants_waiting_7d, waiting > 0 {
                Label("\(waiting) merchant\(waiting == 1 ? "" : "s") tried real payments in the last 7 days", systemImage: "person.crop.circle.badge.exclamationmark")
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(.orange)
            }
        }
        .card()
    }

    private func net(_ name: String, _ sub: String, _ s: NetStats?, live: Bool, pausedLabel: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(name).font(.system(size: 12, weight: .semibold))
                Chip(text: live ? "LIVE" : pausedLabel, color: live ? .green : .orange)
            }
            Text(sub).font(.system(size: 10)).foregroundStyle(.white.opacity(0.45))
            Text("\(s?.settlements ?? 0)")
                .font(.system(size: 24, weight: .bold, design: .rounded).monospacedDigit()).contentTransition(.numericText())
            Text("settled · \(s?.volume_usdc ?? "0.00") USDC").font(.system(size: 10)).foregroundStyle(.white.opacity(0.55))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct WalletCard: View {
    @EnvironmentObject var store: Store

    var body: some View {
        let gas = store.mainnetGas
        let ok = (gas ?? 0) >= minGasEth
        HStack(spacing: 14) {
            Gauge(value: min((gas ?? 0) / 0.002, 1)) { Image(systemName: "fuelpump.fill") }
                .gaugeStyle(.accessoryCircularCapacity)
                .tint(ok ? Color.green : Color.orange)
            VStack(alignment: .leading, spacing: 3) {
                Text("FEE WALLET · BASE MAINNET").caption()
                Text(gas.map { String(format: "%.5f ETH", $0) } ?? "—")
                    .font(.system(size: 18, weight: .bold, design: .rounded).monospacedDigit()).contentTransition(.numericText())
                Text(gas == nil ? "Checking balance…" : ok ? "Funded: real payments can settle" : "Empty: real payments are paused")
                    .font(.system(size: 11)).foregroundStyle(ok ? Color.green : Color.orange)
                if let t = store.testnetGas {
                    Text(String(format: "Test wallet: %.5f ETH", t)).font(.system(size: 10)).foregroundStyle(.white.opacity(0.45))
                }
            }
            Spacer(minLength: 0)
        }
        .card()
        .contextMenu {
            Button("Copy fee wallet address") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(mainnetWallet, forType: .string)
            }
        }
    }
}

private struct SearchCard: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass").foregroundStyle(.white.opacity(0.5))
                TextField("Search the marketplace", text: $store.query).textFieldStyle(.plain).font(.system(size: 12))
                if !store.query.isEmpty {
                    Button { store.query = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).foregroundStyle(.white.opacity(0.4))
                }
            }
            ForEach(store.results) { item in
                Button { store.pick(item.id) } label: {
                    HStack(spacing: 7) {
                        Circle().fill(kind(item.kind).color).frame(width: 6, height: 6)
                        Text(item.name).font(.system(size: 11)).lineLimit(1)
                        Spacer(minLength: 0)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .card()
    }
}

private struct ActivityCard: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("ACTIVITY").caption()
            if store.events.isEmpty {
                Text("Waiting for the first update…").font(.system(size: 11)).foregroundStyle(.white.opacity(0.45))
            }
            ForEach(store.events.prefix(6)) { e in
                HStack(spacing: 7) {
                    Image(systemName: e.symbol).foregroundStyle(e.color).font(.system(size: 11)).frame(width: 14)
                    Text(e.text).font(.system(size: 11)).lineLimit(1)
                    Spacer(minLength: 0)
                    Text(e.date, style: .time).font(.system(size: 10).monospacedDigit()).foregroundStyle(.white.opacity(0.4))
                }
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .card()
    }
}

// MARK: - Selected node

private struct DetailCard: View {
    @EnvironmentObject var store: Store
    @EnvironmentObject var admin: Admin
    let item: CatalogItem
    @State private var confirmHide = false

    var body: some View {
        let k = kind(item.kind)
        HStack(alignment: .top, spacing: 12) {
            Circle().fill(k.color).frame(width: 12, height: 12).shadow(color: k.color, radius: 6).padding(.top, 4)
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text(item.name).font(.system(size: 14, weight: .semibold)).lineLimit(1)
                    Chip(text: k.label.uppercased(), color: k.color)
                    if item.x402 == true { Chip(text: "X402 PAYABLE", color: .green) }
                }
                if let d = item.description, !d.isEmpty {
                    Text(d).font(.system(size: 11)).foregroundStyle(.white.opacity(0.7)).lineLimit(3).fixedSize(horizontal: false, vertical: true)
                }
                if let u = item.url { Text(u).font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.4)).lineLimit(1).textSelection(.enabled) }
            }
            Spacer(minLength: 8)
            VStack(spacing: 6) {
                Button("View on AIPayGen") {
                    var c = URLComponents(string: "https://aipaygen.com/market")!
                    c.queryItems = [URLQueryItem(name: "q", value: item.name), URLQueryItem(name: "kind", value: item.kind)]
                    if let url = c.url { NSWorkspace.shared.open(url) }
                }
                if admin.hasToken {
                    Button("Hide…") { confirmHide = true }
                        .disabled(admin.busy != nil)
                        .confirmationDialog("Hide \"\(item.name)\"?", isPresented: $confirmHide) {
                            Button("Hide listing", role: .destructive) {
                                Task {
                                    if await admin.setHidden(item.id, true) {
                                        store.pick(nil)
                                        await store.refresh()
                                    }
                                }
                            }
                        } message: {
                            Text("Agents stop seeing it in search and listings. You can unhide it from Controls.")
                        }
                }
                Button("Close") { store.pick(nil) }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.white.opacity(0.5))
            }
        }
        .card()
        .frame(maxWidth: 560)
    }
}
