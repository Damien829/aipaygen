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
    var league: League?
    /// Pre-game lines from past refreshes, used to fill in spreads and totals once games finish.
    var lineArchive: [SlateGame]?
    var resultsUpdated: Date?
    var oddsUpdated: Date?
    var oddsRequestsRemaining: Int?
}

@MainActor
final class AppStore: ObservableObject {
    @Published private(set) var state = SavedState()
    @Published private(set) var model = LeagueModel(games: [])
    @Published private(set) var picks: [Pick] = []

    @Published private(set) var isRefreshing = false
    @Published private(set) var liveMessage: String?
    @Published var apiKey = KeyStore.read() {
        didSet { if apiKey != oldValue { KeyStore.save(apiKey) } }
    }

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
    var league: League { state.league ?? .nba }
    var isLive: Bool { state.resultsUpdated != nil }
    var resultsUpdated: Date? { state.resultsUpdated }
    var oddsUpdated: Date? { state.oddsUpdated }
    var oddsRequestsRemaining: Int? { state.oddsRequestsRemaining }
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

    private func leaveLiveMode(_ s: inout SavedState) {
        s.resultsUpdated = nil
        s.oddsUpdated = nil
    }

    func setLeague(_ league: League) {
        guard league != self.league else { return }
        // Odds for the previous league no longer apply once live data is in use.
        change {
            $0.league = league
            if $0.resultsUpdated != nil { $0.slate = [] }
        }
    }

    /// Replaces the games with this season's real results, then loads current odds if a key is set.
    func refreshLive() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        liveMessage = nil
        defer { isRefreshing = false }
        let league = self.league
        let key = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)

        do {
            let games = try await LiveService.results(league: league)
            guard !games.isEmpty else {
                liveMessage = "No finished \(league.title) games were found for the current season."
                return
            }
            change {
                $0.games = ScoresFeed.attachLines(to: games, from: $0.lineArchive ?? [])
                $0.slate = $0.slate.filter { $0.sourceID != nil && $0.date > Date() }
                $0.usingSampleData = false
                $0.resultsUpdated = Date()
            }
        } catch {
            liveMessage = "Could not load results: \(error.localizedDescription)"
            return
        }

        guard !key.isEmpty else {
            liveMessage = "Results loaded. Add an odds API key to load live odds."
            return
        }
        do {
            let live = try await LiveService.odds(league: league, apiKey: key, knownTeams: teamNames)
            change {
                $0.slate = live.slate
                var archive = ($0.lineArchive ?? []).filter { old in
                    old.date > Date().addingTimeInterval(-400 * 86_400)
                        && !live.slate.contains { $0.sourceID == old.sourceID }
                }
                archive.append(contentsOf: live.slate)
                $0.lineArchive = archive
                $0.oddsUpdated = Date()
                $0.oddsRequestsRemaining = live.remaining
            }
            if live.slate.isEmpty { liveMessage = "No upcoming \(league.title) games have odds posted right now." }
        } catch {
            liveMessage = "Results loaded, but odds failed: \(error.localizedDescription)"
        }
    }

    func importGames(_ new: [Game], replacing: Bool) {
        change {
            leaveLiveMode(&$0)
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
            leaveLiveMode(&$0)
            $0.games = sample.games
            $0.slate = sample.slate
            $0.usingSampleData = true
        }
    }

    func clearGames() {
        change { leaveLiveMode(&$0); $0.games = []; $0.slate = []; $0.usingSampleData = false }
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
