import EdgeCore
import SwiftUI

struct BestBetsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var valueOnly = false
    @State private var adding = false
    @State private var selection: Pick.ID?

    private var rows: [Pick] {
        valueOnly ? store.picks.filter { $0.expectedValue > 0 } : store.picks
    }

    var body: some View {
        VStack(spacing: 0) {
            if store.slate.isEmpty {
                EmptyState(title: "No upcoming games",
                           message: "Add a game and its moneyline prices to see where the model disagrees with the market.",
                           icon: "star")
            } else {
                Table(rows, selection: $selection) {
                    TableColumn("Pick") { p in
                        VStack(alignment: .leading) {
                            Text(p.label)
                            Text(p.date, format: .dateTime.month().day()).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .width(min: 190)
                    TableColumn("Odds") { Text(Odds.format(american: $0.odds)).monospacedDigit() }
                    TableColumn("Model") { Text(Fmt.pct($0.modelProbability)).monospacedDigit() }
                    TableColumn("Market") { Text(Fmt.pct($0.marketProbability)).monospacedDigit() }
                    TableColumn("Edge") { p in
                        Text(Fmt.signedPct(p.edge)).monospacedDigit()
                            .fontWeight(p.edge > 0 ? .semibold : .regular)
                            .foregroundStyle(p.edge > 0 ? .primary : .secondary)
                    }
                    TableColumn("EV per $100") { Text(Fmt.signedMoney($0.expectedValue * 100)).monospacedDigit() }
                    TableColumn("Stake") { p in
                        let stake = store.suggestedStake(kelly: p.kelly)
                        Text(stake > 0 ? Fmt.money(stake) : "Pass").monospacedDigit()
                            .foregroundStyle(stake > 0 ? .primary : .secondary)
                    }
                    TableColumn("Streak") { Text(Fmt.streak($0.winStreak)) }
                    TableColumn("") { p in
                        Button("Log Bet") {
                            let stake = store.suggestedStake(kelly: p.kelly)
                            store.addBet(Bet(date: Date(), label: p.label, odds: p.odds, stake: stake > 0 ? stake : 10))
                        }
                    }
                    .width(80)
                }
                .contextMenu(forSelectionType: Pick.ID.self) { ids in
                    Button("Remove Game", role: .destructive) {
                        for p in store.picks where ids.contains(p.id) { store.removeSlateGame(p.gameID) }
                    }
                }
                Text("Model is the app's win probability. Market is the bookmaker's price with its margin removed. Stake is \(Fmt.pct(store.kellyFraction, digits: 0)) of the Kelly amount on a \(Fmt.money(store.currentBalance)) balance, never more than \(Fmt.pct(AppStore.maxStakeShare, digits: 0)) of it.")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            }
        }
        .toolbar {
            Toggle("Positive value only", isOn: $valueOnly)
            Button("Add Game", systemImage: "plus") { adding = true }
        }
        .sheet(isPresented: $adding) { AddSlateGameSheet() }
    }
}

struct AddSlateGameSheet: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var home = ""
    @State private var away = ""
    @State private var homeOdds = -110
    @State private var awayOdds = -110
    @State private var date = Date()

    private var valid: Bool {
        !home.isEmpty && !away.isEmpty && home != away && abs(homeOdds) >= 100 && abs(awayOdds) >= 100
    }

    var body: some View {
        Form {
            Picker("Home", selection: $home) {
                Text("Choose a team").tag("")
                ForEach(store.teamNames, id: \.self) { Text($0).tag($0) }
            }
            Picker("Away", selection: $away) {
                Text("Choose a team").tag("")
                ForEach(store.teamNames, id: \.self) { Text($0).tag($0) }
            }
            TextField("Home moneyline", value: $homeOdds, format: .number.grouping(.never))
            TextField("Away moneyline", value: $awayOdds, format: .number.grouping(.never))
            DatePicker("Date", selection: $date, displayedComponents: .date)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                Button("Add") {
                    store.addSlateGame(SlateGame(date: date, home: home, away: away,
                                                 homeOdds: homeOdds, awayOdds: awayOdds))
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(!valid)
            }
        }
        .padding(20)
        .frame(width: 380)
    }
}
