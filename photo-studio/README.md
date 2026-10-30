# protune: professional editing for your own photos

You shoot, protune edits. Point it at a folder of camera files (RAW or JPEG) and
it gives you finished, professionally toned photos. It can also ask Claude to
review each edit and fine-tune it the way a retoucher would.

**It never creates or alters image content.** No generative AI, no fake skies,
no invented detail. The AI only chooses settings for the same 14 sliders a
photographer uses in Lightroom (exposure, white balance, highlights, shadows, …).
Those settings are then applied to *your* pixels with standard, repeatable image
math.

## Install

You need Python 3.10 or newer.

```bash
cd photo-studio
pip install .
```

## Use it

```bash
# Edit every photo in a folder. Results go to <folder>/edited/
protune ~/Pictures/2026-10-wedding

# Same, but Claude reviews each photo and fine-tunes it (uses your Claude Pro plan, see below)
protune ~/Pictures/2026-10-wedding --ai

# Choose a look: natural (default), vibrant, moody, bright, bw
protune ~/Pictures/portraits --style bright

# Save a before/after image next to each result
protune shot.NEF --compare

# Disagree with something? Override any slider
protune shot.NEF --set exposure=0.3 --set shadows=40
```

For every photo you get:

| File | What it is |
|---|---|
| `edited/NAME.jpg` | The finished photo (full resolution, sRGB, camera EXIF kept) |
| `edited/NAME.json` | The exact settings used. Edit the numbers and re-run with `--settings edited/NAME.json` |
| `edited/NAME_before_after.jpg` | Side-by-side comparison (with `--compare`) |

Supported: RAW from Canon, Nikon, Sony, Fujifilm, Olympus/OM, Panasonic, Pentax,
Leica, DNG and more (via LibRaw), plus JPEG, TIFF and PNG. **Shoot RAW if you can:**
it holds far more highlight and shadow detail for the editor to recover.

## How it decides the edit

1. **Measure.** It checks brightness distribution, clipped highlights, blocked
   shadows, colour cast (from things that should be grey or white), colour
   saturation, noise level and texture.
2. **Correct.** It sets white balance, exposure, highlight/shadow recovery,
   white/black points, contrast, clarity, vibrance, noise reduction and
   sharpening from those measurements. Then it renders a preview, checks the
   result and adjusts exposure again. It respects intent: sunsets stay warm,
   night scenes stay dark.
3. **AI review (`--ai`).** Claude sees the original and the edit, with the
   measurements, and returns better slider values (for example: "portrait,
   skin slightly warm, clarity too high for skin"). It then looks at its own
   rendered result and fine-tunes once more (`--ai-passes` sets how many rounds).
4. **Render.** It applies the final settings to the full-resolution file.
   Highlights roll off smoothly instead of clipping, shadows open without halos,
   noise reduction is edge-aware, and sharpening skips flat areas such as skin
   and sky.

## AI setup (optional): uses your Claude Pro plan

The auto edit needs no account. `--ai` runs through **Claude Code**, which is
included with Claude Pro, so it uses your subscription. No API key or extra bill.

1. Install Claude Code: <https://claude.com/claude-code>
2. Run `claude` once in a terminal and log in with your Claude account.
3. That's it: `protune ~/Pictures/shoot --ai`

Each photo uses one or two Claude messages from your plan's usage allowance
(`--ai-passes 1` halves that). On a very large shoot you may hit your plan's
usage limit. If so, wait for it to reset, or run without `--ai` for the rest.
Only small 1024 px previews are shown to Claude, never your full-resolution files.

Want a particular model? `--ai-model sonnet` or `--ai-model opus`, if your plan
includes it.

*Alternative:* `--ai-via api` uses the Anthropic API with `ANTHROPIC_API_KEY`
instead (pay per use; `pip install ".[api]"`).

## Tips for learning

Open `edited/NAME.json` beside the before/after image. It shows exactly what a
professional edit of *your* photo involved, and is a good way to learn what each
slider does. Change one number, re-run with `--settings`, and compare.

## Run the tests

```bash
pip install pytest && python -m pytest tests
```
