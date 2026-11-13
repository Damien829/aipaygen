import XCTest
@testable import EdgeCore

final class LiveDataTests: XCTestCase {
    /// Four events trimmed from a real scoreboard response.
    static let scoreboard = #"""
{
 "events": [
  {
   "id": "401909966",
   "date": "2026-11-12T00:00Z",
   "season": {
    "year": 2027,
    "type": 2,
    "slug": "regular-season"
   },
   "status": {
    "type": {
     "completed": true,
     "name": "STATUS_FINAL"
    }
   },
   "competitions": [
    {
     "competitors": [
      {
       "homeAway": "home",
       "score": "114",
       "team": {
        "displayName": "Indiana Pacers"
       }
      },
      {
       "homeAway": "away",
       "score": "101",
       "team": {
        "displayName": "Washington Wizards"
       }
      }
     ]
    }
   ]
  },
  {
   "id": "401909967",
   "date": "2026-11-12T00:00Z",
   "season": {
    "year": 2027,
    "type": 2,
    "slug": "regular-season"
   },
   "status": {
    "type": {
     "completed": true,
     "name": "STATUS_FINAL"
    }
   },
   "competitions": [
    {
     "competitors": [
      {
       "homeAway": "home",
       "score": "107",
       "team": {
        "displayName": "New York Knicks"
       }
      },
      {
       "homeAway": "away",
       "score": "115",
       "team": {
        "displayName": "Cleveland Cavaliers"
       }
      }
     ]
    }
   ]
  },
  {
   "id": "401909968",
   "date": "2026-11-12T00:00Z",
   "season": {
    "year": 2027,
    "type": 2,
    "slug": "regular-season"
   },
   "status": {
    "type": {
     "completed": true,
     "name": "STATUS_FINAL"
    }
   },
   "competitions": [
    {
     "competitors": [
      {
       "homeAway": "home",
       "score": "93",
       "team": {
        "displayName": "Toronto Raptors"
       }
      },
      {
       "homeAway": "away",
       "score": "98",
       "team": {
        "displayName": "Boston Celtics"
       }
      }
     ]
    }
   ]
  },
  {
   "id": "401909969",
   "date": "2026-11-12T01:00Z",
   "season": {
    "year": 2027,
    "type": 2,
    "slug": "regular-season"
   },
   "status": {
    "type": {
     "completed": true,
     "name": "STATUS_FINAL"
    }
   },
   "competitions": [
    {
     "competitors": [
      {
       "homeAway": "home",
       "score": "119",
       "team": {
        "displayName": "Chicago Bulls"
       }
      },
      {
       "homeAway": "away",
       "score": "124",
       "team": {
        "displayName": "San Antonio Spurs"
       }
      }
     ]
    }
   ]
  }
 ]
}
"""#

    /// Shaped like the odds service's documented v4 response.
    static let odds = #"""
[
 {"id":"evt1","sport_key":"basketball_nba","commence_time":"2026-11-14T00:10:00Z","home_team":"Los Angeles Clippers","away_team":"Boston Celtics",
  "bookmakers":[
   {"key":"a","title":"Book A","markets":[
     {"key":"h2h","outcomes":[{"name":"Los Angeles Clippers","price":150},{"name":"Boston Celtics","price":-180}]},
     {"key":"spreads","outcomes":[{"name":"Los Angeles Clippers","price":-110,"point":4.5},{"name":"Boston Celtics","price":-110,"point":-4.5}]},
     {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":221.5},{"name":"Under","price":-110,"point":221.5}]}]},
   {"key":"b","title":"Book B","markets":[
     {"key":"h2h","outcomes":[{"name":"Boston Celtics","price":-170},{"name":"Los Angeles Clippers","price":145}]},
     {"key":"spreads","outcomes":[{"name":"Los Angeles Clippers","price":-108,"point":4},{"name":"Boston Celtics","price":-112,"point":-4}]}]}]},
 {"id":"evt2","sport_key":"basketball_nba","commence_time":"2026-11-12T00:10:00Z","home_team":"Indiana Pacers","away_team":"Washington Wizards",
  "bookmakers":[{"key":"a","title":"Book A","markets":[{"key":"h2h","outcomes":[{"name":"Indiana Pacers","price":-200},{"name":"Washington Wizards","price":170}]}]}]},
 {"id":"evt3","sport_key":"basketball_nba","commence_time":"2026-11-15T00:10:00Z","home_team":"Utah Jazz","away_team":"Miami Heat","bookmakers":[]}
]
"""#

    func testScoreboardParsing() throws {
        let records = try ScoresFeed.parse(Data(Self.scoreboard.utf8))
        XCTAssertEqual(records.count, 4)
        let g = records[0].game
        XCTAssertEqual(g.home, "Indiana Pacers")
        XCTAssertEqual(g.away, "Washington Wizards")
        XCTAssertEqual(g.homeScore, 114)
        XCTAssertEqual(g.awayScore, 101)
        XCTAssertEqual(g.date, ISO8601DateFormatter().date(from: "2026-11-12T00:00:00Z"))
        // Duplicates across overlapping months collapse.
        XCTAssertEqual(ScoresFeed.currentSeason(records + records).count, 4)
        XCTAssertThrowsError(try ScoresFeed.parse(Data("{".utf8)))
        XCTAssertEqual(try ScoresFeed.parse(Data("{}".utf8)).count, 0)
    }

    func testMonths() {
        let d = ISO8601DateFormatter().date(from: "2026-02-10T12:00:00Z")!
        XCTAssertEqual(ScoresFeed.months(endingAt: d, count: 3), ["202512", "202601", "202602"])
    }

    func testOddsParsing() throws {
        let now = ISO8601DateFormatter().date(from: "2026-11-13T00:00:00Z")!
        let slate = try OddsFeed.parse(Data(Self.odds.utf8), now: now, knownTeams: ["LA Clippers", "Boston Celtics"])
        // The started game and the one with no prices are dropped.
        XCTAssertEqual(slate.count, 1)
        let g = slate[0]
        XCTAssertEqual(g.home, "LA Clippers")
        XCTAssertEqual(g.homeOdds, 150)
        XCTAssertEqual(g.homeBook, "Book A")
        XCTAssertEqual(g.awayOdds, -170)
        XCTAssertEqual(g.awayBook, "Book B")
        XCTAssertEqual(g.spread, 4.25)
        XCTAssertEqual(g.total, 221.5)
        XCTAssertEqual(g.bookCount, 2)
        let expected = (Odds.noVig(150, -180).a + Odds.noVig(145, -170).a) / 2
        XCTAssertEqual(g.marketHome ?? 0, expected, accuracy: 1e-12)

        let refusal = Data(#"{"message":"API key is not valid.","error_code":"INVALID_KEY"}"#.utf8)
        XCTAssertThrowsError(try OddsFeed.parse(refusal)) {
            XCTAssertEqual(($0 as? LiveDataError)?.message, "API key is not valid.")
        }
    }

    func testTeamNameMatching() {
        let known = ["LA Clippers", "Los Angeles Lakers", "Montreal Canadiens", "St. Louis Blues", "Athletics", "New York Jets", "New York Giants"]
        XCTAssertEqual(TeamNames.match("Los Angeles Clippers", in: known), "LA Clippers")
        XCTAssertEqual(TeamNames.match("Los Angeles Lakers", in: known), "Los Angeles Lakers")
        XCTAssertEqual(TeamNames.match("Montréal Canadiens", in: known), "Montreal Canadiens")
        XCTAssertEqual(TeamNames.match("St Louis Blues", in: known), "St. Louis Blues")
        XCTAssertEqual(TeamNames.match("Oakland Athletics", in: known), "Athletics")
        XCTAssertEqual(TeamNames.match("Seattle Kraken", in: known), "Seattle Kraken")
    }

    func testLinesAttachToResultsAndPicksUseConsensus() {
        let d = Date(timeIntervalSince1970: 1_000_000)
        let line = SlateGame(date: d, home: "A", away: "B", homeOdds: -120, awayOdds: 110, spread: -1.5, total: 210,
                             marketHome: 0.6)
        let games = [Game(date: d.addingTimeInterval(600), home: "A", away: "B", homeScore: 100, awayScore: 90),
                     Game(date: d.addingTimeInterval(86_400 * 3), home: "A", away: "B", homeScore: 100, awayScore: 90)]
        let out = ScoresFeed.attachLines(to: games, from: [line])
        XCTAssertEqual(out[0].spread, -1.5)
        XCTAssertEqual(out[0].total, 210)
        XCTAssertNil(out[1].spread)

        let picks = Picks.evaluate(slate: [line], model: LeagueModel(games: games), games: games)
        XCTAssertEqual(picks.first { $0.isHome }?.marketProbability ?? 0, 0.6, accuracy: 1e-12)
        XCTAssertTrue(picks.allSatisfy(\.hasHistory))
        let unknown = SlateGame(date: d, home: "A", away: "Z", homeOdds: -120, awayOdds: 110)
        XCTAssertFalse(Picks.evaluate(slate: [unknown], model: LeagueModel(games: games), games: games)[0].hasHistory)
    }
}
