import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    // Needed when launched with `swift run`, where there is no app bundle to make it a foreground app.
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct StreakEdgeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var store = AppStore()

    var body: some Scene {
        WindowGroup("StreakEdge") {
            ContentView()
                .environmentObject(store)
                .frame(minWidth: 980, minHeight: 620)
        }
    }
}

enum AppSection: String, CaseIterable, Identifiable {
    case bestBets = "Best Bets"
    case streaks = "Streaks"
    case matchup = "Matchup"
    case parlays = "Parlays"
    case bets = "Bet Tracker"
    case model = "Model"
    case data = "Data"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .bestBets: return "star"
        case .streaks: return "flame"
        case .matchup: return "person.2"
        case .parlays: return "link"
        case .bets: return "list.bullet.rectangle"
        case .model: return "chart.xyaxis.line"
        case .data: return "tray.and.arrow.down"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var store: AppStore
    @State private var section: AppSection? = .bestBets

    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: $section) { s in
                Label(s.rawValue, systemImage: s.icon).tag(s)
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 190)
            .safeAreaInset(edge: .bottom) {
                if store.usingSampleData {
                    Text("Sample league — simulated teams and odds. Import your own results in Data.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(10)
                }
            }
        } detail: {
            Group {
                switch section ?? .bestBets {
                case .bestBets: BestBetsView()
                case .streaks: StreaksView()
                case .matchup: MatchupView()
                case .parlays: ParlaysView()
                case .bets: BetsView()
                case .model: ModelView()
                case .data: DataView()
                }
            }
            .navigationTitle((section ?? .bestBets).rawValue)
        }
    }
}
