import Foundation

/// Odds conversion and bet-sizing math. "Decimal" odds include the returned stake (2.0 = even money).
public enum Odds {
    public static func decimal(fromAmerican a: Int) -> Double {
        a >= 0 ? 1 + Double(a) / 100 : 1 + 100 / Double(-a)
    }

    public static func american(fromDecimal d: Double) -> Int {
        guard d > 1 else { return 0 }
        return d >= 2 ? Int(((d - 1) * 100).rounded()) : Int((-100 / (d - 1)).rounded())
    }

    /// Break-even probability of a price, bookmaker margin included.
    public static func impliedProbability(american a: Int) -> Double {
        1 / decimal(fromAmerican: a)
    }

    /// Fair price for a probability, as American odds.
    public static func fairAmerican(probability p: Double) -> Int {
        guard p > 0, p < 1 else { return 0 }
        return american(fromDecimal: 1 / p)
    }

    /// Strips the bookmaker margin from a two-way market by normalising the implied probabilities.
    public static func noVig(_ a: Int, _ b: Int) -> (a: Double, b: Double, hold: Double) {
        let pa = impliedProbability(american: a), pb = impliedProbability(american: b)
        let sum = pa + pb
        return (pa / sum, pb / sum, sum - 1)
    }

    /// Expected profit per 1 unit staked.
    public static func expectedValue(probability p: Double, american a: Int) -> Double {
        let d = decimal(fromAmerican: a)
        return p * (d - 1) - (1 - p)
    }

    /// Kelly fraction of bankroll; 0 when the bet has no edge.
    public static func kelly(probability p: Double, american a: Int) -> Double {
        let b = decimal(fromAmerican: a) - 1
        guard b > 0 else { return 0 }
        return max(0, (p * (b + 1) - 1) / b)
    }

    public static func parlayDecimal(_ legs: [Int]) -> Double {
        legs.reduce(1) { $0 * decimal(fromAmerican: $1) }
    }

    public static func format(american a: Int) -> String { a > 0 ? "+\(a)" : "\(a)" }
}

public enum Stats {
    public static func normalCDF(_ z: Double) -> Double { 0.5 * (1 + erf(z / 2.0.squareRoot())) }

    public static func mean(_ xs: [Double]) -> Double {
        xs.isEmpty ? 0 : xs.reduce(0, +) / Double(xs.count)
    }

    public static func standardDeviation(_ xs: [Double]) -> Double {
        guard xs.count > 1 else { return 0 }
        let m = mean(xs)
        return (xs.reduce(0) { $0 + ($1 - m) * ($1 - m) } / Double(xs.count - 1)).squareRoot()
    }
}
