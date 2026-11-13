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
                             detail: store.usingSampleData ? "simulated sample league" : "imported")
                    StatTile(title: "Teams", value: "\(store.model.teams.count)")
                    StatTile(title: "Upcoming games", value: "\(store.slate.count)")
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

                Text("Everything stays on this Mac, in Application Support/StreakEdge. Probabilities are estimates from past results, not guarantees — only stake what you can afford to lose.")
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
