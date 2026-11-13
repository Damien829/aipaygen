import EdgeCore
import Foundation
import Security

/// Keeps the odds API key in the login keychain rather than in the app's data file.
enum KeyStore {
    private static let base: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "local.streakedge",
        kSecAttrAccount as String: "odds-api-key",
    ]

    static func read() -> String {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return "" }
        return String(decoding: data, as: UTF8.self)
    }

    static func save(_ value: String) {
        SecItemDelete(base as CFDictionary)
        guard !value.isEmpty else { return }
        var item = base
        item[kSecValueData as String] = Data(value.utf8)
        SecItemAdd(item as CFDictionary, nil)
    }
}

enum LiveService {
    private static func get(_ url: URL) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw LiveDataError("No response from the server.") }
        return (data, http)
    }

    /// This season's finished games, gathered a month at a time.
    static func results(league: League) async throws -> [Game] {
        let months = ScoresFeed.months(endingAt: Date(), count: 12)
        let records = try await withThrowingTaskGroup(of: [ScoreRecord].self) { group in
            for month in months {
                group.addTask {
                    let (data, http) = try await get(ScoresFeed.url(league: league, month: month))
                    // A month with nothing scheduled can come back as an error; treat it as empty.
                    guard http.statusCode == 200 else { return [] }
                    return try ScoresFeed.parse(data)
                }
            }
            var all: [ScoreRecord] = []
            for try await part in group { all += part }
            return all
        }
        return ScoresFeed.currentSeason(records)
    }

    /// Upcoming games with prices, and how many requests the key has left this month.
    static func odds(league: League, apiKey: String, knownTeams: [String]) async throws -> (slate: [SlateGame], remaining: Int?) {
        let (data, http) = try await get(OddsFeed.url(league: league, apiKey: apiKey))
        guard http.statusCode == 200 else {
            throw LiveDataError(OddsFeed.failureMessage(data) ?? "The odds service refused the request (\(http.statusCode)).")
        }
        let remaining = http.value(forHTTPHeaderField: "x-requests-remaining").flatMap { Int($0) }
        return (try OddsFeed.parse(data, knownTeams: knownTeams), remaining)
    }
}
