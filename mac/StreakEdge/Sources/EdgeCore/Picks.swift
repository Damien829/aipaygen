import Foundation

/// One side of an upcoming game, priced against the model.
public struct Pick: Identifiable, Hashable, Sendable {
    public var id: String { "\(gameID.uuidString)-\(team)" }
    public var gameID: UUID
    public var date: Date
    public var team: String
    public var opponent: String
    public var isHome: Bool
    public var odds: Int
    public var modelProbability: Double
    /// Market probability with the bookmaker margin removed.
    public var marketProbability: Double
    public var winStreak: Int

    public var edge: Double { modelProbability - marketProbability }
    public var expectedValue: Double { Odds.expectedValue(probability: modelProbability, american: odds) }
    public var kelly: Double { Odds.kelly(probability: modelProbability, american: odds) }
    public var label: String { "\(team) ML \(isHome ? "vs" : "@") \(opponent)" }
}

public struct Parlay: Identifiable, Sendable {
    public var legs: [Pick]
    public var id: String { legs.map(\.id).joined(separator: "|") }
    /// Assumes the legs are independent, which is reasonable across different games.
    public var probability: Double { legs.reduce(1) { $0 * $1.modelProbability } }
    public var decimalOdds: Double { Odds.parlayDecimal(legs.map(\.odds)) }
    public var americanOdds: Int { Odds.american(fromDecimal: decimalOdds) }
    public var expectedValue: Double { probability * (decimalOdds - 1) - (1 - probability) }
}

public enum Picks {
    public static func evaluate(slate: [SlateGame], model: LeagueModel, games: [Game]) -> [Pick] {
        var streakCache: [String: Int] = [:]
        func streak(_ team: String) -> Int {
            if let s = streakCache[team] { return s }
            let s = Streaks.summarize(Streaks.outcomes(team: team, games: games, kind: .win)).current
            streakCache[team] = s
            return s
        }
        return slate.flatMap { g -> [Pick] in
            let pHome = model.homeWinProbability(home: g.home, away: g.away)
            let market = Odds.noVig(g.homeOdds, g.awayOdds)
            return [
                Pick(gameID: g.id, date: g.date, team: g.home, opponent: g.away, isHome: true,
                     odds: g.homeOdds, modelProbability: pHome, marketProbability: market.a,
                     winStreak: streak(g.home)),
                Pick(gameID: g.id, date: g.date, team: g.away, opponent: g.home, isHome: false,
                     odds: g.awayOdds, modelProbability: 1 - pHome, marketProbability: market.b,
                     winStreak: streak(g.away)),
            ]
        }
        .sorted { $0.expectedValue > $1.expectedValue }
    }

    /// Every combination of `legCount` positive-value picks from different games, best expected value first.
    public static func bestParlays(from picks: [Pick], legCount: Int, limit: Int = 20) -> [Parlay] {
        let pool = Array(picks.filter { $0.expectedValue > 0 }.prefix(14))
        guard legCount >= 2, pool.count >= legCount else { return [] }
        var out: [Parlay] = []
        var chosen: [Pick] = []
        func build(_ start: Int) {
            if chosen.count == legCount { out.append(Parlay(legs: chosen)); return }
            guard start < pool.count else { return }
            for i in start..<pool.count where !chosen.contains(where: { $0.gameID == pool[i].gameID }) {
                chosen.append(pool[i]); build(i + 1); chosen.removeLast()
            }
        }
        build(0)
        return Array(out.sorted { $0.expectedValue > $1.expectedValue }.prefix(limit))
    }
}

public struct BankrollPoint: Identifiable, Sendable {
    public var id: Int
    public var date: Date
    public var balance: Double
}

public struct BankrollStats: Sendable {
    public var settled = 0
    public var wins = 0
    public var losses = 0
    public var staked = 0.0
    public var profit = 0.0
    public var pendingStake = 0.0
    /// Signed: positive is consecutive wins, negative is consecutive losses.
    public var currentStreak = 0
    public var longestWinStreak = 0
    public var longestLosingStreak = 0
    public var curve: [BankrollPoint] = []

    public var roi: Double { staked == 0 ? 0 : profit / staked }
    public var winRate: Double { wins + losses == 0 ? 0 : Double(wins) / Double(wins + losses) }

    public init(bets: [Bet], startingBankroll: Double) {
        let ordered = bets.sorted { $0.date < $1.date }
        var balance = startingBankroll
        var outcomes: [Bool] = []
        for b in ordered {
            switch b.result {
            case .pending: pendingStake += b.stake; continue
            case .won: wins += 1; outcomes.append(true)
            case .lost: losses += 1; outcomes.append(false)
            case .push: break
            }
            settled += 1
            staked += b.stake
            profit += b.profit
            balance += b.profit
            curve.append(BankrollPoint(id: curve.count + 1, date: b.date, balance: balance))
        }
        if let first = ordered.first, !curve.isEmpty {
            curve.insert(BankrollPoint(id: 0, date: first.date, balance: startingBankroll), at: 0)
        }
        let s = Streaks.summarize(outcomes)
        currentStreak = s.current
        longestWinStreak = s.longestHit
        longestLosingStreak = s.longestMiss
    }
}
