import EdgeCore
import SwiftUI

struct MatchupView: View {
    @EnvironmentObject private var store: AppStore
    @State private var home = ""
    @State private var away = ""
    @State private var neutral = false
    @State private var homeOdds: Int?
    @State private var awayOdds: Int?
    @State private var spread: Double?
    @State private var total: Double?

    var body: some View {
        if store.teamNames.count < 2 {
            EmptyState(title: "Not enough teams", message: "Import game results in Data.", icon: "person.2")
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    inputs
                    if !home.isEmpty, !away.isEmpty, home != away {
                        results
                    } else {
                        Text("Choose two different teams.").foregroundStyle(.secondary)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var inputs: some View {
        Form {
            Picker("Home", selection: $home) {
                Text("Choose a team").tag("")
                ForEach(store.teamNames, id: \.self) { Text($0).tag($0) }
            }
            Picker("Away", selection: $away) {
                Text("Choose a team").tag("")
                ForEach(store.teamNames, id: \.self) { Text($0).tag($0) }
            }
            Toggle("Neutral site", isOn: $neutral)
            TextField("Home moneyline", value: $homeOdds, format: .number.grouping(.never), prompt: Text("e.g. -150"))
            TextField("Away moneyline", value: $awayOdds, format: .number.grouping(.never), prompt: Text("e.g. +130"))
            TextField("Home spread", value: $spread, format: .number, prompt: Text("e.g. -3.5"))
            TextField("Total", value: $total, format: .number, prompt: Text("e.g. 221.5"))
        }
        .frame(maxWidth: 380)
    }

    @ViewBuilder private var results: some View {
        let m = store.model
        let pHome = m.homeWinProbability(home: home, away: away, neutral: neutral)
        let margin = m.expectedMargin(home: home, away: away, neutral: neutral)

        HStack(spacing: 10) {
            StatTile(title: "\(home) win", value: Fmt.pct(pHome),
                     detail: "fair price \(Odds.format(american: Odds.fairAmerican(probability: pHome)))")
            StatTile(title: "\(away) win", value: Fmt.pct(1 - pHome),
                     detail: "fair price \(Odds.format(american: Odds.fairAmerican(probability: 1 - pHome)))")
            StatTile(title: "Expected margin",
                     value: String(format: "%@ by %.1f", margin >= 0 ? home : away, abs(margin)),
                     detail: String(format: "typical miss ±%.1f", m.marginSD))
            StatTile(title: "Expected total", value: String(format: "%.1f", m.expectedTotal(home: home, away: away)),
                     detail: String(format: "typical miss ±%.1f", m.totalSD))
        }

        if let h = homeOdds, let a = awayOdds, abs(h) >= 100, abs(a) >= 100 {
            let market = Odds.noVig(h, a)
            GroupBox("Moneyline") {
                Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 6) {
                    GridRow {
                        Text("Side"); Text("Odds"); Text("Model"); Text("Market"); Text("Edge"); Text("EV per $100"); Text("Stake")
                    }
                    .font(.caption).foregroundStyle(.secondary)
                    moneylineRow(home, odds: h, model: pHome, market: market.a)
                    moneylineRow(away, odds: a, model: 1 - pHome, market: market.b)
                }
                .padding(6)
                Text("Bookmaker margin on this market: \(Fmt.pct(market.hold)).")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 6)
            }
        }

        if let s = spread, let cover = m.homeCoverProbability(home: home, away: away, spread: s, neutral: neutral) {
            HStack(spacing: 10) {
                StatTile(title: "\(home) covers \(String(format: "%+.1f", s))", value: Fmt.pct(cover))
                StatTile(title: "\(away) covers \(String(format: "%+.1f", -s))", value: Fmt.pct(1 - cover))
            }
        }
        if let t = total, let over = m.overProbability(home: home, away: away, total: t) {
            HStack(spacing: 10) {
                StatTile(title: "Over \(String(format: "%.1f", t))", value: Fmt.pct(over))
                StatTile(title: "Under \(String(format: "%.1f", t))", value: Fmt.pct(1 - over))
            }
        }

        GroupBox("Current streaks") {
            Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 6) {
                GridRow {
                    Text("Team"); Text("Win"); Text("Spread"); Text("Total"); Text("Last 10 results")
                }
                .font(.caption).foregroundStyle(.secondary)
                streakRow(home)
                streakRow(away)
            }
            .padding(6)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func moneylineRow(_ team: String, odds: Int, model: Double, market: Double) -> some View {
        let stake = store.suggestedStake(kelly: Odds.kelly(probability: model, american: odds))
        return GridRow {
            Text(team)
            Text(Odds.format(american: odds))
            Text(Fmt.pct(model))
            Text(Fmt.pct(market))
            Text(Fmt.signedPct(model - market)).fontWeight(model > market ? .semibold : .regular)
            Text(Fmt.signedMoney(Odds.expectedValue(probability: model, american: odds) * 100))
            Text(stake > 0 ? Fmt.money(stake) : "Pass")
        }
        .monospacedDigit()
    }

    private func streakRow(_ team: String) -> some View {
        let wins = Streaks.outcomes(team: team, games: store.games, kind: .win)
        func current(_ kind: StreakKind) -> String {
            Fmt.streak(Streaks.summarize(Streaks.outcomes(team: team, games: store.games, kind: kind)).current, kind)
        }
        return GridRow {
            Text(team)
            Text(current(.win))
            Text(current(.ats))
            Text(current(.over))
            OutcomeStrip(outcomes: Array(wins.suffix(10)))
        }
    }
}
