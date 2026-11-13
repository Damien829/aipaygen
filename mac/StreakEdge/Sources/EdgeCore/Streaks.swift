import Foundation

public enum StreakKind: String, CaseIterable, Identifiable, Codable, Sendable {
    case win = "Win / Loss"
    case ats = "Against the Spread"
    case over = "Over / Under"
    public var id: String { rawValue }

    /// Labels for the positive and negative outcome.
    public var letters: (hit: String, miss: String) {
        switch self {
        case .win: return ("W", "L")
        case .ats: return ("C", "N")
        case .over: return ("O", "U")
        }
    }
}

public struct StreakSummary: Sendable, Equatable {
    public var games = 0
    public var hits = 0
    /// Signed: +4 is four hits in a row, -2 is two misses in a row.
    public var current = 0
    public var longestHit = 0
    public var longestMiss = 0
    public var last10Hits = 0
    public var last10Games = 0
    /// Wald–Wolfowitz runs test. Below about -2 the sequence is streakier than chance; near 0 it looks random.
    public var runsZ: Double?

    public var rate: Double { games == 0 ? 0 : Double(hits) / Double(games) }
    public var misses: Int { games - hits }
}

public enum Streaks {
    /// Chronological outcomes for one team. Pushes and games without a line are dropped,
    /// so they neither extend nor break a streak.
    public static func outcomes(team: String, games: [Game], kind: StreakKind) -> [Bool] {
        games.filter { $0.home == team || $0.away == team }
            .sorted { $0.date < $1.date }
            .compactMap { g -> Bool? in
                let isHome = g.home == team
                switch kind {
                case .win:
                    if g.margin == 0 { return nil }
                    return (g.margin > 0) == isHome
                case .ats:
                    guard let s = g.spread else { return nil }
                    let adj = Double(g.margin) + s
                    if adj == 0 { return nil }
                    return (adj > 0) == isHome
                case .over:
                    guard let t = g.total else { return nil }
                    let diff = Double(g.points) - t
                    return diff == 0 ? nil : diff > 0
                }
            }
    }

    public static func summarize(_ seq: [Bool]) -> StreakSummary {
        var s = StreakSummary()
        s.games = seq.count
        s.hits = seq.filter { $0 }.count
        var run = 0, runs = 0
        var previous: Bool?
        for o in seq {
            if o == previous { run += 1 } else { run = 1; runs += 1 }
            previous = o
            if o { s.longestHit = max(s.longestHit, run) } else { s.longestMiss = max(s.longestMiss, run) }
        }
        if let last = previous { s.current = last ? run : -run }
        let tail = seq.suffix(10)
        s.last10Games = tail.count
        s.last10Hits = tail.filter { $0 }.count

        let n1 = Double(s.hits), n2 = Double(s.misses), n = n1 + n2
        if n1 > 0, n2 > 0, n > 2 {
            let mu = 2 * n1 * n2 / n + 1
            let variance = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n * n * (n - 1))
            if variance > 0 { s.runsZ = (Double(runs) - mu) / variance.squareRoot() }
        }
        return s
    }

    /// Probability of at least one run of `length` or more hits in `trials` independent games.
    public static func probabilityOfRun(length k: Int, trials n: Int, p: Double) -> Double {
        guard k > 0 else { return 1 }
        guard n >= k, p > 0 else { return 0 }
        // state[j] = probability of currently being on a run of j hits without having reached k.
        var state = [Double](repeating: 0, count: k)
        state[0] = 1
        var reached = 0.0
        for _ in 0..<n {
            var next = [Double](repeating: 0, count: k)
            for j in 0..<k where state[j] > 0 {
                next[0] += state[j] * (1 - p)
                if j + 1 == k { reached += state[j] * p } else { next[j + 1] += state[j] * p }
            }
            state = next
        }
        return reached
    }

    /// Probability the next `k` games all hit, given per-game probabilities.
    public static func probabilityOfExtending(by k: Int, p: Double) -> Double { pow(p, Double(k)) }

    /// Expected number of further hits before the first miss.
    public static func expectedExtension(p: Double) -> Double { p >= 1 ? .infinity : p / (1 - p) }
}
