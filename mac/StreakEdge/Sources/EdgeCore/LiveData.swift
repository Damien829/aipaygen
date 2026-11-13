import Foundation

public enum League: String, CaseIterable, Identifiable, Codable, Sendable {
    case nba, nfl, nhl, mlb
    public var id: String { rawValue }
    public var title: String { rawValue.uppercased() }

    var scoresPath: String {
        switch self {
        case .nba: return "basketball/nba"
        case .nfl: return "football/nfl"
        case .nhl: return "hockey/nhl"
        case .mlb: return "baseball/mlb"
        }
    }

    var oddsKey: String {
        switch self {
        case .nba: return "basketball_nba"
        case .nfl: return "americanfootball_nfl"
        case .nhl: return "icehockey_nhl"
        case .mlb: return "baseball_mlb"
        }
    }
}

public struct LiveDataError: Error, LocalizedError, Sendable {
    public var message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

// MARK: - Results (ESPN's public scoreboard; no key needed, but it is not an official API)

public struct ScoreRecord: Sendable {
    public var eventID: String
    public var season: Int
    public var game: Game
}

public enum ScoresFeed {
    /// The scoreboard takes a whole month as `yyyyMM`. Returns the last `count` months, newest last.
    public static func months(endingAt date: Date, count: Int) -> [String] {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        return (0..<count).reversed().compactMap { back in
            guard let d = cal.date(byAdding: .month, value: -back, to: date) else { return nil }
            let c = cal.dateComponents([.year, .month], from: d)
            return String(format: "%04d%02d", c.year ?? 0, c.month ?? 0)
        }
    }

    public static func url(league: League, month: String) -> URL {
        URL(string: "https://site.api.espn.com/apis/site/v2/sports/\(league.scoresPath)/scoreboard?dates=\(month)&limit=1000")!
    }

    private struct Board: Decodable {
        struct Event: Decodable {
            struct Season: Decodable { var year: Int; var type: Int }
            struct Status: Decodable { struct Kind: Decodable { var completed: Bool }; var type: Kind }
            struct Competition: Decodable {
                struct Competitor: Decodable {
                    struct Team: Decodable { var displayName: String }
                    var homeAway: String
                    var score: String?
                    var team: Team
                }
                var competitors: [Competitor]
            }
            var id: String
            var date: String
            var season: Season
            var status: Status
            var competitions: [Competition]
        }
        var events: [Event]?
    }

    /// Finished regular-season and playoff games in one scoreboard response.
    public static func parse(_ data: Data) throws -> [ScoreRecord] {
        let board: Board
        do { board = try JSONDecoder().decode(Board.self, from: data) } catch {
            throw LiveDataError("The scores service sent something unexpected.")
        }
        return (board.events ?? []).compactMap { e in
            // Season type 1 is preseason: those results say little about real strength.
            guard e.status.type.completed, e.season.type != 1,
                  let teams = e.competitions.first?.competitors,
                  let home = teams.first(where: { $0.homeAway == "home" }),
                  let away = teams.first(where: { $0.homeAway == "away" }),
                  let hs = home.score.flatMap(Int.init), let aw = away.score.flatMap(Int.init),
                  let date = parseDate(e.date)
            else { return nil }
            return ScoreRecord(eventID: e.id, season: e.season.year,
                               game: Game(date: date, home: home.team.displayName, away: away.team.displayName,
                                          homeScore: hs, awayScore: aw))
        }
    }

    /// Drops duplicates and keeps only the most recent season, so streaks do not run across an off-season.
    public static func currentSeason(_ records: [ScoreRecord]) -> [Game] {
        guard let latest = records.max(by: { $0.game.date < $1.game.date })?.season else { return [] }
        var seen = Set<String>()
        return records.filter { $0.season == latest && seen.insert($0.eventID).inserted }
            .map(\.game)
            .sorted { $0.date < $1.date }
    }

    static func parseDate(_ s: String) -> Date? {
        for format in ["yyyy-MM-dd'T'HH:mm'Z'", "yyyy-MM-dd'T'HH:mm:ss'Z'"] {
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = TimeZone(identifier: "UTC")
            f.dateFormat = format
            if let d = f.date(from: s) { return d }
        }
        return nil
    }

    /// Copies the spread and total from saved pre-game lines onto finished games that lack them,
    /// which is how spread and total streaks build up over time with live data.
    public static func attachLines(to games: [Game], from archive: [SlateGame]) -> [Game] {
        guard !archive.isEmpty else { return games }
        let byTeams = Dictionary(grouping: archive) { "\($0.home)|\($0.away)" }
        return games.map { g in
            guard g.spread == nil || g.total == nil,
                  let line = byTeams["\(g.home)|\(g.away)"]?
                      .first(where: { abs($0.date.timeIntervalSince(g.date)) < 18 * 3600 })
            else { return g }
            var out = g
            out.spread = g.spread ?? line.spread
            out.total = g.total ?? line.total
            return out
        }
    }
}

// MARK: - Odds (the-odds-api.com v4; needs the user's own API key)

public enum OddsFeed {
    public static func url(league: League, apiKey: String) -> URL {
        var c = URLComponents(string: "https://api.the-odds-api.com/v4/sports/\(league.oddsKey)/odds")!
        c.queryItems = [
            URLQueryItem(name: "apiKey", value: apiKey),
            URLQueryItem(name: "regions", value: "us"),
            URLQueryItem(name: "markets", value: "h2h,spreads,totals"),
            URLQueryItem(name: "oddsFormat", value: "american"),
        ]
        return c.url!
    }

    private struct Event: Decodable {
        struct Bookmaker: Decodable {
            struct Market: Decodable {
                struct Outcome: Decodable { var name: String; var price: Double; var point: Double? }
                var key: String
                var outcomes: [Outcome]
            }
            var title: String
            var markets: [Market]
        }
        var id: String
        var commence_time: String
        var home_team: String
        var away_team: String
        var bookmakers: [Bookmaker]
    }

    private struct Failure: Decodable { var message: String }

    /// The message the service sends when it refuses a request (bad key, quota used up).
    public static func failureMessage(_ data: Data) -> String? {
        (try? JSONDecoder().decode(Failure.self, from: data))?.message
    }

    /// Games that have not started yet. Team names are matched to `knownTeams` so they line up with results.
    public static func parse(_ data: Data, now: Date = Date(), knownTeams: [String] = []) throws -> [SlateGame] {
        let events: [Event]
        do { events = try JSONDecoder().decode([Event].self, from: data) } catch {
            throw LiveDataError(failureMessage(data) ?? "The odds service sent something unexpected.")
        }
        let iso = ISO8601DateFormatter()
        return events.compactMap { e -> SlateGame? in
            guard let date = iso.date(from: e.commence_time), date > now else { return nil }
            var best: (home: Int, homeBook: String, away: Int, awayBook: String)?
            var fair: [Double] = [], spreads: [Double] = [], totals: [Double] = []

            for book in e.bookmakers {
                for market in book.markets {
                    switch market.key {
                    case "h2h":
                        guard market.outcomes.count == 2,
                              let h = market.outcomes.first(where: { $0.name == e.home_team }),
                              let a = market.outcomes.first(where: { $0.name == e.away_team })
                        else { continue }
                        let hp = Int(h.price.rounded()), ap = Int(a.price.rounded())
                        guard abs(hp) >= 100, abs(ap) >= 100 else { continue }
                        fair.append(Odds.noVig(hp, ap).a)
                        if let b = best {
                            best = (hp > b.home ? hp : b.home, hp > b.home ? book.title : b.homeBook,
                                    ap > b.away ? ap : b.away, ap > b.away ? book.title : b.awayBook)
                        } else {
                            best = (hp, book.title, ap, book.title)
                        }
                    case "spreads":
                        if let p = market.outcomes.first(where: { $0.name == e.home_team })?.point { spreads.append(p) }
                    case "totals":
                        if let p = market.outcomes.first(where: { $0.name == "Over" })?.point { totals.append(p) }
                    default: break
                    }
                }
            }
            guard let best else { return nil }
            return SlateGame(date: date,
                             home: TeamNames.match(e.home_team, in: knownTeams),
                             away: TeamNames.match(e.away_team, in: knownTeams),
                             homeOdds: best.home, awayOdds: best.away,
                             spread: median(spreads), total: median(totals),
                             homeBook: best.homeBook, awayBook: best.awayBook,
                             marketHome: Stats.mean(fair), bookCount: fair.count, sourceID: e.id)
        }
        .sorted { $0.date < $1.date }
    }

    static func median(_ xs: [Double]) -> Double? {
        guard !xs.isEmpty else { return nil }
        let s = xs.sorted()
        return s.count % 2 == 1 ? s[s.count / 2] : (s[s.count / 2 - 1] + s[s.count / 2]) / 2
    }
}

/// The two services spell a few teams differently ("LA Clippers" / "Los Angeles Clippers",
/// "Montreal" / "Montréal", "St." / "St").
public enum TeamNames {
    static func key(_ name: String) -> String {
        let spelled = name.hasPrefix("LA ") ? "Los Angeles " + name.dropFirst(3) : name
        let k = spelled.folding(options: .diacriticInsensitive, locale: Locale(identifier: "en_US"))
            .lowercased().filter { $0.isLetter || $0.isNumber }
        return k
    }

    /// The known team this name refers to, or the name unchanged when nothing matches.
    public static func match(_ name: String, in known: [String]) -> String {
        if known.contains(name) { return name }
        let k = key(name)
        if let hit = known.first(where: { key($0) == k }) { return hit }
        // Fall back to the nickname when exactly one known team shares it ("Oakland Athletics" / "Athletics").
        guard let nick = name.split(separator: " ").last.map({ key(String($0)) }), nick.count > 3 else { return name }
        let hits = known.filter { key($0).hasSuffix(nick) }
        return hits.count == 1 ? hits[0] : name
    }
}
