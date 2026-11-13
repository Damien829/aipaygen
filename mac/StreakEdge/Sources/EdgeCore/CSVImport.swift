import Foundation

public struct CSVImportResult: Sendable {
    public var games: [Game] = []
    public var skipped: [String] = []
}

/// Reads results from CSV. Required columns: date, home, away, home_score, away_score.
/// Optional: spread (home line) and total. Header names are matched loosely.
public enum CSVImport {
    public static let template = "date,home,away,home_score,away_score,spread,total\n2026-01-15,Home Team,Away Team,108,101,-3.5,221.5\n"

    private static let aliases: [String: [String]] = [
        "date": ["date", "gamedate", "day"],
        "home": ["home", "hometeam", "teamhome"],
        "away": ["away", "awayteam", "visitor", "visitorteam", "road"],
        "homeScore": ["homescore", "homepts", "homepoints", "hs", "homegoals"],
        "awayScore": ["awayscore", "awaypts", "awaypoints", "as", "awaygoals", "visitorscore", "visitorpts"],
        "spread": ["spread", "homespread", "line", "homeline"],
        "total": ["total", "ou", "overunder", "totalline"],
    ]

    public static func parse(_ text: String) -> CSVImportResult {
        var result = CSVImportResult()
        let lines = text.split(whereSeparator: \.isNewline).map(String.init)
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        guard let header = lines.first else {
            result.skipped.append("File is empty")
            return result
        }
        let names = fields(header).map {
            $0.lowercased().filter { $0.isLetter || $0.isNumber }
        }
        var column: [String: Int] = [:]
        for (key, options) in aliases {
            if let i = names.firstIndex(where: { options.contains($0) }) { column[key] = i }
        }
        let required = ["date", "home", "away", "homeScore", "awayScore"]
        let missing = required.filter { column[$0] == nil }
        guard missing.isEmpty else {
            result.skipped.append("Missing columns: \(missing.joined(separator: ", "))")
            return result
        }

        for (n, line) in lines.dropFirst().enumerated() {
            let f = fields(line)
            func value(_ key: String) -> String? {
                guard let i = column[key], i < f.count else { return nil }
                let v = f[i].trimmingCharacters(in: .whitespaces)
                return v.isEmpty ? nil : v
            }
            guard let d = value("date").flatMap(date), let home = value("home"), let away = value("away"),
                  let hs = value("homeScore").flatMap(Int.init), let aw = value("awayScore").flatMap(Int.init)
            else {
                result.skipped.append("Row \(n + 2): could not read date, teams or scores")
                continue
            }
            result.games.append(Game(date: d, home: home, away: away, homeScore: hs, awayScore: aw,
                                     spread: value("spread").flatMap(Double.init),
                                     total: value("total").flatMap(Double.init)))
        }
        return result
    }

    /// Splits one CSV line, honouring double-quoted fields.
    static func fields(_ line: String) -> [String] {
        var out: [String] = [], current = "", quoted = false
        var chars = line.makeIterator()
        var pending = chars.next()
        while let c = pending {
            pending = chars.next()
            if quoted {
                if c == "\"" {
                    if pending == "\"" { current.append("\""); pending = chars.next() } else { quoted = false }
                } else { current.append(c) }
            } else if c == "\"" { quoted = true }
            else if c == "," { out.append(current); current = "" }
            else { current.append(c) }
        }
        out.append(current)
        return out
    }

    static func date(_ s: String) -> Date? {
        for format in ["yyyy-MM-dd", "MM/dd/yyyy", "M/d/yyyy", "yyyy/MM/dd", "yyyy-MM-dd'T'HH:mm:ssZ"] {
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = TimeZone(identifier: "UTC")
            f.dateFormat = format
            if let d = f.date(from: s) { return d }
        }
        return nil
    }
}
