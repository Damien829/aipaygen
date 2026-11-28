# Handoff: Crystal Pets Simulator on your Windows PC

**Status:** all code is written, reviewed by hand and pushed. **It has never been run.** There was no Roblox Studio
and no Luau syntax checker in the cloud session. Your first playtest is the first real test, so expect a few small fixes.

- Repo: `Damien829/aipaygen`, branch `claude/focused-turing-m5odmj`
- Pull request: https://github.com/Damien829/aipaygen/pull/1
- Project folder: `roblox/crystal-pets/`

---

## Part 1: Get it running (about 20 minutes)

### 1. Install the tools
1. **Roblox Studio**: https://create.roblox.com (sign in, then Download Studio).
2. **Git for Windows**: https://git-scm.com/download/win (skip it if you already have `git`).
3. **Rojo** (syncs the files into Studio). Easiest route is the Roblox Studio plugin plus the CLI:
   - Install the **Rojo plugin** in Studio: Plugins tab, Manage Plugins, search "Rojo" (the official one by Rojo).
   - Install the CLI: download `rojo-7.x.x-windows-x86_64.zip` from https://github.com/rojo-rbx/rojo/releases, unzip it
     and put `rojo.exe` somewhere on your PATH (or into the project folder).
   - Alternative: install [Aftman](https://github.com/LPGhatguy/aftman) and run `aftman install` in the project folder
     (`aftman.toml` pins Rojo 7.7.1).

### 2. Get the code
Open PowerShell (a normal one, not admin):

```powershell
git clone https://github.com/Damien829/aipaygen.git
cd aipaygen
git checkout claude/focused-turing-m5odmj
cd roblox\crystal-pets
```

### 3. Create the place
1. Studio: **New > Baseplate**. File > Save to Roblox (name it "Crystal Pets") so it has a place ID.
2. **Home > Game Settings > Security > Enable Studio Access to API Services = ON**. Without this, saving and
   purchases cannot work in testing.

### 4. Sync and play
1. In PowerShell (inside `roblox\crystal-pets`): `rojo serve`
2. In Studio: **Plugins > Rojo > Connect**.
3. Press **Play** (F5). Walk around, press **E** on a crystal, and hold **E** on the egg pedestals.

### 5. First-playtest checklist (tell Claude about anything that fails)
- [ ] Map appears: 4 colored zones, glowing crystals, egg pedestals near the spawn.
- [ ] Mining a crystal adds coins and shows a floating "+N".
- [ ] Hatch the Meadow Egg once you have 250 coins: popup appears and the pet follows you.
- [ ] **Pets / Style / Shop / Rebirth / Daily** buttons all open panels. Tapping a pet equips it.
- [ ] Daily panel: Claim works, and the red dot clears.
- [ ] Unlock pedestal for Crystal Cave works after 2,500 coins.
- [ ] Stop and press Play again: coins, pets and zones are still there (saving works).
- [ ] Output window (View > Output) has no red errors. Copy any red text to Claude.

---

## Part 2: Set up monetization (needs your Roblox account)

On https://create.roblox.com/dashboard/creations, open your experience, then **Monetization**.
Paste each ID into `roblox\crystal-pets\src\shared\Config.luau` (it saves on disk and Rojo syncs it).
Anything left at `0` is simply inactive: the shop button shows a reminder and nothing can be bought.

| What | Config key | Suggested price |
|---|---|---|
| Game pass | `GamePasses.DoubleCoins` | 299 R$ |
| Game pass | `GamePasses.AutoCollect` | 399 R$ |
| Game pass | `GamePasses.LuckyHatch` | 249 R$ |
| Game pass | `GamePasses.ExtraSlots` | 199 R$ |
| Game pass | `GamePasses.VIP` | 499 R$ |
| Developer product | `Products.StarterPack` | 99 R$ |
| Developer product | `Products.CoinsSmall` | 49 R$ |
| Developer product | `Products.CoinsMedium` | 199 R$ |
| Developer product | `Products.CoinsLarge` | 799 R$ |
| Developer product | `Products.Boost` | 79 R$ |
| Developer product | `Cosmetics.Rainbow` | 149 R$ |
| Developer product | `Cosmetics.Galaxy` | 299 R$ |
| Subscription | `Subscription.Id` (a string like `EXS-...`) | 199 R$/month |

Test every purchase in Studio first (Studio purchases cost no Robux). Then publish.

---

## Part 3: Publish and grow
1. File > **Publish to Roblox**. Add an icon, a thumbnail and a clear description.
2. Set the experience to **Public** when you're ready.
3. Ship small updates weekly. Fresh updates are what Roblox's recommendations reward.
4. Run the winter event (Winter Egg is live Dec 1, 2026 to Jan 6, 2027). Copy that egg entry for the next event.
5. Promote outside Roblox (creators, short videos). The research shows most games earn very little without it.

---

## What's built (so you know what to test)
Mining, 4 zones, 4 eggs plus a limited-time Winter Egg, 9 pets plus Shiny variants, rebirth, daily streak, friends
bonus, leaderboard (leaderstats), 5 passes, 5 products, Crystal Club subscription, trail cosmetics, contextual
purchase offers, session-locked DataStore saving, idempotent purchase receipts.

## Known limits and risks
- **Never run.** Typos or Roblox API quirks may exist. Fix in small steps with Claude.
- Pets are colored balls with emoji. Replace with real models when you have art.
- No sound, music or 3D art. The map is simple colored floors.
- Subscription status is checked at join only. A lapse mid-session keeps the bonus until the player rejoins.
- Balance numbers (prices, egg costs, multipliers) are first guesses. Tune them in `Config.luau` after watching real
  players.
- Market research is in `MARKET_NOTES.md`. It is directional blog and tracker data, not official numbers.

## Where things are
| File | What it does |
|---|---|
| `src/shared/Config.luau` | All balance, pets, eggs, zones, pass/product IDs |
| `src/server/*.luau` | Data, economy, pets, mining, cosmetics, purchases, map |
| `src/client/*.luau` | UI, pet and trail rendering |
| `README.md` | Quick start and revenue notes |
| `MARKET_NOTES.md` | Research on what top earners do |

## Resuming with Claude on your PC
Open this folder in Claude Code (or paste an error from the Output window into any Claude chat) and say:
"This is the Crystal Pets Roblox project, see HANDOFF_WINDOWS.md. Here is the error: ..."
Fixes get committed on branch `claude/focused-turing-m5odmj` and flow into PR #1.
