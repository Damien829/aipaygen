# ProTune: professional editing for your own photos

You shoot, ProTune edits. Point it at a folder of photos from your camera or
memory card and it saves finished, professionally toned versions. It can also
have Claude (on your Claude Pro plan) review each photo and fine-tune it the way
a retoucher would.

**ProTune never creates or alters image content.** No generative AI, no fake skies,
no invented detail. The AI only chooses settings for the same 14 sliders a
photographer uses in Lightroom (exposure, white balance, highlights, shadows,
colour, sharpening and so on). Those settings are then applied to *your* pixels
with standard, repeatable image processing. Your original files are never changed.

---

## Install on your Mac (one time, about 5 minutes)

1. **Get the files.** On the ProTune GitHub page, click the green **Code** button,
   then **Download ZIP**. Double-click the ZIP in Downloads to unzip it.
2. **Run the installer.** Open **Terminal** (press ⌘-Space, type `Terminal`, press
   Return), then paste this line and press Return:

   ```bash
   bash ~/Downloads/protune-main/install.sh
   ```

   (If the unzipped folder has a different name, drag the `install.sh` file onto
   the Terminal window instead of typing the path.)

   The installer sets up everything ProTune needs inside a private folder
   (`~/.protune`); nothing else on your Mac is changed. It also:
   - adds **ProTune** to your Applications folder,
   - installs ExifTool, so your edits keep camera details (date, lens, GPS, copyright),
   - offers to install **Claude Code**, which AI fine-tuning needs (included with Claude Pro).
3. **Log in to Claude (for AI fine-tuning).** In Terminal, type `claude`, press
   Return and follow the steps to log in with your Claude account. When it says
   you're logged in, type `/exit`. You only do this once.

That's it. To **update** later, download the new ZIP and run the same installer line again.

## Use it

Open **ProTune** from your Applications folder, or press ⌘-Space and type
`ProTune`. It opens in your web browser. It runs entirely on your Mac; the browser
is just its window.

1. **Choose folder…** and pick the folder with your photos. A memory card works
   too, e.g. `EOS_DIGITAL ▸ DCIM ▸ 100CANON`.
2. Pick a **Look** (Natural, Vibrant, Moody, Bright & airy, Black & white). Leave
   **AI fine-tuning** on if you'd like Claude's review.
3. Click **Edit photos**. Edits appear as they finish, and go to
   **Pictures ▸ ProTune ▸ (folder name)**.
4. **Click any photo** to compare and fine-tune it:
   - drag the line across the photo to compare before and after;
   - hold **B** to see the original;
   - move any slider (double-click a slider to reset it);
   - **Save** writes the full-size file;
   - **Auto** and **Ask Claude** suggest new settings;
   - **← →** moves to the next photo.
5. **Copy these settings to other photos…** gives a whole shoot the same look.
   You choose which parts (exposure and white balance usually differ shot to shot).
6. **Show in Finder** opens your edited photos. **Quit** closes ProTune (it also
   quits by itself a few minutes after you close the browser tab).

The first time, macOS may ask whether ProTune may access a folder such as
Pictures, Desktop or a memory card. Click **Allow**.

### What you get

| File | What it is |
|---|---|
| `IMG_0001.jpg` | The finished photo: full size (or the size you chose), sRGB colour, camera details kept |
| `IMG_0001.json` | The exact settings used, plus Claude's notes |

**Your originals are never touched.** Shoot RAW+JPEG? ProTune uses the RAW and
skips its JPEG twin. Photos already edited are skipped, so you can stop and
continue later.

### Supported files

RAW from Canon (CR2, CR3), Nikon (NEF), Sony (ARW), Fujifilm (RAF), Olympus/OM
(ORF), Panasonic (RW2), Pentax (PEF), Leica, Hasselblad, Phase One and DNG, plus
JPEG, HEIC (iPhone), TIFF and PNG. **Shoot RAW if you can:** it holds far more
highlight and shadow detail for the editor to recover.

Photos in the Apple Photos app: select them, then choose **File ▸ Export ▸
Export Unmodified Originals** into a folder, and point ProTune at that folder.

## How it decides the edit

1. **Measure.** It checks brightness, clipped highlights, blocked shadows,
   colour cast (from things that should be grey or white), saturation, noise and
   texture.
2. **Correct.** It sets the sliders from those measurements, renders a preview,
   checks it and adjusts again. Intent is respected: sunsets stay warm, night
   scenes stay dark.
3. **AI review (optional).** Claude looks at the original, the edit and a
   full-resolution detail crop (for noise and sharpness), along with the camera
   settings (ISO, shutter speed, lens). It then returns better slider values and
   notes on what it changed. Next it checks its own result and fine-tunes once
   more.
4. **Render.** It applies the settings to the full-resolution file. Highlights
   roll off smoothly instead of clipping, shadows open without halos, noise
   reduction keeps edges, and sharpening skips smooth areas such as skin and sky.

### About your Claude plan

Each photo uses about two Claude messages from your plan's usage allowance, and
takes about 20 seconds. On a very big shoot you may reach your plan's limit. If
so, ProTune keeps going with automatic edits and marks those photos **Auto**.
Click **Run AI on "Auto" photos** after your limit resets. Only small previews
and one detail crop are shown to Claude, never your full files.

## Learn as you go

Open any photo and look at the sliders and Claude's notes. They show exactly
what a professional edit of *your* photo involved. Move one slider at a time to
see what it does.

---

## For the curious: command line

The installer also adds a `protune` command for Terminal:

```bash
protune ~/Pictures/shoot                  # edit a folder (results in ~/Pictures/shoot/edited)
protune ~/Pictures/shoot --ai --style moody
protune shot.CR3 --compare                # also save a before/after image
protune shot.CR3 --set exposure=0.3 --set shadows=40
protune ~/Pictures/shoot --settings edited/IMG_0001.json   # one look for every photo
protune --help                            # everything else
```

## Troubleshooting

- **"Claude Code not installed"** in the app: run the installer again and answer
  Y when it offers Claude Code, then log in (step 3 above).
- **"Claude Code isn't logged in"**: open Terminal, type `claude`, log in, then `/exit`.
- **Something else went wrong**: the log is in `~/Library/Logs/ProTune.log`
  (Finder ▸ Go ▸ Go to Folder… then paste `~/Library/Logs`).
- **Uninstall**: delete `ProTune` from `~/Applications` and the hidden folder
  `~/.protune` (Finder ▸ Go ▸ Go to Folder… then paste `~/.protune`).

## Developers

```bash
pip install -e ".[test]" && python -m pytest tests
```
