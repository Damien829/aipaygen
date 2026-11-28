# Handoff: Crystal Pets, continue on the Windows PC

For a Claude Code session running **locally on the PC** (not in the cloud).
Start it in PowerShell from this folder:

```powershell
cd $HOME\Documents\aipaygen\roblox\crystal-pets
claude
```

Then say: "Read HANDOFF_PC.md and continue."

## Where things stand (2026-11-28)
- Repo `Damien829/aipaygen`, branch **`claude/wizardly-ramanujan-i96z4j`** (latest). It builds on
  `claude/focused-turing-m5odmj` (PR https://github.com/Damien829/aipaygen/pull/1).
  The PC clone is on `claude/focused-turing-m5odmj` with the newer branch pulled into it.
  Commit and push on whichever branch the user prefers. Ask them first.
- Project: `roblox/crystal-pets/`. Rojo 7.7.1 (`rojo.exe` in this folder), Studio plugin installed.
- **First playtest done: the map loads.** Nothing else has been confirmed yet.
- Fixed since the first handoff:
  - `DataService`: `GetDataStore` is wrapped in `pcall`. In an unpublished place it threw at require time
    and stopped `Main` before the map was built.
  - `DataService.Load`: fails fast in Studio on DataStore errors instead of retrying for about 24s.
    It sets the player attribute `SavingOff`, and the UI shows a toast about it.

## Next steps (user does the Studio clicks; Claude cannot click inside Studio)
1. Save the place: **File > Save to Roblox**. Then **Home > Game Settings > Security > Enable Studio
   Access to API Services**.
2. Run the checklist in `HANDOFF_WINDOWS.md` Part 1, step 5: mining, hatching, panels, daily reward,
   zone unlock, and that progress survives Stop then Play.
3. Fix any red errors from **View > Output** (the user pastes them in).
4. Monetization IDs: see `HANDOFF_WINDOWS.md` Part 2. All are `0` (inactive) in `src/shared/Config.luau`.
5. Publish: `HANDOFF_WINDOWS.md` Part 3. The Winter Egg event runs Dec 1, 2026 to Jan 6, 2027.

## Useful commands (PowerShell, from this folder)
```powershell
git pull                     # get the latest pushed fixes
.\rojo.exe serve             # live-sync into Studio (then Plugins > Rojo > Connect)
.\rojo.exe build -o CrystalPets.rbxl   # standalone place file
```

## Notes for Claude
- The code was reviewed by hand and is now partly tested. Expect the remaining bugs to surface only in playtests.
- On the PC you can run Luau tooling (for example `luau-lsp analyze` or `selene`) to check code before the
  user plays. The cloud session could not run them.
- The user is not technical. Give click-by-click steps, one command block at a time.
