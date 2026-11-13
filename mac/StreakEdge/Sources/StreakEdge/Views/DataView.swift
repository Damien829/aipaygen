import EdgeCore
import SwiftUI
import UniformTypeIdentifiers

struct DataView: View {
    @EnvironmentObject private var store: AppStore
    @State private var importing = false
    @State private var replace = false
    @State private var message: String?
    @State private var confirmingClear = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 10) {
                    StatTile(title: "Games", value: "\(store.games.count)",
                             detail: store.usingSampleData ? "simulated sample league"
                                 : (store.isLive ? "live \(store.league.title) results" : "imported"))
                    StatTile(title: "Teams", value: "\(store.model.teams.count)")
                    StatTile(title: "Upcoming games", value: "\(store.slate.count)")
                }

                GroupBox("Live data") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Loads this season's real results and current bookmaker odds, replacing whatever games are loaded now. Odds need a key from the-odds-api.com; its free plan allows 500 requests a month and each refresh uses 3.")
                        Picker("League", selection: Binding(get: { store.league }, set: { store.setLeague($0) })) {
                            ForEach(League.allCases) { Text($0.title).tag($0) }
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: 320)
                        SecureField("Odds API key", text: $store.apiKey)
                            .frame(maxWidth: 420)
                        HStack {
                            Button("Refresh Now") { Task { await store.refreshLive() } }
                                .disabled(store.isRefreshing)
                            if store.isRefreshing { ProgressView().controlSize(.small) }
                        }
                        if let text = store.liveMessage { Text(text).foregroundStyle(.secondary) }
                        if let updated = store.resultsUpdated {
                            Text("Results updated \(updated.formatted(date: .abbreviated, time: .shortened)).")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if let updated = store.oddsUpdated {
                            Text("Odds updated \(updated.formatted(date: .abbreviated, time: .shortened))"
                                + (store.oddsRequestsRemaining.map { "; \($0) requests left this month." } ?? "."))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .padding(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Import results") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Choose a CSV file with one finished game per row. The spread is the home team's line; spread and total are optional but needed for spread and total streaks.")
                        Text(CSVImport.template)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 6))
                        Toggle("Replace existing games instead of adding to them", isOn: $replace)
                            .disabled(store.usingSampleData)
                        HStack {
                            Button("Import CSV…") { importing = true }
                            Button("Load Sample League") { store.loadSample(); message = nil }
                            Button("Remove All Games", role: .destructive) { confirmingClear = true }
                                .disabled(store.games.isEmpty)
                        }
                        if let message { Text(message).foregroundStyle(.secondary) }
                    }
                    .padding(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Text("Your bets and settings stay on this Mac, in Application Support/StreakEdge; the API key is kept in your keychain. Probabilities are estimates from past results, not guarantees — only stake what you can afford to lose.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(16)
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.commaSeparatedText, .plainText]) { result in
            handle(result)
        }
        .confirmationDialog("Remove all games and upcoming games?", isPresented: $confirmingClear) {
            Button("Remove", role: .destructive) { store.clearGames(); message = nil }
        } message: {
            Text("Your logged bets are kept.")
        }
    }

    private func handle(_ result: Result<URL, Error>) {
        do {
            let url = try result.get()
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let parsed = CSVImport.parse(try String(contentsOf: url, encoding: .utf8))
            guard !parsed.games.isEmpty else {
                message = "Nothing imported. " + (parsed.skipped.first ?? "No games found.")
                return
            }
            store.importGames(parsed.games, replacing: replace)
            message = "Imported \(parsed.games.count) games"
                + (parsed.skipped.isEmpty ? "." : "; skipped \(parsed.skipped.count) rows (\(parsed.skipped[0])).")
        } catch {
            message = "Could not read that file: \(error.localizedDescription)"
        }
    }
}
