# Mix & Smash

Build your fighter from parts, then smash everyone off the stage.

**Status (2026-11-28):** all code is written. Selene finds no errors and `rojo build` succeeds. An independent code
review was done and its real bugs were fixed. **It has never been played.** Expect a few small fixes after the first
playtest.

- Branch: `claude/faceoff-game-c4cfdb` (repo `Damien829/aipaygen`)
- Folder: `roblox/faceoff/`
- Crystal Pets (`roblox/crystal-pets/`) and Crystal Heist (`roblox/crystal-heist/`) are untouched.

---

## How the game plays
1. **Mix your fighter.** Every fighter has 3 parts. The **head** gives your special move (Q), the **arms** give your
   heavy attack (E), and the **legs** set your speed, number of jumps and weight. There are 18 parts (6 per slot), so
   there are 216 combinations, and every part works with every other part.
2. **Smash.** Hits add damage %. The higher someone's %, the farther they fly. Knock them past the glowing pink
   blast walls (left, right, top or bottom) to take one of their 3 lives. Last one standing wins.
3. **Battle from the lobby.** Stand on the **red pad** for 1v1 Ranked or the **blue pad** for Free-for-All (2 to 4
   players). If you wait alone for 12 seconds, a bot joins so nobody sits in an empty queue. Bot matches give 60% of
   the rewards and no trophies.
4. **Story mode: The Scrapyard Saga.** 5 chapters. Each one has comic-style dialogue, waves of Junk Bots, and a boss
   who drops their part the first time you beat them (Hammer Arms, Frost Head, Rocket Boots, Cloud Legs, Thunder King Head).
5. **Come back every day:**
   - **Daily chest** with a 7-day streak (missing a day restarts at day 1).
   - **3 daily quests**, which are new every day.
   - **Win streaks** add +10% coins per win in a row, up to +50%. A 🔥 shows on your name tag.
   - **Star Road:** a free 30-tier track with coins, parts, paints, titles and Second Winds. It has no end date.
   - **Ranks:** Bronze, Silver, Gold, Platinum, Diamond and Champion, from trophies won in 1v1 Ranked.
6. **Everything is in the world**, not only in menus:
   - The **Part Forge** has a spinning model of every part on a pedestal. Walk up and press **R** to buy or equip.
   - The **Paint Shop** row lets you recolor your parts. Paints are cosmetic only.
   - The **Training Grounds** have 3 dummies to test combos on.
   - The **Star Road** is a path of 30 tiles that light up gold as you progress.
   - The lobby also has a **Daily Chest**, a **Story Portal**, a **leaderboard** and a **Shop stall**.

### Controls
| Action | PC | Gamepad | Phone |
|---|---|---|---|
| Move | A / D (W/S in the lobby) | Left stick | Thumbstick |
| Jump / air jump | Space | A | Jump button |
| Drop through a platform | Hold S | Stick down | Thumbstick down |
| Jab | Left click | X | 👊 button |
| Heavy (arms) | E (or right click in a fight) | Y | 💪 button |
| Special (head) | Q | B | ✨ button |
| Dodge (can't be hit) | F | R1 | 💨 button |
| Use things in the lobby | R | L3 | Tap the prompt |

---

## Playtest it (about 15 minutes)

### 1. Start syncing
Open PowerShell and go to the game's folder:

```powershell
cd $HOME\Documents\aipaygen\roblox\crystal-pets\.claude\worktrees\faceoff-game-c4cfdb\roblox\faceoff
```

(After this branch is merged into your main folder, the path is `$HOME\Documents\aipaygen\roblox\faceoff` instead.)

Then start Rojo:

```powershell
& "$HOME\Documents\aipaygen\roblox\crystal-pets\rojo.exe" serve
```

If another game's `rojo serve` is still running (Crystal Pets or Crystal Heist), stop it first: click its window
and press **Ctrl+C**.

### 2. Make a new place
1. In Studio: **File > New > Baseplate**.
2. **File > Save to Roblox**, and name it "Mix & Smash".
3. **Home > Game Settings > Security**: turn on **Enable Studio Access to API Services**, then click **Save**.
   Without this, the game still runs, but a red "SAVING IS OFF" line shows and nothing saves.
4. **Home > Game Settings > Avatar**: keep **R15** (the default). Parts attach to R15 hands and feet.
5. **Plugins > Rojo > Connect**.
6. In the **Explorer** panel, click **Workspace**. In **Properties**, check that **StreamingEnabled** is unchecked.
   Rojo should set this for you. The arenas are far from the lobby and must be loaded.

### 3. Play alone first (bots and story)
1. Press **Play** (the big triangle on the Home tab).
2. Walk onto the red pad and wait 12 seconds. A bot joins and the match starts.
3. Afterwards, walk into the purple Story Portal (north, behind the pads), press **R**, then play Chapter 1.

### 4. Play with 2 players (real 1v1)
1. Stop the test. Click the **Test** tab.
2. Set **Clients and Servers** to **2 Players**, then click **Start**. Three windows open: a server and two players.
3. Arrange the player windows side by side. Walk both players onto the red pad.

### 5. Checklist (tell Claude about anything that fails)
**Lobby**
- [ ] You spawn on a gold plaza. The big "MIX & SMASH" title floats north, and signposts point to Battle, Part Forge, Training and Star Road.
- [ ] The "How to play" panel opens on your first visit. On later days, the Daily panel opens instead.
- [ ] Your character wears its parts: a yellow helmet (Bolt Head), red boxing gloves and white sneakers.
- [ ] The top bar shows coins, Star Road tier, rank and streaks. The left menu has 7 buttons, and each panel opens and closes with ✕.
- [ ] **Part Forge** (east): 18 spinning parts on glowing pedestals. Press R on a Rare part with enough coins (you start with 150, so play a match first). It buys and equips it, your character changes, and the prompt says "Equipped ✓".
- [ ] The **Build menu** shows all parts. Locked ones say where they come from. Equip works, and the Paint tab recolors your parts.
- [ ] **Training Grounds** (west): hitting a dummy shows its % over its head, and it flies farther as % goes up. It walks back home after a few seconds.
- [ ] Try E (heavy) and Q (special) on the dummies. Your fighter really moves: a haymaker with Boxing Gloves, an overhead slam with Hammer Arms, a star-burst pose with Bolt Head, and so on. Each part has its own move. The dummy flinches when hit.
- [ ] Walk up to things: labels pop up when you get close and shrink away when you leave. From a distance you only see the big zone names.
- [ ] **Daily chest** (next to spawn): press R. A celebration pops up with coins. Pressing R again says "Already claimed today".
- [ ] **Star Road** (south): 30 tiles with reward labels. Tiles you've reached turn gold, and the next one turns blue.
- [ ] The Shop stall shows VIP, Star Boost, Starter Bundle and coins. With Ids still 0, each stand says "coming soon". That's expected until you create them.

**Fighting**
- [ ] On the red pad, the sign counts "1/2 waiting · Bot joins in Ns". The bottom bar says "In 1v1 Ranked queue", and **Leave** walks you off the pad.
- [ ] The match starts in a side-view arena. "3, 2, 1, FIGHT!" plays and nobody can move until FIGHT.
- [ ] Movement is left/right only. Space jumps, and pressing Space again in the air air-jumps. You can jump up through the floating platforms, and holding S drops you through.
- [ ] The bottom cards show each fighter's % (white, then yellow, then red) and lives (●●●). The timer counts down from 3:00.
- [ ] Hitting raises % and knocks the other fighter away. At high %, a heavy hit launches them past the pink wall: "KO!", an explosion, and they lose a life.
- [ ] After a KO, the fighter reappears above the stage on a glowing platform and flashes gold (can't be hit) for about 2 seconds.
- [ ] F dodges with a quick dash and a white flash. Hits during it do nothing.
- [ ] When someone loses all 3 lives: "GAME!", then the results card (coins, Star XP, KOs, trophies if ranked), then you're back in the lobby after about 5 seconds.
- [ ] With 2 players in Ranked, the winner gets +25 trophies and the loser -12. The name tag rank updates.
- [ ] The blue pad (Free-for-All) with 2 players starts after a 10-second countdown on the sign.

**Story**
- [ ] The Story panel shows Chapter 1 to play, with the others locked. Play opens the arena and shows dialogue boxes (portrait, name, typing text). Click or press Space to continue, and Skip works.
- [ ] Junk Bots attack you, and the banner says "Wave 1 of 1". After they're KO'd, the boss dialogue plays, then the big boss (Clank) fights.
- [ ] Beating the boss: victory dialogue, then "CHAPTER CLEARED!" with "NEW PART: Hammer Arms". Chapter 2 unlocks.
- [ ] Losing all lives: "DEFEATED", then back to the lobby. Retrying is always free.

**Saving**
- [ ] Stop and press Play again. Your coins, parts, Star Road tier and story progress are still there.

---

## Things to create on the Creator Dashboard
Open [create.roblox.com](https://create.roblox.com), go to your experience, then **Monetization**.
Create each item, then paste its Id into `src/shared/Config.luau` (find the `Id = 0` next to the name).
Rojo syncs the change while it's connected. Anything left at `Id = 0` shows "Not for sale yet" and never prompts.

| What | Type | Config name | Price (Robux) | What the player gets |
|---|---|---|---|---|
| VIP | Game Pass | `GamePasses.VIP` | 199 | +50% coins and Star XP forever, a gold 👑 name, and the Royal paint |
| Star Boost | Game Pass | `GamePasses.StarBoost` | 149 | 2x Star XP forever |
| Pile of Coins | Developer Product | `Products.CoinsS` | 49 | 600 coins |
| Sack of Coins | Developer Product | `Products.CoinsM` | 129 | 1,800 coins |
| Vault of Coins | Developer Product | `Products.CoinsL` | 349 | 5,500 coins |
| Starter Bundle | Developer Product | `Products.Starter` | 99 | Blaster Head, Turbo Wheels, Chrome paint and 1,000 coins (one per account) |
| Second Wind | Developer Product | `Products.SecondWind` | 25 | Refills your 3 lives in a story fight, or is saved for next time |
| 24K Gold Paint | Developer Product | `Products.PaintGold` | 79 | Gold paint (cosmetic) |
| Galaxy Paint | Developer Product | `Products.PaintGalaxy` | 79 | Galaxy paint (cosmetic) |
| Rainbow Paint | Developer Product | `Products.PaintRainbow` | 99 | Color-cycling paint (cosmetic) |

**Why it's honest (Roblox rules, and most players are kids):**
- Every item says exactly what you get. There are no random boxes or loot crates.
- There are no countdowns, no "deals" and no fake "only 3 left". The Second Wind pop-up after a story loss shows no timer, and "No thanks" closes it right away.
- Every part can be earned for free: coins from matches, story bosses and the Star Road. Robux only speeds things up or buys cosmetic paints.
- Offers are rare: a VIP suggestion after 7 minutes, a Star Boost suggestion at Star Road tier 3, a coins suggestion when you can't afford a part, and Second Wind after a story loss. Each shows at most once per visit, never during a fight, and has a "No thanks" button.

## Before you publish
- **Server size:** set it to **12** in the Creator Dashboard (**Places > Configure Place > Server Size**). There are 12 arena slots, so everyone can be in a fight or story at once.
- Add a game icon and thumbnails. Screenshots of a fight with the % cards and a boss make good thumbnails.
- Turn off Studio API access only if you want. It's harmless to leave on.

## Files
| File | What it does |
|---|---|
| `src/shared/Config.luau` | Every number: parts, moves, arenas, story chapters and dialogue, Star Road, ranks, rewards, products |
| `src/server/Combat.luau` | Damage %, knockback, all move types, dodge, freeze, blast zone KO checks |
| `src/server/Match.luau` | Queue pads, bot fill, 1v1 and FFA rounds, lives, results |
| `src/server/Story.luau` | Story chapters: dialogue, waves, bosses, Second Wind |
| `src/server/Npc.luau` | Bots, bosses and training dummies (their AI) |
| `src/server/Arena.luau` | Builds the fight stages, platforms and blast walls |
| `src/server/Lobby.luau` | Builds the lobby: pads, portal, Part Forge, Paint Shop, training, Star Road, chest, leaderboard, shop |
| `src/server/Profile.luau` | Coins, Star Road, daily streak, quests, ranks, ownership, name tags, the state sent to the UI |
| `src/server/Visuals.luau` | Builds the parts onto characters and pedestals, signs and name tags |
| `src/server/DataService.luau` | Safe saving (session lock, retries; never overwrites on a failed load) |
| `src/server/Monetization.luau` | Robux purchases (each receipt is granted once and saved right away) |
| `src/client/Control.client.luau` | Controls, air jumps, knockback, side camera, one-way platforms, phone buttons |
| `src/client/UI.client.luau` | All menus, the fight HUD, dialogue, results and pop-ups |
| `src/client/Effects.client.luau` | Hit sparks, KO blasts, spinning displays, rainbow paint, Star Road tiles |
| `src/client/Animate.client.luau` | Fighting animations made in code: jabs, every arm's heavy attack, every head's special move, dodge, getting hit, and bot walk cycles |

## Ideas for later
- More story chapters (Config.Chapters is easy to extend: copy one and change the text).
- A global leaderboard (OrderedDataStore) for trophies.
- Bots fall through the floating platforms (only players can stand on them). A smarter bot could use them.
