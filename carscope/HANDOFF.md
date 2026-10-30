# CarScope — session handoff

Context for continuing this work in a new (local) Claude Code session.

## What this is

**CarScope** is a standalone, AI-assisted OBD-II diagnostic + tuning tool that
runs on a Mac and talks directly to a vehicle's OBD-II / CAN bus through a
standard adapter. It is **independent of any commercial scan tool** (e.g.
Autel) — it does not touch, modify, bypass, or depend on another device's
software. It reads the open, standardized OBD-II interface. Use on vehicles you
own or are authorized to service.

It lives in the `carscope/` folder of the repo `Damien829/aipaygen`, on branch
`claude/aural-scanner-jailbreak-4swpyw`.

## Scope boundaries held in this project (important)

These are deliberate and should be maintained:

- **Read/diagnose/analyze: yes.** DTCs, live data, CSV logging, raw CAN
  capture (read-only), tuning-log analysis.
- **Tuning analysis is for off-road / track / race use**, and is analysis
  only — it never writes to the vehicle or a calibration.
- **Will NOT build:** anything to defeat a device's licensing/subscription
  (the original "jailbreak the Autel" ask); emissions-control defeat (DPF/EGR/
  O2/cat deletes) on street vehicles; disabling safety systems; or bypassing
  ECU security (seed/key, secure gateway, signature checks). These are both
  off-limits and technically dead ends (locked ECUs reject unsigned writes).
- The **legitimate path to dealer-level programming** is J2534 pass-thru +
  an OEM service subscription + the OEM's signed calibration files — that's
  what any future write/coding layer should be built around (authenticated
  access the owner legitimately has), not a bypass.

## Current state — all built, committed, pushed

CLI (`python main.py <command>`), package in `carscope/carscope/`:

| Command | File | What it does |
|---|---|---|
| `scan` | connection.py | Connect, report adapter/protocol/PID count |
| `codes` | diagnostics.py | Stored/pending/permanent DTCs, MIL, freeze frame |
| `clear` | diagnostics.py | Clear codes (guarded by `--yes`) |
| `live` | live.py | One-shot sensor snapshot |
| `log` | live.py | Stream PIDs to CSV |
| `explain` | ai.py | Claude interprets codes (needs `ANTHROPIC_API_KEY`) |
| `can sniff/log/survey` | can_bus.py | Raw CAN capture (USB-CAN adapter; read-only) |
| `tune analyze` | tuning.py | AFR-error grid + knock events from a datalog |
| `web` | web.py + web_assets/ | **Modern browser dashboard (primary UI)** |
| `gui` | gui.py | Native Tkinter window (offline fallback) |

AI layer uses the Anthropic Python SDK, model `claude-opus-5-5`, adaptive
thinking. It degrades gracefully when the package or key is absent.

## What's tested vs not

- **Tested here** (against an ELM327 emulator + python-can virtual bus +
  synthetic logs): scan/codes/live/log/clear-guard, CAN survey/log, tune
  analyze (lean region + knock events correctly surfaced; lambda→AFR
  conversion; column overrides), and the **entire web API end-to-end over
  HTTP** (connect/live/codes/guarded-clear/tune, path-traversal blocked).
  Frontend JS passes `node --check`. GUI data-handlers exercised via mocked Tk.
- **NOT verified** (needs real hardware / the Mac / a key):
  - The web dashboard and Tkinter window **rendering** (logic tested, visuals
    not — this container has no display and no Tkinter).
  - The AI `explain` / `--explain` **live round-trip** (no API key in the
    cloud env; prompt-building is tested).
  - Anything against a **real vehicle / real adapter**.

## Run it on the Mac

```bash
cd carscope
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py web           # the dashboard; or: scan / codes / live / tune analyze
export ANTHROPIC_API_KEY=... # only for the AI features
```

Adapter ports on macOS: USB `/dev/tty.usbserial-*`, Bluetooth `/dev/tty.*`
(pair first), Wi-Fi `socket://192.168.0.10:35000`. USB-CAN for `can`:
`/dev/tty.usbmodem*` in slcan mode.

## Suggested next steps

1. **Run `python main.py web` on the Mac and eyeball the dashboard** — first
   time the UI actually renders. Report anything visually off.
2. **Set an API key and try `explain`** to confirm the AI round-trip.
3. **Try it on the real car** with the ELM327 and iterate on anything that
   behaves differently from the emulator.
4. **UDS coding/adaptation layer** (the write side) for the track car, when
   ready — needs the ECU details: stock OEM (+ which licensed tool, e.g. HP
   Tuners/EFILive) or a standalone like rusEFI/Speeduino. Build on J2534 /
   authenticated access, with writes gated, logged, and dry-run by default.
   No security bypass.
5. Roadmap also notes: graphical live gauges/charts in the dashboard; signal
   decoding on top of `can survey` (e.g. DBC).

## Notes for the next session

- Develop on branch `claude/aural-scanner-jailbreak-4swpyw`; the project is the
  `carscope/` subfolder (the rest of the `aipaygen` repo is an unrelated
  TypeScript/Cloudflare project).
- No new runtime deps beyond `obd`, `python-can`, `anthropic` (all in
  requirements.txt). The web UI and GUI are stdlib-only.
