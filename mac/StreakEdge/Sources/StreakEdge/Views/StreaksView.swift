import EdgeCore
import SwiftUI

struct StreakRow: Identifiable {
    var id: String { team }
    let team: String
    let rating: Double
    let summary: StreakSummary
    let outcomes: [Bool]
    /// Chance the next game is a hit.
    let hitChance: Double

    var current: Int { summary.current }
    var rate: Double { summary.rate }
    var longest: Int { summary.longestHit }
    var runsZ: Double { summary.runsZ ?? 0 }
    var nextThree: Double { Streaks.probabilityOfExtending(by: 3, p: hitChance) }
}

struct StreaksView: View {
    @EnvironmentObject private var store: AppStore
    @State private var kind: StreakKind = .win
    @State private var sortOrder = [KeyPathComparator(\StreakRow.current, order: .reverse)]
    @State private var selection: StreakRow.ID?
    @State private var runLength = 5
    @State private var horizon = 20

    private var rows: [StreakRow] {
        store.model.teams.map { t in
            let seq = Streaks.outcomes(team: t.name, games: store.games, kind: kind)
            let s = Streaks.summarize(seq)
            // Wins use the rating model; spread and total results use the team's own hit rate.
            let p = kind == .win ? store.model.baselineWinProbability(t.name) : s.rate
            return StreakRow(team: t.name, rating: t.rating, summary: s, outcomes: seq, hitChance: p)
        }
        .filter { $0.summary.games > 0 }
        .sorted(using: sortOrder)
    }

    var body: some View {
        let rows = self.rows
        VStack(spacing: 0) {
            Picker("Streak type", selection: $kind) {
                ForEach(StreakKind.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(10)

            if rows.isEmpty {
                EmptyState(title: "No results for this streak type",
                           message: kind == .win ? "Import game results in Data."
                               : "These streaks need a spread or total on each game.",
                           icon: "flame")
            } else {
                Table(rows, selection: $selection, sortOrder: $sortOrder) {
                    TableColumn("Team", value: \.team)
                    TableColumn("Current", value: \.current) { Text(Fmt.streak($0.current, kind)).monospacedDigit() }
                    TableColumn("Record", value: \.rate) { r in
                        Text("\(r.summary.hits)–\(r.summary.misses)").monospacedDigit()
                    }
                    TableColumn("Last 10") { r in
                        Text("\(r.summary.last10Hits)–\(r.summary.last10Games - r.summary.last10Hits)").monospacedDigit()
                    }
                    TableColumn("Longest", value: \.longest) { Text("\($0.longest)").monospacedDigit() }
                    TableColumn("Rating", value: \.rating) { Text(String(format: "%.0f", $0.rating)).monospacedDigit() }
                    TableColumn("Next game", value: \.hitChance) { Text(Fmt.pct($0.hitChance)).monospacedDigit() }
                    TableColumn("Next 3 straight", value: \.nextThree) { Text(Fmt.pct($0.nextThree)).monospacedDigit() }
                    TableColumn("Streakiness", value: \.runsZ) { r in
                        Text(r.summary.runsZ.map { String(format: "%+.2f", $0) } ?? "—").monospacedDigit()
                    }
                }

                if let row = rows.first(where: { $0.id == selection }) {
                    detail(row)
                } else {
                    Text("Select a team for its recent form and a streak calculator. Streakiness is a runs-test score: below −2 means results clump more than chance would; near 0 means the streaks look like ordinary luck.")
                        .font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                }
            }
        }
    }

    private func detail(_ row: StreakRow) -> some View {
        let p = row.hitChance
        let chance = Streaks.probabilityOfRun(length: runLength, trials: horizon, p: p)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                Text(row.team).font(.headline)
                OutcomeStrip(outcomes: Array(row.outcomes.suffix(30)))
                Text("last \(min(30, row.outcomes.count))").font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 10) {
                StatTile(title: "Chance next game hits", value: Fmt.pct(p),
                         detail: kind == .win ? "vs an average opponent" : "season hit rate")
                StatTile(title: "Expected further hits", value: String(format: "%.1f", Streaks.expectedExtension(p: p)),
                         detail: "before the next miss")
                StatTile(title: "A run of \(runLength)+ in next \(horizon)", value: Fmt.pct(chance),
                         detail: "if games are independent")
            }
            HStack(spacing: 20) {
                Stepper("Run length: \(runLength)", value: $runLength, in: 2...15)
                Stepper("Games ahead: \(horizon)", value: $horizon, in: 2...82)
            }
        }
        .padding(12)
    }
}
