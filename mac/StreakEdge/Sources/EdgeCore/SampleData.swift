import Foundation

/// Deterministic generator so sample data is identical on every launch.
struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { state = seed }
    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
    mutating func gaussian() -> Double {
        let u1 = Double.random(in: Double.leastNonzeroMagnitude..<1, using: &self)
        let u2 = Double.random(in: 0..<1, using: &self)
        return (-2 * log(u1)).squareRoot() * cos(2 * .pi * u2)
    }
}

/// A made-up league for trying the app. Teams, scores and odds are simulated, not real.
public enum SampleData {
    public static let teamNames = ["Anchors", "Blaze", "Comets", "Drifters", "Embers", "Falcons",
                                   "Glaciers", "Harriers", "Ironsides", "Jackals", "Kestrels", "Lanterns"]

    public static func make(asOf now: Date = Date()) -> (games: [Game], slate: [SlateGame]) {
        var rng = SeededGenerator(seed: 20261113)
        let strength = Dictionary(uniqueKeysWithValues: teamNames.map { ($0, rng.gaussian() * 90) })
        let day = 86_400.0
        let start = Calendar(identifier: .gregorian).startOfDay(for: now).addingTimeInterval(-100 * day)

        func trueMargin(_ home: String, _ away: String) -> Double {
            (strength[home]! - strength[away]! + 60) / 28
        }
        func halfPoint(_ x: Double) -> Double { (x * 2).rounded() / 2 }

        var pairs: [(String, String)] = []
        for round in 0..<3 {
            for i in teamNames.indices {
                for j in teamNames.indices where i < j {
                    pairs.append((i + j + round) % 2 == 0 ? (teamNames[i], teamNames[j]) : (teamNames[j], teamNames[i]))
                }
            }
        }
        pairs.shuffle(using: &rng)

        var games: [Game] = []
        for (n, pair) in pairs.enumerated() {
            let mu = trueMargin(pair.0, pair.1)
            var margin = Int((mu + rng.gaussian() * 11).rounded())
            if margin == 0 { margin = rng.next() % 2 == 0 ? 1 : -1 }
            let points = max(160, Int((218 + rng.gaussian() * 15).rounded()))
            let homeScore = (points + margin + 1) / 2
            games.append(Game(date: start.addingTimeInterval(Double(n) * day * 98 / Double(pairs.count)),
                              home: pair.0, away: pair.1,
                              homeScore: homeScore, awayScore: homeScore - margin,
                              spread: -halfPoint(mu + rng.gaussian() * 1.2),
                              total: halfPoint(218 + rng.gaussian() * 3)))
        }

        var slate: [SlateGame] = []
        let order = teamNames.shuffled(using: &rng)
        for i in stride(from: 0, to: order.count - 1, by: 2) {
            let home = order[i], away = order[i + 1]
            let mu = trueMargin(home, away)
            // Bookmaker's price: the true chance, nudged a little, with about 4.5% margin added.
            let p = min(0.93, max(0.07, Stats.normalCDF(mu / 11) + rng.gaussian() * 0.035))
            slate.append(SlateGame(date: now.addingTimeInterval(Double(1 + i / 4) * day),
                                   home: home, away: away,
                                   homeOdds: Odds.american(fromDecimal: 1 / (p * 1.045)),
                                   awayOdds: Odds.american(fromDecimal: 1 / ((1 - p) * 1.045)),
                                   spread: -halfPoint(mu), total: 218.5))
        }
        return (games, slate)
    }
}
