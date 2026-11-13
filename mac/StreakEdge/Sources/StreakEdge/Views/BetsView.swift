import Charts
import EdgeCore
import SwiftUI

struct BetsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var adding = false
    @State private var selection: Bet.ID?

    var body: some View {
        let stats = store.bankrollStats
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                StatTile(title: "Balance", value: Fmt.money(store.currentBalance),
                         detail: "started at \(Fmt.money(store.bankroll))")
                StatTile(title: "Profit", value: Fmt.signedMoney(stats.profit),
                         detail: "ROI \(Fmt.signedPct(stats.roi))")
                StatTile(title: "Record", value: "\(stats.wins)–\(stats.losses)",
                         detail: stats.settled > 0 ? "\(Fmt.pct(stats.winRate)) won" : "no settled bets")
                StatTile(title: "Streak", value: Fmt.streak(stats.currentStreak),
                         detail: "best W\(stats.longestWinStreak), worst L\(stats.longestLosingStreak)")
                StatTile(title: "Open bets", value: Fmt.money(stats.pendingStake), detail: "at risk")
            }
            .padding(10)

            if stats.curve.count > 1 {
                Chart(stats.curve) { point in
                    LineMark(x: .value("Settled bets", point.id), y: .value("Balance", point.balance))
                        .lineStyle(StrokeStyle(lineWidth: 2))
                }
                .chartYScale(domain: .automatic(includesZero: false))
                .chartXAxisLabel("Settled bets")
                .chartYAxisLabel("Balance ($)")
                .frame(height: 150)
                .padding(.horizontal, 12)
                .padding(.bottom, 8)
            }

            if store.bets.isEmpty {
                EmptyState(title: "No bets logged",
                           message: "Log a bet from Best Bets or Parlays, or add one here.",
                           icon: "list.bullet.rectangle")
            } else {
                Table(store.bets.sorted { $0.date > $1.date }, selection: $selection) {
                    TableColumn("Date") { Text($0.date, format: .dateTime.month().day()) }.width(60)
                    TableColumn("Bet") { Text($0.label) }.width(min: 220)
                    TableColumn("Odds") { Text(Odds.format(american: $0.odds)).monospacedDigit() }
                    TableColumn("Stake") { Text(Fmt.money($0.stake)).monospacedDigit() }
                    TableColumn("Result") { bet in
                        Picker("Result", selection: Binding(get: { bet.result },
                                                            set: { store.setResult(bet.id, $0) })) {
                            ForEach(BetResult.allCases, id: \.self) { Text($0.rawValue.capitalized).tag($0) }
                        }
                        .labelsHidden()
                    }
                    .width(110)
                    TableColumn("Profit") { bet in
                        Text(bet.result == .pending ? "—" : Fmt.signedMoney(bet.profit)).monospacedDigit()
                    }
                }
                .contextMenu(forSelectionType: Bet.ID.self) { ids in
                    Button("Delete", role: .destructive) { for id in ids { store.removeBet(id) } }
                }
            }
        }
        .toolbar {
            Button("Add Bet", systemImage: "plus") { adding = true }
        }
        .sheet(isPresented: $adding) { AddBetSheet() }
    }
}

struct AddBetSheet: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var label = ""
    @State private var odds = -110
    @State private var stake = 10.0

    var body: some View {
        Form {
            TextField("Bet", text: $label, prompt: Text("e.g. Falcons -3.5"))
            TextField("Odds", value: $odds, format: .number.grouping(.never))
            TextField("Stake", value: $stake, format: .number)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                Button("Add") {
                    store.addBet(Bet(date: Date(), label: label, odds: odds, stake: stake))
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(label.isEmpty || abs(odds) < 100 || stake <= 0)
            }
        }
        .padding(20)
        .frame(width: 380)
    }
}
