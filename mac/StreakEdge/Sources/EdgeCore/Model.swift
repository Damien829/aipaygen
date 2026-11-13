import Foundation

public struct ModelConfig: Codable, Equatable, Sendable {
    /// How fast ratings react to a result.
    public var k: Double = 20
    /// Rating points added to the home side.
    public var homeAdvantage: Double = 60
    public init(k: Double = 20, homeAdvantage: Double = 60) {
        self.k = k; self.homeAdvantage = homeAdvantage
    }
}

public struct CalibrationBucket: Identifiable, Sendable {
    public var id: Int
    public var predicted: Double
    public var actual: Double
    public var count: Int
}

/// How the walk-forward predictions did. Every prediction used only games played before it.
public struct Calibration: Sendable {
    public var games = 0
    public var accuracy = 0.0
    /// Mean squared error of the probability; 0.25 is a coin flip, lower is better.
    public var brier = 0.25
    public var logLoss = 0.0
    public var buckets: [CalibrationBucket] = []
}

public struct TeamProfile: Identifiable, Sendable {
    public var id: String { name }
    public var name: String
    public var rating: Double
    public var games: Int
    public var wins: Int
    public var losses: Int
    public var pointsFor: Double
    public var pointsAgainst: Double
}

/// Elo ratings with a margin-of-victory multiplier, plus margin and total models fitted to the same games.
public struct LeagueModel: Sendable {
    public static let baseRating = 1500.0

    public let config: ModelConfig
    public private(set) var ratings: [String: Double] = [:]
    public private(set) var teams: [TeamProfile] = []
    public private(set) var calibration = Calibration()
    /// Points of expected margin per rating point of difference.
    public private(set) var pointsPerRating = 0.0
    public private(set) var marginSD = 0.0
    public private(set) var totalSD = 0.0
    public private(set) var leagueAverageScore = 0.0
    public private(set) var gameCount = 0

    private var profile: [String: TeamProfile] = [:]

    public init(games: [Game], config: ModelConfig = ModelConfig()) {
        self.config = config
        let sorted = games.sorted { $0.date < $1.date }
        gameCount = sorted.count

        var predictions: [(p: Double, y: Double)] = []
        var diffs: [Double] = [], margins: [Double] = []

        for g in sorted {
            let rh = ratings[g.home] ?? Self.baseRating
            let ra = ratings[g.away] ?? Self.baseRating
            let diff = rh - ra + config.homeAdvantage
            let p = Self.expected(diff)
            let y = g.margin > 0 ? 1.0 : (g.margin < 0 ? 0.0 : 0.5)

            // Skip each team's first few games when scoring the model: ratings are still uninformed.
            if (profile[g.home]?.games ?? 0) >= 5, (profile[g.away]?.games ?? 0) >= 5 {
                predictions.append((p, y))
                diffs.append(diff); margins.append(Double(g.margin))
            }

            // Bigger wins move ratings more, damped when the favourite was already expected to win big.
            let winnerDiff = g.margin >= 0 ? diff : -diff
            let mov = log(Double(abs(g.margin)) + 1) * 2.2 / (max(-800, winnerDiff) * 0.001 + 2.2)
            let delta = config.k * max(mov, 0.5) * (y - p)
            ratings[g.home] = rh + delta
            ratings[g.away] = ra - delta

            update(g.home, scored: g.homeScore, allowed: g.awayScore)
            update(g.away, scored: g.awayScore, allowed: g.homeScore)
        }

        for name in profile.keys { profile[name]?.rating = ratings[name] ?? Self.baseRating }
        teams = profile.values.sorted { $0.rating > $1.rating }

        // Least-squares slope through the origin: margin ≈ slope × rating difference.
        let sxx = diffs.reduce(0) { $0 + $1 * $1 }
        let sxy = zip(diffs, margins).reduce(0) { $0 + $1.0 * $1.1 }
        pointsPerRating = sxx > 0 ? max(0, sxy / sxx) : 0
        let residuals = zip(diffs, margins).map { $1 - pointsPerRating * $0 }
        marginSD = Stats.standardDeviation(residuals)
        if marginSD == 0 { marginSD = Stats.standardDeviation(sorted.map { Double($0.margin) }) }

        leagueAverageScore = sorted.isEmpty ? 0 : Stats.mean(sorted.map { Double($0.points) }) / 2
        let totalErrors = sorted.map { Double($0.points) - expectedTotal(home: $0.home, away: $0.away) }
        totalSD = Stats.standardDeviation(totalErrors)

        calibration = Self.calibrate(predictions)
    }

    private mutating func update(_ team: String, scored: Int, allowed: Int) {
        var t = profile[team] ?? TeamProfile(name: team, rating: Self.baseRating, games: 0, wins: 0,
                                             losses: 0, pointsFor: 0, pointsAgainst: 0)
        let n = Double(t.games)
        t.pointsFor = (t.pointsFor * n + Double(scored)) / (n + 1)
        t.pointsAgainst = (t.pointsAgainst * n + Double(allowed)) / (n + 1)
        t.games += 1
        if scored > allowed { t.wins += 1 } else if scored < allowed { t.losses += 1 }
        profile[team] = t
    }

    static func expected(_ diff: Double) -> Double { 1 / (1 + pow(10, -diff / 400)) }

    private static func calibrate(_ preds: [(p: Double, y: Double)]) -> Calibration {
        var c = Calibration()
        c.games = preds.count
        guard !preds.isEmpty else { return c }
        let n = Double(preds.count)
        c.brier = preds.reduce(0) { $0 + ($1.p - $1.y) * ($1.p - $1.y) } / n
        c.logLoss = -preds.reduce(0) { acc, x in
            let p = min(max(x.p, 1e-9), 1 - 1e-9)
            return acc + x.y * log(p) + (1 - x.y) * log(1 - p)
        } / n
        c.accuracy = preds.filter { ($0.p >= 0.5) == ($0.y >= 0.5) }.count.double / n
        for b in 0..<10 {
            let lo = Double(b) / 10, hi = Double(b + 1) / 10
            let inside = preds.filter { $0.p >= lo && (b == 9 ? $0.p <= hi : $0.p < hi) }
            guard !inside.isEmpty else { continue }
            c.buckets.append(CalibrationBucket(id: b,
                                               predicted: Stats.mean(inside.map(\.p)),
                                               actual: Stats.mean(inside.map(\.y)),
                                               count: inside.count))
        }
        return c
    }

    // MARK: Predictions

    public func rating(_ team: String) -> Double { ratings[team] ?? Self.baseRating }
    public func team(_ name: String) -> TeamProfile? { profile[name] }

    private func ratingDiff(home: String, away: String, neutral: Bool) -> Double {
        rating(home) - rating(away) + (neutral ? 0 : config.homeAdvantage)
    }

    public func homeWinProbability(home: String, away: String, neutral: Bool = false) -> Double {
        Self.expected(ratingDiff(home: home, away: away, neutral: neutral))
    }

    /// Win probability against a league-average opponent, averaging home and away.
    public func baselineWinProbability(_ team: String) -> Double {
        let d = rating(team) - Self.baseRating
        return (Self.expected(d + config.homeAdvantage) + Self.expected(d - config.homeAdvantage)) / 2
    }

    public func expectedMargin(home: String, away: String, neutral: Bool = false) -> Double {
        pointsPerRating * ratingDiff(home: home, away: away, neutral: neutral)
    }

    /// Probability the home side covers `spread` (home line, e.g. -3.5).
    public func homeCoverProbability(home: String, away: String, spread: Double, neutral: Bool = false) -> Double? {
        guard marginSD > 0 else { return nil }
        return Stats.normalCDF((expectedMargin(home: home, away: away, neutral: neutral) + spread) / marginSD)
    }

    public func expectedTotal(home: String, away: String) -> Double {
        guard let h = profile[home], let a = profile[away] else { return leagueAverageScore * 2 }
        // Each side's scoring is its own attack blended with the opponent's defence.
        return (h.pointsFor + a.pointsAgainst) / 2 + (a.pointsFor + h.pointsAgainst) / 2
    }

    public func overProbability(home: String, away: String, total: Double) -> Double? {
        guard totalSD > 0 else { return nil }
        return Stats.normalCDF((expectedTotal(home: home, away: away) - total) / totalSD)
    }
}

private extension Int {
    var double: Double { Double(self) }
}
