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

## Safety notes

- `clear` erases stored codes **and** freeze-frame data and resets readiness
  monitors — don't do it right before an emissions test, and not at all if you
  still need the data to diagnose the fault.
- Permanent (Mode 0A) codes won't clear until the fault actually self-heals
  over several drive cycles. That's by design.
- Don't stare at the laptop while driving. For logging on the move, start it,
  set it down, and review the CSV afterward — or have a passenger run it.

## Roadmap

- **CAN sniffing / decoding** on vehicles you own (`python-can` + a USB-CAN
  interface like CANable, or SocketCAN on a Pi).
- **UDS / manufacturer PIDs** via a J2534 pass-thru interface, where supported.
- A lightweight **web UI** (gauges + code list + log viewer) you can hit from
  your phone when it runs on a Pi in the garage.
- **AI anomaly spotting** over logged CSVs, not just code interpretation.

## How it's organized

```
carscope/
  main.py              # entry point (python main.py <command>)
  carscope/
    connection.py      # adapter connection (ELM327 over serial/BT/Wi-Fi)
    diagnostics.py     # DTC read/clear + freeze frame (standard OBD-II modes)
    live.py            # live snapshots + CSV logging
    ai.py              # optional Claude interpretation layer
    cli.py             # argparse command-line interface
```
