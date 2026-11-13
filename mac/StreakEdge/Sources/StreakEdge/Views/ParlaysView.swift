import EdgeCore
import SwiftUI

struct ParlaysView: View {
    @EnvironmentObject private var store: AppStore
    @State private var legs = 2

    var body: some View {
        let parlays = Picks.bestParlays(from: store.picks, legCount: legs)
        VStack(spacing: 0) {
            Picker("Legs", selection: $legs) {
                ForEach(2...4, id: \.self) { Text("\($0) legs").tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(maxWidth: 300)
            .padding(10)

            if parlays.isEmpty {
                EmptyState(title: "No parlays worth building",
                           message: "Parlays are only built from picks the model rates as positive value, one per game. There are not enough of those for \(legs) legs.",
                           icon: "link")
            } else {
                List(parlays) { p in
                    HStack(alignment: .top, spacing: 16) {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(p.legs) { leg in
                                Text("\(leg.label)  \(Odds.format(american: leg.odds))")
                            }
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 2) {
                            Text("Pays \(Odds.format(american: p.americanOdds))").fontWeight(.semibold)
                            Text("Hits \(Fmt.pct(p.probability))")
                            Text("EV \(Fmt.signedMoney(p.expectedValue * 100)) per $100")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        .monospacedDigit()
                        Button("Log Bet") {
                            store.addBet(Bet(date: Date(),
                                             label: "Parlay: " + p.legs.map(\.team).joined(separator: " + "),
                                             odds: p.americanOdds, stake: 10))
                        }
                    }
                    .padding(.vertical, 4)
                }
                Text("Ranked by expected value. Hit chance multiplies the legs' model probabilities, so any model error compounds with every leg added.")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            }
        }
    }
}
