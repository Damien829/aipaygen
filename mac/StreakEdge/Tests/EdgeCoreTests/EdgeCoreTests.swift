import XCTest
@testable import EdgeCore

final class EdgeCoreTests: XCTestCase {
    func testOddsConversion() {
        XCTAssertEqual(Odds.decimal(fromAmerican: -110), 1.9090909, accuracy: 1e-6)
        XCTAssertEqual(Odds.decimal(fromAmerican: 150), 2.5, accuracy: 1e-9)
        XCTAssertEqual(Odds.american(fromDecimal: 2.5), 150)
        XCTAssertEqual(Odds.american(fromDecimal: 1.5), -200)
        XCTAssertEqual(Odds.fairAmerican(probability: 0.6), -150)
        for a in [-450, -110, 100, 135, 900] {
            XCTAssertEqual(Odds.american(fromDecimal: Odds.decimal(fromAmerican: a)), a)
        }
    }

    func testNoVigAndValue() {
        let m = Odds.noVig(-110, -110)
        XCTAssertEqual(m.a, 0.5, accuracy: 1e-9)
        XCTAssertEqual(m.hold, 0.047619, accuracy: 1e-5)
        XCTAssertEqual(Odds.expectedValue(probability: 0.5, american: 100), 0, accuracy: 1e-12)
        XCTAssertEqual(Odds.expectedValue(probability: 0.55, american: -110), 0.05, accuracy: 1e-9)
        XCTAssertEqual(Odds.kelly(probability: 0.6, american: 100), 0.2, accuracy: 1e-12)
        XCTAssertEqual(Odds.kelly(probability: 0.4, american: 100), 0)
        XCTAssertEqual(Odds.parlayDecimal([100, 100, -200]), 6, accuracy: 1e-12)
    }

    func testStreakSummary() {
        let s = Streaks.summarize([true, true, false, true, true, true, false, false])
        XCTAssertEqual(s.current, -2)
        XCTAssertEqual(s.longestHit, 3)
        XCTAssertEqual(s.longestMiss, 2)
        XCTAssertEqual(s.hits, 5)
        XCTAssertEqual(Streaks.summarize([false, true, true]).current, 2)
        XCTAssertEqual(Streaks.summarize([]).current, 0)
        // Perfectly alternating results have far more runs than chance predicts.
        let alternating = Streaks.summarize((0..<20).map { $0 % 2 == 0 })
        XCTAssertGreaterThan(alternating.runsZ ?? 0, 3)
        let clumped = Streaks.summarize(Array(repeating: true, count: 10) + Array(repeating: false, count: 10))
        XCTAssertLessThan(clumped.runsZ ?? 0, -3)
    }

    func testOutcomeKinds() {
        let d = Date(timeIntervalSince1970: 0)
        let games = [
            Game(date: d, home: "A", away: "B", homeScore: 100, awayScore: 97, spread: -3.5, total: 200),
            Game(date: d.addingTimeInterval(1), home: "B", away: "A", homeScore: 90, awayScore: 95, spread: 5, total: 185),
            Game(date: d.addingTimeInterval(2), home: "A", away: "C", homeScore: 80, awayScore: 85, spread: -2, total: 150),
        ]
        XCTAssertEqual(Streaks.outcomes(team: "A", games: games, kind: .win), [true, true, false])
        // A wins by 3 laying 3.5 (no cover); A wins by 5 as a 5-point road favourite (push); A loses.
        XCTAssertEqual(Streaks.outcomes(team: "A", games: games, kind: .ats), [false, false])
        XCTAssertEqual(Streaks.outcomes(team: "B", games: games, kind: .ats), [true])
        XCTAssertEqual(Streaks.outcomes(team: "A", games: games, kind: .over), [false, true])
    }

    func testRunProbability() {
        XCTAssertEqual(Streaks.probabilityOfRun(length: 2, trials: 2, p: 0.5), 0.25, accuracy: 1e-12)
        XCTAssertEqual(Streaks.probabilityOfRun(length: 2, trials: 3, p: 0.5), 0.375, accuracy: 1e-12)
        XCTAssertEqual(Streaks.probabilityOfRun(length: 1, trials: 4, p: 0.5), 1 - 0.0625, accuracy: 1e-12)
        XCTAssertEqual(Streaks.probabilityOfRun(length: 5, trials: 4, p: 0.9), 0)
        XCTAssertEqual(Streaks.probabilityOfExtending(by: 3, p: 0.5), 0.125, accuracy: 1e-12)
        XCTAssertEqual(Streaks.expectedExtension(p: 0.75), 3, accuracy: 1e-12)
    }

    func testModelLearnsFromSampleLeague() {
        let data = SampleData.make(asOf: Date(timeIntervalSince1970: 1_800_000_000))
        XCTAssertEqual(data.games.count, 198)
        XCTAssertEqual(data.slate.count, 6)
        let model = LeagueModel(games: data.games)
        XCTAssertEqual(model.teams.count, 12)
        // Ratings are zero-sum around the base.
        XCTAssertEqual(Stats.mean(model.teams.map(\.rating)), 1500, accuracy: 1e-6)
        // Must beat a coin flip out of sample.
        XCTAssertLessThan(model.calibration.brier, 0.25)
        XCTAssertGreaterThan(model.calibration.accuracy, 0.5)
        XCTAssertGreaterThan(model.pointsPerRating, 0)
        let best = model.teams.first!.name, worst = model.teams.last!.name
        XCTAssertGreaterThan(model.homeWinProbability(home: best, away: worst), 0.6)
        let p = model.homeWinProbability(home: best, away: worst, neutral: true)
        XCTAssertEqual(p + model.homeWinProbability(home: worst, away: best, neutral: true), 1, accuracy: 1e-9)
        XCTAssertGreaterThan(model.baselineWinProbability(best), model.baselineWinProbability(worst))
        let cover = model.homeCoverProbability(home: best, away: worst, spread: -model.expectedMargin(home: best, away: worst))
        XCTAssertEqual(cover ?? 0, 0.5, accuracy: 1e-9)
    }

    func testPicksAndParlays() {
        let data = SampleData.make(asOf: Date(timeIntervalSince1970: 1_800_000_000))
        let model = LeagueModel(games: data.games)
        let picks = Picks.evaluate(slate: data.slate, model: model, games: data.games)
        XCTAssertEqual(picks.count, 12)
        XCTAssertEqual(picks.map(\.expectedValue), picks.map(\.expectedValue).sorted(by: >))
        for g in data.slate {
            let sides = picks.filter { $0.gameID == g.id }
            XCTAssertEqual(sides.reduce(0) { $0 + $1.modelProbability }, 1, accuracy: 1e-9)
            XCTAssertEqual(sides.reduce(0) { $0 + $1.marketProbability }, 1, accuracy: 1e-9)
        }
        let parlays = Picks.bestParlays(from: picks, legCount: 2)
        for p in parlays {
            XCTAssertEqual(Set(p.legs.map(\.gameID)).count, 2)
            XCTAssertGreaterThan(p.expectedValue, 0)
        }
    }

    func testBankroll() {
        let d = Date(timeIntervalSince1970: 0)
        let bets = [
            Bet(date: d, label: "a", odds: 100, stake: 50, result: .won),
            Bet(date: d.addingTimeInterval(1), label: "b", odds: -110, stake: 110, result: .won),
            Bet(date: d.addingTimeInterval(2), label: "c", odds: 200, stake: 40, result: .lost),
            Bet(date: d.addingTimeInterval(3), label: "d", odds: 100, stake: 25, result: .pending),
        ]
        let s = BankrollStats(bets: bets, startingBankroll: 1000)
        XCTAssertEqual(s.profit, 110, accuracy: 1e-9)
        XCTAssertEqual(s.staked, 200, accuracy: 1e-9)
        XCTAssertEqual(s.roi, 0.55, accuracy: 1e-9)
        XCTAssertEqual(s.currentStreak, -1)
        XCTAssertEqual(s.longestWinStreak, 2)
        XCTAssertEqual(s.pendingStake, 25)
        XCTAssertEqual(s.curve.last?.balance ?? 0, 1110, accuracy: 1e-9)
    }

    func testCSVImport() {
        let csv = """
        Date,Home Team,Away Team,Home Score,Away Score,Spread,Total
        2026-01-15,"Kings, The",Aces,108,101,-3.5,221.5
        01/16/2026,Aces,Jets,99,104,,
        bad,row,here
        """
        let r = CSVImport.parse(csv)
        XCTAssertEqual(r.games.count, 2)
        XCTAssertEqual(r.skipped.count, 1)
        XCTAssertEqual(r.games[0].home, "Kings, The")
        XCTAssertEqual(r.games[0].spread, -3.5)
        XCTAssertNil(r.games[1].total)
        XCTAssertEqual(CSVImport.parse(CSVImport.template).games.count, 1)
        XCTAssertTrue(CSVImport.parse("a,b\n1,2").games.isEmpty)
    }
}
