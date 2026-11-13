# StreakEdge

A native macOS app (SwiftUI) for sports betting analytics: team streaks, win probabilities,
value against the bookmaker's price, parlays, and a bet tracker. Everything runs and is stored locally.

## Run it

Needs macOS 14+ and Xcode 15+.

```sh
cd mac/StreakEdge
swift run StreakEdge          # quick launch
./scripts/make-app.sh         # or build build/StreakEdge.app
open Package.swift            # or open in Xcode and press Run
swift test                    # analytics tests
```

It opens with a simulated sample league so every screen has something to show.

### Live results and odds

In **Data**, pick a league (NBA, NFL, NHL, MLB), paste an API key from
[the-odds-api.com](https://the-odds-api.com) and press **Refresh Now** (or use Refresh on Best Bets).

- **Results** — this season's finished games from ESPN's public scoreboard. No key needed, but it is
  an unofficial feed and could change without notice.
- **Odds** — current moneylines, spreads and totals from US bookmakers. Each side shows the best
  price on offer and which book has it; "Market" is the average across books with the margin removed.
  The free plan allows 500 requests a month; each refresh uses 3. The key is stored in your keychain.
- Odds update when you press Refresh, not continuously.
- Past games arrive without spreads or totals, so spread and over/under streaks start empty and fill
  in as games you refreshed odds for are played.

### Your own results

Or import a CSV in **Data** with one finished game per row:

```
date,home,away,home_score,away_score,spread,total
2026-01-15,Home Team,Away Team,108,101,-3.5,221.5
```

`spread` is the home team's line. `spread` and `total` are optional.

## Screens

| Screen | What it does |
|---|---|
| Best Bets | Upcoming games you enter with moneylines, ranked by expected value: model probability vs the market's (margin removed), edge, and a suggested stake |
| Streaks | Current and longest win, against-the-spread and over/under streaks per team; chance the streak continues; a runs test that says whether a team is streakier than luck; a "run of N in the next M games" calculator |
| Matchup | Any two teams: win probability, fair price, expected margin and total, cover and over probabilities, value against odds you type in |
| Parlays | Best 2–4 leg combinations of positive-value picks |
| Bet Tracker | Log bets, settle them, and see balance, ROI and your own winning and losing streaks |
| Model | How well the predictions have held up (accuracy, Brier score, calibration chart), team ratings, and tuning |
| Data | CSV import, sample league, reset |

## How the numbers are made

- **Win probability** — Elo ratings with home advantage and a margin-of-victory multiplier, updated game by game.
- **Margin and total** — expected margin is fitted from rating differences; expected total from each side's scoring for and against. Cover and over probabilities assume normally distributed misses.
- **Value** — expected value of a price given the model probability; stakes are a fraction of the Kelly amount (a quarter by default), capped at 5% of the balance.
- **Streaks** — pushes neither extend nor break a streak. Continuation chances treat games as independent.
- **Model check** — every game is predicted using only earlier games, so the scores on the Model screen are out of sample.

The model sees only past scores — no injuries, rest, or lineup news — and bookmakers' prices already include those.
Treat a large "edge" as a prompt to look closer, not a guarantee.

## Layout

- `Sources/EdgeCore` — the analytics, no UI, portable and unit tested
- `Sources/StreakEdge` — the SwiftUI app (macOS only)
