import Foundation

/// A completed game. `spread` is the closing home line (e.g. -3.5 means home favored by 3.5).
public struct Game: Codable, Identifiable, Hashable, Sendable {
    public var id: UUID
    public var date: Date
    public var home: String
    public var away: String
    public var homeScore: Int
    public var awayScore: Int
    public var spread: Double?
    public var total: Double?

    public init(id: UUID = UUID(), date: Date, home: String, away: String,
                homeScore: Int, awayScore: Int, spread: Double? = nil, total: Double? = nil) {
        self.id = id; self.date = date; self.home = home; self.away = away
        self.homeScore = homeScore; self.awayScore = awayScore
        self.spread = spread; self.total = total
    }

    public var margin: Int { homeScore - awayScore }
    public var points: Int { homeScore + awayScore }
}

/// An upcoming game with moneyline prices (American odds).
/// From the live feed, each side's price is the best one on offer and the `…Book` fields say where.
public struct SlateGame: Codable, Identifiable, Hashable, Sendable {
    public var id: UUID
    public var date: Date
    public var home: String
    public var away: String
    public var homeOdds: Int
    public var awayOdds: Int
    public var spread: Double?
    public var total: Double?
    public var homeBook: String?
    public var awayBook: String?
    /// Home win probability averaged over every bookmaker, margin removed.
    public var marketHome: Double?
    public var bookCount: Int?
    /// The feed's own event id, so a refresh updates a game instead of duplicating it.
    public var sourceID: String?

    public init(id: UUID = UUID(), date: Date, home: String, away: String,
                homeOdds: Int, awayOdds: Int, spread: Double? = nil, total: Double? = nil,
                homeBook: String? = nil, awayBook: String? = nil, marketHome: Double? = nil,
                bookCount: Int? = nil, sourceID: String? = nil) {
        self.id = id; self.date = date; self.home = home; self.away = away
        self.homeOdds = homeOdds; self.awayOdds = awayOdds
        self.spread = spread; self.total = total
        self.homeBook = homeBook; self.awayBook = awayBook
        self.marketHome = marketHome; self.bookCount = bookCount; self.sourceID = sourceID
    }
}

public enum BetResult: String, Codable, CaseIterable, Sendable {
    case pending, won, lost, push
}

public struct Bet: Codable, Identifiable, Hashable, Sendable {
    public var id: UUID
    public var date: Date
    public var label: String
    public var odds: Int
    public var stake: Double
    public var result: BetResult

    public init(id: UUID = UUID(), date: Date, label: String, odds: Int, stake: Double,
                result: BetResult = .pending) {
        self.id = id; self.date = date; self.label = label
        self.odds = odds; self.stake = stake; self.result = result
    }

    /// Net profit for a settled bet; 0 while pending or on a push.
    public var profit: Double {
        switch result {
        case .won: return stake * (Odds.decimal(fromAmerican: odds) - 1)
        case .lost: return -stake
        case .pending, .push: return 0
        }
    }
}
