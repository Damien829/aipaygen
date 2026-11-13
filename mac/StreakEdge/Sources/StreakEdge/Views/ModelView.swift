import Charts
import EdgeCore
import SwiftUI

struct ModelView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        let c = store.model.calibration
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 10) {
                    StatTile(title: "Games tested", value: "\(c.games)", detail: "each predicted before it was played")
                    StatTile(title: "Winners picked", value: c.games > 0 ? Fmt.pct(c.accuracy) : "—")
                    StatTile(title: "Brier score", value: c.games > 0 ? String(format: "%.3f", c.brier) : "—",
                             detail: "coin flip is 0.250; lower is better")
                    StatTile(title: "Log loss", value: c.games > 0 ? String(format: "%.3f", c.logLoss) : "—",
                             detail: "coin flip is 0.693")
                }

                if !c.buckets.isEmpty {
                    GroupBox("Predicted vs actual home win rate") {
                        Chart {
                            LineMark(x: .value("Predicted", 0.0), y: .value("Actual", 0.0), series: .value("Line", "Perfect"))
                                .foregroundStyle(.secondary)
                                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                            LineMark(x: .value("Predicted", 1.0), y: .value("Actual", 1.0), series: .value("Line", "Perfect"))
                                .foregroundStyle(.secondary)
                                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                            ForEach(c.buckets) { b in
                                PointMark(x: .value("Predicted", b.predicted), y: .value("Actual", b.actual))
                                    .symbolSize(60 + Double(b.count) * 4)
                                    .annotation(position: .top) {
                                        Text("\(b.count)").font(.caption2).foregroundStyle(.secondary)
                                    }
                            }
                        }
                        .chartXScale(domain: 0...1)
                        .chartYScale(domain: 0...1)
                        .chartXAxisLabel("Model's home win probability")
                        .chartYAxisLabel("How often home won")
                        .frame(height: 240)
                        .padding(6)
                        Text("Dots on the dashed line mean the probabilities can be trusted. Numbers are games in each group; small groups are noisy.")
                            .font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                if !store.model.teams.isEmpty {
                    GroupBox("Team ratings (1500 is average)") {
                        Chart(store.model.teams) { t in
                            BarMark(x: .value("Rating", t.rating - LeagueModel.baseRating),
                                    y: .value("Team", t.name), height: .ratio(0.6))
                                .annotation(position: t.rating >= LeagueModel.baseRating ? .trailing : .leading) {
                                    Text(String(format: "%.0f", t.rating)).font(.caption2).foregroundStyle(.secondary)
                                }
                        }
                        .chartYScale(domain: store.model.teams.map(\.name))
                        .chartXAxisLabel("Rating points above or below average")
                        .frame(height: CGFloat(store.model.teams.count) * 24 + 40)
                        .padding(6)
                    }
                }

                GroupBox("Settings") {
                    Form {
                        LabeledContent("Rating speed: \(Int(store.config.k))") {
                            Slider(value: Binding(get: { store.config.k },
                                                  set: { store.setConfig(ModelConfig(k: $0.rounded(), homeAdvantage: store.config.homeAdvantage)) }),
                                   in: 5...50)
                        }
                        LabeledContent("Home advantage: \(Int(store.config.homeAdvantage))") {
                            Slider(value: Binding(get: { store.config.homeAdvantage },
                                                  set: { store.setConfig(ModelConfig(k: store.config.k, homeAdvantage: $0.rounded())) }),
                                   in: 0...150)
                        }
                        LabeledContent("Stake size: \(Fmt.pct(store.kellyFraction, digits: 0)) of Kelly") {
                            Slider(value: Binding(get: { store.kellyFraction }, set: { store.setKellyFraction($0) }),
                                   in: 0.05...1, step: 0.05)
                        }
                        TextField("Starting bankroll ($)",
                                  value: Binding(get: { store.bankroll }, set: { store.setBankroll($0) }),
                                  format: .number)
                    }
                    .padding(6)
                    Text("Adjust rating speed and home advantage until the Brier score is lowest for your league. Full Kelly swings hard when the model is wrong; a quarter is a common choice.")
                        .font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(16)
        }
    }
}
