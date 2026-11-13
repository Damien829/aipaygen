import EdgeCore
import Foundation

struct SavedState: Codable {
    var games: [Game] = []
    var slate: [SlateGame] = []
    var bets: [Bet] = []
    var config = ModelConfig()
    var bankroll = 1000.0
    var kellyFraction = 0.25
    var usingSampleData = false
}

@MainActor
final class AppStore: ObservableObject {
    @Published private(set) var state = SavedState()
    @Published private(set) var model = LeagueModel(games: [])
    @Published private(set) var picks: [Pick] = []

    private let fileURL: URL

    init() {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        let folder = support.appendingPathComponent("StreakEdge", isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        fileURL = folder.appendingPathComponent("state.json")

        if let data = try? Data(contentsOf: fileURL),
           let saved = try? JSONDecoder().decode(SavedState.self, from: data) {
            state = saved
        } else {
            let sample = SampleData.make()
            state.games = sample.games
            state.slate = sample.slate
            state.usingSampleData = true
        }
        rebuild()
    }

    // MARK: Read access

    var games: [Game] { state.games }
    var slate: [SlateGame] { state.slate }
    var bets: [Bet] { state.bets }
    var config: ModelConfig { state.config }
    var bankroll: Double { state.bankroll }
    var kellyFraction: Double { state.kellyFraction }
    var usingSampleData: Bool { state.usingSampleData }
    var teamNames: [String] { model.teams.map(\.name).sorted() }
    var bankrollStats: BankrollStats { BankrollStats(bets: state.bets, startingBankroll: state.bankroll) }
    var currentBalance: Double { state.bankroll + bankrollStats.profit }

    /// Largest share of the balance ever suggested for one bet, however big the model thinks the edge is.
    static let maxStakeShare = 0.05

    /// Suggested stake: a fraction of full Kelly on the current balance, capped, rounded to whole dollars.
    func suggestedStake(kelly: Double) -> Double {
        max(0, (min(kelly * state.kellyFraction, Self.maxStakeShare) * currentBalance).rounded())
    }

    // MARK: Changes

    private func change(remodel: Bool = true, _ body: (inout SavedState) -> Void) {
        body(&state)
        if remodel { rebuild() }
        if let data = try? JSONEncoder().encode(state) { try? data.write(to: fileURL, options: .atomic) }
    }

    private func rebuild() {
        model = LeagueModel(games: state.games, config: state.config)
        picks = Picks.evaluate(slate: state.slate, model: model, games: state.games)
    }

    func importGames(_ new: [Game], replacing: Bool) {
        change {
            if replacing || $0.usingSampleData {
                $0.games = new
                if $0.usingSampleData { $0.slate = [] }
            } else {
                $0.games.append(contentsOf: new)
            }
            $0.usingSampleData = false
        }
    }

    func loadSample() {
        let sample = SampleData.make()
        change {
            $0.games = sample.games
            $0.slate = sample.slate
            $0.usingSampleData = true
        }
    }

    func clearGames() {
        change { $0.games = []; $0.slate = []; $0.usingSampleData = false }
    }

    func addSlateGame(_ g: SlateGame) { change { $0.slate.append(g) } }
    func removeSlateGame(_ id: UUID) { change { $0.slate.removeAll { $0.id == id } } }

    func setConfig(_ c: ModelConfig) { change { $0.config = c } }
    func setBankroll(_ v: Double) { change(remodel: false) { $0.bankroll = max(0, v) } }
    func setKellyFraction(_ v: Double) { change(remodel: false) { $0.kellyFraction = v } }

    func addBet(_ b: Bet) { change(remodel: false) { $0.bets.append(b) } }
    func removeBet(_ id: UUID) { change(remodel: false) { $0.bets.removeAll { $0.id == id } } }
    func setResult(_ id: UUID, _ r: BetResult) {
        change(remodel: false) { s in
            if let i = s.bets.firstIndex(where: { $0.id == id }) { s.bets[i].result = r }
        }
    }
}
