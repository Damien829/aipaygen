# CarScope

An AI-assisted OBD-II diagnostic tool you own and control, built to run on a
Mac (and later a Raspberry Pi). It plugs into your vehicle's OBD-II port
through a standard adapter and lets you read/clear trouble codes, stream and
log live sensor data, and — optionally — have Claude help interpret what it
finds.

CarScope is **standalone**. It does not touch, modify, depend on, or bypass any
commercial scan tool or its software. It talks directly to the vehicle's
OBD-II / CAN bus, which is an open, standardized interface. Use it only on
vehicles you own or are authorized to service.

## What it does today

- **`scan`** — connect and report adapter + vehicle info (protocol, supported PIDs).
- **`codes`** — read stored / pending / permanent trouble codes, with the
  check-engine light status and optional freeze-frame data.
- **`clear`** — clear codes and turn off the check-engine light (guarded; needs `--yes`).
- **`live`** — one-shot snapshot of live sensor values.
- **`log`** — stream live sensor data to a CSV for later analysis/charting.
- **`explain`** — read the codes, then have Claude rank likely causes and
  suggest concrete next tests. (Optional; needs an API key.)

## Hardware you need

Any **ELM327** adapter (USB, Bluetooth, or Wi-Fi) to start — the cheap ~$20
ones work. On macOS:

- **USB**: shows up as `/dev/tty.usbserial-XXXX`.
- **Bluetooth**: pair it in System Settings first; it appears as `/dev/tty.*`.
- **Wi-Fi**: join its network, then use `--port socket://192.168.0.10:35000`
  (check your adapter's IP/port).

J2534 pass-thru and raw USB-CAN interfaces are on the roadmap (see below) for
deeper, manufacturer-level diagnostics.

## Setup (macOS)

```bash
cd carscope
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

For the optional AI layer, set an API key (get one at
https://console.anthropic.com/):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or: cp .env.example .env  and fill it in, then `source .env`
```

## Usage

```bash
# See what you're connected to
python main.py scan

# If auto-detect doesn't find it, pass the port explicitly
python main.py scan --port /dev/tty.usbserial-1420

# Read trouble codes (+ freeze frame)
python main.py codes --freeze

# One-shot live snapshot
python main.py live

# Log live data to CSV at 2 Hz for 60 seconds
python main.py log --out drive.csv --interval 0.5 --duration 60

# Clear codes (destructive — needs explicit confirmation)
python main.py clear --yes

# Read codes and have Claude interpret them
python main.py explain --vehicle "2014 Subaru Outback 2.5i"
```

Custom PID set for `live` / `log`:

```bash
python main.py live --pids RPM,SPEED,COOLANT_TEMP,MAF
```

(PID names follow python-OBD's command names; `scan` reports how many your
vehicle supports.)

## The dashboard (recommended UI)

```bash
python main.py web
```

This starts a small local server and opens a modern dashboard in your browser.
It runs entirely on your Mac — nothing is sent anywhere (except, if you use the
AI features, your prompt to the Claude API). It's built to be clean and
accessible: automatic light/dark, responsive layout, the system font so it
feels native, keyboard-operable tabs, screen-reader-aware regions, and a
tuning heatmap that always shows the number (color is never the only cue).

- **Connect** from the top bar — type the adapter port or leave it blank to
  auto-detect.
- **Live data** tab — start/stop a live readout of sensor tiles.
- **Trouble codes** tab — read codes, clear them (behind a confirmation), and
  "Explain with AI" if you've set an API key.
- **Tuning log** tab — point it at a CSV and get the color-coded AFR-error
  grid, knock events, and optional AI analysis.

Reach it from your phone on the same Wi-Fi with
`python main.py web --host 0.0.0.0` and your Mac's IP.

### Offline fallback: native window

If you'd rather not use a browser, there's a native Tkinter window with the
same core features (Tkinter ships with Python):

```bash
python main.py gui
```

> If it says Tkinter isn't available: on macOS the python.org installer
> includes it (verify with `python3 -m tkinter`); Homebrew Python needs
> `brew install python-tk`.

## Tuning datalog analysis (off-road / track use)

For a track/race car, analyze a datalog to see where the tune needs work. The
log can come from CarScope's own `log` command or be exported from your tuning
software (rusEFI, Speeduino, MegaSquirt, HP Tuners, AEM, Haltech, …).

```bash
# AFR-error grid + knock events; give a target AFR if the log has no target channel
python main.py tune analyze --log drive.csv --target 12.8

# Map oddly-named columns, and add Claude's analysis
python main.py tune analyze --log drive.csv --target 12.8 \
    --map "rpm=EngineSpeed,load=MAP,afr=WB_AFR" --explain
```

The grid shows mean AFR error (actual − target) across RPM × load — positive is
lean, negative is rich — so you can see exactly which cells to adjust. Knock /
ignition-retard events are listed with the conditions they occurred under, so
you address the dangerous high-load/high-rpm corner first.

This is **analysis only** — it never writes to the vehicle or a calibration.
You make the changes in your own tuning software. It's for off-road / track /
race use; it does not help defeat emissions equipment.

## Raw CAN capture

For signals the standard PIDs don't expose, CarScope can listen to raw CAN
traffic. This needs a real **USB-CAN adapter** (e.g. CANable / CANtact in
`slcan` mode); an ELM327 can't provide raw frames. Capture is read-only:
CarScope never transmits onto the bus.

```bash
ls /dev/tty.usbmodem*                                    # find the adapter
python main.py can sniff  --channel /dev/tty.usbmodem14201
python main.py can log    --channel /dev/tty.usbmodem14201 --out can.csv --duration 60
python main.py can survey --channel /dev/tty.usbmodem14201 --duration 20
```

`survey` lists every active arbitration ID and which byte positions change.
That's the quick way to locate a signal: run it, operate a control (a window
switch, for example), and see which ID/byte moves. If you see no frames, try
`--bitrate 125000` (the body/comfort bus speed on many cars) instead of the
500000 default.

## Safety notes

- `clear` erases stored codes **and** freeze-frame data and resets readiness
  monitors — don't do it right before an emissions test, and not at all if you
  still need the data to diagnose the fault.
- Permanent (Mode 0A) codes won't clear until the fault actually self-heals
  over several drive cycles. That's by design.
- Don't stare at the laptop while driving. For logging on the move, start it,
  set it down, and review the CSV afterward — or have a passenger run it.

## Roadmap

- **Signal decoding** on top of `can survey`: name and scale the IDs/bytes
  you've identified (e.g. via a DBC file).
- **UDS / manufacturer PIDs**. Note that J2534 pass-thru drivers are mostly
  Windows-only, so on a Mac this would go over raw CAN (ISO-TP) instead.
- **Live gauges in the GUI** drawn graphically (arcs/bars), and live charting
  of logged PIDs.
- **Coding / adaptations** over UDS on vehicles you own (authenticated access
  only — no security bypass), for retrofits and post-repair configuration.

## How it's organized

```
carscope/
  main.py              # entry point (python main.py <command>)
  carscope/
    connection.py      # adapter connection (ELM327 over serial/BT/Wi-Fi)
    diagnostics.py     # DTC read/clear + freeze frame (standard OBD-II modes)
    live.py            # live snapshots + CSV logging
    can_bus.py         # raw CAN capture: sniff / log / survey (read-only)
    tuning.py          # tuning datalog analysis (AFR grid, knock events)
    web.py             # local web dashboard backend (stdlib http.server)
    web_assets/        #   the dashboard frontend (single accessible HTML page)
    gui.py             # native desktop UI (Tkinter) — offline fallback
    ai.py              # optional Claude interpretation layer
    cli.py             # argparse command-line interface
```
